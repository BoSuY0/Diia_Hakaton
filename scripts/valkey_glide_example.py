from __future__ import annotations

import asyncio
import os
from glide import GlideClusterClient, GlideClusterClientConfiguration, NodeAddress


def _load_addresses() -> list[NodeAddress]:
    addresses_env = os.getenv("VALKEY_ADDRESSES")
    if not addresses_env:
        raise SystemExit("VALKEY_ADDRESSES is not set (expected comma-separated host:port)")
    result: list[NodeAddress] = []
    for part in addresses_env.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            host, port = part.split(":", 1)
            port_int = int(port)
        else:
            host, port_int = part, 6379
        result.append(NodeAddress(host, port_int))
    return result


async def main() -> None:
    addresses = _load_addresses()
    use_tls = os.getenv("VALKEY_USE_TLS", "true").lower() == "true"
    config = GlideClusterClientConfiguration(addresses=addresses, use_tls=use_tls)
    client = await GlideClusterClient.create(config)
    try:
        await client.set("key", "value")
        value = await client.get("key")
        print("GET key:", value)
        print("PING:", await client.ping())
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
