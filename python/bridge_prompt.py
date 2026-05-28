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

            tool_call = block.get("ToolCall")
            if tool_call:
                text_parts.append(_format_tool_call(tool_call))

            tool_result = block.get("ToolResult")
            if tool_result:
                text_parts.append(_format_tool_result(tool_result))

        content = "\n".join(text_parts)
        if role == "tool":
            role = "user"
        chat_messages.append({"role": role, "content": content})
    return chat_messages


def _format_tool_call(tool_call: dict) -> str:
    input_value = tool_call.get("input", "{}")
    try:
        input_json = json.loads(input_value) if isinstance(input_value, str) else input_value
    except json.JSONDecodeError:
        input_json = {}

    payload = {
        "id": tool_call.get("id", "call-unknown"),
        "name": tool_call.get("name", "unknown"),
        "input": input_json,
    }
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"<tool_call>{compact}</tool_call>"


def _format_tool_result(tool_result: dict) -> str:
    tool_call_id = tool_result.get("tool_call_id", "call-unknown")
    output = tool_result.get("output", "")
    is_error = bool(tool_result.get("is_error", False))
    prefix = "Tool error" if is_error else "Tool result"
    return f"{prefix} for {tool_call_id}:\n{output}"
