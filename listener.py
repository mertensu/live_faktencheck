import pyaudio
import wave
import threading
import requests
import time
import io
import numpy as np
from pathlib import Path

# Silero VAD importieren
try:
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps
except ImportError:
    print("❌ silero-vad oder torch nicht gefunden. Installiere mit: uv sync")
    exit(1)

# Keyboard-Listener für manuelles Senden
try:
    from pynput import keyboard
except ImportError:
    print("❌ pynput nicht gefunden. Installiere mit: uv sync")
    exit(1)

# --- KONFIGURATION ---
import sys
import os
from config import get_guests, DEFAULT_SHOW

N8N_WEBHOOK_URL = "http://localhost:5678/webhook/fact-check-audio"
MIN_RECORDING_TIME = 60  # Mindestens 2 Minuten (120 Sekunden)
VAD_CHECK_INTERVAL = 1.0  # Alle 1 Sekunde prüfen (besser für Performance)
VAD_BUFFER_SIZE = 1.5  # 1.5 Sekunden Audio für VAD-Analyse (bessere Genauigkeit)
SILENCE_THRESHOLD = 2.0  # 3 Sekunden Stille bevor gesendet wird (natürlichere Pausen)
FORMAT = pyaudio.paInt16
CHANNELS = 1  # BlackHole 2ch reicht, wir nutzen Mono
DEVICE_RATE = 48000  # BlackHole läuft i.d.R. auf 48 kHz
VAD_RATE = 16000  # Silero VAD erwartet 16 kHz
CHUNK = 1024  # Größeres Chunk für 48 kHz Input

# Sendungsdetails aus zentraler Config
# Kann über Kommandozeilen-Parameter oder Umgebungsvariable gesetzt werden
# Beispiel: uv run python listener.py test
# Oder: SHOW=test uv run python listener.py
def get_current_show():
    """Bestimmt die aktuelle Sendung aus Parameter, Umgebungsvariable oder Default"""
    # 1. Kommandozeilen-Parameter (z.B. python listener.py test)
    if len(sys.argv) > 1:
        show_key = sys.argv[1].lower()
        print(f"📺 Sendung aus Parameter: {show_key}")
        return show_key
    
    # 2. Umgebungsvariable (z.B. SHOW=test python listener.py)
    env_show = os.environ.get('SHOW')
    if env_show:
        show_key = env_show.lower()
        print(f"📺 Sendung aus Umgebungsvariable: {show_key}")
        return show_key
    
    # 3. Fallback: DEFAULT_SHOW aus config.py
    print(f"📺 Verwende Standard-Sendung: {DEFAULT_SHOW}")
    return DEFAULT_SHOW

CURRENT_SHOW = get_current_show()
GUESTS = get_guests(CURRENT_SHOW)  # Lädt automatisch die Gäste-Beschreibung für die gewählte Sendung

# Debug-Modus: Speichere jeden Block als WAV-Datei
# Aktivieren mit: DEBUG=true uv run python listener.py
# Oder: uv run python listener.py --debug
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes') or '--debug' in sys.argv
DEBUG_OUTPUT_DIR = Path(__file__).parent / "debug_audio"
if DEBUG_MODE:
    DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"🐛 Debug-Modus aktiviert. Audio-Blöcke werden gespeichert in: {DEBUG_OUTPUT_DIR}")

# Debug-Modus: Speichere jeden Block als WAV-Datei
# Aktivieren mit: DEBUG=true uv run python listener.py
# Oder: uv run python listener.py --debug
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes') or '--debug' in sys.argv
DEBUG_OUTPUT_DIR = Path(__file__).parent / "debug_audio"
if DEBUG_MODE:
    DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"🐛 Debug-Modus aktiviert. Audio-Blöcke werden gespeichert in: {DEBUG_OUTPUT_DIR}")

