import json
import sys


turn = 0

for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        context = repr(line[max(0, exc.pos - 80) : exc.pos + 80])
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"invalid fixture request at {exc.pos}: {context}",
                }
            ),
            flush=True,
        )
        continue
    request_type = request.get("type")

    if request_type == "generate_turn":
        turn += 1
        result = {
            "ok": True,
            "result": {
                "final_text": f"bridge turn {turn}",
                "tool_calls": [],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                    "cached_prompt_tokens": 80,
                    "cache_miss_prompt_tokens": 20,
                },
            },
        }
        print(json.dumps(result), flush=True)
    elif request_type == "healthcheck":
        print(json.dumps({"ok": True, "message": "counting bridge ok"}), flush=True)
    elif request_type == "shutdown":
        print(json.dumps({"ok": True, "message": "shutdown"}), flush=True)
        break
    else:
        print(json.dumps({"ok": False, "error": "unknown request"}), flush=True)
