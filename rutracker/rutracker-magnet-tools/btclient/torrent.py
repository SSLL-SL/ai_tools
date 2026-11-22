import hashlib
import os
from dataclasses import dataclass, field
from typing import List

from .bencode import BencodeError, decode_torrent


@dataclass(frozen=True)
class FileInfo:
    path: str
    length: int


@dataclass(frozen=True)
class TorrentInfo:
    name: str
    piece_length: int
    pieces: List[bytes]
    files: List[FileInfo]
    info_hash: bytes
    trackers: List[str] = field(default_factory=list)
    multi_file: bool = False
    raw_info: bytes = b""

    @property
    def total_size(self) -> int:
        return sum(file.length for file in self.files)

    @property
    def num_pieces(self) -> int:
        return len(self.pieces)

    @property
    def is_multi_file(self) -> bool:
        return self.multi_file

    def get_piece_length(self, piece_index: int) -> int:
        if not 0 <= piece_index < self.num_pieces:
            raise IndexError("Piece index out of range")
        if piece_index == self.num_pieces - 1:
            return self.total_size - piece_index * self.piece_length
        return self.piece_length


class Torrent:
    def __init__(self, info: TorrentInfo):
        self.info = info
        self.bitfield = bytearray((info.num_pieces + 7) // 8)
        self.have = [False] * info.num_pieces

    def set_have(self, piece_index: int):
        if not 0 <= piece_index < self.info.num_pieces:
            raise IndexError("Piece index out of range")
        self.bitfield[piece_index // 8] |= 0x80 >> (piece_index % 8)
        self.have[piece_index] = True

    def has_piece(self, piece_index: int) -> bool:
        return self.have[piece_index]

    def is_complete(self) -> bool:
        return all(self.have)

    def progress(self) -> float:
        return sum(self.have) / len(self.have) if self.have else 1.0

    def get_missing_pieces(self) -> List[int]:
        return [index for index, have in enumerate(self.have) if not have]

    def verify_piece(self, piece_index: int, data: bytes) -> bool:
        if not 0 <= piece_index < self.info.num_pieces:
            return False
        return (
            len(data) == self.info.get_piece_length(piece_index)
            and hashlib.sha1(data).digest() == self.info.pieces[piece_index]
        )


def _text(value: bytes, field_name: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BencodeError(f"Torrent field {field_name!r} is not valid UTF-8") from exc


def _safe_relative_path(parts) -> str:
    decoded = [_text(part, "path") for part in parts]
    if not decoded or any(part in ("", ".", "..") or "/" in part or "\\" in part for part in decoded):
        raise BencodeError("Torrent contains an unsafe file path")
    path = os.path.join(*decoded)
    if os.path.isabs(path):
        raise BencodeError("Torrent contains an absolute file path")
    return path


def parse_torrent_bytes(data: bytes) -> TorrentInfo:
    decoded, raw_info = decode_torrent(data)
    info = decoded[b"info"]
    try:
        name = _text(info[b"name"], "name")
        _safe_relative_path([info[b"name"]])
        piece_length = info[b"piece length"]
        pieces_raw = info[b"pieces"]
    except (KeyError, TypeError) as exc:
        raise BencodeError("Torrent info dictionary is missing required fields") from exc

    if not isinstance(piece_length, int) or piece_length <= 0:
        raise BencodeError("Invalid piece length")
    if not isinstance(pieces_raw, bytes) or len(pieces_raw) % 20:
        raise BencodeError("Invalid pieces hash string")
    pieces = [pieces_raw[offset:offset + 20] for offset in range(0, len(pieces_raw), 20)]

    multi_file = b"files" in info
    files = []
    try:
        if multi_file:
            for entry in info[b"files"]:
                length = entry[b"length"]
                files.append(FileInfo(_safe_relative_path(entry[b"path"]), length))
        else:
            files.append(FileInfo(_safe_relative_path([info[b"name"]]), info[b"length"]))
    except (KeyError, TypeError) as exc:
        raise BencodeError("Torrent contains invalid file metadata") from exc

    if any(not isinstance(file.length, int) or file.length < 0 for file in files):
        raise BencodeError("Torrent contains an invalid file length")
    total_size = sum(file.length for file in files)
    expected_pieces = (total_size + piece_length - 1) // piece_length
    if len(pieces) != expected_pieces:
        raise BencodeError(
            f"Torrent has {len(pieces)} piece hashes; expected {expected_pieces}"
        )

    trackers = []
    announce = decoded.get(b"announce")
    if isinstance(announce, bytes):
        trackers.append(_text(announce, "announce"))
    for tier in decoded.get(b"announce-list", []):
        if isinstance(tier, list):
            for tracker in tier:
                if isinstance(tracker, bytes):
                    value = _text(tracker, "announce-list")
                    if value not in trackers:
                        trackers.append(value)

    return TorrentInfo(
        name=name,
        piece_length=piece_length,
        pieces=pieces,
        files=files,
        info_hash=hashlib.sha1(raw_info).digest(),
        trackers=trackers,
        multi_file=multi_file,
        raw_info=raw_info,
    )


def parse_torrent_file(path: str) -> TorrentInfo:
    with open(path, "rb") as file:
        return parse_torrent_bytes(file.read())


def parse_info_bytes(raw_info: bytes, trackers=None) -> TorrentInfo:
    """Parse BEP 9 metadata bytes without altering their hashed representation."""
    # Keep the supplied info dictionary byte-for-byte for its SHA-1 info-hash.
    wrapped = b"d4:info" + raw_info + b"e"
    info = parse_torrent_bytes(wrapped)
    if trackers:
        from dataclasses import replace
        info = replace(info, trackers=list(dict.fromkeys(trackers)))
    return info
