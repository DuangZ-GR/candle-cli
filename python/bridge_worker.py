import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    request = json.loads(line)
    match request.get("type"):
        case "healthcheck":
            print(json.dumps({"ok": True, "message": "bridge worker ok"}), flush=True)
        case "generate_turn":
            print(
                json.dumps(
                    {
                        "ok": True,
                        "result": {
                            "final_text": "bridge response",
                            "tool_calls": [],
                        },
                    }
                ),
                flush=True,
            )
        case "shutdown":
            print(json.dumps({"ok": True, "message": "shutdown"}), flush=True)
            break
        case _:
            print(json.dumps({"ok": False, "error": "unknown request"}), flush=True)
