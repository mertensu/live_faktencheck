import pyaudio
import wave
import threading
import requests
import time
import io
import numpy as np

# Silero VAD importieren
try:
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps
except ImportError:
    print("❌ silero-vad oder torch nicht gefunden. Installiere mit: uv sync")
    exit(1)

# --- KONFIGURATION ---
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/fact-check-audio"
MIN_RECORDING_TIME = 60  # Mindestens 2 Minuten (120 Sekunden)
VAD_CHECK_INTERVAL = 1.0  # Alle 1 Sekunde prüfen (besser für Performance)
VAD_BUFFER_SIZE = 1.5  # 1.5 Sekunden Audio für VAD-Analyse (bessere Genauigkeit)
SILENCE_THRESHOLD = 2.0  # 3 Sekunden Stille bevor gesendet wird (natürlichere Pausen)
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000  # Silero VAD benötigt 16kHz
CHUNK = 512  # Kleinere Chunks für bessere VAD-Performance

GUESTS = "Sandra Maischberger interviewt Gitta Connemann und Katharina Dröge. Sendung vom 19.September 2025"

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
        
        # Audio-Stream öffnen
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        print(f"🔴 Aufnahme läuft...")
        print(f"📋 Mindestaufnahmezeit: {MIN_RECORDING_TIME} Sekunden")
        print(f"🔍 VAD-Prüfung alle {VAD_CHECK_INTERVAL} Sekunden nach Mindestzeit")
        print(f"📊 VAD-Buffer: {VAD_BUFFER_SIZE} Sekunden")
        print(f"🔇 Stille-Schwelle: {SILENCE_THRESHOLD} Sekunden")

    def convert_to_float32(self, audio_data):
        """Konvertiert Int16 Audio-Daten zu Float32 für Silero VAD"""
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        # Normalisiere auf [-1.0, 1.0]
        audio_float = audio_array.astype(np.float32) / 32768.0
        return audio_float

    def check_speech_activity(self, audio_chunk):
        """Prüft ob in einem Audio-Chunk Sprache erkannt wird"""
        try:
            # Konvertiere zu Float32
            audio_float = self.convert_to_float32(audio_chunk)
            
            # Konvertiere zu PyTorch Tensor
            audio_tensor = torch.from_numpy(audio_float)
            
            # Silero VAD anwenden
            speech_timestamps = get_speech_timestamps(
                audio_tensor,
                self.model,
                sampling_rate=RATE,
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

    def save_and_send(self):
        """Speichert die aktuellen Frames als WAV und sendet sie"""
        if not self.frames:
            print("⚠️ Keine Daten zum Senden.")
            return

        print(f"💾 Speichere {len(self.frames)} Chunks...")
        
        seq_num = self.chunk_count
        self.chunk_count += 1

        # Erstelle WAV-Datei im Speicher
        buffer = io.BytesIO()
        wf = wave.open(buffer, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(self.frames))
        wf.close()

        audio_content = buffer.getvalue()
        
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
                max_buffer_chunks = int((RATE / CHUNK) * VAD_BUFFER_SIZE)
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
                                print(f"✅ Stille-Schwelle ({SILENCE_THRESHOLD}s) erreicht. Beende Aufnahme und sende...")
                                self.is_recording = False
                                break
                        else:
                            # Sollte nicht passieren, aber falls doch
                            print("⚠️ Kein last_speech_time gesetzt")
                    
                    last_vad_check = current_time
                
        except KeyboardInterrupt:
            print("\n⚠️ Aufnahme durch Benutzer unterbrochen")
            self.is_recording = False
        except Exception as e:
            print(f"❌ Fehler während der Aufnahme: {e}")
            self.is_recording = False
        
        # Aufnahme beendet - sende Daten
        total_duration = time.time() - start_time
        print(f"\n📊 Aufnahme beendet nach {total_duration:.1f} Sekunden")
        print(f"📦 Gesammelte Chunks: {len(self.frames)}")
        
        if self.frames:
            self.save_and_send()
        
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
    recorder = VADRecorder()
    recorder.record()
    print("👋 Programm beendet.")
