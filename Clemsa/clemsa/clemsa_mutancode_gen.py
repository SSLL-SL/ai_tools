#!/usr/bin/env python3
"""
Generador de tramas KeeLoq para Clemsa Mutancode.

Uso:
    python3 clemsa_mutancode_gen.py <serial> <discriminador> <contador> <boton>

Ejemplo:
    python3 clemsa_mutancode_gen.py 75513654 53 13 2
"""

import sys
import os

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


def generate_frame(serial, discriminator, counter, button):
    """
    Genera una trama Clemsa Mutancode de 64 bits.

    Args:
        serial:       Número de serie (28 bits, sin botón)
        discriminator: Discriminador (12 bits, fijo = 53)
        counter:      Contador (16 bits)
        button:       Botón (4 bits, 1-4)

    Returns:
        tuple: (frame_hex, fix, hop, man_key, decrypted_hop)
    """
    if not (1 <= button <= 4):
        raise ValueError(f"Botón debe ser 1-4, recibido: {button}")
    if not (0 <= serial <= 0x0FFFFFFF):
        raise ValueError(f"Serial debe ser 28 bits (0-{0x0FFFFFFF}), recibido: {serial}")
    if not (0 <= discriminator <= 0xFFF):
        raise ValueError(f"Discriminador debe ser 12 bits (0-4095), recibido: {discriminator}")
    if not (0 <= counter <= 0xFFFF):
        raise ValueError(f"Counter debe ser 16 bits (0-65535), recibido: {counter}")

    fix = (button << 28) | serial
    hop_plain = (button << 28) | (discriminator << 16) | counter
    man_key = normal_learning(fix, CLEMSA_KEY)
    hop_encrypted = keeloq_encrypt(hop_plain, man_key)
    frame_internal = (fix << 32) | hop_encrypted
    frame_air = reverse_bits(frame_internal, 64)

    return frame_air, fix, hop_encrypted, man_key, hop_plain


def decode_frame(frame_air):
    """Decodifica una trama Clemsa Mutancode (para verificación)."""
    internal = reverse_bits(frame_air, 64)
    fix = (internal >> 32) & 0xFFFFFFFF
    hop = internal & 0xFFFFFFFF
    button = (fix >> 28) & 0xF
    serial = fix & 0x0FFFFFFF

    man_key = normal_learning(fix, CLEMSA_KEY)
    decrypted = keeloq_decrypt(hop, man_key)

    disc12 = (decrypted >> 16) & 0xFFF
    cnt = decrypted & 0xFFFF

    return {
        "button": button,
        "serial": serial,
        "discriminator": disc12,
        "counter": cnt,
        "fix": fix,
        "hop_encrypted": hop,
        "hop_decrypted": decrypted,
        "man_key": man_key,
    }


def print_bytes(value, label=""):
    """Imprime los 8 bytes de un valor de 64 bits."""
    b = value.to_bytes(8, "big")
    hex_str = " ".join(f"{byte:02X}" for byte in b)
    if label:
        print(f"  {label}: {hex_str}")
    else:
        print(f"  {hex_str}")
    return b


def generate_sub(frame_air, serial, button, counter, discriminator):
    """Genera el contenido de un archivo .sub para Flipper Zero (modo protocolo)."""
    b = frame_air.to_bytes(8, "big")
    key_hex = " ".join(f"{byte:02X}" for byte in b)

    return f"""Filetype: Flipper SubGhz Key File
Version: 1
# Clemsa Mutancode - Boton {button}
Protocol: KeeLoq
Bit: 64
Key: {key_hex}
"""


def generate_sub_raw(frame_air, button):
    """Genera el contenido de un archivo .sub RAW para Flipper Zero."""
    TE = 400
    raw_values = []

    # Preamble: 10 pares de alto/bajo corto
    for _ in range(10):
        raw_values.append(f"+{TE}")
        raw_values.append(f"-{TE}")

    # Datos: 64 bits, LSB first
    for i in range(64):
        bit = (frame_air >> i) & 1
        if bit == 0:
            raw_values.append(f"+{TE}")
            raw_values.append(f"-{TE * 2}")
        else:
            raw_values.append(f"+{TE * 2}")
            raw_values.append(f"-{TE}")

    raw_data = " ".join(raw_values)

    return f"""Filetype: Flipper SubGhz RAW File
Version: 1
# Clemsa Mutancode - Boton {button}
Protocol: Raw
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
RAW_Data: {raw_data}
"""


