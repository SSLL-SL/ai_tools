"""Crash-safe, per-torrent download checkpoints."""

import base64
import json
import os
import tempfile

from .torrent import TorrentInfo


class ResumeStore:
    VERSION = 1

    def __init__(self, save_path: str, info: TorrentInfo):
        self.directory = os.path.join(os.path.abspath(save_path), ".btclient")
        self.path = os.path.join(self.directory, f"{info.info_hash.hex()}.resume.json")
        self.info = info

    def load(self):
        """Return the saved bitfield, or None when there is no valid checkpoint."""
        try:
            with open(self.path, "rb") as file:
                raw = file.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                return None
            document = json.loads(raw)
            if not isinstance(document, dict):
                return None
            if (
                document.get("version") != self.VERSION
                or document.get("info_hash") != self.info.info_hash.hex()
                or document.get("piece_length") != self.info.piece_length
                or document.get("total_size") != self.info.total_size
                or document.get("num_pieces") != self.info.num_pieces
            ):
                return None
            bitfield = base64.b64decode(document["bitfield"], validate=True)
            expected_length = (self.info.num_pieces + 7) // 8
            if len(bitfield) != expected_length:
                return None
            if self.info.num_pieces % 8 and bitfield:
                unused_mask = (1 << (8 - self.info.num_pieces % 8)) - 1
                if bitfield[-1] & unused_mask:
                    return None
            return bitfield
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def save(self, bitfield: bytes):
        expected_length = (self.info.num_pieces + 7) // 8
        if len(bitfield) != expected_length:
            raise ValueError("Resume bitfield has an unexpected length")
        os.makedirs(self.directory, exist_ok=True)
        document = {
            "version": self.VERSION,
            "info_hash": self.info.info_hash.hex(),
            "piece_length": self.info.piece_length,
            "total_size": self.info.total_size,
            "num_pieces": self.info.num_pieces,
            "bitfield": base64.b64encode(bitfield).decode("ascii"),
        }
        payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        fd, temporary_path = tempfile.mkstemp(prefix=".resume-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
            raise
