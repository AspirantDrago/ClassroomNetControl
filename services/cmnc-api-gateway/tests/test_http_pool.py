import asyncio
from cmnc_api_gateway.clients import ServiceClient


def test_service_client_reuses_connection_and_closes_pool():
    async def run():
        connections = 0
        async def handle(reader, writer):
            nonlocal connections
            connections += 1
            try:
                while await reader.readuntil(b"\r\n\r\n"):
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nContent-Type: application/json\r\n\r\n{"ok":true}')
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        client = ServiceClient(f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}")
        await client.start()
        pool = client._client
        try:
            assert await client.get_json("/first", timeout_seconds=1) == {"ok": True}
            assert await client.get_json("/second", timeout_seconds=1) == {"ok": True}
            assert connections == 1
        finally:
            await client.close()
            server.close()
            await server.wait_closed()
        assert pool.is_closed
        assert client._client is None
    asyncio.run(run())
