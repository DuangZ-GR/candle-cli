import sys

from bridge_protocol import decode_request, encode_error, encode_ok
from bridge_runtime import BridgeRuntime

runtime = BridgeRuntime()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    request = decode_request(line)
    match request.get("type"):
        case "healthcheck":
            print(encode_ok(runtime.health()), flush=True)
        case "generate_turn":
            print(encode_ok(runtime.generate_turn(request.get("request", {}))), flush=True)
        case "shutdown":
            print(encode_ok({"message": "shutdown"}), flush=True)
            break
        case _:
            print(encode_error("unknown request"), flush=True)
