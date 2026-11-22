"""Compact peer address helpers used by BEP 11 peer exchange."""

import ipaddress
import socket
import struct

from .bencode import encode


def parse_pex(message: dict):
    """Return added and dropped ``(ip, port)`` tuples from a PEX dictionary."""
    added = _parse_compact(message.get(b"added", b""), 6, socket.AF_INET)
    added.update(_parse_compact(message.get(b"added6", b""), 18, socket.AF_INET6))
    dropped = _parse_compact(message.get(b"dropped", b""), 6, socket.AF_INET)
    dropped.update(_parse_compact(message.get(b"dropped6", b""), 18, socket.AF_INET6))
    return added, dropped


def _parse_compact(data: bytes, stride: int, family: int):
    addresses = set()
    if not isinstance(data, bytes) or len(data) % stride:
        return addresses
    ip_size = 4 if family == socket.AF_INET else 16
    for offset in range(0, len(data), stride):
        ip = socket.inet_ntop(family, data[offset:offset + ip_size])
        port = struct.unpack("!H", data[offset + ip_size:offset + stride])[0]
        if port:
            addresses.add((ip, port))
    return addresses


def encode_pex(added=(), dropped=()) -> bytes:
    ipv4_added, ipv6_added = bytearray(), bytearray()
    ipv4_dropped, ipv6_dropped = bytearray(), bytearray()
    for collection, ipv4, ipv6 in (
        (added, ipv4_added, ipv6_added),
        (dropped, ipv4_dropped, ipv6_dropped),
    ):
        for ip, port in collection:
            address = ipaddress.ip_address(ip)
            if not 1 <= int(port) <= 65535:
                continue
            target = ipv4 if address.version == 4 else ipv6
            target.extend(address.packed)
            target.extend(struct.pack("!H", int(port)))
    return encode({
        b"added": bytes(ipv4_added),
        b"added6": bytes(ipv6_added),
        b"dropped": bytes(ipv4_dropped),
        b"dropped6": bytes(ipv6_dropped),
    })
