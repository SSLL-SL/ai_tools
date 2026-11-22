import asyncio
import struct

from .bencode import encode


class PeerError(Exception):
    pass


class MessageType:
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOT_INTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7
    CANCEL = 8
    EXTENDED = 20


PEX_LOCAL_ID = 1
METADATA_LOCAL_ID = 2


class PeerConnection:
    def __init__(self, peer_id: bytes, info_hash: bytes, ip: str, port: int, client):
        self.peer_id = peer_id
        self.info_hash = info_hash
        self.ip = ip
        self.port = port
        self.pex_address = (ip, port)
        self.client = client
        self.reader = None
        self.writer = None
        self.connected = False
        self.peer_choking = True
        self.am_choking = True
        self.supports_extensions = False
        self.bitfield = bytearray()
        self.bitfield_sent = False
        self.assigned_piece = None
        self.outstanding = set()
        self.remote_extensions = {}
        self.pex_announced = set()
        self.metadata_size = None
        self.metadata_queue = []
        self.metadata_outstanding = set()
        self.pending_bitfield = None
        self.pending_have = set()

    async def connect(self, timeout: float = 10.0):
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port), timeout=timeout
            )
            await asyncio.wait_for(self._handshake(), timeout=timeout)
            self.connected = True
            if self.supports_extensions:
                await self.send_extension_handshake()
        except Exception as exc:
            await self.close()
            raise PeerError(f"Connection to {self.ip}:{self.port} failed: {exc}") from exc

    async def _handshake(self):
        reserved = bytearray(8)
        reserved[5] |= 0x10  # BEP 10: supports the extension protocol.
        request = b"\x13BitTorrent protocol" + bytes(reserved) + self.info_hash + self.peer_id
        self.writer.write(request)
        await self.writer.drain()
        response = await self.reader.readexactly(68)
        if response[0] != 19 or response[1:20] != b"BitTorrent protocol":
            raise PeerError("Peer returned an invalid handshake")
        if response[28:48] != self.info_hash:
            raise PeerError("Peer returned a different info hash")
        if response[48:68] == self.peer_id:
            raise PeerError("Peer returned our own peer ID")
        self.supports_extensions = bool(response[25] & 0x10)

    async def send_message(self, message_id: int, payload: bytes = b""):
        if not self.connected or self.writer is None:
            return
        self.writer.write(struct.pack("!I", len(payload) + 1) + bytes((message_id,)) + payload)
        await self.writer.drain()

    async def send_interested(self):
        await self.send_message(MessageType.INTERESTED)

    async def send_extension_handshake(self):
        fields = {
            b"m": {b"ut_pex": PEX_LOCAL_ID, b"ut_metadata": METADATA_LOCAL_ID},
            b"reqq": 128,
            b"v": b"PythonTorrent 0.1",
        }
        torrent = getattr(self.client, "torrent", None)
        if torrent:
            fields[b"metadata_size"] = len(torrent.info.raw_info)
        handshake = encode(fields)
        await self.send_message(MessageType.EXTENDED, b"\0" + handshake)

    async def send_pex(self, payload: bytes):
        await self.send_message(MessageType.EXTENDED, bytes((PEX_LOCAL_ID,)) + payload)

    async def send_extended(self, extension_id: int, payload: bytes):
        if not 0 < extension_id < 256:
            raise ValueError("Extension ID must be between 1 and 255")
        await self.send_message(MessageType.EXTENDED, bytes((extension_id,)) + payload)

    async def send_request(self, piece_index: int, begin: int, length: int):
        payload = struct.pack("!III", piece_index, begin, length)
        await self.send_message(MessageType.REQUEST, payload)
        self.outstanding.add((piece_index, begin))

    async def send_cancel(self, piece_index: int, begin: int, length: int):
        await self.send_message(MessageType.CANCEL, struct.pack("!III", piece_index, begin, length))

    async def read_message(self):
        try:
            raw_length = await self.reader.readexactly(4)
            length = struct.unpack("!I", raw_length)[0]
            if length == 0:
                return None, b""
            if length > 4 * 1024 * 1024:
                raise PeerError(f"Peer message too large: {length} bytes")
            message = await self.reader.readexactly(length)
            return message[0], message[1:]
        except asyncio.IncompleteReadError:
            return None, None

    def has_piece(self, piece_index: int) -> bool:
        byte_index, bit_index = divmod(piece_index, 8)
        return byte_index < len(self.bitfield) and bool(self.bitfield[byte_index] & (0x80 >> bit_index))

    def update_bitfield(self, bitfield: bytes, piece_count: int):
        expected_length = (piece_count + 7) // 8
        if len(bitfield) != expected_length:
            raise PeerError("Peer sent a bitfield of the wrong length")
        self.bitfield = bytearray(bitfield)

    def set_have(self, piece_index: int, piece_count: int):
        if not 0 <= piece_index < piece_count:
            raise PeerError("Peer sent an out-of-range HAVE message")
        byte_index, bit_index = divmod(piece_index, 8)
        if not self.bitfield:
            self.bitfield = bytearray((piece_count + 7) // 8)
        self.bitfield[byte_index] |= 0x80 >> bit_index

    async def close(self):
        self.connected = False
        if self.writer is not None:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (OSError, RuntimeError):
                pass
