"""
Audio Listener for Live Fact-Checking

Captures audio from BlackHole virtual audio device, uses Silero VAD
for speech detection, and sends audio blocks to the backend for processing.
"""

import pyaudio
import wave
import threading
import requests
import time
import io
import numpy as np
from pathlib import Path

# Silero VAD
try:
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps
except ImportError:
    print("❌ silero-vad or torch not found. Install with: uv sync")
    exit(1)

# Keyboard listener for manual sending
try:
    from pynput import keyboard
except ImportError:
    print("❌ pynput not found. Install with: uv sync")
    exit(1)

# --- CONFIGURATION ---
import sys
import os
from config import get_guests, DEFAULT_SHOW

# Backend URL (no more N8N!)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
AUDIO_ENDPOINT = f"{BACKEND_URL}/api/audio-block"

# Recording settings
MIN_RECORDING_TIME = 60  # Minimum 60 seconds before VAD triggers
VAD_CHECK_INTERVAL = 1.0  # Check every 1 second
VAD_BUFFER_SIZE = 1.5  # 1.5 seconds of audio for VAD analysis
SILENCE_THRESHOLD = 2.0  # 2 seconds of silence before sending
FORMAT = pyaudio.paInt16
CHANNELS = 1  # Mono
DEVICE_RATE = 48000  # BlackHole runs at 48 kHz
VAD_RATE = 16000  # Silero VAD expects 16 kHz
CHUNK = 1024


def get_current_show():
    """Determine current show from parameter, env var, or default"""
    # 1. Command line parameter (e.g., python listener.py test)
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        show_key = sys.argv[1].lower()
        print(f"📺 Show from parameter: {show_key}")
        return show_key

    # 2. Environment variable (e.g., SHOW=test python listener.py)
    env_show = os.environ.get('SHOW')
    if env_show:
        show_key = env_show.lower()
        print(f"📺 Show from environment: {show_key}")
        return show_key

    # 3. Fallback: DEFAULT_SHOW from config.py
    print(f"📺 Using default show: {DEFAULT_SHOW}")
    return DEFAULT_SHOW


CURRENT_SHOW = get_current_show()
GUESTS = get_guests(CURRENT_SHOW)

# Debug mode: Save each block as WAV file
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes') or '--debug' in sys.argv
DEBUG_OUTPUT_DIR = Path(__file__).parent / "debug_audio"
if DEBUG_MODE:
    DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"🐛 Debug mode enabled. Audio blocks saved to: {DEBUG_OUTPUT_DIR}")


