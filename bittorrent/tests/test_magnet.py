import asyncio
import base64
import hashlib
import os
import socket
import struct
import tempfile
import unittest
from urllib.parse import quote

from btclient.bencode import decode, decode_complete, encode
from btclient.client import BitTorrentClient
from btclient.magnet import parse_magnet_uri


class MagnetParsingTests(unittest.TestCase):
    def test_parses_hex_base32_name_and_trackers(self):
        info_hash = bytes(range(20))
        tracker = "udp://tracker.example:80/announce"
        for digest in (info_hash.hex(), base64.b32encode(info_hash).decode().rstrip("=")):
            magnet = parse_magnet_uri(
                f"magnet:?xt=urn:btih:{digest}&dn=demo&tr={quote(tracker, safe='')}"
            )
            self.assertEqual(magnet.info_hash, info_hash)
            self.assertEqual(magnet.display_name, "demo")
            self.assertEqual(magnet.trackers, (tracker,))


class MagnetDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_magnet_fetches_metadata_then_downloads_verified_pieces(self):
        content = b"magnet metadata exchange integration " * 170
        piece_length = 4096
        piece_hashes = b"".join(
            hashlib.sha1(content[offset:offset + piece_length]).digest()
            for offset in range(0, len(content), piece_length)
        )
        info_dict = {
            b"length": len(content),
            b"name": b"magnet-payload.bin",
            b"piece length": piece_length,
            b"pieces": piece_hashes,
        }
        info_raw = encode(info_dict)
        info_hash = hashlib.sha1(info_raw).digest()
        metadata_exchanged = False
        peer_port = None

        async def peer_handler(reader, writer):
            nonlocal metadata_exchanged
            try:
                await reader.readexactly(68)
                reserved = bytearray(8)
                reserved[5] |= 0x10
                writer.write(b"\x13BitTorrent protocol" + bytes(reserved) + info_hash + b"-SE0001-abcdefghijkl")
                bitfield = bytes([0xC0])
                writer.write(struct.pack("!IB", len(bitfield) + 1, 5) + bitfield)
                writer.write(struct.pack("!IB", 1, 1))
                await writer.drain()

                while True:
                    length = struct.unpack("!I", await reader.readexactly(4))[0]
                    if length == 0:
                        continue
                    message = await reader.readexactly(length)
                    if message[0] == 20 and message[1] == 0:
                        metadata_exchanged = True
                        handshake = b"\0" + encode({
                            b"m": {b"ut_metadata": 3, b"ut_pex": 4},
                            b"metadata_size": len(info_raw),
                        })
                        writer.write(struct.pack("!IB", len(handshake) + 1, 20) + handshake)
                        await writer.drain()
                    elif message[0] == 20 and message[1] == 3:
                        request, _ = decode(message[2:])
                        if request.get(b"msg_type") == 0:
                            piece = request[b"piece"]
                            start = piece * 16 * 1024
                            # Replies use the extension ID this client advertised (2).
                            response = b"\x02" + encode({
                                b"msg_type": 1,
                                b"piece": piece,
                                b"total_size": len(info_raw),
                            }) + info_raw[start:start + 16 * 1024]
                            writer.write(struct.pack("!IB", len(response) + 1, 20) + response)
                            await writer.drain()
                    elif message[0] == 6 and len(message) == 13:
                        piece_index, begin, block_length = struct.unpack("!III", message[1:])
                        start = piece_index * piece_length + begin
                        block = content[start:start + block_length]
                        response = struct.pack("!II", piece_index, begin) + block
                        writer.write(struct.pack("!IB", len(response) + 1, 7) + response)
                        await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()

        peer_server = await asyncio.start_server(peer_handler, "127.0.0.1", 0)
        peer_port = peer_server.sockets[0].getsockname()[1]

        async def tracker_handler(reader, writer):
            try:
                await reader.readline()
                while await reader.readline() != b"\r\n":
                    pass
                compact_peer = socket.inet_aton("127.0.0.1") + struct.pack("!H", peer_port)
                body = encode({b"interval": 30, b"peers": compact_peer})
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Length: "
                    + str(len(body)).encode("ascii")
                    + b"\r\nConnection: close\r\n\r\n"
                    + body
                )
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        tracker_server = await asyncio.start_server(tracker_handler, "127.0.0.1", 0)
        tracker_port = tracker_server.sockets[0].getsockname()[1]
        magnet = (
            f"magnet:?xt=urn:btih:{info_hash.hex()}&dn=magnet-payload.bin"
            f"&tr={quote(f'http://127.0.0.1:{tracker_port}/announce', safe='')}"
        )
        try:
            with tempfile.TemporaryDirectory() as output_dir:
                client = BitTorrentClient(output_dir, port=0)
                await asyncio.wait_for(client.download(magnet), timeout=8)
                self.assertTrue(metadata_exchanged)
                self.assertEqual(client.get_progress()["progress"], 1.0)
                with open(os.path.join(output_dir, "magnet-payload.bin"), "rb") as file:
                    self.assertEqual(file.read(), content)
        finally:
            tracker_server.close()
            peer_server.close()
            await tracker_server.wait_closed()
            await peer_server.wait_closed()


if __name__ == "__main__":
    unittest.main()
