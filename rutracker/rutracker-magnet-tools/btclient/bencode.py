"""Small, strict bencode implementation used by torrent metadata and trackers."""


class BencodeError(ValueError):
    pass


def _decode(data: bytes, pos: int = 0):
    if pos >= len(data):
        raise BencodeError("Unexpected end of data")

    marker = data[pos]
    if marker == ord("i"):
        end = data.find(b"e", pos + 1)
        if end < 0:
            raise BencodeError("Unterminated integer")
        raw = data[pos + 1:end]
        digits = raw[1:] if raw.startswith(b"-") else raw
        if (
            not digits
            or not digits.isdigit()
            or (len(digits) > 1 and digits.startswith(b"0"))
        ):
            raise BencodeError("Invalid bencoded integer")
        try:
            return int(raw), end + 1
        except ValueError as exc:
            raise BencodeError("Invalid bencoded integer") from exc

    if marker == ord("l"):
        result = []
        pos += 1
        while True:
            if pos >= len(data):
                raise BencodeError("Unterminated list")
            if data[pos] == ord("e"):
                return result, pos + 1
            item, pos = _decode(data, pos)
            result.append(item)

    if marker == ord("d"):
        result = {}
        pos += 1
        previous_key = None
        while True:
            if pos >= len(data):
                raise BencodeError("Unterminated dictionary")
            if data[pos] == ord("e"):
                return result, pos + 1
            key, pos = _decode(data, pos)
            if not isinstance(key, bytes):
                raise BencodeError("Dictionary keys must be byte strings")
            if key in result:
                raise BencodeError("Duplicate dictionary key")
            if previous_key is not None and key < previous_key:
                raise BencodeError("Dictionary keys are not sorted")
            previous_key = key
            result[key], pos = _decode(data, pos)

    if ord("0") <= marker <= ord("9"):
        colon = data.find(b":", pos)
        if colon < 0:
            raise BencodeError("Byte string has no length separator")
        raw_length = data[pos:colon]
        if not raw_length or (len(raw_length) > 1 and raw_length.startswith(b"0")):
            raise BencodeError("Invalid byte string length")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BencodeError("Invalid byte string length") from exc
        start = colon + 1
        end = start + length
        if end > len(data):
            raise BencodeError("Byte string extends beyond end of data")
        return data[start:end], end

    raise BencodeError(f"Invalid bencode marker at offset {pos}")


def decode(data: bytes, pos: int = 0):
    """Decode one bencoded value, returning ``(value, next_offset)``."""
    return _decode(data, pos)


def decode_complete(data: bytes):
    value, end = _decode(data)
    if end != len(data):
        raise BencodeError("Trailing data after bencoded value")
    return value


def decode_torrent(data: bytes):
    """Decode a torrent dictionary and return its exact raw ``info`` bytes."""
    if not data.startswith(b"d"):
        if not data:
            raise BencodeError("El archivo .torrent está vacío")
        sample = data[:80].lstrip(b"\xef\xbb\xbf\r\n\t ").lower()
        if sample.startswith((b"<!doctype html", b"<html", b"<?xml")):
            raise BencodeError(
                "El archivo parece ser una página HTML/XML, no un .torrent; "
                "comprueba que descargaste el archivo torrent y no una página web"
            )
        if sample.startswith(b"magnet:"):
            raise BencodeError(
                "El archivo contiene un enlace magnet, no metadatos .torrent"
            )
        raise BencodeError(
            "El archivo no parece un .torrent bencode válido "
            f"(bytes iniciales: {data[:24]!r})"
        )

    result = {}
    raw_info = None
    pos = 1
    previous_key = None
    while True:
        if pos >= len(data):
            raise BencodeError("Unterminated torrent dictionary")
        if data[pos] == ord("e"):
            pos += 1
            break
        key, pos = _decode(data, pos)
        if not isinstance(key, bytes):
            raise BencodeError("Dictionary keys must be byte strings")
        if key in result:
            raise BencodeError("Duplicate dictionary key")
        if previous_key is not None and key < previous_key:
            raise BencodeError("Dictionary keys are not sorted")
        previous_key = key
        value_start = pos
        value, pos = _decode(data, pos)
        result[key] = value
        if key == b"info":
            raw_info = data[value_start:pos]

    if pos != len(data):
        raise BencodeError("Trailing data after torrent dictionary")
    if raw_info is None or not isinstance(result.get(b"info"), dict):
        raise BencodeError("Torrent has no info dictionary")
    return result, raw_info


def encode(value) -> bytes:
    if isinstance(value, bool):
        raise BencodeError("Booleans are not bencode values")
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        return encode(value.encode("utf-8"))
    if isinstance(value, (list, tuple)):
        return b"l" + b"".join(encode(item) for item in value) + b"e"
    if isinstance(value, dict):
        if not all(isinstance(key, bytes) for key in value):
            raise BencodeError("Dictionary keys must be bytes")
        parts = []
        for key in sorted(value):
            parts.extend((encode(key), encode(value[key])))
        return b"d" + b"".join(parts) + b"e"
    raise BencodeError(f"Cannot bencode values of type {type(value).__name__}")