class VADRecorder:
    def __init__(self):
        print("🔧 Initializing Silero VAD...")
        try:
            self.model = load_silero_vad()
            print("✅ Silero VAD model loaded successfully")
        except Exception as e:
            print(f"❌ Error loading Silero VAD: {e}")
            import traceback
            traceback.print_exc()
            exit(1)

        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.is_recording = True
        self.chunk_count = 1
        self.lock = threading.Lock()

        # Find BlackHole device
        blackhole_index = self.find_blackhole_device()
        if blackhole_index is None:
            print("⚠️ BlackHole not found. Using default input device.")
            print("💡 Available devices:")
            self.list_audio_devices()
            input_device = None
        else:
            print(f"✅ BlackHole device found (index: {blackhole_index})")
            input_device = blackhole_index

        # Open audio stream
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=DEVICE_RATE,
            input=True,
            input_device_index=input_device,
            frames_per_buffer=CHUNK
        )

        print(f"🔴 Recording started...")
        print(f"📺 Show: {CURRENT_SHOW}")
        print(f"👥 Guests: {GUESTS}")
        print(f"📋 Minimum recording time: {MIN_RECORDING_TIME} seconds")
        print(f"🔍 VAD check every {VAD_CHECK_INTERVAL} seconds after minimum time")
        print(f"📊 VAD buffer: {VAD_BUFFER_SIZE} seconds")
        print(f"🔇 Silence threshold: {SILENCE_THRESHOLD} seconds")
        print(f"📡 Backend: {BACKEND_URL}")

    def find_blackhole_device(self):
        """Find the BlackHole audio device"""
        try:
            device_count = self.audio.get_device_count()
            for i in range(device_count):
                device_info = self.audio.get_device_info_by_index(i)
                device_name = device_info.get('name', '').lower()
                if 'blackhole' in device_name and device_info.get('maxInputChannels', 0) > 0:
                    return i
            return None
        except Exception as e:
            print(f"⚠️ Error finding BlackHole: {e}")
            return None

    def list_audio_devices(self):
        """List all available audio input devices"""
        try:
            device_count = self.audio.get_device_count()
            for i in range(device_count):
                device_info = self.audio.get_device_info_by_index(i)
                if device_info.get('maxInputChannels', 0) > 0:
                    print(f"   [{i}] {device_info.get('name', 'Unknown')} "
                          f"({device_info.get('maxInputChannels', 0)} channels, "
                          f"{int(device_info.get('defaultSampleRate', 0))} Hz)")
        except Exception as e:
            print(f"⚠️ Error listing devices: {e}")

    def convert_to_float32(self, audio_data):
        """Convert Int16 audio data to Float32 for Silero VAD"""
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        audio_float = audio_array.astype(np.float32) / 32768.0
        return audio_float

    def check_speech_activity(self, audio_chunk):
        """Check if speech is detected in an audio chunk"""
        try:
            # Convert to Float32 (48 kHz)
            audio_float = self.convert_to_float32(audio_chunk)

            # Downsample from 48 kHz to 16 kHz
            audio_float_16k = audio_float[::3]

            # Convert to PyTorch tensor
            audio_tensor = torch.from_numpy(audio_float_16k)

            # Apply Silero VAD (16 kHz)
            speech_timestamps = get_speech_timestamps(
                audio_tensor,
                self.model,
                sampling_rate=VAD_RATE,
                threshold=0.5,
                min_speech_duration_ms=250,
                min_silence_duration_ms=100
            )

            return len(speech_timestamps) > 0
        except Exception as e:
            print(f"⚠️ Error in VAD check: {e}")
            return True  # Assume speech on error (safer)

    def send_to_backend(self, audio_data, sequence_num):
        """Send audio data to the backend for processing"""
        print(f"📤 Sending block {sequence_num} to backend...")
        try:
            files = {
                'audio': (f'chunk_{sequence_num}.wav', audio_data, 'audio/wav')
            }
            data = {
                'episode_key': CURRENT_SHOW,
                'guests': GUESTS
            }

            response = requests.post(
                AUDIO_ENDPOINT,
                files=files,
                data=data,
                timeout=30
            )

            if response.ok:
                result = response.json()
                print(f"✅ Block {sequence_num} sent successfully: {result.get('message', 'OK')}")
            else:
                print(f"❌ Backend error: {response.status_code} - {response.text}")

        except requests.exceptions.ConnectionError:
            print(f"❌ Cannot connect to backend at {BACKEND_URL}")
            print(f"   Make sure the backend is running: ./backend/run.sh")
        except Exception as e:
            print(f"❌ Error sending: {e}")

    def save_and_send(self, reset_frames=True):
        """Save current frames as WAV and send to backend"""
        with self.lock:
            if not self.frames:
                print("⚠️ No data to send.")
                return

            frames_to_send = self.frames.copy()

            if reset_frames:
                self.frames = []

        print(f"💾 Saving {len(frames_to_send)} chunks...")

        seq_num = self.chunk_count
        self.chunk_count += 1

        # Create WAV file in memory
        buffer = io.BytesIO()
        wf = wave.open(buffer, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(FORMAT))
        wf.setframerate(DEVICE_RATE)
        wf.writeframes(b''.join(frames_to_send))
        wf.close()

        audio_content = buffer.getvalue()

        # Debug mode: Save as local WAV file
        if DEBUG_MODE:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{CURRENT_SHOW}_block_{seq_num:03d}_{timestamp}.wav"
            filepath = DEBUG_OUTPUT_DIR / filename
            try:
                with open(filepath, 'wb') as f:
                    f.write(audio_content)
                duration = len(frames_to_send) * CHUNK / DEVICE_RATE
                print(f"🐛 Debug: Block saved as {filename} ({duration:.1f}s)")
            except Exception as e:
                print(f"⚠️ Debug: Error saving: {e}")

        # Send in separate thread
        send_thread = threading.Thread(
            target=self.send_to_backend,
            args=(audio_content, seq_num),
            daemon=False
        )
        send_thread.start()

        # Wait for completion with timeout
        send_thread.join(timeout=30)
        if send_thread.is_alive():
            print("⚠️ Send timeout reached, but thread continues in background")

    def manual_send(self):
        """Manually send current frames (called by keyboard listener)"""
        if not self.is_recording:
            print("⚠️ Recording not active, cannot send.")
            return

        with self.lock:
            if not self.frames:
                print("⚠️ No data to send (no frames recorded yet).")
                return

        print("\n⌨️ Manual send command received...")
        self.save_and_send(reset_frames=True)
        print("✅ Manual block sent. Recording continues...\n")

    def record(self):
        """Main recording loop with VAD"""
        start_time = time.time()
        last_speech_time = None
        vad_buffer = []
        last_vad_check = None
        last_progress_time = 0
        consecutive_silence_checks = 0

        print(f"🎙️ Starting recording...")

        try:
            while self.is_recording:
                # Read audio chunk
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                with self.lock:
                    self.frames.append(data)

                current_time = time.time()
                elapsed_time = current_time - start_time

                # Minimum time not reached yet
                if elapsed_time < MIN_RECORDING_TIME:
                    if int(elapsed_time) % 10 == 0 and int(elapsed_time) != last_progress_time:
                        remaining = MIN_RECORDING_TIME - elapsed_time
                        print(f"⏳ Minimum time: {remaining:.0f}s remaining...")
                        last_progress_time = int(elapsed_time)
                    continue

                # Initialize last_speech_time when minimum time reached
                if last_speech_time is None:
                    last_speech_time = current_time
                    last_vad_check = current_time
                    print(f"✅ Minimum time reached. Starting VAD monitoring...")

                # Collect audio for VAD buffer (rolling window)
                vad_buffer.append(data)

                # Limit buffer to VAD_BUFFER_SIZE seconds
                max_buffer_chunks = int((DEVICE_RATE / CHUNK) * VAD_BUFFER_SIZE)
                if len(vad_buffer) > max_buffer_chunks:
                    vad_buffer.pop(0)

                # Check every VAD_CHECK_INTERVAL seconds
                if last_vad_check is None or (current_time - last_vad_check) >= VAD_CHECK_INTERVAL:
                    audio_chunk = b''.join(vad_buffer[-max_buffer_chunks:])
                    has_speech = self.check_speech_activity(audio_chunk)

                    if has_speech:
                        last_speech_time = current_time
                        consecutive_silence_checks = 0
                        print("🗣️ Speech detected")
                    else:
                        consecutive_silence_checks += 1

                        if last_speech_time:
                            silence_duration = current_time - last_speech_time
                            print(f"🔇 No speech in last 1.5s | Silence since last speech: {silence_duration:.1f}s ({consecutive_silence_checks}x check)")

                            if silence_duration >= SILENCE_THRESHOLD:
                                print(f"✅ Silence threshold ({SILENCE_THRESHOLD}s) reached. Sending block...")
                                self.save_and_send(reset_frames=True)
                                # Reset for next block
                                start_time = time.time()
                                last_speech_time = None
                                consecutive_silence_checks = 0
                                last_progress_time = 0
                                print("🔄 Recording continues...")
                                continue

                    last_vad_check = current_time

        except KeyboardInterrupt:
            print("\n⚠️ Recording interrupted by user")
            self.is_recording = False
            if self.frames:
                total_duration = time.time() - start_time
                print(f"\n📊 Recording ended after {total_duration:.1f} seconds")
                print(f"📦 Collected chunks: {len(self.frames)}")
                print("💡 Data was not sent (early termination)")
            return
        except Exception as e:
            print(f"❌ Error during recording: {e}")
            self.is_recording = False

        if not self.is_recording:
            total_duration = time.time() - start_time
            print(f"\n📊 Recording ended after {total_duration:.1f} seconds")
            print(f"📦 Collected chunks: {len(self.frames)}")

            with self.lock:
                if self.frames:
                    print("💾 Sending remaining data...")
                    self.save_and_send(reset_frames=False)

            self.stop()

    def stop(self):
        """Stop recording and cleanup"""
        self.is_recording = False
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'audio') and self.audio:
            self.audio.terminate()
        print("⏹ Recording stopped and resources released.")


