"""
Audio Listener for Live Fact-Checking

Captures audio from BlackHole virtual audio device and sends audio blocks
to the backend at fixed intervals for processing.
"""

import pyaudio
import wave
import threading
import requests
import time
import io
from pathlib import Path

# Keyboard listener for manual sending
try:
    from pynput import keyboard
except ImportError:
    print("pynput not found. Install with: uv sync")
    exit(1)

# --- CONFIGURATION ---
import sys
import os
from config import get_info, DEFAULT_SHOW

# Backend URL
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
AUDIO_ENDPOINT = f"{BACKEND_URL}/api/audio-block"

# Recording settings
BLOCK_DURATION = 180  # Send audio block every 3 minutes
FORMAT = pyaudio.paInt16
CHANNELS = 1  # Mono
DEVICE_RATE = 48000  # BlackHole runs at 48 kHz
CHUNK = 1024
PROGRESS_INTERVAL = 30  # Print progress every 30 seconds


def get_current_show():
    """Determine current show from parameter, env var, or default"""
    # 1. Command line parameter (e.g., python listener.py test)
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        show_key = sys.argv[1].lower()
        print(f"Show from parameter: {show_key}")
        return show_key

    # 2. Environment variable (e.g., SHOW=test python listener.py)
    env_show = os.environ.get('SHOW')
    if env_show:
        show_key = env_show.lower()
        print(f"Show from environment: {show_key}")
        return show_key

    # 3. Fallback: DEFAULT_SHOW from config.py
    print(f"Using default show: {DEFAULT_SHOW}")
    return DEFAULT_SHOW


CURRENT_SHOW = get_current_show()
INFO = get_info(CURRENT_SHOW)

# Debug mode: Save each block as WAV file
DEBUG_MODE = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes') or '--debug' in sys.argv
DEBUG_OUTPUT_DIR = Path(__file__).parent / "debug_audio"
if DEBUG_MODE:
    DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"Debug mode enabled. Audio blocks saved to: {DEBUG_OUTPUT_DIR}")


