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


def build_chat_messages(messages_json: str) -> list[dict]:
    """Convert Rust session messages into chat messages for the API.

    Uses a plain-text format for tool calls and results (not native OpenAI
    tool_calls) so that the conversation format stays consistent with
    the <tool_call> text protocol described in the system prompt.

    - ToolCall blocks are rendered as assistant text showing the JSON.
    - ToolResult blocks are rendered as user text showing the output.
    """
    messages = json.loads(messages_json)
    chat_messages: list[dict] = []
    for msg in messages:
        role = msg.get("role", "").lower()
        blocks = msg.get("blocks", [])

        # Build text representation from all blocks
        parts: list[str] = []
        for block in blocks:
            if "Text" in block:
                text = block["Text"].get("text", "")
                if text:
                    parts.append(text)
            elif "ToolCall" in block:
                tc = block["ToolCall"]
                parts.append(
                    '<tool_call>{"id":%s,"name":%s,"input":%s}</tool_call>'
                    % (
                        json.dumps(tc.get("id", "")),
                        json.dumps(tc.get("name", "")),
                        tc.get("input", "{}"),
                    )
                )
            elif "ToolResult" in block:
                tr = block["ToolResult"]
                label = "error" if tr.get("is_error") else "result"
                parts.append(
                    "Tool %s (call %s): %s"
                    % (
                        label,
                        tr.get("tool_call_id", ""),
                        tr.get("output", ""),
                    )
                )

        # Map Tool role messages to user role for the API
        api_role = "user" if role == "tool" else role
        chat_messages.append(
            {"role": api_role, "content": "\n".join(parts)}
        )

    return chat_messages
