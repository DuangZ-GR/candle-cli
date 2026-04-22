import json


def decode_request(line: str) -> dict:
    return json.loads(line)


def encode_ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload})


def encode_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message})