class AudioRecorder:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.is_recording = True
        self.chunk_count = 1
        self.lock = threading.Lock()
        self.block_start_time = time.time()

        # Find BlackHole device
        blackhole_index = self.find_blackhole_device()
        if blackhole_index is None:
            print("BlackHole not found. Using default input device.")
            print("Available devices:")
            self.list_audio_devices()
            input_device = None
        else:
            print(f"BlackHole device found (index: {blackhole_index})")
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

        print(f"Recording started...")
        print(f"  Show: {CURRENT_SHOW}")
        print(f"  Info: {INFO}")
        print(f"  Block duration: {BLOCK_DURATION}s")
        print(f"  Backend: {BACKEND_URL}")

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
            print(f"Error finding BlackHole: {e}")
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
            print(f"Error listing devices: {e}")

    def send_to_backend(self, audio_data, sequence_num):
        """Send audio data to the backend for processing"""
        print(f"Sending block {sequence_num} to backend...")
        try:
            files = {
                'audio': (f'chunk_{sequence_num}.wav', audio_data, 'audio/wav')
            }
            data = {
                'episode_key': CURRENT_SHOW,
                'info': INFO
            }

            response = requests.post(
                AUDIO_ENDPOINT,
                files=files,
                data=data,
                timeout=30
            )

            if response.ok:
                result = response.json()
                print(f"Block {sequence_num} sent successfully: {result.get('message', 'OK')}")
            else:
                print(f"Backend error: {response.status_code} - {response.text}")

        except requests.exceptions.ConnectionError:
            print(f"Cannot connect to backend at {BACKEND_URL}")
            print(f"   Make sure the backend is running: ./backend/run.sh")
        except Exception as e:
            print(f"Error sending: {e}")

    def save_and_send(self, reset_frames=True):
        """Save current frames as WAV and send to backend"""
        with self.lock:
            if not self.frames:
                print("No data to send.")
                return

            frames_to_send = self.frames.copy()

            if reset_frames:
                self.frames = []

        print(f"Saving {len(frames_to_send)} chunks...")

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
        duration = len(frames_to_send) * CHUNK / DEVICE_RATE

        # Debug mode: Save as local WAV file
        if DEBUG_MODE:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{CURRENT_SHOW}_block_{seq_num:03d}_{timestamp}.wav"
            filepath = DEBUG_OUTPUT_DIR / filename
            try:
                with open(filepath, 'wb') as f:
                    f.write(audio_content)
                print(f"Debug: Block saved as {filename} ({duration:.1f}s)")
            except Exception as e:
                print(f"Debug: Error saving: {e}")

        print(f"Block {seq_num}: {duration:.1f}s of audio")

        # Send in separate thread
        send_thread = threading.Thread(
            target=self.send_to_backend,
            args=(audio_content, seq_num),
            daemon=False
        )
        send_thread.start()

    def manual_send(self):
        """Manually send current frames and reset the block timer"""
        if not self.is_recording:
            print("Recording not active, cannot send.")
            return

        with self.lock:
            if not self.frames:
                print("No data to send (no frames recorded yet).")
                return

        print("\nManual send command received...")
        self.save_and_send(reset_frames=True)
        self.block_start_time = time.time()
        print("Manual block sent. Timer reset. Recording continues...\n")

    def record(self):
        """Main recording loop with fixed-interval sending"""
        self.block_start_time = time.time()
        last_progress_report = 0

        print(f"Recording... auto-send every {BLOCK_DURATION}s")

        try:
            while self.is_recording:
                # Read audio chunk
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                with self.lock:
                    self.frames.append(data)

                elapsed = time.time() - self.block_start_time

                # Progress report
                elapsed_int = int(elapsed)
                if elapsed_int > 0 and elapsed_int % PROGRESS_INTERVAL == 0 and elapsed_int != last_progress_report:
                    remaining = BLOCK_DURATION - elapsed
                    print(f"  Block {self.chunk_count}: {elapsed_int}s recorded, {remaining:.0f}s until auto-send")
                    last_progress_report = elapsed_int

                # Auto-send when block duration reached
                if elapsed >= BLOCK_DURATION:
                    print(f"Block duration ({BLOCK_DURATION}s) reached. Sending...")
                    self.save_and_send(reset_frames=True)
                    self.block_start_time = time.time()
                    last_progress_report = 0
                    print("Recording continues...")

        except KeyboardInterrupt:
            print("\nRecording interrupted by user")
            self.is_recording = False
            if self.frames:
                total_duration = time.time() - self.block_start_time
                print(f"Recording ended after {total_duration:.1f} seconds in current block")
                print(f"Collected chunks: {len(self.frames)}")
                print("Data was not sent (early termination)")
            return
        except Exception as e:
            print(f"Error during recording: {e}")
            self.is_recording = False

        if not self.is_recording:
            total_duration = time.time() - self.block_start_time
            print(f"\nRecording ended after {total_duration:.1f} seconds in current block")
            print(f"Collected chunks: {len(self.frames)}")

            with self.lock:
                if self.frames:
                    print("Sending remaining data...")
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
        print("Recording stopped and resources released.")


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
            print(f"Episode set in backend: {CURRENT_SHOW}")
        else:
            print(f"Could not set episode in backend: {response.status_code}")
    except Exception as e:
        print(f"Could not set episode in backend: {e}")
        print("   (Backend may not be running)")

    recorder = AudioRecorder()

    # Terminal input for manual sending
    def stdin_listener():
        """Read input from terminal (blocking in separate thread)"""
        print("\nTerminal input enabled:")
        print("   Type 's' + Enter to manually send an audio block (resets timer)")
        print("   Type 'q' + Enter to quit")
        print("   (Recording continues after sending)\n")

        if not sys.stdin.isatty():
            print("Warning: stdin not in TTY mode. Terminal input may not work.")

        try:
            while recorder.is_recording:
                try:
                    line = input().strip().lower()

                    if line == 's':
                        print("'s' detected - sending block...")
                        recorder.manual_send()
                    elif line == 'q' or line == 'quit':
                        print("\nQuitting by user input...")
                        recorder.is_recording = False
                        break
                    elif line:
                        print(f"Unknown command: '{line}'. Use 's' to send or 'q' to quit.")
                except (EOFError, KeyboardInterrupt):
                    break
                except Exception as e:
                    print(f"Input error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"Terminal input listener ended: {e}")

    # Try global keyboard listener (if permissions available)
    keyboard_listener = None
    try:
        def on_press(key):
            try:
                if key == keyboard.Key.f10:
                    print("F10 detected (global)")
                    recorder.manual_send()
            except:
                pass

        keyboard_listener = keyboard.Listener(on_press=on_press)
        keyboard_listener.start()
        print("Global keyboard listener enabled (F10)")
    except Exception as e:
        print(f"Global keyboard listener not available: {e}")
        print("   (Using terminal input instead)")

    # Start terminal input listener in separate thread
    stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
    stdin_thread.start()

    # Start recording (blocking)
    recorder.record()

    # Cleanup
    if keyboard_listener:
        keyboard_listener.stop()
    print("Program ended.")
