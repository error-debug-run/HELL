# hell/stt/detector.py

import asyncio
import numpy as np
from config import config
from stt.listener import AudioListener
from stt.transcriber import Transcriber
from api.server import audio_state

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


class WakeWordDetector:

    IDLE    = "idle"
    ACTIVE  = "active"    # ← replaces COMMAND — stays active forever
    COMMAND = "command"   # ← sub-state within ACTIVE — capturing right now

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
        self._running            = True
        audio_state["recording"] = True
        audio_state["mode"]      = "idle"
        print(f"  wake word detector ready — waiting for '{self.wake_word}'",
              flush=True)

    def stop(self):
        self.listener.stop()
        self._running            = False
        audio_state["recording"] = False
        audio_state["mode"]      = "idle"
        print("  wake word detector stopped")

    async def run(self):
        while self._running:
            await asyncio.sleep(self.slide_every)

            if not self.listener.has_sound():
                continue

            if self.mode == self.IDLE:
                await self._check_wake_word()

            elif self.mode == self.ACTIVE:
                await self._capture_command()

    async def _check_wake_word(self):
        """IDLE mode — cheap check for wake word only."""
        energy = self.listener.get_energy()
        if energy < self.transcribe_threshold:
            return

        audio      = self.listener.get_window()
        transcript = self.transcriber.transcribe(audio)

        if not transcript or is_hallucination(transcript):
            return

        print(f"  heard: '{transcript}'")

        if self.wake_word in transcript:
            print(f"  wake word detected → ACTIVE")
            self.mode           = self.ACTIVE
            audio_state["mode"] = "active"

            # clear buffer — don't include wake word in first command
            self.listener.buffer = np.zeros(
                len(self.listener.buffer),
                dtype=np.float32
            )

    async def _capture_command(self):
        """
        ACTIVE mode — listen for next command.
        Stays in ACTIVE after each command.
        Only returns to IDLE on sleep word or stop().
        """
        audio_state["mode"] = "command"
        print(f"  listening for command ({self.command_timeout}s)...")
        await asyncio.sleep(self.command_timeout)

        audio      = self.listener.get_window(seconds=self.command_timeout)
        command    = self.transcriber.transcribe(audio)

        # clear buffer after each capture
        self.listener.buffer = np.zeros(
            len(self.listener.buffer),
            dtype=np.float32
        )

        if not command or is_hallucination(command):
            # nothing heard — stay active, keep listening
            audio_state["mode"] = "active"
            print("  nothing heard — still listening...")
            return

        # sleep word → back to IDLE
        if self.sleep_word in command.lower():
            print(f"  sleep word heard → going idle")
            self.mode           = self.IDLE
            audio_state["mode"] = "idle"
            return

        # valid command — process it, stay ACTIVE
        print(f"  command: '{command}'")
        audio_state["mode"] = "active"

        if self.on_command:
            await self.on_command(command)

        # stay in ACTIVE — ready for next command immediately
        print(f"  ready for next command...")


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