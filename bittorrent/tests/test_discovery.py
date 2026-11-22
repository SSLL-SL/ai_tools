import asyncio
import socket
import struct
import unittest
from unittest.mock import AsyncMock

from btclient.bencode import decode_complete, encode
from btclient.client import BitTorrentClient
from btclient.dht import DHTClient, compact_node
from btclient.peer import PeerConnection
from btclient.pex import encode_pex, parse_pex


class DHTTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_discovers_peers_and_announces_port(self):
        node_id = b"n" * 20
        peer_compact = socket.inet_aton("127.0.0.1") + struct.pack("!H", 45678)

        class FakeNode(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport
                self.announced = False

            def datagram_received(self, data, address):
                query = decode_complete(data)
                transaction = query[b"t"]
                method = query[b"q"]
                if method == b"find_node":
                    result = {
                        b"id": node_id,
                        b"nodes": compact_node(node_id, "127.0.0.1", self.transport.get_extra_info("sockname")[1]),
                    }
                elif method == b"get_peers":
                    result = {b"id": node_id, b"token": b"test-token", b"values": [peer_compact]}
                elif method == b"announce_peer":
                    self.announced = query[b"a"][b"port"] == 6881
                    result = {b"id": node_id}
                else:
                    result = {b"id": node_id}
                self.transport.sendto(encode({b"t": transaction, b"y": b"r", b"r": result}), address)

        loop = asyncio.get_running_loop()
        fake_transport, fake_protocol = await loop.create_datagram_endpoint(
            FakeNode, local_addr=("127.0.0.1", 0)
        )
        fake_port = fake_transport.get_extra_info("sockname")[1]
        dht = await DHTClient(
            b"h" * 20,
            peer_port=6881,
            bind_port=0,
            bootstrap_nodes=(("127.0.0.1", fake_port),),
        ).start()
        try:
            peers = await asyncio.wait_for(dht.find_peers(), timeout=5)
            self.assertIn(("127.0.0.1", 45678), peers)
            self.assertTrue(fake_protocol.announced)
        finally:
            dht.close()
            fake_transport.close()

    async def test_local_dht_node_checks_token_and_stores_announce(self):
        dht = await DHTClient(b"h" * 20, peer_port=6881, bind_port=0, bootstrap_nodes=()).start()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind(("127.0.0.1", 0))
        loop = asyncio.get_running_loop()
        target = ("127.0.0.1", dht._transport.get_extra_info("sockname")[1])
        node_id = b"r" * 20
        try:
            request = {b"t": b"g1", b"y": b"q", b"q": b"get_peers", b"a": {b"id": node_id, b"info_hash": b"h" * 20}}
            await loop.sock_sendto(sock, encode(request), target)
            response = decode_complete(await asyncio.wait_for(loop.sock_recv(sock, 2048), 2))
            token = response[b"r"][b"token"]

            announce = {
                b"t": b"a1", b"y": b"q", b"q": b"announce_peer",
                b"a": {b"id": node_id, b"info_hash": b"h" * 20, b"token": token, b"port": 43210},
            }
            await loop.sock_sendto(sock, encode(announce), target)
            await asyncio.wait_for(loop.sock_recv(sock, 2048), 2)

            query = {b"t": b"g2", b"y": b"q", b"q": b"get_peers", b"a": {b"id": node_id, b"info_hash": b"h" * 20}}
            await loop.sock_sendto(sock, encode(query), target)
            stored = decode_complete(await asyncio.wait_for(loop.sock_recv(sock, 2048), 2))[b"r"][b"values"]
            self.assertEqual(stored, [socket.inet_aton("127.0.0.1") + struct.pack("!H", 43210)])
        finally:
            sock.close()
            dht.close()


class PEXTests(unittest.IsolatedAsyncioTestCase):
    def test_compact_pex_supports_ipv4_and_ipv6(self):
        peers = {("192.0.2.1", 6881), ("2001:db8::2", 51413)}
        message = decode_complete(encode_pex(added=peers, dropped={("192.0.2.2", 6882)}))
        added, dropped = parse_pex(message)
        self.assertEqual(added, peers)
        self.assertEqual(dropped, {("192.0.2.2", 6882)})

    async def test_extension_handshake_negotiates_ut_pex_and_forwards_peers(self):
        client = BitTorrentClient()
        client._connect_to_peers = AsyncMock()
        peer = PeerConnection(b"p" * 20, b"h" * 20, "127.0.0.1", 12345, client)
        peer.connected = True
        try:
            await client._handle_extension(peer, b"\0" + encode({b"m": {b"ut_pex": 7}}))
            self.assertEqual(peer.remote_extensions[b"ut_pex"], 7)
            added = {("192.0.2.3", 6881)}
            await client._handle_extension(peer, b"\x01" + encode_pex(added=added))
            client._connect_to_peers.assert_awaited_once_with(added)
        finally:
            peer.connected = False


if __name__ == "__main__":
    unittest.main()