class VADRecorder:
    def __init__(self):
        print("🔧 Initialisiere Silero VAD...")
        # Silero VAD Modell laden
        try:
            self.model = load_silero_vad()
            print("✅ Silero VAD Modell erfolgreich geladen")
        except Exception as e:
            print(f"❌ Fehler beim Laden von Silero VAD: {e}")
            import traceback
            traceback.print_exc()
            exit(1)
        
        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.is_recording = True
        self.chunk_count = 1
        self.lock = threading.Lock()  # Lock für Thread-sichere Zugriffe auf frames
        
        # Finde BlackHole Device
        blackhole_index = self.find_blackhole_device()
        if blackhole_index is None:
            print("⚠️ BlackHole nicht gefunden. Verwende Standard-Input-Device.")
            print("💡 Verfügbare Devices:")
            self.list_audio_devices()
            input_device = None  # Standard-Device verwenden
        else:
            print(f"✅ BlackHole Device gefunden (Index: {blackhole_index})")
            input_device = blackhole_index
        
        # Audio-Stream öffnen
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=DEVICE_RATE,
            input=True,
            input_device_index=input_device,
            frames_per_buffer=CHUNK
        )
        
        print(f"🔴 Aufnahme läuft...")
        print(f"📺 Sendung: {CURRENT_SHOW}")
        print(f"👥 Gäste: {GUESTS}")
        print(f"📋 Mindestaufnahmezeit: {MIN_RECORDING_TIME} Sekunden")
        print(f"🔍 VAD-Prüfung alle {VAD_CHECK_INTERVAL} Sekunden nach Mindestzeit")
        print(f"📊 VAD-Buffer: {VAD_BUFFER_SIZE} Sekunden")
        print(f"🔇 Stille-Schwelle: {SILENCE_THRESHOLD} Sekunden")

    def find_blackhole_device(self):
        """Findet das BlackHole Audio-Device"""
        try:
            device_count = self.audio.get_device_count()
            for i in range(device_count):
                device_info = self.audio.get_device_info_by_index(i)
                device_name = device_info.get('name', '').lower()
                # Suche nach "blackhole" im Device-Namen
                if 'blackhole' in device_name and device_info.get('maxInputChannels', 0) > 0:
                    return i
            return None
        except Exception as e:
            print(f"⚠️ Fehler beim Suchen nach BlackHole: {e}")
            return None
    
    def list_audio_devices(self):
        """Listet alle verfügbaren Audio-Input-Devices auf"""
        try:
            device_count = self.audio.get_device_count()
            for i in range(device_count):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info.get('maxInputChannels', 0) > 0:
                    print(f"   [{i}] {device_info.get('name', 'Unknown')} "
                          f"({device_info.get('maxInputChannels', 0)} channels, "
                          f"{int(device_info.get('defaultSampleRate', 0))} Hz)")
        except Exception as e:
            print(f"⚠️ Fehler beim Auflisten der Devices: {e}")

    def convert_to_float32(self, audio_data):
        """Konvertiert Int16 Audio-Daten zu Float32 für Silero VAD"""
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        # Normalisiere auf [-1.0, 1.0]
        audio_float = audio_array.astype(np.float32) / 32768.0
        return audio_float

    def check_speech_activity(self, audio_chunk):
        """Prüft ob in einem Audio-Chunk Sprache erkannt wird"""
        try:
            # Konvertiere zu Float32 (48 kHz)
            audio_float = self.convert_to_float32(audio_chunk)
            
            # Downsample von 48 kHz auf 16 kHz (einfaches Decimation)
            audio_float_16k = audio_float[::3]
            
            # Konvertiere zu PyTorch Tensor
            audio_tensor = torch.from_numpy(audio_float_16k)
            
            # Silero VAD anwenden (16 kHz)
            speech_timestamps = get_speech_timestamps(
                audio_tensor,
                self.model,
                sampling_rate=VAD_RATE,
                threshold=0.5,  # Threshold für Sprach-Erkennung
                min_speech_duration_ms=250,  # Mindestdauer für Sprache
                min_silence_duration_ms=100  # Mindestdauer für Stille
            )
            
            # Wenn Timestamps gefunden wurden, gibt es Sprache
            return len(speech_timestamps) > 0
        except Exception as e:
            print(f"⚠️ Fehler bei VAD-Prüfung: {e}")
            import traceback
            traceback.print_exc()
            # Bei Fehler annehmen, dass Sprache vorhanden ist (sicherer)
            return True

    def send_to_n8n(self, audio_data, sequence_num):
        """Sendet Audio-Daten an N8N"""
        print(f"📤 Sende Block {sequence_num} an n8n...")
        try:
            files = {'data': (f'chunk_{sequence_num}.wav', audio_data, 'audio/wav')}
            response = requests.post(
                N8N_WEBHOOK_URL,
                files=files,
                data={'seq': sequence_num, "guests": GUESTS}
            )
            print(f"✅ Block {sequence_num} erfolgreich gesendet.")
        except Exception as e:
            print(f"❌ Fehler beim Senden: {e}")

    def save_and_send(self, reset_frames=True):
        """Speichert die aktuellen Frames als WAV und sendet sie"""
        with self.lock:
            if not self.frames:
                print("⚠️ Keine Daten zum Senden.")
                return

            # Kopiere Frames für Thread-sichere Verarbeitung
            frames_to_send = self.frames.copy()
            
            # Reset frames wenn gewünscht (für manuelles Senden während laufender Aufnahme)
            if reset_frames:
                self.frames = []

        print(f"💾 Speichere {len(frames_to_send)} Chunks...")
        
        seq_num = self.chunk_count
        self.chunk_count += 1

        # Erstelle WAV-Datei im Speicher
        buffer = io.BytesIO()
        wf = wave.open(buffer, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(FORMAT))
        wf.setframerate(DEVICE_RATE)
        wf.writeframes(b''.join(frames_to_send))
        wf.close()

        audio_content = buffer.getvalue()
        
        # Debug-Modus: Speichere als lokale WAV-Datei
        if DEBUG_MODE:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{CURRENT_SHOW}_block_{seq_num:03d}_{timestamp}.wav"
            filepath = DEBUG_OUTPUT_DIR / filename
            try:
                with open(filepath, 'wb') as f:
                    f.write(audio_content)
                duration = len(frames_to_send) * CHUNK / DEVICE_RATE
                print(f"🐛 Debug: Block gespeichert als {filename} ({duration:.1f}s)")
            except Exception as e:
                print(f"⚠️ Debug: Fehler beim Speichern: {e}")
        
        # Sende in separatem Thread (nicht daemon, damit wir darauf warten können)
        send_thread = threading.Thread(
            target=self.send_to_n8n,
            args=(audio_content, seq_num),
            daemon=False
        )
        send_thread.start()
        
        # Warte auf Abschluss des Sendens (mit Timeout)
        send_thread.join(timeout=30)  # Maximal 30 Sekunden warten
        if send_thread.is_alive():
            print("⚠️ Send-Timeout erreicht, aber Thread läuft weiter im Hintergrund")
    
    def manual_send(self):
        """Sendet manuell die aktuellen Frames (wird von Keyboard-Listener aufgerufen)"""
        if not self.is_recording:
            print("⚠️ Aufnahme nicht aktiv, kann nicht senden.")
            return
        
        with self.lock:
            if not self.frames:
                print("⚠️ Keine Daten zum Senden (noch keine Frames aufgenommen).")
                return
        
        print("\n⌨️ Manueller Send-Befehl empfangen...")
        # Sende aktuellen Stand, reset frames damit nicht doppelt gesendet wird
        # reset_frames=True, aber is_recording bleibt True (läuft weiter)
        self.save_and_send(reset_frames=True)
        print("✅ Manueller Block gesendet. Aufnahme läuft weiter...\n")

    def record(self):
        """Hauptaufnahme-Loop mit VAD"""
        start_time = time.time()
        last_speech_time = None  # Wird gesetzt wenn Mindestzeit erreicht ist
        vad_buffer = []  # Buffer für VAD-Analyse
        last_vad_check = None  # Zeitpunkt der letzten VAD-Prüfung
        last_progress_time = 0
        consecutive_silence_checks = 0  # Zähler für aufeinanderfolgende Stille-Erkennungen
        
        print(f"🎙️ Starte Aufnahme...")
        
        try:
            while self.is_recording:
                # Audio-Chunk lesen
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                with self.lock:
                    self.frames.append(data)
                
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                # Mindestzeit noch nicht erreicht
                if elapsed_time < MIN_RECORDING_TIME:
                    # Zeige Fortschritt alle 10 Sekunden
                    if int(elapsed_time) % 10 == 0 and int(elapsed_time) != last_progress_time:
                        remaining = MIN_RECORDING_TIME - elapsed_time
                        print(f"⏳ Mindestzeit: {remaining:.0f}s verbleibend...")
                        last_progress_time = int(elapsed_time)
                    continue
                
                # Wenn Mindestzeit gerade erreicht wurde, initialisiere last_speech_time
                if last_speech_time is None:
                    last_speech_time = current_time
                    last_vad_check = current_time
                    print(f"✅ Mindestzeit erreicht. Starte VAD-Überwachung...")
                
                # Sammle Audio für VAD-Buffer (rolling window)
                vad_buffer.append(data)
                
                # Begrenze Buffer auf VAD_BUFFER_SIZE Sekunden
                max_buffer_chunks = int((DEVICE_RATE / CHUNK) * VAD_BUFFER_SIZE)
                if len(vad_buffer) > max_buffer_chunks:
                    vad_buffer.pop(0)  # Ältester Chunk entfernen
                
                # Prüfe alle VAD_CHECK_INTERVAL Sekunden
                if last_vad_check is None or (current_time - last_vad_check) >= VAD_CHECK_INTERVAL:
                    # Verwende die letzten VAD_BUFFER_SIZE Sekunden für Analyse
                    audio_chunk = b''.join(vad_buffer[-max_buffer_chunks:])
                    has_speech = self.check_speech_activity(audio_chunk)
                    
                    if has_speech:
                        # Sprache erkannt: Aktualisiere Zeitpunkt der letzten Sprache
                        last_speech_time = current_time
                        consecutive_silence_checks = 0
                        print("🗣️ Sprache erkannt")
                    else:
                        # Keine Sprache in den letzten 1.5 Sekunden
                        consecutive_silence_checks += 1
                        
                        if last_speech_time:
                            # Berechne wie lange es still ist seit der letzten erkannten Sprache
                            silence_duration = current_time - last_speech_time
                            print(f"🔇 Keine Sprache in letzten 1.5s | Stille seit letzter Sprache: {silence_duration:.1f}s ({consecutive_silence_checks}x Prüfung)")
                            
                            # Wenn Stille-Schwelle überschritten (z.B. 2 Sekunden)
                            # Das bedeutet: Wir haben 2 Sekunden lang keine Sprache mehr erkannt
                            if silence_duration >= SILENCE_THRESHOLD:
                                print(f"✅ Stille-Schwelle ({SILENCE_THRESHOLD}s) erreicht. Sende Block...")
                                # Sende Block, aber setze is_recording NICHT auf False
                                # Aufnahme läuft kontinuierlich weiter
                                self.save_and_send(reset_frames=True)
                                # Reset VAD-Tracking für nächsten Block
                                last_speech_time = None
                                consecutive_silence_checks = 0
                                print("🔄 Aufnahme läuft weiter...")
                                continue
                        else:
                            # Sollte nicht passieren, aber falls doch
                            print("⚠️ Kein last_speech_time gesetzt")
                    
                    last_vad_check = current_time
                
        except KeyboardInterrupt:
            print("\n⚠️ Aufnahme durch Benutzer unterbrochen")
            self.is_recording = False
            # Bei vorzeitigem Beenden: Frage ob gesendet werden soll
            if self.frames:
                total_duration = time.time() - start_time
                print(f"\n📊 Aufnahme beendet nach {total_duration:.1f} Sekunden")
                print(f"📦 Gesammelte Chunks: {len(self.frames)}")
                print("💡 Daten wurden nicht gesendet (vorzeitiges Beenden)")
                # Optional: Hier könnte man fragen ob gesendet werden soll
                # self.save_and_send()
            return  # Beende sofort ohne zu senden
        except Exception as e:
            print(f"❌ Fehler während der Aufnahme: {e}")
            self.is_recording = False
        
        # Nur wenn is_recording auf False gesetzt wurde (z.B. durch KeyboardInterrupt)
        # wird hier die Aufnahme beendet
        if not self.is_recording:
            total_duration = time.time() - start_time
            print(f"\n📊 Aufnahme beendet nach {total_duration:.1f} Sekunden")
            print(f"📦 Gesammelte Chunks: {len(self.frames)}")
            
            # Sende verbleibende Daten nur wenn explizit beendet wurde
            with self.lock:
                if self.frames:
                    print("💾 Sende verbleibende Daten...")
                    self.save_and_send(reset_frames=False)
            
            # Cleanup
            self.stop()

    def stop(self):
        """Beendet die Aufnahme und räumt auf"""
        self.is_recording = False
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'audio') and self.audio:
            self.audio.terminate()
        print("⏹ Aufnahme beendet und Ressourcen freigegeben.")

