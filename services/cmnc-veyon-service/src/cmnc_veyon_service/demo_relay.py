"""Read-only RFB relay for browser and PC captures, authenticated by Veyon demo tokens.

Frames are shared compressed JPEGs in memory, never decoded per recipient.
Only Tight JPEG encoding is offered; arbitrary VNC control is not supported.
"""
import asyncio
import secrets
import struct
from contextlib import suppress

WIDTH, HEIGHT = 1280, 720
MAX_FRAME = 2 * 1024 * 1024
MAX_NATIVE_FRAME = (1 << 22) - 1  # Tight compact-length limit


def compact_length(size):
    result = bytearray()
    for _ in range(2):
        value = size & 127
        size >>= 7
        result.append(value | (128 if size else 0))
        if not size:
            return bytes(result)
    result.append(size)
    return bytes(result)


def jpeg_size(data, max_bytes=MAX_NATIVE_FRAME):
    if not 4 <= len(data) <= max_bytes or data[:2] != b'\xff\xd8' or data[-2:] != b'\xff\xd9':
        raise ValueError('Некорректный JPEG или слишком большой кадр. Уменьшите CMNC_VEYON_DEMO_QUALITY')
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 255:
            break
        marker = data[pos + 1]
        pos += 2
        if marker == 255:
            pos -= 1
            continue
        size = int.from_bytes(data[pos:pos + 2], 'big')
        if size < 2 or pos + size > len(data):
            break
        if marker in (192, 193, 194) and size >= 8:
            height, width = struct.unpack('!HH', data[pos + 3:pos + 7])
            if 1 <= width <= 8192 and 1 <= height <= 8192 and width * height <= 33554432:
                return width, height
            break
        if marker == 218:
            break
        pos += size
    raise ValueError('Некорректные размеры кадра JPEG')


def validate_frame(data):
    if jpeg_size(data, MAX_FRAME) != (WIDTH, HEIGHT):
        raise ValueError('Размер кадра должен быть 1280 × 720')


def variant_int(value):
    return struct.pack('!IBi', 2, 0, value)


async def message(reader):
    size, = struct.unpack('!I', await reader.readexactly(4))
    if size > 8192:
        raise ValueError('Oversized authentication message')
    return await reader.readexactly(size)


def byte_array(data):
    if len(data) < 9 or data[:5] != struct.pack('!IB', 12, 0):
        raise ValueError('Invalid authentication token')
    size, = struct.unpack('!I', data[5:9])
    if not 16 <= size <= 256 or len(data) != 9 + size:
        raise ValueError('Invalid authentication token')
    return data[9:]


class DemoRelay:
    def __init__(self, sessions):
        self.sessions = sessions
        self.server = None
        self.clients = set()
        self.tasks = set()

    async def start(self, port):
        self.server = await asyncio.start_server(self.handle, '0.0.0.0', port, limit=16384)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in list(self.clients):
            writer.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        if len(self.clients) >= 512:
            writer.close()
            self.tasks.discard(task)
            return
        self.clients.add(writer)
        try:
            async with asyncio.timeout(10):
                writer.write(b'RFB 003.008\n')
                await writer.drain()
                if await reader.readexactly(12) != b'RFB 003.008\n':
                    return
                writer.write(b'\x01\x28')
                await writer.drain()
                if await reader.readexactly(1) != b'\x28':
                    return
                auth = variant_int(1) + variant_int(5)
                writer.write(struct.pack('!I', len(auth)) + auth)
                await writer.drain()
                reply = await message(reader)
                if reply[:9] != variant_int(5):
                    return
                writer.write(b'\x00\x00\x00\x00')  # empty VariantArrayMessage ACK
                await writer.drain()
                token = byte_array(await message(reader))
                session = next((s for s in self.sessions.values() if secrets.compare_digest(s.token.encode(), token) and not s.stopping), None)
                if session is None:
                    return
                writer.write(struct.pack('!I', 0))
                await writer.drain()
                await reader.readexactly(1)
                width, height = getattr(session, 'frame_size', (WIDTH, HEIGHT))
                name = b'CMNC screen demonstration'
                pixel_format = struct.pack('!BBBBHHHBBB3x', 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
                writer.write(struct.pack('!HH', width, height) + pixel_format + struct.pack('!I', len(name)) + name)
                await writer.drain()
            tight = False
            can_resize = False
            seen = 0
            while not session.stopping and self.sessions.get(session.id) is session:
                async with asyncio.timeout(65):
                    kind = (await reader.readexactly(1))[0]
                    if kind == 0:
                        await reader.readexactly(19)
                    elif kind == 2:
                        header = await reader.readexactly(3)
                        count = int.from_bytes(header[1:], 'big')
                        if count > 256:
                            return
                        encodings = struct.unpack('!' + 'i' * count, await reader.readexactly(count * 4))
                        tight = 7 in encodings
                        can_resize = -223 in encodings
                    elif kind == 3:
                        request = await reader.readexactly(9)
                        if not tight:
                            return
                        # Wait for a newer frame without queuing old frames for slow clients.
                        async with session.changed:
                            await session.changed.wait_for(lambda: session.stopping or getattr(session, "source_error", None) or
                                (session.frame is not None and (not request[0] or session.version != seen)))
                        if session.stopping or getattr(session, 'source_error', None):
                            return
                        data, seen = session.frame, session.version
                        size = getattr(session, 'frame_size', (WIDTH, HEIGHT))
                        resize = b''
                        if size != (width, height):
                            if not can_resize:
                                return  # reconnect with the new ServerInit dimensions
                            width, height = size
                            resize = struct.pack('!HHHHi', 0, 0, width, height, -223)
                        writer.write(struct.pack('!BBH', 0, 0, 2 if resize else 1) + resize +
                                     struct.pack('!HHHHi', 0, 0, width, height, 7) +
                                     b'\x90' + compact_length(len(data)) + data)
                        await writer.drain()
                    elif kind in (4, 5):  # ignore read-only input
                        await reader.readexactly(7 if kind == 4 else 5)
                    elif kind == 6:
                        header = await reader.readexactly(7)
                        size = int.from_bytes(header[3:], 'big')
                        if size > 65536:
                            return
                        await reader.readexactly(size)
                    else:
                        return
        except (TimeoutError, ConnectionError, asyncio.IncompleteReadError, ValueError, struct.error):
            pass
        finally:
            self.clients.discard(writer)
            self.tasks.discard(task)
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
