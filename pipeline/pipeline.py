# hell/pipeline/pipeline.py

from pipeline.intent      import detect
from core.orchestrator    import Orchestrator

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

    # clean wake word bleed
    from config import config
    wake_word = config.stt["wake_word"]
    command   = command.replace(wake_word, "").strip()

    if not command:
        print("  empty command after cleaning")
        return

    # detect intent
    result = detect(command)
    print(f"  intent: {result['intent']} ({result['confidence']}%)")

    # low confidence — don't guess
    if not result["understood"]:
        print(f"  not understood — confidence too low")
        return

    # route to handler
    await orchestrator.route(result)