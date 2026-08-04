import json
import sys


for stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="strict")


MIN_PYTHON = (3, 10)


def _run_version_error_worker():
    actual = ".".join(str(part) for part in sys.version_info[:3])
    error = {
        "ok": False,
        "error": f"Python 3.10+ is required by candle-cli bridge; found {actual}",
    }
    for line in sys.stdin:
        if not line.strip():
            continue
        print(json.dumps(error), flush=True)
        try:
            if json.loads(line).get("type") == "shutdown":
                break
        except (TypeError, ValueError):
            pass


if sys.version_info < MIN_PYTHON:
    _run_version_error_worker()
    sys.exit(0)

from bridge_protocol import decode_request, encode_error, encode_ok
from bridge_runtime import BridgeRuntime

runtime = BridgeRuntime()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    try:
        request = decode_request(line)
        request_type = request.get("type")
        if request_type == "healthcheck":
            print(encode_ok(runtime.health()), flush=True)
        elif request_type == "generate_turn":
            print(encode_ok(runtime.generate_turn(request.get("request", {}))), flush=True)
        elif request_type == "shutdown":
            print(encode_ok({"message": "shutdown"}), flush=True)
            break
        else:
            print(encode_error("unknown request"), flush=True)
    except Exception as exc:
        print(encode_error(str(exc)), flush=True)