# --- MAIN PROGRAM ---
if __name__ == "__main__":
    # Set current episode in backend
    try:
        response = requests.post(
            f"{BACKEND_URL}/api/set-episode",
            json={"episode_key": CURRENT_SHOW},
            timeout=5
        )
        if response.ok:
            print(f"✅ Episode set in backend: {CURRENT_SHOW}")
        else:
            print(f"⚠️ Could not set episode in backend: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Could not set episode in backend: {e}")
        print("   (Backend may not be running)")

    recorder = VADRecorder()

    # Terminal input for manual sending
    def stdin_listener():
        """Read input from terminal (blocking in separate thread)"""
        print("\n⌨️ Terminal input enabled:")
        print("   Type 's' + Enter to manually send an audio block")
        print("   Type 'q' + Enter to quit")
        print("   (Recording continues after sending)")
        print("   💡 Important: Make sure the terminal window is focused!\n")

        if not sys.stdin.isatty():
            print("⚠️ Warning: stdin not in TTY mode. Terminal input may not work.")

        try:
            while recorder.is_recording:
                try:
                    line = input().strip().lower()

                    if line == 's':
                        print("⌨️ 's' detected - sending block...")
                        recorder.manual_send()
                    elif line == 'q' or line == 'quit':
                        print("\n⚠️ Quitting by user input...")
                        recorder.is_recording = False
                        break
                    elif line:
                        print(f"💡 Unknown command: '{line}'. Use 's' to send or 'q' to quit.")
                except (EOFError, KeyboardInterrupt):
                    break
                except Exception as e:
                    print(f"⚠️ Input error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Terminal input listener ended: {e}")

    # Try global keyboard listener (if permissions available)
    keyboard_listener = None
    try:
        def on_press(key):
            try:
                if key == keyboard.Key.f10:
                    print("⌨️ F10 detected (global)")
                    recorder.manual_send()
            except:
                pass

        keyboard_listener = keyboard.Listener(on_press=on_press)
        keyboard_listener.start()
        print("⌨️ Global keyboard listener enabled (F10)")
    except Exception as e:
        print(f"⚠️ Global keyboard listener not available: {e}")
        print("   (Using terminal input instead)")

    # Start terminal input listener in separate thread
    stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
    stdin_thread.start()

    # Start recording (blocking)
    recorder.record()

    # Cleanup
    if keyboard_listener:
        keyboard_listener.stop()
    print("👋 Program ended.")
