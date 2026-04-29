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


def build_chat_messages(messages_json: str) -> list[dict[str, str]]:
    messages = json.loads(messages_json)
    chat_messages: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role", "").lower()
        text_parts = []
        for block in msg.get("blocks", []):
            text_block = block.get("Text")
            if text_block and text_block.get("text"):
                text_parts.append(text_block["text"])
        content = "\n".join(text_parts)
        chat_messages.append({"role": role, "content": content})
    return chat_messages
