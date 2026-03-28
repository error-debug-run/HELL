# hell/pipeline/pipeline.py

from pipeline.intent import detect
from core.orchestrator    import Orchestrator
from core.log import logger   # ← ADDED

orchestrator = Orchestrator()

async def handle_command(command: str):
    """
    Entry point for all commands.
    Called by STT detector on_command callback.
    Called by hotkey handler.
    Called by CLI.
    All roads lead here.
    """
    print(f"\n  command received: '{command}'")
    logger.info("command_received", raw=command)   # ← ADDED

    # clean wake word bleed
    from config import config
    wake_word = config.stt["wake_word"]
    command   = command.replace(wake_word, "").strip()

    logger.debug("command_cleaned", wake_word=wake_word, cleaned=command)   # ← ADDED

    if not command:
        print("  empty command after cleaning")
        logger.warning("empty_command_after_clean")   # ← ADDED
        return

    # detect intent
    result = detect(command)

    logger.info(
        "intent_detected",
        intent=result.get("intent"),
        confidence=result.get("confidence"),
        understood=result.get("understood")
    )   # ← ADDED

    print(f"  intent: {result['intent']} ({result['confidence']}%)")

    # low confidence — don't guess
    if not result["understood"]:
        print(f"  not understood — confidence too low")
        logger.warning(
            "intent_not_understood",
            intent=result.get("intent"),
            confidence=result.get("confidence")
        )   # ← ADDED
        return

    logger.info("routing_to_orchestrator", intent=result.get("intent"))   # ← ADDED

    # route to handler
    await orchestrator.route(result)

    logger.info("command_handled_complete", intent=result.get("intent"))   # ← ADDED