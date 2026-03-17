# hell/stt/transcriber.py

import numpy as np
from faster_whisper import WhisperModel
from config import config

class Transcriber:
    """
    Faster-Whisper wrapper.
    Takes raw audio array → returns transcript string.
    Runs on GPU via CUDA.
    """

    def __init__(self):
        self.model      = None
        self.model_size = config.stt["model_size"]    # "small"
        self.device     = config.stt["device"]         # "cuda"
        self.language   = config.stt["language"]       # "en"
        self.sample_rate = config.stt["sample_rate"]   # 16000

    def load(self):
        """
        Load Whisper model from local path.
        No internet required.
        """
        import os
        from pathlib import Path

        model_path = config.stt.get("model_path")

        if model_path:
            # resolve relative to project root
            full_path = Path(__file__).parent.parent / model_path

            if not full_path.exists():
                raise FileNotFoundError(
                    f"Model not found at {full_path}\n"
                    f"Download from: https://huggingface.co/guillaumekln/faster-whisper-small\n"
                    f"Place in: {full_path}"
                )

            print(f"  loading Whisper from local path: {full_path}")
            self.model = WhisperModel(
                str(full_path),
                device=self.device,
                compute_type="float32"
            )
        else:
            # fallback to downloading
            print(f"  loading Whisper {self.model_size} from HuggingFace...")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type="float32"
            )

        print(f"  Whisper ready ✓")

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcribe a numpy audio array.
        Returns lowercase transcript string.
        Returns empty string if nothing heard.
        """
        if self.model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if len(audio) == 0:
            return ""

        # faster-whisper expects float32 numpy array at 16kHz
        # which is exactly what our listener provides
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,              # beam_size=1 = fastest, good enough for commands
            vad_filter=True,          # skip silent parts automatically
            vad_parameters={
                "min_silence_duration_ms": 500
            }
        )

        # join all segments into one string
        transcript = " ".join(segment.text for segment in segments)
        return transcript.strip().lower()


if __name__ == "__main__":
    import time
    import sounddevice as sd
    from stt.listener import AudioListener

    # load model
    transcriber = Transcriber()
    transcriber.load()

    # start listener
    listener = AudioListener()
    listener.start()

    print("\nWhisper is ready. Recording 5 seconds — speak now...")
    print("─" * 40)

    time.sleep(5)

    audio      = listener.get_window(seconds=10)
    transcript = transcriber.transcribe(audio)

    print(f"Transcript: '{transcript}'")

    listener.stop()
