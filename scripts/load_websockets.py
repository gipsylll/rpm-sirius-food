"""Open 100 order sockets and report event latency.
Requires ``websockets`` (``uv add websockets`` for local runs).
"""

import asyncio
import json
import os
import statistics
import time
import tracemalloc

import websockets


async def one(
    order_id: int, token: str, url: str, samples: list[float], errors: list[str]
):
    try:
        async with websockets.connect(
            f"{url}/ws/orders/{order_id}?token={token}"
        ) as socket:
            started = time.perf_counter()
            while True:
                data = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
                if data.get("type") == "ping":
                    await socket.send(json.dumps({"type": "pong"}))
                elif data.get("type") in ("snapshot", "status_update"):
                    samples.append((time.perf_counter() - started) * 1000)
                    return
    except Exception as exc:
        errors.append(str(exc))


async def main():
    token = os.environ["WS_TOKEN"]
    order_id = int(os.getenv("WS_ORDER_ID", "1"))
    count = int(os.getenv("WS_CONNECTIONS", "100"))
    url = os.getenv("WS_URL", "ws://127.0.0.1:8000")
    samples, errors = [], []
    tracemalloc.start()
    await asyncio.gather(
        *(one(order_id, token, url, samples, errors) for _ in range(count))
    )
    print(
        json.dumps(
            {
                "connections": count,
                "events": len(samples),
                "errors": len(errors),
                "p50_ms": statistics.median(samples) if samples else None,
                "p95_ms": sorted(samples)[int(len(samples) * 0.95) - 1]
                if samples
                else None,
                "peak_memory_bytes": tracemalloc.get_traced_memory()[1],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
