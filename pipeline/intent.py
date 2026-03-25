# hell/pipeline/intent.py

from pipeline.classifier import MiniLMEngine, TFIDFEngine
from pipeline.dataset import HELL_DATASET
from pathlib import Path

# ── choose engine ─────────────────────────────────────────
USE_MINILM = (Path(__file__).parent.parent / "models" / "minilm").exists()

if USE_MINILM:
    print("  using MiniLM engine")
    _model = MiniLMEngine()
    _model.load()
    _model.fit(HELL_DATASET)
else:
    print("  using TF-IDF engine (MiniLM not found)")
    _model = TFIDFEngine()
    _model.fit(HELL_DATASET)

CONFIDENCE_THRESHOLD = 40.0

def detect(text: str) -> dict:
    text               = text.strip().lower()
    intent, confidence = _model.predict(text)
    return {
        "intent":     intent,
        "confidence": confidence,
        "text":       text,
        "understood": confidence >= CONFIDENCE_THRESHOLD,
    }


if __name__ == "__main__":
    tests = [
        "game mode",
        "dev mode for hell",
        "open spotify",
        "close discord",
        "check my ping",
        "startup",
        "hide steam",
        "what is my cpu usage",
        "turn off hell",
        "abcdefg random nonsense",
        "kill discord"
    ]

    print("HELL Intent Classifier")
    print("─" * 50)
    for t in tests:
        result = detect(t)
        status = "✓" if result["understood"] else "✗"
        print(f"{status} '{t}'")
        print(f"  → {result['intent']}  ({result['confidence']}%)")
    print("─" * 50)