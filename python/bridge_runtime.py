from bridge_prompt import extract_latest_user_text


class BridgeRuntime:
    def __init__(self):
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            self._initialized = True

    def health(self) -> dict:
        return {"message": "bridge worker ok"}

    def generate_turn(self, request: dict) -> dict:
        self._ensure_initialized()
        user_text = extract_latest_user_text(request)
        return {
            "result": {
                "final_text": f"generated: {user_text}",
                "tool_calls": [],
            }
        }