if __name__ == "__main__":
    if len(sys.argv) < 5 or "--help" in sys.argv or "-h" in sys.argv:
        print(f"Uso: {sys.argv[0]} <serial> <discriminador> <contador> <boton> [--sub|--raw]")
        print(f"  serial:       número de serie (28 bits)")
        print(f"                formatos: 75513523 | 4803EB3 | 0480 16051")
        print(f"  discriminador: discriminador (12 bits, normalmente 53)")
        print(f"  contador:     contador (16 bits)")
        print(f"  boton:        botón (1-4)")
        print(f"  --sub:        generar archivo .sub (modo protocolo KeeLoq)")
        print(f"  --raw:        generar archivo .sub (modo RAW)")
        print()
        print(f"Ejemplos:")
        print(f"  {sys.argv[0]} 0480 16051 53 948 4")
        print(f"  {sys.argv[0]} 0480 16051 53 948 4 --sub")
        print(f"  {sys.argv[0]} 0480 16051 53 948 4 --raw")
        sys.exit(1)

    serial_str = sys.argv[1]
    discriminator = int(sys.argv[2])
    counter = int(sys.argv[3])
    button = int(sys.argv[4])
    gen_sub = "--sub" in sys.argv
    gen_raw = "--raw" in sys.argv

    # Parse serial: accept "0480 16051", "048016051", "4803EB3", "75513523"
    serial_clean = serial_str.replace(" ", "")
    try:
        if len(serial_clean) == 9 and serial_clean.isdigit():
            hi = int(serial_clean[:4], 16)
            lo = int(serial_clean[4:], 10)
            serial = (hi << 16) | lo
        else:
            serial = int(serial_clean, 0)
    except ValueError:
        print(f"Error: formato de serial no válido: '{serial_str}'")
        sys.exit(1)

    try:
        frame, fix, hop, man, hop_plain = generate_frame(
            serial, discriminator, counter, button
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print()
    print("╔═══════════════════════════════════════════════╗")
    print("║  CLEMSA MUTANCODE - GENERADOR DE TRAMA       ║")
    print("╚═══════════════════════════════════════════════╝")
    print()
    print(f"  Clave fabricante: 0x{CLEMSA_KEY:016X}")
    print()
    print("─── Datos de entrada ───")
    serial_hi = (serial >> 16) & 0xFFFF
    serial_lo = serial & 0xFFFF
    print(f"  Serial:         {serial_hi:04X} {serial_lo:05d} ({serial})")
    print(f"  Discriminador:  {discriminator} (0x{discriminator:03X})")
    print(f"  Counter:        {counter} (0x{counter:04X})")
    print(f"  Botón:          {button}")
    print()
    print("─── Construcción ───")
    print(f"  Fix:            0x{fix:08X}")
    print(f"  Hop (plain):    0x{hop_plain:08X}")
    print(f"  Man (derived):  0x{man:016X}")
    print(f"  Hop (encrypted):0x{hop:08X}")
    print()
    print("─── Trama resultante (64 bits) ───")
    print_bytes(frame, "Frame (hex)  ")
    print()
    b = frame.to_bytes(8, "big")
    print(f"  LSB first:      {' '.join(f'{byte:02X}' for byte in reversed(b))}")
    print()

    # Verificación: decodificar la trama generada
    decoded = decode_frame(frame)
    print("─── Verificación (decodificación) ───")
    ok = (decoded["button"] == button and
          decoded["discriminator"] == discriminator)
    print(f"  Botón:          {decoded['button']} {'✓' if decoded['button'] == button else '✗'}")
    print(f"  Discriminador:  {decoded['discriminator']} {'✓' if decoded['discriminator'] == discriminator else '✗'}")
    print(f"  Counter:        {decoded['counter']} {'✓' if decoded['counter'] == counter else '✗'}")
    dserial = decoded['serial']
    print(f"  Serial:         {(dserial >> 16) & 0xFFFF:04X} {dserial & 0xFFFF:05d}")
    print()
    print(f"  Resultado: {'✓ TRAMA VÁLIDA' if ok else '✗ ERROR'}")
    print()

    if gen_sub:
        sub_content = generate_sub(frame, serial, button, counter, discriminator)
        filename = f"Clemsa_Mutancode_{serial_hi:04X}{serial_lo:05d}_B{button}.sub"
        with open(filename, "w") as f:
            f.write(sub_content)
        print(f"─── Archivo Flipper Zero (.sub) ───")
        print(f"  Guardado: {filename}")
        print()
        print(sub_content)

    if gen_raw:
        raw_content = generate_sub_raw(frame, button)
        filename = f"Clemsa_Mutancode_{serial_hi:04X}{serial_lo:05d}_B{button}_RAW.sub"
        with open(filename, "w") as f:
            f.write(raw_content)
        print(f"─── Archivo Flipper Zero (.sub RAW) ───")
        print(f"  Guardado: {filename}")
        print()
        print(raw_content)

        # Generar array Arduino
        print("─── Array para Arduino ───")
        print("Pegar en 'const int raw_data[]':")
        print()
        TE = 400
        arr = []
        # Preamble
        for _ in range(10):
            arr.append(f"+{TE}")
            arr.append(f"-{TE}")
        # Data: 64 bits LSB first
        for i in range(64):
            bit = (frame >> i) & 1
            if bit == 0:
                arr.append(f"+{TE}")
                arr.append(f"-{TE * 2}")
            else:
                arr.append(f"+{TE * 2}")
                arr.append(f"-{TE}")
        # Imprimir en líneas de 8
        for i in range(0, len(arr), 8):
            chunk = arr[i:i+8]
            print("  " + ", ".join(chunk) + ",")
        print()
        print(f"  // Total: {len(arr)} valores")
