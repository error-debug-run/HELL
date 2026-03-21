# core/orchestrator.py

import asyncio
from pipeline.extractor import extract_entities

class Orchestrator:
    """
    Central router for HELL.
    Receives intent result from pipeline.
    Extracts entities.
    Calls the correct handler.
    Reports result back.
    """

    def __init__(self):
        self.handlers = {}
        self._register_handlers()

    def _register_handlers(self):
        """
        Map intent names to handler functions.
        Adding a new intent = one new line here.
        """
        from intents.library.startup_mode  import run as startup_run
        # from intents.library.dev_mode      import run as dev_run
        # from intents.library.game_mode     import run as game_run
        from intents.library.app_control   import run as app_run

        self.handlers = {
            "startup_mode":  startup_run,
            # "dev_mode":      dev_run,
            # "game_mode":     game_run,
            "open_app":      app_run,
            "kill_app":      app_run,
            "close_app":     app_run,
            "hide_app":      app_run,
            # "stop_hell":     self._stop,
            "system_status": self._system_status,
        }

    async def route(self, intent_result: dict):
        """
        Main routing function.
        Called by pipeline with intent result dict.
        """
        intent     = intent_result["intent"]
        confidence = intent_result["confidence"]
        text       = intent_result["text"]
        entities = extract_entities(intent, text)
        entities["intent"] = intent

        print(f"\n  routing: {intent} ({confidence}%)")

        # find handler
        handler = self.handlers.get(intent)

        if not handler:
            print(f"  no handler for intent: {intent}")
            return {
                "success": False,
                "reason":  "no_handler",
                "intent":  intent,
            }

        # call handler
        try:
            result = await handler(entities)
            print(f"  {intent} → {'✓' if result['success'] else '✗'}")
            return result

        except Exception as e:
            print(f"  handler error: {e}")
            return {
                "success": False,
                "reason":  str(e),
                "intent":  intent,
            }
    #
    # async def _stop(self, entities: dict):
    #     """Stop HELL gracefully."""
    #     print("  HELL shutting down...")
    #     raise SystemExit(0)

    async def _system_status(self, entities: dict):
        """Quick system status check."""
        import psutil
        cpu  = psutil.cpu_percent(interval=1)
        ram  = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        print(f"  CPU:  {cpu}%")
        print(f"  RAM:  {ram}%")
        print(f"  Disk: {disk}%")

        return {
            "success": True,
            "data": {
                "cpu":  cpu,
                "ram":  ram,
                "disk": disk,
            }
        }