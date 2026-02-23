"""
Audio Listener for Live Fact-Checking

Captures audio from BlackHole virtual audio device and sends audio blocks
to the backend at fixed intervals for processing.
"""

import io
import os
import sys
import threading
import time
import wave
from pathlib import Path

import pyaudio
import requests

from config import get_info, DEFAULT_SHOW

# Audio constants
FORMAT = pyaudio.paInt16
CHANNELS = 1  # Mono
DEVICE_RATE = 48000  # BlackHole runs at 48 kHz
CHUNK = 1024
PROGRESS_INTERVAL = 30  # Print progress every 30 seconds
BLOCK_DURATION = 120  # Send audio block every 120 seconds (default)


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


def set_backend_episode(backend_url, show):
    """Set current episode in backend"""
    try:
        response = requests.post(
            f"{backend_url}/api/set-episode",
            json={"episode_key": show},
            timeout=5
        )
        if response.ok:
            print(f"Episode set in backend: {show}")
        else:
            print(f"Could not set episode in backend: {response.status_code}")
    except Exception as e:
        print(f"Could not set episode in backend: {e}")
        print("   (Backend may not be running)")


class AudioRecorder:
    def __init__(self, show: str, info: str, backend_url: str, block_duration: int = BLOCK_DURATION, debug: bool = False):
        self.show = show
        self.info = info
        self.backend_url = backend_url
        self.audio_endpoint = f"{backend_url}/api/audio-block"
        self.block_duration = block_duration
        self.debug = debug
        self.debug_output_dir = Path(__file__).parent / "debug_audio"

        if self.debug:
            self.debug_output_dir.mkdir(exist_ok=True)
            print(f"Debug mode enabled. Audio blocks saved to: {self.debug_output_dir}")

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

        print("Recording started...")
        print(f"  Show: {self.show}")
        print(f"  Info: {self.info}")
        print(f"  Block duration: {self.block_duration}s")
        print(f"  Backend: {self.backend_url}")

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

    def _build_wav(self, frames: list[bytes]) -> bytes:
        """Encode raw audio frames as WAV data"""
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(FORMAT))
            wf.setframerate(DEVICE_RATE)
            wf.writeframes(b''.join(frames))
        return buffer.getvalue()

    def send_to_backend(self, audio_data, sequence_num):
        """Send audio data to the backend for processing"""
        print(f"Sending block {sequence_num} to backend...")
        try:
            files = {
                'audio': (f'chunk_{sequence_num}.wav', audio_data, 'audio/wav')
            }
            data = {
                'episode_key': self.show,
                'info': self.info
            }

            response = requests.post(
                self.audio_endpoint,
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
            print(f"Cannot connect to backend at {self.backend_url}")
            print("   Make sure the backend is running: ./backend/run.sh")
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

        audio_content = self._build_wav(frames_to_send)
        duration = len(frames_to_send) * CHUNK / DEVICE_RATE

        # Debug mode: Save as local WAV file
        if self.debug:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{self.show}_block_{seq_num:03d}_{timestamp}.wav"
            filepath = self.debug_output_dir / filename
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
            daemon=True
        )
        send_thread.start()
        return send_thread

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

    def _flush_and_stop(self):
        """Send remaining frames, release resources, and force exit."""
        total_duration = time.time() - self.block_start_time
        print(f"\nRecording ended after {total_duration:.1f} seconds in current block")
        with self.lock:
            num_frames = len(self.frames)
            has_frames = bool(self.frames)
        print(f"Collected chunks: {num_frames}")
        if has_frames:
            print("Sending remaining data...")
            send_thread = self.save_and_send(reset_frames=False)
            if send_thread:
                send_thread.join(timeout=10)
                if send_thread.is_alive():
                    print("Send timed out, exiting anyway.")
        self.stop()
        os._exit(0)

    def record(self):
        """Main recording loop with fixed-interval sending"""
        self.block_start_time = time.time()
        last_progress_report = 0

        print(f"Recording... auto-send every {self.block_duration}s")

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
                    remaining = self.block_duration - elapsed
                    print(f"  Block {self.chunk_count}: {elapsed_int}s recorded, {remaining:.0f}s until auto-send")
                    last_progress_report = elapsed_int

                # Auto-send when block duration reached
                if elapsed >= self.block_duration:
                    print(f"Block duration ({self.block_duration}s) reached. Sending...")
                    self.save_and_send(reset_frames=True)
                    self.block_start_time = time.time()
                    last_progress_report = 0
                    print("Recording continues...")

        except KeyboardInterrupt:
            print("\nRecording interrupted by user")
        finally:
            self.is_recording = False
            self._flush_and_stop()

    def stop(self):
        """Stop recording and cleanup"""
        self.is_recording = False
        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'audio') and self.audio:
            self.audio.terminate()
        print("Recording stopped and resources released.")


def setup_input_listeners(recorder):
    """Set up stdin and global keyboard listeners. Returns a cleanup callable."""
    # Terminal input for manual sending
    def stdin_listener():
        """Read input from terminal (blocking in separate thread)"""
        print("\nControls:")
        print("   F10        - manually send current audio block (resets timer)")
        print("   Ctrl+C     - stop recording and exit\n")

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

    # Try global keyboard listener (if pynput available and permissions granted)
    keyboard_listener = None
    try:
        from pynput import keyboard

        def on_press(key):
            try:
                if key == keyboard.Key.f10:
                    print("F10 detected (global)")
                    recorder.manual_send()
            except Exception:
                pass

        keyboard_listener = keyboard.Listener(on_press=on_press)
        keyboard_listener.start()
        print("Global keyboard listener enabled (F10)")
    except ImportError:
        print("pynput not found. Install with: uv sync")
        print("   (Using terminal input only)")
    except Exception as e:
        print(f"Global keyboard listener not available: {e}")
        print("   (Using terminal input instead)")

    # Start terminal input listener in separate thread
    stdin_thread = threading.Thread(target=stdin_listener, daemon=True)
    stdin_thread.start()

    def cleanup():
        if keyboard_listener:
            keyboard_listener.stop()

    return cleanup


def main():
    show = get_current_show()
    info = get_info(show)
    debug = os.environ.get('DEBUG', '').lower() in ('true', '1', 'yes') or '--debug' in sys.argv
    backend_url = os.getenv("BACKEND_URL", "http://localhost:5000")

    set_backend_episode(backend_url, show)

    recorder = AudioRecorder(show, info, backend_url, debug=debug)
    cleanup = setup_input_listeners(recorder)

    recorder.record()

    cleanup()
    print("Program ended.")


if __name__ == "__main__":
    main()