# --- HAUPT-PROGRAMM ---
if __name__ == "__main__":
    # Setze aktuelle Episode im Backend
    try:
        import requests
        response = requests.post(
            "http://localhost:5000/api/set-episode",
            json={"episode_key": CURRENT_SHOW},
            timeout=5
        )
        if response.ok:
            print(f"✅ Episode im Backend gesetzt: {CURRENT_SHOW}")
        else:
            print(f"⚠️ Konnte Episode nicht im Backend setzen: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Konnte Episode nicht im Backend setzen: {e}")
        print("   (Backend läuft möglicherweise nicht)")
    
    recorder = VADRecorder()
    
    # Terminal-basierte Eingabe für manuelles Senden (robustere Lösung für macOS)
    def stdin_listener():
        """Liest Eingaben vom Terminal (blockierend in separatem Thread)"""
        import sys
        
        print("\n⌨️ Terminal-Eingabe aktiviert:")
        print("   Tippe 's' + Enter für manuelles Senden eines Audio-Blocks")
        print("   Tippe 'q' + Enter zum Beenden")
        print("   (Aufnahme läuft danach weiter)")
        print("   💡 Wichtig: Stelle sicher, dass das Terminal-Fenster fokussiert ist!\n")
        
        # Prüfe ob stdin verfügbar ist
        if not sys.stdin.isatty():
            print("⚠️ Warnung: stdin ist nicht im TTY-Modus. Terminal-Eingabe könnte nicht funktionieren.")
        
        try:
            while recorder.is_recording:
                try:
                    # Blockierend lesen (funktioniert zuverlässig)
                    # Wichtig: Terminal-Fenster muss fokussiert sein!
                    if DEBUG_MODE:
                        print("🐛 Debug: Warte auf Eingabe...")
                    line = input().strip().lower()
                    if DEBUG_MODE:
                        print(f"🐛 Debug: Eingabe empfangen: '{line}'")
                    
                    if line == 's':
                        print("⌨️ 's' erkannt - sende Block...")
                        recorder.manual_send()
                    elif line == 'q' or line == 'quit':
                        print("\n⚠️ Beende durch Benutzereingabe...")
                        recorder.is_recording = False
                        break
                    elif line:
                        print(f"💡 Unbekannter Befehl: '{line}'. Verwende 's' zum Senden oder 'q' zum Beenden.")
                except (EOFError, KeyboardInterrupt):
                    if DEBUG_MODE:
                        print("🐛 Debug: EOF oder KeyboardInterrupt in stdin_listener")
                    break
                except Exception as e:
                    print(f"⚠️ Fehler bei Eingabe: {e}")
                    if DEBUG_MODE:
                        import traceback
                        traceback.print_exc()
                    # Bei Fehler kurz warten und weiter versuchen
                    time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Terminal-Eingabe-Listener beendet: {e}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
    
    # Versuche auch globalen Keyboard-Listener (falls Berechtigungen vorhanden)
    keyboard_listener = None
    try:
        def on_press(key):
            try:
                if key == keyboard.Key.f10:
                    print("⌨️ F10 erkannt (global)")
                    recorder.manual_send()
            except:
                pass
        
        keyboard_listener = keyboard.Listener(on_press=on_press)
        keyboard_listener.start()
        print("⌨️ Globaler Keyboard-Listener aktiviert (F10)")
    except Exception as e:
        print(f"⚠️ Globaler Keyboard-Listener nicht verfügbar: {e}")
        print("   (Verwende Terminal-Eingabe stattdessen)")
    
    # Starte Terminal-Eingabe-Listener in separatem Thread
    stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
    stdin_thread.start()
    
    # Starte Aufnahme (blockierend)
    recorder.record()
    
    # Cleanup
    if keyboard_listener:
        keyboard_listener.stop()
    print("👋 Programm beendet.")
