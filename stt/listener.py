from config import config

wake_word  = config.stt["wake_word"]        # "bring it on"
model_size = config.stt["model_size"]       # "small"
device     = config.stt["device"]           # "cuda"


# hell/stt/listener.py

import numpy as np
import sounddevice as sd
from config import config

class AudioListener:

    def __init__(self):
        self.sample_rate  = config.stt["sample_rate"]
        self.window_size  = config.stt["window_size"]
        self.buffer_size  = self.sample_rate * 10
        self.buffer       = np.zeros(self.buffer_size, dtype=np.float32)
        self._running     = False

    def _audio_callback(self, indata, frames, time, status):
        if status:
            print(f"  audio status: {status}")
        chunk      = indata[:, 0]
        chunk_size = len(chunk)
        self.buffer = np.roll(self.buffer, -chunk_size)
        self.buffer[-chunk_size:] = chunk

    def get_window(self, seconds=None):
        seconds = seconds or self.window_size
        samples = self.sample_rate * seconds
        return self.buffer[-samples:].copy()

    def has_sound(self):
        threshold = config.stt["energy_threshold"]
        window    = self.get_window()
        energy    = np.sqrt(np.mean(window ** 2))
        return float(energy) > threshold

    def get_energy(self):
        """Return raw energy value — useful for threshold calibration."""
        window = self.get_window()
        return float(np.sqrt(np.mean(window ** 2)))

    def start(self):
        device = config.stt["mic_device"]
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            blocksize=256,              # low latency
            device=device,
            latency="low",
            callback=self._audio_callback
        )
        self._stream.start()
        self._running = True
        print(f"  audio listener started — device: {device or 'system default'}")

    def stop(self):
        if self._running:
            self._stream.stop()
            self._stream.close()
            self._running = False
            print("  audio listener stopped")

    @staticmethod
    def list_devices():
        """Print all available audio input devices with their index."""
        devices = sd.query_devices()
        print("\nAvailable audio input devices:")
        print("─" * 40)
        for i, device in enumerate(devices):
            if device["max_input_channels"] > 0:
                print(f"  [{i}] {device['name']}")
        print("─" * 40)
        print("Set 'mic_device' in config.json to your device index")


if __name__ == "__main__":
    import time

    # list devices first
    AudioListener.list_devices()

    listener = AudioListener()
    listener.start()

    print("\nCalibrating — stay silent for 3 seconds...")
    time.sleep(3)
    silent_energy = listener.get_energy()
    print(f"  silent energy: {silent_energy:.4f}")

    print("\nNow speak normally...")
    time.sleep(3)
    speak_energy = listener.get_energy()
    print(f"  speaking energy: {speak_energy:.4f}")

    suggested = (silent_energy + speak_energy) / 2
    print(f"\nSuggested threshold: {suggested:.4f}")
    print(f"Set 'energy_threshold': {suggested:.4f} in config.json")

    listener.stop()

