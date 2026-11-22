"""Minimal IPv4 BitTorrent Mainline DHT implementation (BEP 5)."""

import asyncio
import hashlib
import hmac
import ipaddress
import logging
import secrets
import socket
import struct
import time

from .bencode import BencodeError, decode_complete, encode

log = logging.getLogger(__name__)

BOOTSTRAP_NODES = (
    ("router.bittorrent.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
)
MAX_ROUTING_NODES = 512
MAX_LOOKUP_NODES = 32
ALPHA = 8


def compact_node(node_id: bytes, host: str, port: int) -> bytes:
    address = ipaddress.ip_address(host)
    if address.version != 4 or len(node_id) != 20 or not 0 < int(port) <= 65535:
        return b""
    return node_id + address.packed + struct.pack("!H", int(port))


def parse_nodes(data: bytes):
    if not isinstance(data, bytes) or len(data) % 26:
        return []
    result = []
    for offset in range(0, len(data), 26):
        node_id = data[offset:offset + 20]
        ip = socket.inet_ntop(socket.AF_INET, data[offset + 20:offset + 24])
        port = struct.unpack("!H", data[offset + 24:offset + 26])[0]
        if port:
            result.append((node_id, ip, port))
    return result


def parse_compact_peers(values):
    peers = set()
    if not isinstance(values, list):
        return peers
    for value in values:
        if not isinstance(value, bytes) or len(value) not in (6, 18):
            continue
        ip_size = len(value) - 2
        family = socket.AF_INET if ip_size == 4 else socket.AF_INET6
        ip = socket.inet_ntop(family, value[:ip_size])
        port = struct.unpack("!H", value[ip_size:])[0]
        if port:
            peers.add((ip, port))
    return peers


class DHTClient(asyncio.DatagramProtocol):
    """Queries DHT nodes for peers, announces this client's TCP port, and answers KRPC."""

    def __init__(self, info_hash: bytes, peer_port: int, bind_port: int = 6881, bootstrap_nodes=None):
        if len(info_hash) != 20:
            raise ValueError("DHT info hash must be 20 bytes")
        self.info_hash = info_hash
        self.peer_port = peer_port
        self.bind_port = bind_port
        self.bootstrap_nodes = tuple(bootstrap_nodes or BOOTSTRAP_NODES)
        self.node_id = secrets.token_bytes(20)
        self._token_secret = secrets.token_bytes(32)
        self._transport = None
        self._pending = {}
        self._nodes = {}
        self._peer_store = {}
        self._closed = False

    async def start(self):
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self, local_addr=("0.0.0.0", self.bind_port)
            )
        except OSError:
            if not self.bind_port:
                raise
            log.warning("Could not bind DHT UDP port %d; using an ephemeral port", self.bind_port)
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: self, local_addr=("0.0.0.0", 0)
            )
        return self

    def datagram_received(self, data, address):
        if len(data) > 4096:
            return
        try:
            message = decode_complete(data)
        except BencodeError:
            return
        if not isinstance(message, dict):
            return
        kind = message.get(b"y")
        transaction = message.get(b"t")
        if not isinstance(transaction, bytes):
            return
        if kind == b"r":
            future = self._pending.get(transaction)
            if future and not future.done() and isinstance(message.get(b"r"), dict):
                future.set_result((message[b"r"], address))
        elif kind == b"e":
            future = self._pending.get(transaction)
            if future and not future.done():
                future.set_exception(RuntimeError(f"DHT error: {message.get(b'e')}"))
        elif kind == b"q":
            asyncio.create_task(self._answer_query(message, address))

    def error_received(self, exc):
        log.debug("DHT UDP error: %s", exc)

    async def _query(self, address, query: bytes, arguments: dict, timeout=2.5):
        if not self._transport or self._closed:
            return None
        loop = asyncio.get_running_loop()
        for _ in range(5):
            transaction = secrets.token_bytes(2)
            if transaction not in self._pending:
                break
        future = loop.create_future()
        self._pending[transaction] = future
        packet = encode({b"t": transaction, b"y": b"q", b"q": query, b"a": arguments})
        try:
            self._transport.sendto(packet, address)
            return await asyncio.wait_for(future, timeout)
        except (asyncio.TimeoutError, OSError, RuntimeError):
            return None
        finally:
            self._pending.pop(transaction, None)
            if not future.done():
                future.cancel()

    async def _answer_query(self, message, address):
        transaction = message.get(b"t", b"")
        query = message.get(b"q")
        arguments = message.get(b"a")
        if not isinstance(query, bytes) or not isinstance(arguments, dict):
            self._send_error(transaction, address, 203, b"Invalid arguments")
            return
        remote_id = arguments.get(b"id")
        if not isinstance(remote_id, bytes) or len(remote_id) != 20:
            self._send_error(transaction, address, 203, b"Invalid node ID")
            return
        self._add_node(remote_id, address[0], address[1])
        result = {b"id": self.node_id}

        if query == b"ping":
            pass
        elif query == b"find_node":
            target = arguments.get(b"target")
            if not isinstance(target, bytes) or len(target) != 20:
                self._send_error(transaction, address, 203, b"Invalid target")
                return
            result[b"nodes"] = self._closest_nodes(target, exclude=address)
        elif query == b"get_peers":
            target = arguments.get(b"info_hash")
            if not isinstance(target, bytes) or len(target) != 20:
                self._send_error(transaction, address, 203, b"Invalid info_hash")
                return
            result[b"token"] = self._make_token(address[0])
            peers = self._stored_peers(target)
            if peers:
                result[b"values"] = peers
            else:
                result[b"nodes"] = self._closest_nodes(target, exclude=address)
        elif query == b"announce_peer":
            target = arguments.get(b"info_hash")
            token = arguments.get(b"token")
            if not isinstance(target, bytes) or len(target) != 20 or not isinstance(token, bytes):
                self._send_error(transaction, address, 203, b"Invalid announce_peer arguments")
                return
            if not hmac.compare_digest(token, self._make_token(address[0])):
                self._send_error(transaction, address, 203, b"Invalid token")
                return
            implied_port = arguments.get(b"implied_port", 0) == 1
            peer_port = address[1] if implied_port else arguments.get(b"port")
            if not isinstance(peer_port, int) or not 0 < peer_port <= 65535:
                self._send_error(transaction, address, 203, b"Invalid peer port")
                return
            peers = self._peer_store.setdefault(target, {})
            peers[(address[0], peer_port)] = time.monotonic() + 1800
        else:
            self._send_error(transaction, address, 204, b"Method Unknown")
            return

        if self._transport and not self._closed:
            self._transport.sendto(encode({b"t": transaction, b"y": b"r", b"r": result}), address)

    def _send_error(self, transaction, address, code: int, text: bytes):
        if self._transport and not self._closed:
            self._transport.sendto(encode({b"t": transaction, b"y": b"e", b"e": [code, text]}), address)

    def _make_token(self, ip: str) -> bytes:
        packed_ip = ipaddress.ip_address(ip).packed
        return hmac.new(self._token_secret, packed_ip, hashlib.sha1).digest()

    def _add_node(self, node_id: bytes, ip: str, port: int):
        if len(node_id) != 20 or not 0 < int(port) <= 65535:
            return
        try:
            if ipaddress.ip_address(ip).version != 4:
                return
        except ValueError:
            return
        self._nodes[(ip, int(port))] = node_id
        if len(self._nodes) > MAX_ROUTING_NODES:
            self._nodes.pop(next(iter(self._nodes)))

    def _closest_nodes(self, target: bytes, exclude=None):
        candidates = sorted(
            ((node_id, ip, port) for (ip, port), node_id in self._nodes.items()
             if (ip, port) != exclude),
            key=lambda entry: int.from_bytes(entry[0], "big") ^ int.from_bytes(target, "big"),
        )[:8]
        return b"".join(compact_node(node_id, ip, port) for node_id, ip, port in candidates)

    def _stored_peers(self, info_hash: bytes):
        now = time.monotonic()
        stored = self._peer_store.get(info_hash, {})
        expired = [address for address, expiry in stored.items() if expiry <= now]
        for address in expired:
            stored.pop(address, None)
        values = []
        for ip, port in list(stored):
            packed = compact_node(b"\0" * 20, ip, port)
            if packed:
                values.append(packed[20:])
        return values[:50]

    async def _resolve_bootstrap(self):
        loop = asyncio.get_running_loop()
        resolved = []
        for host, port in self.bootstrap_nodes:
            try:
                entries = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
            except OSError as exc:
                log.debug("Could not resolve DHT bootstrap %s: %s", host, exc)
                continue
            for _, _, _, _, address in entries:
                if address not in resolved:
                    resolved.append(address)
        return resolved

    async def find_peers(self):
        """Bootstrap, iteratively query closest nodes, and announce this peer port."""
        bootstrap = await self._resolve_bootstrap()
        if not bootstrap:
            return set()

        candidates = {}
        bootstrap_results = await asyncio.gather(*(
            self._query(address, b"find_node", {b"id": self.node_id, b"target": self.info_hash})
            for address in bootstrap
        ))
        for response in bootstrap_results:
            if not response:
                continue
            result, address = response
            node_id = result.get(b"id")
            if isinstance(node_id, bytes) and len(node_id) == 20:
                self._add_node(node_id, address[0], address[1])
                candidates[address] = node_id
            for found_id, ip, port in parse_nodes(result.get(b"nodes", b"")):
                self._add_node(found_id, ip, port)
                candidates[(ip, port)] = found_id

        for address, node_id in self._nodes.items():
            candidates[address] = node_id

        visited = set()
        peers = set()
        announced = set()
        query_count = 0
        while candidates and query_count < MAX_LOOKUP_NODES:
            batch = sorted(
                ((node_id, address) for address, node_id in candidates.items() if address not in visited),
                key=lambda entry: int.from_bytes(entry[0], "big") ^ int.from_bytes(self.info_hash, "big"),
            )[:ALPHA]
            if not batch:
                break
            visited.update(address for _, address in batch)
            query_count += len(batch)
            responses = await asyncio.gather(*(
                self._query(address, b"get_peers", {b"id": self.node_id, b"info_hash": self.info_hash})
                for _, address in batch
            ))
            announce_tasks = []
            for response in responses:
                if not response:
                    continue
                result, address = response
                node_id = result.get(b"id")
                if isinstance(node_id, bytes) and len(node_id) == 20:
                    self._add_node(node_id, address[0], address[1])
                peers.update(parse_compact_peers(result.get(b"values", [])))
                token = result.get(b"token")
                if isinstance(token, bytes) and address not in announced:
                    announced.add(address)
                    announce_tasks.append(self._query(address, b"announce_peer", {
                        b"id": self.node_id,
                        b"info_hash": self.info_hash,
                        b"port": self.peer_port,
                        b"token": token,
                        b"implied_port": 0,
                    }))
                for found_id, ip, port in parse_nodes(result.get(b"nodes", b"")):
                    self._add_node(found_id, ip, port)
                    candidates[(ip, port)] = found_id
            if announce_tasks:
                await asyncio.gather(*announce_tasks)
        return peers

    def close(self):
        self._closed = True
        if self._transport:
            self._transport.close()
            self._transport = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
