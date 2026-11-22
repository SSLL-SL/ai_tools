import os

from .torrent import TorrentInfo


class PieceStorage:
    """Maps the torrent's contiguous byte stream to its destination files."""

    def __init__(self, info: TorrentInfo, save_path: str):
        self.info = info
        root = os.path.abspath(save_path)
        base = os.path.join(root, info.name) if info.is_multi_file else root
        os.makedirs(base, exist_ok=True)
        self._segments = []
        self._files = []
        offset = 0
        try:
            for entry in info.files:
                full_path = os.path.abspath(os.path.join(base, entry.path))
                if os.path.commonpath((base, full_path)) != base:
                    raise ValueError("Torrent path escapes destination directory")
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                try:
                    handle = open(full_path, "r+b")
                except FileNotFoundError:
                    handle = open(full_path, "w+b")
                self._files.append(handle)
                handle.truncate(entry.length)
                self._segments.append((offset, offset + entry.length, handle))
                offset += entry.length
        except Exception:
            self.close()
            raise

    def _write_at(self, offset: int, data: bytes):
        end = offset + len(data)
        cursor = offset
        for segment_start, segment_end, handle in self._segments:
            if segment_end <= cursor or segment_start >= end:
                continue
            start = max(cursor, segment_start)
            stop = min(end, segment_end)
            if stop > start:
                handle.seek(start - segment_start)
                handle.write(data[start - offset:stop - offset])
                cursor = stop
            if cursor >= end:
                break
        if cursor != end:
            raise IOError("Torrent piece could not be mapped to destination files")

    def write_piece(self, piece_index: int, data: bytes):
        expected = self.info.get_piece_length(piece_index)
        if len(data) != expected:
            raise ValueError(f"Piece {piece_index} has {len(data)} bytes; expected {expected}")
        self._write_at(piece_index * self.info.piece_length, data)
        for handle in self._files:
            handle.flush()

    def read_piece(self, piece_index: int) -> bytes:
        offset = piece_index * self.info.piece_length
        length = self.info.get_piece_length(piece_index)
        end = offset + length
        chunks = []
        cursor = offset
        for segment_start, segment_end, handle in self._segments:
            if segment_end <= cursor or segment_start >= end:
                continue
            start = max(cursor, segment_start)
            stop = min(end, segment_end)
            handle.seek(start - segment_start)
            chunks.append(handle.read(stop - start))
            cursor = stop
            if cursor >= end:
                break
        data = b"".join(chunks)
        if len(data) != length:
            raise IOError(f"Piece {piece_index} is not fully present on disk")
        return data

    def close(self):
        for handle in getattr(self, "_files", []):
            if not handle.closed:
                handle.close()
