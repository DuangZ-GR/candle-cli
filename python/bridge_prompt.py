import json


def extract_latest_user_text(request: dict) -> str:
    messages = json.loads(request.get("messages_json", "[]"))
    for message in reversed(messages):
        if message.get("role") == "User":
            for block in message.get("blocks", []):
                text_block = block.get("Text")
                if text_block and text_block.get("text"):
                    return text_block["text"]
    return ""
