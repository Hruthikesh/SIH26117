"""A local DNS sinkhole: answers every query NXDOMAIN. Used by seal tests/demos so that
software insisting on a resolver gets a fast, honest 'no' instead of a timeout."""

from __future__ import annotations

import asyncio
import contextlib


def _nxdomain_response(query: bytes) -> bytes:
    if len(query) < 12:
        return b""
    transaction_id = query[:2]
    flags = (0x8183).to_bytes(2, "big")  # response, recursion available, NXDOMAIN
    counts = query[4:6] + b"\x00\x00\x00\x00\x00\x00"  # echo QDCOUNT, zero the rest
    return transaction_id + flags + counts + query[12:]


class _SinkProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.queries = 0

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.queries += 1
        if self.transport is not None:
            response = _nxdomain_response(data)
            if response:
                self.transport.sendto(response, addr)


class DnsSink:
    def __init__(self, host: str = "127.0.0.1", port: int = 5353) -> None:
        self.host = host
        self.port = port
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _SinkProtocol | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, self._protocol = await loop.create_datagram_endpoint(
            _SinkProtocol, local_addr=(self.host, self.port)
        )

    @property
    def queries(self) -> int:
        return self._protocol.queries if self._protocol else 0

    def stop(self) -> None:
        if self._transport is not None:
            with contextlib.suppress(Exception):
                self._transport.close()
            self._transport = None
