# hell/main.py

import asyncio
import threading
import uvicorn
from api.server import app, audio_state
from core.log import logger

logger.set_debug(True)


async def start_stt():
    """Start the wake word detector."""
    from stt.detector import WakeWordDetector
    from pipeline.pipeline import handle_command

    logger.info("stt_init")

    detector            = WakeWordDetector()
    detector.on_command = handle_command
    detector.start()

    logger.info("stt_detector_started")

    print("  STT detector running")

    try:
        await detector.run()
    except Exception as e:
        logger.critical("stt_crash", error=str(e))


def run_api():
    """Run FastAPI in a thread."""
    logger.info("api_start")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning"
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

    logger.info("hell_start")

    print("\n  HELL starting...")

    # start API in background thread
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    logger.info("api_thread_started")

    print("  API running on http://127.0.0.1:8000")

    try:
        asyncio.run(start_stt())
    except KeyboardInterrupt:
        logger.info("hell_shutdown_keyboard")
    except Exception as e:
        logger.critical("hell_shutdown_crash", error=str(e))
