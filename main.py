# hell/main.py

import asyncio
import threading
import uvicorn
from api.server import app, audio_state

async def start_stt():
    """Start the wake word detector."""
    from stt.detector import WakeWordDetector
    from pipeline.pipeline import handle_command

    detector            = WakeWordDetector()
    detector.on_command = handle_command
    detector.start()

    print("  STT detector running")
    await detector.run()

def run_api():
    """Run FastAPI in a thread."""
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning"    # quieter output
    )

if __name__ == "__main__":
    import sys
    import io

    # force UTF-8 output — fixes Windows console encoding
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
        line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding="utf-8",
        errors="replace",
        line_buffering=True
    )
    print("\n  HELL starting...")

    # start API in background thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    print("  API running on http://127.0.0.1:8000")

    # run STT in main async loop
    asyncio.run(start_stt())