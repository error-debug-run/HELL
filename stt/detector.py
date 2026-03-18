# hell/stt/detector.py

import asyncio
import numpy as np
from config import config
from stt.listener import AudioListener
from stt.transcriber import Transcriber

# ── hallucination filter ──────────────────────────────────────────

HALLUCINATIONS = [
    "thank you for watching",
    "see you in the next video",
    "bye bye",
    "please subscribe",
    "i'll see you next time",
    "thanks for watching",
    "subtitles by",
    "transcribed by",
    "www.",
    ".com",
]

def is_hallucination(transcript):
    t = transcript.lower().strip()

    if len(t) < 3:
        return True

    for phrase in HALLUCINATIONS:
        if phrase in t:
            return True

    words = t.split()
    if len(words) >= 2:
        unique = set(words)
        if len(unique) / len(words) < 0.5:
            return True

    return False

# ── detector ─────────────────────────────────────────────────────

class WakeWordDetector:

    IDLE    = "idle"
    COMMAND = "command"

    def __init__(self):
        self.wake_word            = config.stt["wake_word"].lower()
        self.sleep_word           = config.stt["sleep_word"].lower()
        self.slide_every          = config.stt["slide_every"]
        self.command_timeout      = config.stt["command_timeout"]
        self.transcribe_threshold = config.stt["transcribe_threshold"]
        self.mode                 = self.IDLE
        self.on_command           = None
        self.listener             = AudioListener()
        self.transcriber          = Transcriber()
        self._running             = False

    def start(self):
        self.transcriber.load()
        self.listener.start()
        self._running = True
        print(f"  wake word detector ready — waiting for '{self.wake_word}'")

    def stop(self):
        self.listener.stop()
        self._running = False
        print("  wake word detector stopped")

    async def run(self):
        while self._running:
            await asyncio.sleep(self.slide_every)

            if not self.listener.has_sound():
                continue

            if self.mode == self.IDLE:
                await self._check_wake_word()
            elif self.mode == self.COMMAND:
                await self._capture_command()

    async def _check_wake_word(self):
        # strict energy gate
        energy = self.listener.get_energy()
        if energy < self.transcribe_threshold:
            return

        audio      = self.listener.get_window()
        transcript = self.transcriber.transcribe(audio)

        print(f"  energy: {energy:.4f}  transcript: '{transcript}'")

        if not transcript:
            return

        # hallucination filter
        if is_hallucination(transcript):
            print(f"  filtered: '{transcript}'")
            return

        print(f"  heard: '{transcript}'")

        # wake word check
        if self.wake_word in transcript:
            print(f"  wake word detected → listening for command")
            self.mode = self.COMMAND
            # clear buffer so command doesn't include wake word audio
            self.listener.buffer = np.zeros(
                len(self.listener.buffer),
                dtype=np.float32
            )

    async def _capture_command(self):
        print(f"  capturing command for {self.command_timeout}s...")
        await asyncio.sleep(self.command_timeout)

        audio   = self.listener.get_window(seconds=self.command_timeout)
        command = self.transcriber.transcribe(audio)

        self.mode = self.IDLE

        if command and not is_hallucination(command):
            print(f"  command: '{command}'")
            if self.on_command:
                await self.on_command(command)
        else:
            print("  no command heard — back to idle")


if __name__ == "__main__":

    from pipeline.pipeline import handle_command

    async def main():
        detector            = WakeWordDetector()
        detector.on_command = handle_command
        detector.start()

        print(f"\nSay '{detector.wake_word}' to activate")
        print("Then speak your command")
        print("Ctrl+C to stop\n")

        try:
            await detector.run()
        except KeyboardInterrupt:
            detector.stop()

    asyncio.run(main())