# hell/pipeline/intent.py

from pipeline.classifier import TFIDFEngine
from pipeline.dataset    import HELL_DATASET

# train once on import
_model = TFIDFEngine()
_model.fit(HELL_DATASET)

CONFIDENCE_THRESHOLD = 40.0

def detect(text: str) -> dict:
    """
    Main entry point.
    Takes raw text → returns intent result dict.

    Returns:
        {
            "intent":     "game_mode",
            "confidence": 94.0,
            "text":       "game mode",
            "understood": True
        }
    """
    # clean wake word bleed if present
    text = text.strip().lower()

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
    ]

    print("HELL Intent Classifier")
    print("─" * 50)
    for t in tests:
        result = detect(t)
        status = "✓" if result["understood"] else "✗"
        print(f"{status} '{t}'")
        print(f"  → {result['intent']}  ({result['confidence']}%)")
    print("─" * 50)