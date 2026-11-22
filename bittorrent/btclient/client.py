import asyncio
import hashlib
import logging
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .bencode import decode, decode_complete, encode
from .dht import DHTClient
from .magnet import parse_magnet_uri
from .peer import METADATA_LOCAL_ID, PEX_LOCAL_ID, MessageType, PeerConnection, PeerError
from .pex import encode_pex, parse_pex
from .resume import ResumeStore
from .storage import PieceStorage
from .torrent import Torrent, TorrentInfo, parse_info_bytes, parse_torrent_file
from .tracker import TrackerClient

log = logging.getLogger(__name__)

BLOCK_SIZE = 16 * 1024
METADATA_BLOCK_SIZE = 16 * 1024
MAX_METADATA_SIZE = 16 * 1024 * 1024
MAX_METADATA_IN_FLIGHT = 8
METADATA_REQUEST_TIMEOUT = 15
MAX_IN_FLIGHT = 16
MAX_PEERS = 40


@dataclass
class PieceAssembly:
    data: bytearray
    block_lengths: Dict[int, int]
    received: Set[int] = field(default_factory=set)
    owner: Optional[PeerConnection] = None


class BitTorrentClient:
    def __init__(self, save_path: str = ".", port: int = 6881):
        self.save_path = save_path
        self.port = port
        self.peer_id = b"-PC0001-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12)).encode("ascii")
        self.torrent: Optional[Torrent] = None
        self.info_hash: Optional[bytes] = None
        self.tracker_urls: List[str] = []
        self.display_name = ""
        self.storage: Optional[PieceStorage] = None
        self.resume_store: Optional[ResumeStore] = None
        self.peers: List[PeerConnection] = []
        self.tracker: Optional[TrackerClient] = None
        self.dht: Optional[DHTClient] = None
        self.running = False
        self.downloaded = 0
        self.uploaded = 0
        self._pieces: Dict[int, PieceAssembly] = {}
        self._assigned: Dict[int, PeerConnection] = {}
        self._peer_tasks: Set[asyncio.Task] = set()
        self._started_trackers = set()
        self._download_started = 0.0
        self._server = None
        self._connecting = set()
        self._metadata_size = None
        self._metadata_chunks = {}
        self._metadata_sources = {}
        self._metadata_requested = {}
        self._metadata_timeouts = {}

    async def download(self, torrent_path: str):
        is_magnet = torrent_path.lower().startswith("magnet:")
        if is_magnet:
            magnet = parse_magnet_uri(torrent_path)
            self.info_hash = magnet.info_hash
            self.tracker_urls = list(magnet.trackers)
            self.display_name = magnet.display_name
        else:
            info = parse_torrent_file(torrent_path)
            self.info_hash = info.info_hash
            self.tracker_urls = list(info.trackers)
            self.display_name = info.name
            self._install_metadata(info)
        self.tracker = TrackerClient(self.info_hash, self.peer_id, self.port)
        self._download_started = time.monotonic()
        self.running = True
        if self.torrent:
            log.info("Starting %s (%s bytes; %s pieces)", self.display_name, self.torrent.info.total_size, self.torrent.info.num_pieces)
        else:
            log.info("Resolving magnet metadata for %s (%s)", self.display_name, self.info_hash.hex())

        try:
            await self._start_listener()
            self.tracker.port = self.port
            background_tasks = [asyncio.create_task(self._dht_loop())]
            if self.tracker_urls:
                background_tasks.append(asyncio.create_task(self._tracker_loop()))
            else:
                log.info("No trackers in source; discovering peers through DHT")
            try:
                while self.running and (self.torrent is None or not self.torrent.is_complete()):
                    await asyncio.sleep(0.2)
            finally:
                self.running = False
                for task in background_tasks:
                    task.cancel()
                await asyncio.gather(*background_tasks, return_exceptions=True)
        finally:
            self.running = False
            for task in tuple(self._peer_tasks):
                task.cancel()
            if self._peer_tasks:
                await asyncio.gather(*self._peer_tasks, return_exceptions=True)
            for task in self._metadata_timeouts.values():
                task.cancel()
            if self._metadata_timeouts:
                await asyncio.gather(*self._metadata_timeouts.values(), return_exceptions=True)
            self._metadata_timeouts.clear()
            for peer in self.peers:
                await peer.close()
            if self._server:
                self._server.close()
                await self._server.wait_closed()
            if self.dht:
                self.dht.close()
            if self.storage:
                self._persist_resume()
                self.storage.close()

    def _install_metadata(self, info: TorrentInfo):
        if self.info_hash is not None and info.info_hash != self.info_hash:
            raise ValueError("Los metadatos recibidos no coinciden con el info-hash del magnet")
        self.info_hash = info.info_hash
        self.torrent = Torrent(info)
        self.storage = PieceStorage(info, self.save_path)
        self.resume_store = ResumeStore(self.save_path, info)
        self._restore_resume()
        self.display_name = info.name

    def _restore_resume(self):
        if not self.resume_store or not self.storage or not self.torrent:
            return
        saved_bitfield = self.resume_store.load()
        if saved_bitfield is None:
            return

        restored = 0
        for piece_index in range(self.torrent.info.num_pieces):
            bit_set = bool(saved_bitfield[piece_index // 8] & (0x80 >> (piece_index % 8)))
            if not bit_set:
                continue
            try:
                data = self.storage.read_piece(piece_index)
            except OSError as exc:
                log.warning("Could not read saved piece %d; downloading it again: %s", piece_index, exc)
                continue
            if self.torrent.verify_piece(piece_index, data):
                self.torrent.set_have(piece_index)
                self.downloaded += len(data)
                restored += 1
            else:
                log.warning("Saved piece %d failed SHA-1 verification; downloading it again", piece_index)

        if bytes(self.torrent.bitfield) != saved_bitfield:
            self._persist_resume()
        if restored:
            log.info("Resumed %d verified pieces (%.1f%%)", restored, self.torrent.progress() * 100)

    def _persist_resume(self):
        if not self.resume_store or not self.torrent:
            return
        try:
            self.resume_store.save(bytes(self.torrent.bitfield))
        except OSError as exc:
            log.warning("Could not save resume checkpoint: %s", exc)

    async def _start_listener(self):
        try:
            self._server = await asyncio.start_server(self._accept_peer, "0.0.0.0", self.port)
        except OSError as exc:
            if self.port == 0:
                raise
            log.warning("Could not bind peer port %d (%s); using an ephemeral port", self.port, exc)
            self._server = await asyncio.start_server(self._accept_peer, "0.0.0.0", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("Listening for peer connections on port %d", self.port)

    async def _accept_peer(self, reader, writer):
        peer = None
        try:
            handshake = await asyncio.wait_for(reader.readexactly(68), timeout=10)
            if handshake[:20] != b"\x13BitTorrent protocol" or handshake[28:48] != self.info_hash:
                return
            if handshake[48:68] == self.peer_id:
                return
            address = writer.get_extra_info("peername") or ("unknown", 0)
            peer = PeerConnection(self.peer_id, self.info_hash, address[0], address[1], self)
            peer.reader, peer.writer, peer.connected = reader, writer, True
            peer.supports_extensions = bool(handshake[25] & 0x10)
            reserved = bytearray(8)
            reserved[5] |= 0x10
            response = b"\x13BitTorrent protocol" + bytes(reserved) + self.info_hash + self.peer_id
            writer.write(response)
            await writer.drain()
            if peer.supports_extensions:
                await peer.send_extension_handshake()
            peer.pex_address = None  # Inbound source ports are not necessarily listening ports.
            if self.torrent and any(self.torrent.bitfield):
                await peer.send_message(MessageType.BITFIELD, bytes(self.torrent.bitfield))
                peer.bitfield_sent = True
            self.peers.append(peer)
            task = asyncio.create_task(self._handle_peer(peer))
            self._peer_tasks.add(task)
            task.add_done_callback(self._peer_tasks.discard)
            peer = None  # Ownership transferred to _handle_peer.
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, OSError):
            pass
        finally:
            if peer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _tracker_loop(self):
        urls = list(dict.fromkeys(self.tracker_urls))
        if not urls:
            return

        while self.running and (self.torrent is None or not self.torrent.is_complete()):
            requests = []
            request_urls = []
            for tracker_url in urls:
                event = "started" if tracker_url not in self._started_trackers else ""
                requests.append(
                    self.tracker.announce(
                        tracker_url,
                        uploaded=self.uploaded,
                        downloaded=self.downloaded,
                        left=(self.torrent.info.total_size - self.downloaded) if self.torrent else 1,
                        event=event,
                    )
                )
                request_urls.append(tracker_url)

            results = await asyncio.gather(*requests, return_exceptions=True)
            next_interval = 300
            peers = []
            for tracker_url, result in zip(request_urls, results):
                if isinstance(result, BaseException):
                    log.warning("Tracker %s failed: %s", tracker_url, result)
                    continue
                response = result
                self._started_trackers.add(tracker_url)
                next_interval = min(next_interval, response.interval)
                log.info("Tracker %s returned %d peers", tracker_url, len(response.peers))
                peers.extend(response.peers)
            await self._connect_to_peers(peers)
            await asyncio.sleep(max(15, min(next_interval, 300)))

    async def _dht_loop(self):
        try:
            self.dht = await DHTClient(
                self.info_hash,
                peer_port=self.port,
                bind_port=self.port,
            ).start()
            while self.running and (self.torrent is None or not self.torrent.is_complete()):
                peers = await self.dht.find_peers()
                log.info("DHT lookup returned %d peers", len(peers))
                await self._connect_to_peers(peers)
                await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("DHT discovery unavailable: %s", exc)

    async def _connect_to_peers(self, addresses):
        current = {(peer.ip, peer.port) for peer in self.peers if peer.connected}
        unique = []
        for ip, port in addresses:
            address = (ip, int(port))
            if address not in current and address not in self._connecting and address not in unique and 0 < address[1] <= 65535:
                unique.append(address)
            if len(unique) >= MAX_PEERS - len(current):
                break

        async def connect_one(ip, port):
            address = (ip, int(port))
            self._connecting.add(address)
            peer = PeerConnection(self.peer_id, self.info_hash, ip, port, self)
            try:
                await peer.connect()
                if self.torrent and any(self.torrent.bitfield):
                    await peer.send_message(MessageType.BITFIELD, bytes(self.torrent.bitfield))
                    peer.bitfield_sent = True
                await peer.send_interested()
                self.peers.append(peer)
                task = asyncio.create_task(self._handle_peer(peer))
                self._peer_tasks.add(task)
                task.add_done_callback(self._peer_tasks.discard)
                return peer
            except Exception as exc:
                log.debug("Peer %s:%d rejected connection: %s", ip, port, exc)
                await peer.close()
                return None
            finally:
                self._connecting.discard(address)

        if unique:
            results = await asyncio.gather(*(connect_one(ip, port) for ip, port in unique), return_exceptions=True)
            await self._broadcast_pex(peer.pex_address for peer in results if isinstance(peer, PeerConnection))

    async def _handle_extension(self, peer: PeerConnection, payload: bytes):
        if not payload:
            return
        extension_id, body = payload[0], payload[1:]
        if extension_id == 0:
            try:
                handshake = decode_complete(body)
            except ValueError:
                return
            if not isinstance(handshake, dict):
                return
            extensions = handshake.get(b"m", {})
            if not isinstance(extensions, dict):
                return
            pex_id = extensions.get(b"ut_pex")
            if isinstance(pex_id, int) and 0 < pex_id < 256:
                peer.remote_extensions[b"ut_pex"] = pex_id
                addresses = (
                    known.pex_address for known in self.peers
                    if known is not peer and known.connected and known.pex_address
                )
                await self._send_pex(peer, addresses)
            metadata_id = extensions.get(b"ut_metadata")
            if isinstance(metadata_id, int) and 0 < metadata_id < 256:
                peer.remote_extensions[b"ut_metadata"] = metadata_id
                size = handshake.get(b"metadata_size")
                if (
                    self.torrent is None
                    and isinstance(size, int)
                    and 0 < size <= MAX_METADATA_SIZE
                    and (self._metadata_size is None or self._metadata_size == size)
                ):
                    self._metadata_size = size
                    peer.metadata_size = size
                    await self._queue_metadata(peer)
            return

        if extension_id == METADATA_LOCAL_ID:
            await self._handle_metadata_message(peer, body)
        elif extension_id == PEX_LOCAL_ID:
            try:
                message = decode_complete(body)
            except ValueError:
                return
            if not isinstance(message, dict):
                return
            added, dropped = parse_pex(message)
            if added:
                await self._connect_to_peers(added)
            if dropped:
                await self._broadcast_pex((), exclude=peer, dropped=dropped)

    async def _queue_metadata(self, peer: PeerConnection):
        if (
            self.torrent
            or not peer.connected
            or self._metadata_size is None
            or peer.metadata_size != self._metadata_size
        ):
            return
        piece_count = (self._metadata_size + METADATA_BLOCK_SIZE - 1) // METADATA_BLOCK_SIZE
        queued = set(peer.metadata_queue)
        for piece in range(piece_count):
            if piece not in self._metadata_chunks and piece not in self._metadata_requested and piece not in queued:
                peer.metadata_queue.append(piece)
        await self._fill_metadata_window(peer)

    async def _fill_metadata_window(self, peer: PeerConnection):
        if self.torrent or not peer.connected or b"ut_metadata" not in peer.remote_extensions:
            return
        while peer.metadata_queue and len(peer.metadata_outstanding) < MAX_METADATA_IN_FLIGHT:
            piece = peer.metadata_queue.pop(0)
            if piece in self._metadata_chunks or piece in self._metadata_requested:
                continue
            peer.metadata_outstanding.add(piece)
            self._metadata_requested[piece] = peer
            request = encode({b"msg_type": 0, b"piece": piece})
            await peer.send_extended(peer.remote_extensions[b"ut_metadata"], request)
            self._metadata_timeouts[piece] = asyncio.create_task(
                self._metadata_request_timeout(piece, peer)
            )

    async def _handle_metadata_message(self, peer: PeerConnection, body: bytes):
        try:
            header, header_end = decode(body)
        except ValueError:
            return
        if not isinstance(header, dict):
            return
        message_type = header.get(b"msg_type")
        piece = header.get(b"piece")
        if not isinstance(piece, int) or piece < 0:
            return
        if message_type == 0:
            await self._serve_metadata_request(peer, piece)
            return
        if message_type == 2:
            if self._metadata_requested.get(piece) is peer:
                self._metadata_requested.pop(piece, None)
                peer.metadata_outstanding.discard(piece)
                self._cancel_metadata_timeout(piece)
                await self._assign_metadata_piece(piece, peer)
            return
        if message_type != 1 or self.torrent is not None:
            return
        if self._metadata_requested.get(piece) is not peer or self._metadata_size is None:
            return
        reported_size = header.get(b"total_size")
        if reported_size is not None and reported_size != self._metadata_size:
            await peer.close()
            return

        expected_size = min(METADATA_BLOCK_SIZE, self._metadata_size - piece * METADATA_BLOCK_SIZE)
        data = body[header_end:]
        if expected_size <= 0 or len(data) != expected_size:
            await peer.close()
            return

        self._metadata_requested.pop(piece, None)
        peer.metadata_outstanding.discard(piece)
        self._cancel_metadata_timeout(piece)
        self._metadata_chunks[piece] = data
        self._metadata_sources[piece] = peer
        count = (self._metadata_size + METADATA_BLOCK_SIZE - 1) // METADATA_BLOCK_SIZE
        if len(self._metadata_chunks) == count:
            raw_info = b"".join(self._metadata_chunks[index] for index in range(count))
            if hashlib.sha1(raw_info).digest() != self.info_hash:
                log.warning("Magnet metadata failed info-hash verification")
                bad_peers = set(self._metadata_sources.values())
                self._metadata_chunks.clear()
                self._metadata_sources.clear()
                self._metadata_requested.clear()
                self._cancel_all_metadata_timeouts()
                for connected_peer in self.peers:
                    connected_peer.metadata_outstanding.clear()
                    connected_peer.metadata_queue.clear()
                for bad_peer in bad_peers:
                    await bad_peer.close()
                return
            try:
                info = parse_info_bytes(raw_info, trackers=self.tracker_urls)
                self._install_metadata(info)
            except (ValueError, OSError) as exc:
                log.warning("Invalid magnet metadata: %s", exc)
                await peer.close()
                return
            self._metadata_chunks.clear()
            self._metadata_sources.clear()
            self._metadata_requested.clear()
            self._cancel_all_metadata_timeouts()
            await self._activate_metadata_for_peers()
            return

        await self._queue_metadata(peer)

    def _cancel_metadata_timeout(self, piece: int):
        task = self._metadata_timeouts.pop(piece, None)
        if task:
            task.cancel()

    def _cancel_all_metadata_timeouts(self):
        for task in self._metadata_timeouts.values():
            task.cancel()
        self._metadata_timeouts.clear()

    async def _metadata_request_timeout(self, piece: int, peer: PeerConnection):
        try:
            await asyncio.sleep(METADATA_REQUEST_TIMEOUT)
            if self._metadata_requested.get(piece) is not peer:
                return
            self._metadata_requested.pop(piece, None)
            peer.metadata_outstanding.discard(piece)
            self._metadata_timeouts.pop(piece, None)
            await self._assign_metadata_piece(piece, peer, retry_same=True)
        except asyncio.CancelledError:
            raise

    async def _assign_metadata_piece(self, piece: int, exclude: PeerConnection, retry_same=False):
        candidates = [candidate for candidate in self.peers if candidate is not exclude]
        if retry_same:
            candidates.extend(candidate for candidate in self.peers if candidate is exclude)
        for candidate in candidates:
            if (
                candidate.connected
                and b"ut_metadata" in candidate.remote_extensions
                and candidate.metadata_size == self._metadata_size
            ):
                if piece not in candidate.metadata_queue:
                    candidate.metadata_queue.append(piece)
                await self._fill_metadata_window(candidate)
                return

    async def _release_metadata_peer(self, peer: PeerConnection):
        lost = [piece for piece, owner in self._metadata_requested.items() if owner is peer]
        for piece in lost:
            self._metadata_requested.pop(piece, None)
            self._cancel_metadata_timeout(piece)
        received = [piece for piece, owner in self._metadata_sources.items() if owner is peer]
        for piece in received:
            self._metadata_sources.pop(piece, None)
            self._metadata_chunks.pop(piece, None)
        peer.metadata_outstanding.clear()
        peer.metadata_queue.clear()
        if self.torrent is None:
            for candidate in self.peers:
                if candidate is not peer and candidate.connected:
                    await self._queue_metadata(candidate)

    async def _serve_metadata_request(self, peer: PeerConnection, piece: int):
        extension_id = peer.remote_extensions.get(b"ut_metadata")
        if extension_id is None:
            return
        raw_info = self.torrent.info.raw_info if self.torrent else b""
        start = piece * METADATA_BLOCK_SIZE
        if not raw_info or start >= len(raw_info):
            response = encode({b"msg_type": 2, b"piece": piece})
        else:
            response = encode({b"msg_type": 1, b"piece": piece, b"total_size": len(raw_info)})
            response += raw_info[start:start + METADATA_BLOCK_SIZE]
        await peer.send_extended(extension_id, response)

    async def _activate_metadata_for_peers(self):
        if not self.torrent:
            return
        for peer in tuple(self.peers):
            if not peer.connected:
                continue
            if peer.supports_extensions:
                await peer.send_extension_handshake()
            if peer.pending_bitfield is not None:
                try:
                    peer.update_bitfield(peer.pending_bitfield, self.torrent.info.num_pieces)
                except (ValueError, PeerError):
                    await peer.close()
                    continue
                peer.pending_bitfield = None
            for piece in peer.pending_have:
                try:
                    peer.set_have(piece, self.torrent.info.num_pieces)
                except (ValueError, PeerError):
                    await peer.close()
                    break
            peer.pending_have.clear()
            if not peer.connected:
                continue
            if not peer.bitfield_sent and any(self.torrent.bitfield):
                await peer.send_message(MessageType.BITFIELD, bytes(self.torrent.bitfield))
                peer.bitfield_sent = True
            if not peer.peer_choking:
                await self._assign_piece(peer)

    async def _send_pex(self, peer: PeerConnection, addresses, dropped=()):
        if not peer.connected or b"ut_pex" not in peer.remote_extensions:
            return
        added = []
        for address in addresses:
            if not address or address == peer.pex_address or address in peer.pex_announced:
                continue
            added.append(address)
            if len(added) == 50:
                break
        dropped = list(dropped)[:50]
        if not added and not dropped:
            return
        try:
            payload = encode_pex(added, dropped)
            peer_id = peer.remote_extensions[b"ut_pex"]
            await peer.send_message(MessageType.EXTENDED, bytes((peer_id,)) + payload)
            peer.pex_announced.update(added)
        except (OSError, ValueError):
            log.debug("Could not send PEX update to %s:%d", peer.ip, peer.port)

    async def _broadcast_pex(self, addresses=(), exclude=None, dropped=()):
        addresses = tuple(address for address in addresses if address)
        dropped = tuple(address for address in dropped if address)
        if not addresses and not dropped:
            return
        await asyncio.gather(*(
            self._send_pex(peer, addresses, dropped)
            for peer in self.peers
            if peer is not exclude and peer.connected and b"ut_pex" in peer.remote_extensions
        ), return_exceptions=True)

    async def _handle_peer(self, peer: PeerConnection):
        try:
            while self.running and peer.connected:
                message_id, payload = await peer.read_message()
                if message_id is None:
                    break
                if message_id == MessageType.CHOKE:
                    peer.peer_choking = True
                    await self._release_peer_piece(peer)
                elif message_id == MessageType.UNCHOKE:
                    peer.peer_choking = False
                    await self._assign_piece(peer)
                elif message_id == MessageType.INTERESTED:
                    if peer.am_choking:
                        peer.am_choking = False
                        await peer.send_message(MessageType.UNCHOKE)
                elif message_id == MessageType.HAVE:
                    if len(payload) != 4:
                        raise ValueError("Malformed HAVE message")
                    piece_index = int.from_bytes(payload, "big")
                    if self.torrent is None:
                        peer.pending_have.add(piece_index)
                    else:
                        peer.set_have(piece_index, self.torrent.info.num_pieces)
                        if not peer.peer_choking and peer.assigned_piece is None:
                            await self._assign_piece(peer)
                elif message_id == MessageType.BITFIELD:
                    if self.torrent is None:
                        peer.pending_bitfield = payload
                    else:
                        peer.update_bitfield(payload, self.torrent.info.num_pieces)
                        if not peer.peer_choking:
                            await self._assign_piece(peer)
                elif message_id == MessageType.PIECE:
                    await self._receive_block(peer, payload)
                elif message_id == MessageType.REQUEST:
                    await self._serve_request(peer, payload)
                elif message_id == MessageType.EXTENDED:
                    await self._handle_extension(peer, payload)
                # Ignore keepalives and message types we do not implement.
        except (OSError, ValueError, PeerError, asyncio.IncompleteReadError) as exc:
            log.debug("Peer %s:%d ended: %s", peer.ip, peer.port, exc)
        finally:
            await self._release_peer_piece(peer)
            await self._release_metadata_peer(peer)
            if peer.pex_address:
                await self._broadcast_pex((), exclude=peer, dropped=(peer.pex_address,))
            await peer.close()

    async def _assign_piece(self, peer: PeerConnection):
        if self.torrent is None or peer.peer_choking or peer.assigned_piece is not None or not peer.connected:
            return
        candidates = [
            index for index in range(self.torrent.info.num_pieces)
            if not self.torrent.has_piece(index)
            and index not in self._assigned
            and peer.has_piece(index)
        ]
        if not candidates:
            return
        # Rarest-first among pieces currently advertised by connected peers.
        piece_index = min(
            candidates,
            key=lambda index: sum(1 for other in self.peers if other.connected and other.has_piece(index)),
        )
        piece_length = self.torrent.info.get_piece_length(piece_index)
        blocks = {
            offset: min(BLOCK_SIZE, piece_length - offset)
            for offset in range(0, piece_length, BLOCK_SIZE)
        }
        assembly = self._pieces.setdefault(piece_index, PieceAssembly(bytearray(piece_length), blocks))
        assembly.owner = peer
        peer.assigned_piece = piece_index
        self._assigned[piece_index] = peer
        await self._fill_request_window(peer, assembly)

    async def _fill_request_window(self, peer: PeerConnection, assembly: PieceAssembly):
        piece_index = peer.assigned_piece
        if piece_index is None or peer.peer_choking or not peer.connected:
            return
        pending = [
            (offset, length) for offset, length in assembly.block_lengths.items()
            if offset not in assembly.received and (piece_index, offset) not in peer.outstanding
        ]
        slots = max(0, MAX_IN_FLIGHT - len(peer.outstanding))
        for offset, length in pending[:slots]:
            await peer.send_request(piece_index, offset, length)

    async def _receive_block(self, peer: PeerConnection, payload: bytes):
        if len(payload) < 8:
            raise ValueError("Malformed PIECE message")
        piece_index, begin = int.from_bytes(payload[:4], "big"), int.from_bytes(payload[4:8], "big")
        block = payload[8:]
        if (piece_index, begin) not in peer.outstanding:
            return
        peer.outstanding.remove((piece_index, begin))
        if peer.assigned_piece != piece_index:
            return
        assembly = self._pieces.get(piece_index)
        if assembly is None or begin not in assembly.block_lengths:
            return
        expected_length = assembly.block_lengths[begin]
        if len(block) != expected_length or begin in assembly.received:
            return

        assembly.data[begin:begin + len(block)] = block
        assembly.received.add(begin)
        self.downloaded += len(block)

        if len(assembly.received) == len(assembly.block_lengths):
            piece_data = bytes(assembly.data)
            if self.torrent.verify_piece(piece_index, piece_data):
                self.storage.write_piece(piece_index, piece_data)
                self.torrent.set_have(piece_index)
                self._persist_resume()
                log.debug("Verified piece %d/%d (%.1f%%)", piece_index + 1, self.torrent.info.num_pieces, self.torrent.progress() * 100)
                for other in self.peers:
                    if other.connected:
                        await other.send_message(MessageType.HAVE, piece_index.to_bytes(4, "big"))
            else:
                log.warning("Piece %d failed SHA-1 verification; retrying", piece_index)
                self.downloaded -= len(piece_data)
            self._assigned.pop(piece_index, None)
            self._pieces.pop(piece_index, None)
            peer.assigned_piece = None
            await self._assign_piece(peer)
            return

        await self._fill_request_window(peer, assembly)

    async def _release_peer_piece(self, peer: PeerConnection):
        piece_index = peer.assigned_piece
        if piece_index is None:
            peer.outstanding.clear()
            return
        if self._assigned.get(piece_index) is peer:
            self._assigned.pop(piece_index, None)
            self._pieces.pop(piece_index, None)
        peer.assigned_piece = None
        peer.outstanding.clear()

    async def _serve_request(self, peer: PeerConnection, payload: bytes):
        if len(payload) != 12 or not self.torrent or peer.am_choking:
            return
        piece_index, begin, length = (int.from_bytes(payload[i:i + 4], "big") for i in (0, 4, 8))
        if length <= 0 or length > BLOCK_SIZE or not self.torrent.has_piece(piece_index):
            return
        piece_length = self.torrent.info.get_piece_length(piece_index)
        if begin + length > piece_length:
            return
        data = self.storage.read_piece(piece_index)
        await peer.send_message(MessageType.PIECE, piece_index.to_bytes(4, "big") + begin.to_bytes(4, "big") + data[begin:begin + length])
        self.uploaded += length

    def get_progress(self) -> dict:
        if not self.torrent:
            return {"progress": 0.0, "downloaded": 0, "total": 0, "peers": 0, "speed": 0.0}
        elapsed = max(time.monotonic() - self._download_started, 0.001)
        return {
            "progress": self.torrent.progress(),
            "downloaded": self.downloaded,
            "total": self.torrent.info.total_size,
            "peers": sum(peer.connected for peer in self.peers),
            "speed": self.downloaded / elapsed,
        }
