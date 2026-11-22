import asyncio
import hashlib
import os
import socket
import struct
import tempfile
import unittest

from btclient.bencode import BencodeError, decode, decode_complete, decode_torrent, encode
from btclient.client import BitTorrentClient
from btclient.resume import ResumeStore
from btclient.storage import PieceStorage
from btclient.torrent import Torrent, parse_torrent_bytes
from btclient.tracker import TrackerClient


class BencodeAndMetadataTests(unittest.TestCase):
    def test_round_trip(self):
        value = {b"a": [1, b"data"], b"z": -4}
        self.assertEqual(decode_complete(encode(value)), value)

    def test_non_torrent_input_has_actionable_error(self):
        with self.assertRaisesRegex(BencodeError, "HTML/XML"):
            decode_torrent(b"<!doctype html><html></html>")
        with self.assertRaisesRegex(BencodeError, "vacío"):
            decode_torrent(b"")

    def test_info_hash_is_from_raw_info_dictionary(self):
        info_dict = {
            b"length": 3,
            b"name": b"test",
            b"piece length": 3,
            b"pieces": hashlib.sha1(b"abc").digest(),
        }
        payload = encode({b"announce": b"http://localhost/announce", b"info": info_dict})
        info = parse_torrent_bytes(payload)
        _, raw_info = decode_torrent(payload)
        self.assertEqual(info.info_hash, hashlib.sha1(raw_info).digest())
        self.assertEqual(info.total_size, 3)

    def test_piece_spanning_two_files_is_written_at_both_offsets(self):
        content = b"abcDEFG"
        info_dict = {
            b"files": [
                {b"length": 3, b"path": [b"first.bin"]},
                {b"length": 4, b"path": [b"nested", b"second.bin"]},
            ],
            b"name": b"bundle",
            b"piece length": 4,
            b"pieces": hashlib.sha1(content[:4]).digest() + hashlib.sha1(content[4:]).digest(),
        }
        torrent = parse_torrent_bytes(encode({b"info": info_dict}))
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = PieceStorage(torrent, temp_dir)
            try:
                storage.write_piece(0, content[:4])
                storage.write_piece(1, content[4:])
                self.assertEqual(storage.read_piece(0), content[:4])
                self.assertEqual(storage.read_piece(1), content[4:])
            finally:
                storage.close()
            with open(os.path.join(temp_dir, "bundle", "first.bin"), "rb") as first:
                self.assertEqual(first.read(), b"abc")
            with open(os.path.join(temp_dir, "bundle", "nested", "second.bin"), "rb") as second:
                self.assertEqual(second.read(), b"DEFG")

    def test_resume_restores_only_pieces_whose_data_still_matches_hash(self):
        content = b"goodBAD!"
        info_dict = {
            b"length": len(content),
            b"name": b"resume.bin",
            b"piece length": 4,
            b"pieces": hashlib.sha1(content[:4]).digest() + hashlib.sha1(content[4:]).digest(),
        }
        info = parse_torrent_bytes(encode({b"info": info_dict}))
        with tempfile.TemporaryDirectory() as temp_dir:
            initial_storage = PieceStorage(info, temp_dir)
            initial_storage.write_piece(0, content[:4])
            initial_torrent = Torrent(info)
            initial_torrent.set_have(0)
            ResumeStore(temp_dir, info).save(bytes(initial_torrent.bitfield))
            initial_storage.close()

            resumed = BitTorrentClient(temp_dir)
            resumed.torrent = Torrent(info)
            resumed.storage = PieceStorage(info, temp_dir)
            resumed.resume_store = ResumeStore(temp_dir, info)
            resumed._restore_resume()
            self.assertTrue(resumed.torrent.has_piece(0))
            self.assertFalse(resumed.torrent.has_piece(1))
            self.assertEqual(resumed.downloaded, 4)
            resumed.storage.close()

            with open(os.path.join(temp_dir, "resume.bin"), "r+b") as output:
                output.seek(0)
                output.write(b"xxxx")
            restarted = BitTorrentClient(temp_dir)
            restarted.torrent = Torrent(info)
            restarted.storage = PieceStorage(info, temp_dir)
            restarted.resume_store = ResumeStore(temp_dir, info)
            restarted._restore_resume()
            self.assertFalse(restarted.torrent.has_piece(0))
            self.assertEqual(restarted.downloaded, 0)
            self.assertEqual(restarted.resume_store.load(), b"\0")
            restarted.storage.close()


class DownloadIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_execution_finishes_from_saved_checkpoint(self):
        content = b"resume me"
        info_dict = {
            b"length": len(content),
            b"name": b"saved.bin",
            b"piece length": len(content),
            b"pieces": hashlib.sha1(content).digest(),
        }
        torrent_data = encode({
            b"announce": b"http://127.0.0.1:1/announce",
            b"info": info_dict,
        })
        info = parse_torrent_bytes(torrent_data)
        with tempfile.TemporaryDirectory() as temp_dir:
            torrent_path = os.path.join(temp_dir, "saved.torrent")
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir)
            with open(torrent_path, "wb") as file:
                file.write(torrent_data)

            storage = PieceStorage(info, output_dir)
            storage.write_piece(0, content)
            completed = Torrent(info)
            completed.set_have(0)
            ResumeStore(output_dir, info).save(bytes(completed.bitfield))
            storage.close()

            restarted = BitTorrentClient(output_dir, port=0)
            await asyncio.wait_for(restarted.download(torrent_path), timeout=3)
            self.assertEqual(restarted.get_progress()["progress"], 1.0)
            self.assertEqual(restarted.get_progress()["downloaded"], len(content))
            with open(os.path.join(output_dir, "saved.bin"), "rb") as file:
                self.assertEqual(file.read(), content)

    async def test_udp_tracker_connect_and_announce(self):
        class FakeUDPTracker(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, address):
                action, transaction = struct.unpack("!II", data[8:16])
                if action == 0:
                    self.transport.sendto(struct.pack("!IIQ", 0, transaction, 0x123456789ABCDEF0), address)
                elif action == 1:
                    self.transport.sendto(
                        struct.pack("!IIIII", 1, transaction, 60, 0, 1)
                        + socket.inet_aton("127.0.0.1")
                        + struct.pack("!H", 45678),
                        address,
                    )

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(FakeUDPTracker, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        try:
            tracker = TrackerClient(b"h" * 20, b"p" * 20, port=6881, timeout=2)
            response = await tracker.announce(f"udp://127.0.0.1:{port}/announce", left=42, event="started")
            self.assertEqual(response.interval, 60)
            self.assertEqual(response.peers, [("127.0.0.1", 45678)])
        finally:
            transport.close()

    async def test_downloads_and_verifies_piece_from_local_peer(self):
        content = b"bit torrent local integration test " * 600
        piece_length = 32768
        hashes = b"".join(
            hashlib.sha1(content[i:i + piece_length]).digest()
            for i in range(0, len(content), piece_length)
        )
        info_dict = {
            b"length": len(content),
            b"name": b"payload.bin",
            b"piece length": piece_length,
            b"pieces": hashes,
        }
        info_raw = encode(info_dict)
        info_hash = hashlib.sha1(info_raw).digest()
        tracker_port = None
        peer_port = None
        pex_negotiated = False
        metadata_served = False

        async def peer_handler(reader, writer):
            nonlocal pex_negotiated, metadata_served
            try:
                await reader.readexactly(68)
                reserved = bytearray(8)
                reserved[5] |= 0x10
                writer.write(b"\x13BitTorrent protocol" + bytes(reserved) + info_hash + b"-SE0001-123456789012")
                writer.write(struct.pack("!IB", 2, 5) + b"\x80")
                writer.write(struct.pack("!IB", 1, 1))
                await writer.drain()
                while True:
                    length = struct.unpack("!I", await reader.readexactly(4))[0]
                    if length == 0:
                        continue
                    message = await reader.readexactly(length)
                    if message[0] == 20 and message[1] == 0:
                        pex_negotiated = True
                        handshake = b"\0" + encode({
                            b"m": {b"ut_pex": 7, b"ut_metadata": 6},
                            b"metadata_size": len(info_raw),
                        })
                        writer.write(struct.pack("!IB", len(handshake) + 1, 20) + handshake)
                        metadata_request = b"\x02" + encode({b"msg_type": 0, b"piece": 0})
                        writer.write(struct.pack("!IB", len(metadata_request) + 1, 20) + metadata_request)
                        await writer.drain()
                        continue
                    if message[0] == 20 and message[1] == 6:
                        header, offset = decode(message[2:])
                        metadata_served = header.get(b"msg_type") == 1 and message[2 + offset:] == info_raw
                        continue
                    if message[0] != 6 or len(message) != 13:
                        continue
                    piece_index, begin, block_length = struct.unpack("!III", message[1:])
                    block = content[piece_index * piece_length + begin:piece_index * piece_length + begin + block_length]
                    response_payload = struct.pack("!II", piece_index, begin) + block
                    writer.write(struct.pack("!IB", len(response_payload) + 1, 7) + response_payload)
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
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: "
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
        torrent_data = encode({
            b"announce": f"http://127.0.0.1:{tracker_port}/announce".encode(),
            b"info": info_dict,
        })

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                torrent_path = os.path.join(temp_dir, "test.torrent")
                output_dir = os.path.join(temp_dir, "output")
                with open(torrent_path, "wb") as file:
                    file.write(torrent_data)
                client = BitTorrentClient(output_dir, port=0)
                await asyncio.wait_for(client.download(torrent_path), timeout=10)
                with open(os.path.join(output_dir, "payload.bin"), "rb") as file:
                    self.assertEqual(file.read(), content)
                self.assertEqual(client.get_progress()["progress"], 1.0)
                self.assertTrue(pex_negotiated)
                self.assertTrue(metadata_served)
        finally:
            tracker_server.close()
            peer_server.close()
            await tracker_server.wait_closed()
            await peer_server.wait_closed()


if __name__ == "__main__":
    unittest.main()
