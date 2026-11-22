import asyncio
import secrets
import socket
import struct
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .bencode import BencodeError, decode_complete


class TrackerError(Exception):
    pass


class TrackerResponse:
    def __init__(self, data: dict):
        failure = data.get(b"failure reason")
        if failure:
            raise TrackerError(failure.decode("utf-8", errors="replace"))
        self.interval = max(30, int(data.get(b"interval", 1800)))
        self.complete = int(data.get(b"complete", 0))
        self.incomplete = int(data.get(b"incomplete", 0))
        self.peers = self._parse_peers(data.get(b"peers", b""), 6)
        self.peers.extend(self._parse_peers(data.get(b"peers6", b""), 18, ipv6=True))

    @staticmethod
    def _parse_peers(value, stride, ipv6=False):
        peers = []
        if isinstance(value, list):
            for peer in value:
                try:
                    ip = peer[b"ip"].decode("ascii")
                    port = int(peer[b"port"])
                    if 0 < port <= 65535:
                        peers.append((ip, port))
                except (KeyError, AttributeError, ValueError):
                    continue
            return peers
        if not isinstance(value, bytes) or len(value) % stride:
            return peers
        ip_size = 16 if ipv6 else 4
        for offset in range(0, len(value), stride):
            ip = socket.inet_ntop(socket.AF_INET6 if ipv6 else socket.AF_INET, value[offset:offset + ip_size])
            port = struct.unpack("!H", value[offset + ip_size:offset + stride])[0]
            if port:
                peers.append((ip, port))
        return peers


class TrackerClient:
    def __init__(self, info_hash: bytes, peer_id: bytes, port: int = 6881, timeout: float = 15):
        if len(info_hash) != 20 or len(peer_id) != 20:
            raise ValueError("info_hash and peer_id must be exactly 20 bytes")
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.port = port
        self.timeout = timeout

    async def announce(self, tracker_url: str, uploaded=0, downloaded=0, left=0, event=""):
        parsed = urlsplit(tracker_url)
        if parsed.scheme in ("http", "https"):
            return await asyncio.to_thread(
                self._http_announce, tracker_url, uploaded, downloaded, left, event
            )
        if parsed.scheme == "udp":
            return await self._udp_announce(parsed, uploaded, downloaded, left, event)
        raise TrackerError(f"Unsupported tracker scheme: {parsed.scheme or '(none)'}")

    def _http_announce(self, tracker_url, uploaded, downloaded, left, event):
        parsed = urlsplit(tracker_url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.extend([
            ("info_hash", self.info_hash),
            ("peer_id", self.peer_id),
            ("port", str(self.port)),
            ("uploaded", str(uploaded)),
            ("downloaded", str(downloaded)),
            ("left", str(left)),
            ("compact", "1"),
            ("numwant", "50"),
        ])
        if event:
            query.append(("event", event))
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        request = Request(url, headers={"User-Agent": "PythonTorrent/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = decode_complete(response.read())
        except (HTTPError, URLError, TimeoutError, OSError, BencodeError) as exc:
            raise TrackerError(f"HTTP tracker request failed: {exc}") from exc
        if not isinstance(result, dict):
            raise TrackerError("Tracker returned a non-dictionary response")
        return TrackerResponse(result)

    async def _udp_announce(self, parsed, uploaded, downloaded, left, event):
        if not parsed.hostname:
            raise TrackerError("UDP tracker URL has no hostname")
        port = parsed.port or 80
        loop = asyncio.get_running_loop()
        addresses = await loop.getaddrinfo(parsed.hostname, port, type=socket.SOCK_DGRAM)
        family, socktype, proto, _, address = addresses[0]
        sock = socket.socket(family, socktype, proto)
        sock.setblocking(False)
        try:
            connection_id = await self._udp_connect(loop, sock, address)
            transaction_id = secrets.randbits(32)
            event_code = {"": 0, "completed": 1, "started": 2, "stopped": 3}.get(event, 0)
            key = secrets.randbits(32)
            packet = struct.pack(
                "!QII20s20sQQQIIIiH",
                connection_id,
                1,
                transaction_id,
                self.info_hash,
                self.peer_id,
                downloaded,
                left,
                uploaded,
                event_code,
                0,
                key,
                50,
                self.port,
            )
            await loop.sock_sendto(sock, packet, address)
            data = await asyncio.wait_for(loop.sock_recv(sock, 65535), self.timeout)
            if len(data) < 8:
                raise TrackerError("Truncated UDP tracker announce response")
            action, response_tx = struct.unpack("!II", data[:8])
            if response_tx != transaction_id:
                raise TrackerError("UDP tracker transaction ID mismatch")
            if action == 3:
                raise TrackerError(data[8:].decode("utf-8", errors="replace"))
            if action != 1:
                raise TrackerError("Unexpected UDP tracker response")
            if len(data) < 20:
                raise TrackerError("Truncated UDP tracker announce response")
            _, _, interval, leechers, seeders = struct.unpack("!IIIII", data[:20])
            peers = TrackerResponse._parse_peers(data[20:], 6)
            response = TrackerResponse({b"interval": interval, b"complete": seeders, b"incomplete": leechers})
            response.peers = peers
            return response
        except asyncio.TimeoutError as exc:
            raise TrackerError("UDP tracker timed out") from exc
        except OSError as exc:
            raise TrackerError(f"UDP tracker request failed: {exc}") from exc
        finally:
            sock.close()

    async def _udp_connect(self, loop, sock, address):
        transaction_id = secrets.randbits(32)
        packet = struct.pack("!QII", 0x41727101980, 0, transaction_id)
        for attempt in range(3):
            await loop.sock_sendto(sock, packet, address)
            try:
                data = await asyncio.wait_for(loop.sock_recv(sock, 2048), min(self.timeout, 2 ** (attempt + 1)))
            except asyncio.TimeoutError:
                continue
            if len(data) < 8:
                continue
            action, response_tx = struct.unpack("!II", data[:8])
            if response_tx != transaction_id:
                continue
            if action == 3:
                raise TrackerError(data[8:].decode("utf-8", errors="replace"))
            if action != 0 or len(data) != 16:
                raise TrackerError("Invalid UDP tracker connect response")
            return struct.unpack("!Q", data[8:16])[0]
        raise TrackerError("UDP tracker connect timed out")
