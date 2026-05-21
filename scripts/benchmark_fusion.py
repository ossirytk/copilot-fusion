"""Simple benchmark harness for copilot-fusion startup and core calls."""

from __future__ import annotations

import asyncio
import time
from statistics import mean

from copilot_fusion.server import create_server


async def _measure_once() -> dict[str, float]:
    started = time.perf_counter()
    server = create_server()
    create_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    tools = await server.list_tools()
    list_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    await server.call_tool("fusion_health", {})
    health_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    await server.call_tool("fusion_api_compat", {})
    compat_elapsed = time.perf_counter() - started

    return {
        "create_server_ms": create_elapsed * 1000,
        "list_tools_ms": list_elapsed * 1000,
        "fusion_health_ms": health_elapsed * 1000,
        "fusion_api_compat_ms": compat_elapsed * 1000,
        "tool_count": float(len(tools)),
    }


async def _run(iterations: int) -> None:
    samples = [await _measure_once() for _ in range(iterations)]
    keys = ("create_server_ms", "list_tools_ms", "fusion_health_ms", "fusion_api_compat_ms", "tool_count")
    print(f"iterations={iterations}")
    for key in keys:
        print(f"{key}={mean(sample[key] for sample in samples):.3f}")


def main() -> None:
    asyncio.run(_run(iterations=10))


if __name__ == "__main__":
    main()
