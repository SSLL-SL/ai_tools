"""Magnet URI parsing for BitTorrent v1 (BEP 9 metadata exchange)."""

import base64
import binascii
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class MagnetInfo:
    info_hash: bytes
    display_name: str
    trackers: tuple[str, ...]


def parse_magnet_uri(uri: str) -> MagnetInfo:
    if not uri.lower().startswith("magnet:?"):
        raise ValueError("Enlace magnet inválido: debe comenzar por magnet:?")
    params = parse_qs(urlsplit(uri).query, keep_blank_values=True)
    xt = next((value for value in params.get("xt", ()) if value.lower().startswith("urn:btih:")), None)
    if not xt:
        raise ValueError("El magnet debe incluir xt=urn:btih:<info-hash>")
    digest = xt.split(":", 2)[2]
    try:
        if re.fullmatch(r"[0-9a-fA-F]{40}", digest):
            info_hash = bytes.fromhex(digest)
        elif re.fullmatch(r"[A-Z2-7a-z]{32}", digest):
            info_hash = base64.b32decode(digest.upper())
        else:
            raise ValueError
    except (ValueError, binascii.Error) as exc:
        raise ValueError("El info-hash del magnet debe ser BTIH hexadecimal o Base32") from exc
    if len(info_hash) != 20:
        raise ValueError("El info-hash BTIH debe ocupar 20 bytes")
    trackers = tuple(dict.fromkeys(value for value in params.get("tr", ()) if value))
    return MagnetInfo(
        info_hash=info_hash,
        display_name=params.get("dn", ["Magnet torrent"])[0],
        trackers=trackers,
    )
