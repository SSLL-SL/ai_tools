#!/usr/bin/env python3
"""
Descifrador de tramas KeeLoq para Clemsa Mutancode.

Uso:
    python3 keeloq_clemsa.py <trama_hex>

Ejemplo:
    python3 keeloq_clemsa.py 24803f36a5634e40
"""

import sys

NLF = 0x3A5C742E
ROUNDS = 528
CLEMSA_KEY = 0xA1B58921A3A738AA


def keeloq_encrypt(data, key):
    x = data
    for r in range(ROUNDS):
        g = (((x >> 1) & 1) + ((x >> 9) & 1) * 2 + ((x >> 20) & 1) * 4 +
             ((x >> 26) & 1) * 8 + ((x >> 31) & 1) * 16)
        f = (((x >> 0) & 1) ^ ((x >> 16) & 1) ^ ((key >> (r & 63)) & 1) ^
             ((NLF >> g) & 1))
        x = ((x >> 1) | (f << 31)) & 0xFFFFFFFF
    return x


def keeloq_decrypt(data, key):
    x = data
    for r in range(ROUNDS):
        g = (((x >> 0) & 1) + ((x >> 8) & 1) * 2 + ((x >> 19) & 1) * 4 +
             ((x >> 25) & 1) * 8 + ((x >> 30) & 1) * 16)
        m = (15 - r) & 63
        f = (((x >> 31) & 1) ^ ((x >> 15) & 1) ^ ((key >> m) & 1) ^
             ((NLF >> g) & 1))
        x = ((x << 1) | f) & 0xFFFFFFFF
    return x


def normal_learning(serial28, key):
    d = serial28 & 0x0FFFFFFF
    k1 = keeloq_decrypt(d | 0x20000000, key)
    k2 = keeloq_decrypt(d | 0x60000000, key)
    return (k2 << 32) | k1


def reverse_bits(value, bit_count):
    result = 0
    for i in range(bit_count):
        result = (result << 1) | ((value >> i) & 1)
    return result


def decode_frame(frame_hex, air_format=False):
    frame = int(frame_hex, 16)
    if air_format:
        frame = reverse_bits(frame, 64)
    fix = (frame >> 32) & 0xFFFFFFFF
    hop = frame & 0xFFFFFFFF

    button = (fix >> 28) & 0xF
    serial = fix & 0x0FFFFFFF
    serial_hi = (serial >> 16) & 0xFFFF
    serial_lo = serial & 0xFFFF
    serial_display = f"{serial_hi:04X} {serial_lo:05d}"

    man_key = normal_learning(fix, CLEMSA_KEY)
    decrypted = keeloq_decrypt(hop, man_key)

    dec_btn = (decrypted >> 28) & 0xF
    disc12 = (decrypted >> 16) & 0xFFF
    disc8 = (decrypted >> 16) & 0xFF
    cnt = decrypted & 0xFFFF

    valid = dec_btn == button and disc12 == 53

    return {
        "frame": frame,
        "fix": fix,
        "hop_encrypted": hop,
        "man_key": man_key,
        "button": button,
        "serial": serial,
        "serial_display": serial_display,
        "discriminator": disc12,
        "counter": cnt,
        "decrypted_hop": decrypted,
        "valid": valid,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 keeloq_clemsa.py <trama_hex> [--air]")
        print("  --air: trama en formato RF (bits invertidos)")
        print("Ejemplo: python3 keeloq_clemsa.py 24803f36a5634e40")
        print("Ejemplo: python3 keeloq_clemsa.py 0272C6A56CFC0124 --air")
        sys.exit(1)

    hex_frame = sys.argv[1]
    air_format = "--air" in sys.argv
    r = decode_frame(hex_frame, air_format)

    print()
    print("╔═══════════════════════════════════════════════╗")
    print("║  CLEMSA MUTANCODE - DESCIFRADOR DE TRAMA     ║")
    print("╚═══════════════════════════════════════════════╝")
    print()
    print(f"  Clave fabricante:  0x{CLEMSA_KEY:016X}")
    print(f"  Trama entrada:     {hex_frame}")
    print()
    print("─── Fix (parte fija) ───")
    print(f"  Fix:               0x{r['fix']:08X}")
    print(f"    Botón:           {r['button']}")
    print(f"    Serial:          {r['serial_display']}")
    print()
    print("─── Hop (parte hopping) ───")
    print(f"  Hop (encrypted):   0x{r['hop_encrypted']:08X}")
    print(f"  Man (device key):  0x{r['man_key']:016X}")
    print(f"  Hop (decrypted):   0x{r['decrypted_hop']:08X}")
    print(f"    Botón:           {r['button']}")
    print(f"    Discriminador:   {r['discriminator']} (0x{r['discriminator']:03X})")
    print(f"    Counter:         {r['counter']}")
    print()
    print(f"  Resultado:         {'✓ VÁLIDA' if r['valid'] else '✗ INVÁLIDA'}")
    print()
