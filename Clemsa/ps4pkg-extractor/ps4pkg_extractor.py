#!/usr/bin/env python3
"""
PS4 PKG Extractor - Extrae y descifra paquetes PKG de PlayStation 4.
Basado en la implementacion de shadPS4Plus (AzaharPlus/shadPS4Plus).

Uso:
    python3 ps4pkg_extractor.py <archivo.pkg> [-o <directorio_salida>]
"""

import struct
import os
import sys
import zlib
import hashlib
import hmac
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

PKG_MAGIC = b'\x7fCNT'
CONTENT_ID_SIZE = 0x24
HEADER_SIZE = 0x1000
ENTRY_SIZE = 32
PFSC_MAGIC = 0x43534650
PFS_MAGIC = 20130315
INODE_SIZE = 0xA8
DIRECT_BLOCKS = 12

KNOWN_ENTRY_NAMES: Dict[int, str] = {
    0x0001: "DIGESTS", 0x0010: "ENTRY_KEYS", 0x0020: "IMAGE_KEY",
    0x0080: "GENERAL_DIGESTS", 0x0100: "METAS", 0x0200: "ENTRY_NAMES",
    0x0400: "license.dat", 0x0401: "license.info", 0x0402: "nptitle.dat",
    0x0403: "npbind.dat", 0x0404: "selfinfo.dat", 0x0406: "imageinfo.dat",
    0x0409: "psreserved.dat", 0x1000: "param.sfo", 0x1001: "playgo-chunk.dat",
    0x1002: "playgo-chunk.sha", 0x1003: "playgo-manifest.xml",
    0x1004: "pronunciation.xml", 0x1005: "pronunciation.sig",
    0x1006: "pic1.png", 0x1008: "app/playgo-chunk.dat",
    0x1200: "icon0.png", 0x1220: "pic0.png", 0x1240: "snd0.at9",
    0x1260: "changeinfo/changeinfo.xml", 0x1280: "icon0.dds", 0x12A0: "pic0.dds",
}


def read_cstring(data: bytes, offset: int = 0) -> str:
    end = data.find(b'\x00', offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode('ascii', errors='replace')


def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ═══════════════════════════════════════════════════════════════
# RSA Keys - from shadPS4Plus (keys.h)
# ═══════════════════════════════════════════════════════════════

PKG_DERIVED_KEY3 = {
    'n': bytes([
        0xd2, 0x12, 0xfc, 0x33, 0x5f, 0x6d, 0xdb, 0x83, 0x16, 0x09, 0x62, 0x8b, 0x03, 0x56, 0x27,
        0x37, 0x82, 0xd4, 0x77, 0x85, 0x35, 0x29, 0x39, 0x2d, 0x52, 0x6b, 0x8c, 0x4c, 0x8c, 0xfb,
        0x06, 0xc1, 0x84, 0x5b, 0xe7, 0xd4, 0xf7, 0xbc, 0xd2, 0x4e, 0x62, 0x45, 0xcd, 0x2a, 0xbb,
        0xd7, 0x77, 0x76, 0x45, 0x36, 0x55, 0x27, 0x3f, 0xb3, 0xf5, 0xf9, 0x8e, 0xda, 0x4b, 0xef,
        0xaa, 0x59, 0xae, 0xb3, 0x9b, 0xea, 0x54, 0x98, 0xd2, 0x06, 0x32, 0x6a, 0x58, 0x31, 0x2a,
        0xe0, 0xd4, 0x4f, 0x90, 0xb5, 0x0a, 0x7d, 0xec, 0xf4, 0x3a, 0x9c, 0x52, 0x67, 0x2d, 0x99,
        0x31, 0x8e, 0x0c, 0x43, 0xe6, 0x82, 0xfe, 0x07, 0x46, 0xe1, 0x2e, 0x50, 0xd4, 0x1f, 0x2d,
        0x2f, 0x7e, 0xd9, 0x08, 0xba, 0x06, 0xb3, 0xbf, 0x2e, 0x20, 0x3f, 0x4e, 0x3f, 0xfe, 0x44,
        0xff, 0xaa, 0x50, 0x43, 0x57, 0x91, 0x69, 0x94, 0x49, 0x15, 0x82, 0x82, 0xe4, 0x0f, 0x4c,
        0x8d, 0x9d, 0x2c, 0xc9, 0x5b, 0x1d, 0x64, 0xbf, 0x88, 0x8b, 0xd4, 0xc5, 0x94, 0xe7, 0x65,
        0x47, 0x84, 0x1e, 0xe5, 0x79, 0x10, 0xfb, 0x98, 0x93, 0x47, 0xb9, 0x7d, 0x85, 0x12, 0xa6,
        0x40, 0x98, 0x2c, 0xf7, 0x92, 0xbc, 0x95, 0x19, 0x32, 0xed, 0xe8, 0x90, 0x56, 0x0d, 0x65,
        0xc1, 0xaa, 0x78, 0xc6, 0x2e, 0x54, 0xfd, 0x5f, 0x54, 0xa1, 0xf6, 0x7e, 0xe5, 0xe0, 0x5f,
        0x61, 0xc1, 0x20, 0xb4, 0xb9, 0xb4, 0x33, 0x08, 0x70, 0xe4, 0xdf, 0x89, 0x56, 0xed, 0x01,
        0x29, 0x46, 0x77, 0x5f, 0x8c, 0xb8, 0xa9, 0xf5, 0x1e, 0x2e, 0xb3, 0xb9, 0xbf, 0xe0, 0x09,
        0xb7, 0x8d, 0x28, 0xd4, 0xa6, 0xc3, 0xb8, 0x1e, 0x1f, 0x07, 0xeb, 0xb4, 0x12, 0x0b, 0x95,
        0xb8, 0x85, 0x30, 0xfd, 0xdc, 0x39, 0x13, 0xd0, 0x7c, 0xdc, 0x8f, 0xed, 0xf9, 0xc9, 0xa3,
        0xc1,
    ]),
    'd': bytes([
        0x32, 0xD9, 0x03, 0x90, 0x8F, 0xBD, 0xB0, 0x8F, 0x57, 0x2B, 0x28, 0x5E, 0x0B, 0x8D, 0xB3,
        0xEA, 0x5C, 0xD1, 0x7E, 0xA8, 0x90, 0x88, 0x8C, 0xDD, 0x6A, 0x80, 0xBB, 0xB1, 0xDF, 0xC1,
        0xF7, 0x0D, 0xAA, 0x32, 0xF0, 0xB7, 0x7C, 0xCB, 0x88, 0x80, 0x0E, 0x8B, 0x64, 0xB0, 0xBE,
        0x4C, 0xD6, 0x0E, 0x9B, 0x8C, 0x1E, 0x2A, 0x64, 0xE1, 0xF3, 0x5C, 0xD7, 0x76, 0x01, 0x41,
        0x5E, 0x93, 0x5C, 0x94, 0xFE, 0xDD, 0x46, 0x62, 0xC3, 0x1B, 0x5A, 0xE2, 0xA0, 0xBC, 0x2D,
        0xEB, 0xC3, 0x98, 0x0A, 0xA7, 0xB7, 0x85, 0x69, 0x70, 0x68, 0x2B, 0x64, 0x4A, 0xB3, 0x1F,
        0xCC, 0x7D, 0xDC, 0x7C, 0x26, 0xF4, 0x77, 0xF6, 0x5C, 0xF2, 0xAE, 0x5A, 0x44, 0x2D, 0xD3,
        0xAB, 0x16, 0x62, 0x04, 0x19, 0xBA, 0xFB, 0x90, 0xFF, 0xE2, 0x30, 0x50, 0x89, 0x6E, 0xCB,
        0x56, 0xB2, 0xEB, 0xC0, 0x91, 0x16, 0x92, 0x5E, 0x30, 0x8E, 0xAE, 0xC7, 0x94, 0x5D, 0xFD,
        0x35, 0xE1, 0x20, 0xF8, 0xAD, 0x3E, 0xBC, 0x08, 0xBF, 0xC0, 0x36, 0x74, 0x9F, 0xD5, 0xBB,
        0x52, 0x08, 0xFD, 0x06, 0x66, 0xF3, 0x7A, 0xB3, 0x04, 0xF4, 0x75, 0x29, 0x5D, 0xE9, 0x5F,
        0xAA, 0x10, 0x30, 0xB2, 0x0F, 0x5A, 0x1A, 0xC1, 0x2A, 0xB3, 0xFE, 0xCB, 0x21, 0xAD, 0x80,
        0xEC, 0x8F, 0x20, 0x09, 0x1C, 0xDB, 0xC5, 0x58, 0x94, 0xC2, 0x9C, 0xC6, 0xCE, 0x82, 0x65,
        0x3E, 0x57, 0x90, 0xBC, 0xA9, 0x8B, 0x06, 0xB4, 0xF0, 0x72, 0xF6, 0x77, 0xDF, 0x98, 0x64,
        0xF1, 0xEC, 0xFE, 0x37, 0x2D, 0xBC, 0xAE, 0x8C, 0x08, 0x81, 0x1F, 0xC3, 0xC9, 0x89, 0x1A,
        0xC7, 0x42, 0x82, 0x4B, 0x2E, 0xDC, 0x8E, 0x8D, 0x73, 0xCE, 0xB1, 0xCC, 0x01, 0xD9, 0x08,
        0x70, 0x87, 0x3C, 0x44, 0x08, 0xEC, 0x49, 0x8F, 0x81, 0x5A, 0xE2, 0x40, 0xFF, 0x77, 0xFC,
        0x0D,
    ]),
    'e': 65537,
}

FAKE_KEYSET = {
    'n': bytes([
        0xC6, 0xCF, 0x71, 0xE7, 0xE5, 0x9A, 0xF0, 0xD1, 0x2A, 0x2C, 0x45, 0x8B, 0xF9, 0x2A, 0x0E,
        0xC1, 0x43, 0x05, 0x8B, 0xC3, 0x71, 0x17, 0x80, 0x1D, 0xCD, 0x49, 0x7D, 0xDE, 0x35, 0x9D,
        0x25, 0x9B, 0xA0, 0xD7, 0xA0, 0xF2, 0x7D, 0x6C, 0x08, 0x7E, 0xAA, 0x55, 0x02, 0x68, 0x2B,
        0x23, 0xC6, 0x44, 0xB8, 0x44, 0x18, 0xEB, 0x56, 0xCF, 0x16, 0xA2, 0x48, 0x03, 0xC9, 0xE7,
        0x4F, 0x87, 0xEB, 0x3D, 0x30, 0xC3, 0x15, 0x88, 0xBF, 0x20, 0xE7, 0x9D, 0xFF, 0x77, 0x0C,
        0xDE, 0x1D, 0x24, 0x1E, 0x63, 0xA9, 0x4F, 0x8A, 0xBF, 0x5B, 0xBE, 0x60, 0x19, 0x68, 0x33,
        0x3B, 0xFC, 0xED, 0x9F, 0x47, 0x4E, 0x5F, 0xF8, 0xEA, 0xCB, 0x3D, 0x00, 0xBD, 0x67, 0x01,
        0xF9, 0x2C, 0x6D, 0xC6, 0xAC, 0x13, 0x64, 0xE7, 0x67, 0x14, 0xF3, 0xDC, 0x52, 0x69, 0x6A,
        0xB9, 0x83, 0x2C, 0x42, 0x30, 0x13, 0x1B, 0xB2, 0xD8, 0xA5, 0x02, 0x0D, 0x79, 0xED, 0x96,
        0xB1, 0x0D, 0xF8, 0xCC, 0x0C, 0xDF, 0x81, 0x95, 0x4F, 0x03, 0x58, 0x09, 0x57, 0x0E, 0x80,
        0x69, 0x2E, 0xFE, 0xFF, 0x52, 0x77, 0xEA, 0x75, 0x28, 0xA8, 0xFB, 0xC9, 0xBE, 0xBF, 0x9F,
        0xBB, 0xB7, 0x79, 0x8E, 0x18, 0x05, 0xE1, 0x80, 0xBD, 0x50, 0x34, 0x94, 0x81, 0xD3, 0x53,
        0xC2, 0x69, 0xA2, 0xD2, 0x4C, 0xCF, 0x6C, 0xF4, 0x57, 0x2C, 0x10, 0x4A, 0x3F, 0xFB, 0x22,
        0xFD, 0x8B, 0x97, 0xE2, 0xC9, 0x5B, 0xA6, 0x2B, 0xCD, 0xD6, 0x1B, 0x6B, 0xDB, 0x68, 0x7F,
        0x4B, 0xC2, 0xA0, 0x50, 0x34, 0xC0, 0x05, 0xE5, 0x8D, 0xEF, 0x24, 0x67, 0xFF, 0x93, 0x40,
        0xCF, 0x2D, 0x62, 0xA2, 0xA0, 0x50, 0xB1, 0xF1, 0x3A, 0xA8, 0x3D, 0xFD, 0x80, 0xD1, 0xF9,
        0xB8, 0x05, 0x22, 0xAF, 0xC8, 0x35, 0x45, 0x90, 0x58, 0x8E, 0xE3, 0x3A, 0x7C, 0xBD, 0x3E,
        0x27,
    ]),
    'd': bytes([
        0x7F, 0x76, 0xCD, 0x0E, 0xE2, 0xD4, 0xDE, 0x05, 0x1C, 0xC6, 0xD9, 0xA8, 0x0E, 0x8D, 0xFA,
        0x7B, 0xCA, 0x1E, 0xAA, 0x27, 0x1A, 0x40, 0xF8, 0xF1, 0x22, 0x87, 0x35, 0xDD, 0xDB, 0xFD,
        0xEE, 0xF8, 0xC2, 0xBC, 0xBD, 0x01, 0xFB, 0x8B, 0xE2, 0x3E, 0x63, 0xB2, 0xB1, 0x22, 0x5C,
        0x56, 0x49, 0x6E, 0x11, 0xBE, 0x07, 0x44, 0x0B, 0x9A, 0x26, 0x66, 0xD1, 0x49, 0x2C, 0x8F,
        0xD3, 0x1B, 0xCF, 0xA4, 0xA1, 0xB8, 0xD1, 0xFB, 0xA4, 0x9E, 0xD2, 0x21, 0x28, 0x83, 0x09,
        0x8A, 0xF6, 0xA0, 0x0B, 0xA3, 0xD6, 0x0F, 0x9B, 0x63, 0x68, 0xCC, 0xBC, 0x0C, 0x4E, 0x14,
        0x5B, 0x27, 0xA4, 0xA9, 0xF4, 0x2B, 0xB9, 0xB8, 0x7B, 0xC0, 0xE6, 0x51, 0xAD, 0x1D, 0x77,
        0xD4, 0x6B, 0xB9, 0xCE, 0x20, 0xD1, 0x26, 0x66, 0x7E, 0x5E, 0x9E, 0xA2, 0xE9, 0x6B, 0x90,
        0xF3, 0x73, 0xB8, 0x52, 0x8F, 0x44, 0x11, 0x03, 0x0C, 0x13, 0x97, 0x39, 0x3D, 0x13, 0x22,
        0x58, 0xD5, 0x43, 0x82, 0x49, 0xDA, 0x6E, 0x7C, 0xA1, 0xC5, 0x8C, 0xA5, 0xB0, 0x09, 0xE0,
        0xCE, 0x3D, 0xDF, 0xF4, 0x9D, 0x3C, 0x97, 0x15, 0xE2, 0x6A, 0xC7, 0x2B, 0x3C, 0x50, 0x93,
        0x23, 0xDB, 0xBA, 0x4A, 0x22, 0x66, 0x44, 0xAC, 0x78, 0xBB, 0x0E, 0x1A, 0x27, 0x43, 0xB5,
        0x71, 0x67, 0xAF, 0xF4, 0xAB, 0x48, 0x46, 0x93, 0x73, 0xD0, 0x42, 0xAB, 0x93, 0x63, 0xE5,
        0x6C, 0x9A, 0xDE, 0x50, 0x24, 0xC0, 0x23, 0x7D, 0x99, 0x79, 0x3F, 0x22, 0x07, 0xE0, 0xC1,
        0x48, 0x56, 0x1B, 0xDF, 0x83, 0x09, 0x12, 0xB4, 0x2D, 0x45, 0x6B, 0xC9, 0xC0, 0x68, 0x85,
        0x99, 0x90, 0x79, 0x96, 0x1A, 0xD7, 0xF5, 0x4D, 0x1F, 0x37, 0x83, 0x40, 0x4A, 0xEC, 0x39,
        0x37, 0xA6, 0x80, 0x92, 0x7D, 0xC5, 0x80, 0xC7, 0xD6, 0x6F, 0xFE, 0x8A, 0x79, 0x89, 0xC6,
        0xB1,
    ]),
    'e': 65537,
}


# ═══════════════════════════════════════════════════════════════
# Crypto - RSA, AES, XTS (matching shadPS4Plus implementation)
# ═══════════════════════════════════════════════════════════════

def rsa_decrypt(ciphertext: bytes, key_params: dict) -> bytes:
    """RSA decrypt with automatic padding detection (PKCS#1 v1.5 or raw)."""
    if not HAS_CRYPTO:
        raise RuntimeError("Se requiere 'cryptography': pip install cryptography")
    n = int.from_bytes(key_params['n'], 'big')
    d = int.from_bytes(key_params['d'], 'big')
    c_int = int.from_bytes(ciphertext, 'big')
    m_int = pow(c_int, d, n)
    plaintext = m_int.to_bytes(256, 'big')
    print(f"      [RSA] raw first 16: {plaintext[:16].hex()}")
    print(f"      [RSA] raw[0]=0x{plaintext[0]:02X} raw[1]=0x{plaintext[1]:02X}")

    # Try PKCS#1 v1.5 padding first: 0x00 0x02 [random] 0x00 [data]
    if plaintext[0] == 0x00 and plaintext[1] == 0x02:
        print(f"      [RSA] PKCS1v15 detected")
        try:
            pad_end = plaintext.index(0x00, 2)
            if pad_end >= 10:  # Minimum 8 bytes of padding
                result = plaintext[pad_end + 1:]
                print(f"      [RSA] pad_end={pad_end}, result len={len(result)}, first 16: {result[:16].hex()}")
                return result
        except ValueError:
            pass
    else:
        print(f"      [RSA] NO PKCS1v15 - raw RSA")

    # Raw RSA (no padding) - return as-is
    return plaintext


def aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    if not HAS_CRYPTO:
        raise RuntimeError("Se requiere 'cryptography'")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()


def xts_xor_block(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def xts_mult(data: bytearray):
    feedback = 0
    for k in range(len(data)):
        tmp = (data[k] >> 7) & 1
        data[k] = ((data[k] << 1) + feedback) & 0xFF
        feedback = tmp
    if feedback:
        data[0] ^= 0x87


class AES128XTS:
    def __init__(self, tweak_key: bytes, data_key: bytes):
        self.tweak_key = tweak_key
        self.data_key = data_key

    def decrypt(self, src: bytes, start_sector: int = 0) -> bytes:
        dst = bytearray(len(src))
        num_sectors = len(src) // 0x1000
        for i in range(0, len(src), 0x1000):
            sector = start_sector + (i // 0x1000)
            chunk = src[i:i + 0x1000]
            if len(chunk) < 0x1000:
                chunk = chunk + b'\x00' * (0x1000 - len(chunk))

            # Encrypt tweak with tweakKey (AES-ECB)
            tweak_plain = bytearray(16)
            struct.pack_into('<Q', tweak_plain, 0, sector)
            enc_tweak = aes_ecb_encrypt(self.tweak_key, bytes(tweak_plain))

            # Process each 16-byte block in the sector
            for j in range(0, 0x1000, 16):
                block = chunk[j:j + 16]

                # XTS step 1: XOR ciphertext with encrypted tweak
                xor_buffer = xts_xor_block(block, enc_tweak)

                # XTS step 2: AES-ECB decrypt with dataKey
                decrypted = aes_ecb_decrypt(self.data_key, xor_buffer)

                # XTS step 3: XOR result with encrypted tweak -> plaintext
                plaintext = xts_xor_block(decrypted, enc_tweak)

                # Store plaintext
                dst[i + j:i + j + 16] = plaintext

                # XTS step 4: GF(2^128) multiply tweak for next block
                enc_tweak_arr = bytearray(enc_tweak)
                xts_mult(enc_tweak_arr)
                enc_tweak = bytes(enc_tweak_arr)

        return bytes(dst[:len(src)])


def aes_ecb_encrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    enc = cipher.encryptor()
    return enc.update(data) + enc.finalize()


def aes_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    dec = cipher.decryptor()
    return dec.update(data) + dec.finalize()


def pfs_gen_crypto_key(ekpfs: bytes, seed: bytes) -> Tuple[bytes, bytes]:
    payload = struct.pack("<I", 1) + seed
    h = hmac.new(ekpfs, payload, hashlib.sha256).digest()
    tweak_key = h[0:16]
    data_key = h[16:32]
    return tweak_key, data_key


# ═══════════════════════════════════════════════════════════════
# PKG Parser
# ═══════════════════════════════════════════════════════════════

@dataclass
class PkgHeader:
    magic: bytes = b''
    type_flags: int = 0
    entry_count: int = 0
    sc_entry_count: int = 0
    table_offset: int = 0
    entry_data_size: int = 0
    body_offset: int = 0
    body_size: int = 0
    content_offset: int = 0
    content_size: int = 0
    content_id: str = ''
    drm_type: int = 0
    content_type: int = 0
    content_flags: int = 0
    promote_size: int = 0
    version_date: int = 0
    version_hash: int = 0
    pfs_image_offset: int = 0
    pfs_image_size: int = 0
    mount_image_offset: int = 0
    mount_image_size: int = 0
    package_size: int = 0
    pfs_signed_size: int = 0
    pfs_cache_size: int = 0

    @classmethod
    def parse(cls, f) -> 'PkgHeader':
        f.seek(0)
        header_data = f.read(HEADER_SIZE)
        if header_data[:4] != PKG_MAGIC:
            raise ValueError(f"Magic invalido: esperado {PKG_MAGIC.hex()}, "
                             f"obtenido {header_data[:4].hex()}")
        h = cls()
        h.magic = header_data[:4]
        h.type_flags = struct.unpack('>I', header_data[4:8])[0]
        h.entry_count = struct.unpack('>I', header_data[0x10:0x14])[0]
        h.sc_entry_count = struct.unpack('>H', header_data[0x14:0x16])[0]
        h.table_offset = struct.unpack('>I', header_data[0x18:0x1C])[0]
        h.entry_data_size = struct.unpack('>I', header_data[0x1C:0x20])[0]
        h.body_offset = struct.unpack('>Q', header_data[0x20:0x28])[0]
        h.body_size = struct.unpack('>Q', header_data[0x28:0x30])[0]
        h.content_offset = struct.unpack('>Q', header_data[0x30:0x38])[0]
        h.content_size = struct.unpack('>Q', header_data[0x38:0x40])[0]
        h.content_id = read_cstring(header_data, 0x40)
        h.drm_type = struct.unpack('>I', header_data[0x70:0x74])[0]
        h.content_type = struct.unpack('>I', header_data[0x74:0x78])[0]
        h.content_flags = struct.unpack('>I', header_data[0x78:0x7C])[0]
        h.promote_size = struct.unpack('>I', header_data[0x7C:0x80])[0]
        h.version_date = struct.unpack('>I', header_data[0x80:0x84])[0]
        h.version_hash = struct.unpack('>I', header_data[0x84:0x88])[0]
        h.pfs_image_offset = struct.unpack('>Q', header_data[0x410:0x418])[0]
        h.pfs_image_size = struct.unpack('>Q', header_data[0x418:0x420])[0]
        h.mount_image_offset = struct.unpack('>Q', header_data[0x420:0x428])[0]
        h.mount_image_size = struct.unpack('>Q', header_data[0x428:0x430])[0]
        h.package_size = struct.unpack('>Q', header_data[0x430:0x438])[0]
        h.pfs_signed_size = struct.unpack('>I', header_data[0x438:0x43C])[0]
        h.pfs_cache_size = struct.unpack('>I', header_data[0x43C:0x440])[0]
        return h

    def is_encrypted(self) -> bool:
        return (self.type_flags & 0x80000000) != 0

    def content_type_str(self) -> str:
        types = {
            0x0: "UserGameData", 0x1: "AC", 0x2: "GD", 0x3: "AC_GC",
            0x4: "GD_AC", 0x0E: "License", 0x13: "Patch", 0x14: "PatchDelta",
            0x15: "AddcontPack", 0x16: "Addcont", 0x1A: "Avatar", 0x1B: "Theme",
        }
        return types.get(self.content_type, f"Unknown(0x{self.content_type:X})")

    def get_cusa_serial(self) -> str:
        if '-' in self.content_id:
            parts = self.content_id.split('-')
            if len(parts) >= 2:
                return parts[1].split('_')[0]
        return "UNKNOWN"


@dataclass
class PkgEntry:
    id: int = 0
    filename_offset: int = 0
    flags1: int = 0
    flags2: int = 0
    offset: int = 0
    size: int = 0
    name: Optional[str] = None
    raw_bytes: bytes = b''

    @property
    def key_index(self) -> int:
        return (self.flags2 & 0xF000) >> 12

    @property
    def is_encrypted(self) -> bool:
        return (self.flags1 & 0x80000000) != 0

    @property
    def known_name(self) -> Optional[str]:
        return KNOWN_ENTRY_NAMES.get(self.id)

    @classmethod
    def parse(cls, f) -> 'PkgEntry':
        entry = cls()
        data = f.read(ENTRY_SIZE)
        entry.raw_bytes = data[:32]
        (entry.id, entry.filename_offset, entry.flags1,
         entry.flags2, entry.offset, entry.size) = struct.unpack('>IIIIII', data[:24])
        return entry

    def resolve_name(self, names_data: bytes = b'') -> str:
        if self.name:
            return self.name
        known = self.known_name
        if known:
            self.name = known
            return self.name
        if self.filename_offset != 0 and names_data:
            name = read_cstring(names_data, self.filename_offset)
            if name:
                self.name = name
                return self.name
        self.name = f"entry_0x{self.id:04X}.bin"
        return self.name


@dataclass
class PkgInfo:
    header: PkgHeader = field(default_factory=PkgHeader)
    entries: List[PkgEntry] = field(default_factory=list)
    names_data: bytes = b''


def parse_pkg(filepath: str) -> PkgInfo:
    info = PkgInfo()
    with open(filepath, 'rb') as f:
        info.header = PkgHeader.parse(f)
        if info.header.table_offset < HEADER_SIZE:
            info.header.table_offset = HEADER_SIZE
        f.seek(info.header.table_offset)
        for _ in range(info.header.entry_count):
            entry = PkgEntry.parse(f)
            info.entries.append(entry)
        names_entry = None
        for entry in info.entries:
            if entry.id == 0x0200:
                names_entry = entry
                break
        if names_entry:
            f.seek(names_entry.offset)
            info.names_data = f.read(names_entry.size)
        for entry in info.entries:
            entry.resolve_name(info.names_data)
    return info


# ═══════════════════════════════════════════════════════════════
# PKG Decryption - matching shadPS4Plus flow
# ═══════════════════════════════════════════════════════════════

def decrypt_ekpfs(info: PkgInfo, pkg_path: str) -> Optional[bytes]:
    print("\nDescifrando claves del PKG...")

    entry_keys_entry = None
    image_key_entry = None
    for entry in info.entries:
        if entry.id == 0x0010:
            entry_keys_entry = entry
        elif entry.id == 0x0020:
            image_key_entry = entry

    if not entry_keys_entry or not image_key_entry:
        print("  [WARN] ENTRY_KEYS o IMAGE_KEY no encontrados")
        return None

    with open(pkg_path, 'rb') as f:
        f.seek(entry_keys_entry.offset)
        entry_keys_data = f.read(entry_keys_entry.size)

        f.seek(image_key_entry.offset)
        image_key_data = f.read(image_key_entry.size)

    # entry_keys structure (from shadPS4Plus):
    # [0x000] seed_digest    (32 bytes)
    # [0x020] digest1[0..6]  (7 x 32 = 224 bytes)
    # [0x100] key1[0..6]     (7 x 256 = 1792 bytes)
    # key1[3] is at offset 0x100 + 3*0x100 = 0x400
    KEY1_3_OFFSET = 0x400

    # Step 1: RSA decrypt key1[3] with PkgDerivedKey3 -> dk3_
    print("  [1] Descifrando dk3_ con PkgDerivedKey3Keyset...")
    print(f"      entry_keys tamano: {len(entry_keys_data)} bytes")
    print(f"      key1[3] offset: 0x{KEY1_3_OFFSET:X}")

    if len(entry_keys_data) < KEY1_3_OFFSET + 0x100:
        print(f"  [ERROR] entry_keys demasiado pequeno")
        return None

    key1_3 = entry_keys_data[KEY1_3_OFFSET:KEY1_3_OFFSET + 0x100]
    print(f"      key1[3] first 32: {key1_3[:32].hex()}")

    try:
        dk3_ = rsa_decrypt(key1_3, PKG_DERIVED_KEY3)
        print(f"      dk3_: {dk3_.hex()[:32]}...")
    except Exception as e:
        print(f"  [ERROR] No se pudo descifrar dk3_: {e}")
        return None

    # Step 2: Derive ivKey = SHA256(PKGEntry[IMAGE_KEY] || dk3_)
    # Use the RAW 32 bytes from the file (matching C++ &entry, sizeof(entry))
    print("  [2] Derivando ivKey...")
    entry_struct = image_key_entry.raw_bytes[:32]
    print(f"      IMAGE_KEY raw bytes ({len(entry_struct)} bytes): {entry_struct.hex()}")
    print(f"      dk3_ ({len(dk3_)} bytes): {dk3_.hex()}")
    concat = entry_struct + dk3_[:32]
    print(f"      concat ({len(concat)} bytes): {concat.hex()}")
    iv_key = hashlib.sha256(concat).digest()
    print(f"      ivKey: {iv_key.hex()}")

    # Step 3: AES-CBC decrypt imgkeydata with ivKey
    # ivKey[0:16] = IV, ivKey[16:32] = Key
    print("  [3] Descifrando imgKey con AES-CBC...")
    aes_key = iv_key[16:32]
    aes_iv = iv_key[0:16]
    img_key = aes_cbc_decrypt(aes_key, aes_iv, image_key_data[:256])
    print(f"      imgKey: {img_key.hex()[:32]}...")

    # Step 4: RSA decrypt imgKey with FakeKeyset -> ekpfsKey
    print("  [4] Descifrando ekpfsKey con FakeKeyset...")
    try:
        ekpfs_key = rsa_decrypt(img_key, FAKE_KEYSET)
        print(f"      ekpfsKey: {ekpfs_key.hex()[:32]}...")
        return ekpfs_key
    except Exception as e:
        print(f"  [ERROR] No se pudo descifrar ekpfsKey: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# PFSC Decompressor
# ═══════════════════════════════════════════════════════════════

@dataclass
class PFSCHeader:
    magic: int = 0
    block_sz: int = 0
    block_sz2: int = 0
    block_offsets: int = 0
    data_start: int = 0
    data_length: int = 0

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> 'PFSCHeader':
        h = cls()
        h.magic = struct.unpack_from('<I', data, offset + 0x00)[0]
        h.block_sz = struct.unpack_from('<i', data, offset + 0x0C)[0]
        h.block_sz2 = struct.unpack_from('<q', data, offset + 0x10)[0]
        h.block_offsets = struct.unpack_from('<q', data, offset + 0x18)[0]
        h.data_start = struct.unpack_from('<Q', data, offset + 0x20)[0]
        h.data_length = struct.unpack_from('<q', data, offset + 0x28)[0]
        return h


def find_pfsc(data: bytes) -> int:
    search_len = min(len(data), 0x200000)
    for offset in range(0, search_len, 0x10000):
        if struct.unpack_from('<I', data, offset)[0] == PFSC_MAGIC:
            return offset
    # Also try unaligned search in first 0x10000 bytes
    for offset in range(0, min(len(data), 0x10000), 4):
        if struct.unpack_from('<I', data, offset)[0] == PFSC_MAGIC:
            return offset
    return -1


def decompress_pfsc(pfs_data: bytes, pfsc_offset: int) -> bytes:
    hdr = PFSCHeader.parse(pfs_data, pfsc_offset)
    if hdr.magic != PFSC_MAGIC:
        raise ValueError(f"PFSC magic invalido: 0x{hdr.magic:08X}")

    num_blocks = hdr.data_length // hdr.block_sz2
    if hdr.data_length % hdr.block_sz2 != 0:
        num_blocks += 1

    print(f"  PFSC: {num_blocks} bloques, block_sz={hdr.block_sz2}, "
          f"total={format_size(hdr.data_length)}")

    sm = pfsc_offset + hdr.block_offsets
    sector_map = []
    for i in range(num_blocks + 1):
        sector_map.append(struct.unpack_from('<Q', pfs_data, sm + i * 8)[0])

    print(f"  PFSC data_start: 0x{hdr.data_start:X}, block_offsets: 0x{hdr.block_offsets:X}")
    if num_blocks > 0:
        s0_off = sector_map[0]
        s0_raw = pfs_data[pfsc_offset + hdr.data_start + s0_off:
                          pfsc_offset + hdr.data_start + s0_off + min(64, sector_map[1] - s0_off)]
        print(f"  Primer bloque compressed first 64: {s0_raw[:64].hex()}")

    result = bytearray()
    for i in range(num_blocks):
        s_off = sector_map[i]
        s_size = sector_map[i + 1] - s_off
        raw = pfs_data[pfsc_offset + hdr.data_start + s_off:
                       pfsc_offset + hdr.data_start + s_off + s_size]

        if i < 3:
            print(f"  Bloque {i}: off=0x{s_off:X} size={s_size} raw_first16={raw[:16].hex()}")

        if s_size == hdr.block_sz2:
            decompressed = raw
        elif s_size < hdr.block_sz2:
            decompressed = None
            try:
                decompressed = zlib.decompress(raw)
            except zlib.error:
                try:
                    decompressed = zlib.decompress(raw, -zlib.MAX_WBITS)
                except zlib.error:
                    try:
                        decompressed = zlib.decompress(raw, zlib.MAX_WBITS | 16)
                    except zlib.error as e3:
                        print(f"  [ERR] Bloque {i}: zlib fallo: {e3}")
                        print(f"        raw first 32: {raw[:32].hex()}")
                        raise
        else:
            raise ValueError(f"Sector {i}: tamano {s_size} > block_sz2")

        result.extend(decompressed[:hdr.block_sz2])

    return bytes(result[:hdr.data_length])


# ═══════════════════════════════════════════════════════════════
# PFS Filesystem Parser
# ═══════════════════════════════════════════════════════════════

@dataclass
class PFSHeader:
    version: int = 0
    magic: int = 0
    blocksz: int = 0
    ndinode: int = 0
    ndblock: int = 0
    superroot_ino: int = 0

    @classmethod
    def parse(cls, data: bytes) -> 'PFSHeader':
        h = cls()
        h.version = struct.unpack_from('<q', data, 0x00)[0]
        h.magic = struct.unpack_from('<q', data, 0x08)[0]
        h.blocksz = struct.unpack_from('<i', data, 0x20)[0]
        h.ndinode = struct.unpack_from('<q', data, 0x30)[0]
        h.ndblock = struct.unpack_from('<q', data, 0x38)[0]
        h.superroot_ino = struct.unpack_from('<q', data, 0x48)[0]
        return h

    def validate(self):
        if self.magic != PFS_MAGIC:
            raise ValueError(f"PFS magic invalido: {self.magic}")


@dataclass
class Inode:
    mode: int = 0
    size: int = 0
    blocks: int = 0
    db: List[int] = field(default_factory=list)
    ib: List[int] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> 'Inode':
        ino = cls()
        ino.mode = struct.unpack_from('<H', data, 0x00)[0]
        ino.size = struct.unpack_from('<q', data, 0x08)[0]
        ino.blocks = struct.unpack_from('<I', data, 0x60)[0]
        ino.db = [struct.unpack_from('<i', data, 0x64 + i * 4)[0] for i in range(12)]
        ino.ib = [struct.unpack_from('<i', data, 0x94 + i * 4)[0] for i in range(5)]
        return ino

    def is_dir(self) -> bool:
        return (self.mode & 0xF000) == 0x4000

    def is_file(self) -> bool:
        return (self.mode & 0xF000) == 0x8000


@dataclass
class Dirent:
    ino: int = 0
    dtype: int = 0
    namelen: int = 0
    entsize: int = 0
    name: str = ''
    PFS_FILE = 2
    PFS_DIR = 3
    PFS_CURRENT = 4
    PFS_PARENT = 5

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> 'Optional[Dirent]':
        if offset + 16 > len(data):
            return None
        d = cls()
        d.ino = struct.unpack_from('<i', data, offset + 0x00)[0]
        if d.ino == 0:
            return None
        d.dtype = struct.unpack_from('<i', data, offset + 0x04)[0]
        d.namelen = struct.unpack_from('<i', data, offset + 0x08)[0]
        d.entsize = struct.unpack_from('<i', data, offset + 0x0C)[0]
        if d.entsize <= 0:
            return None
        name_end = offset + 0x10 + d.namelen
        if name_end > len(data):
            return None
        d.name = data[offset + 0x10:name_end].decode('utf-8', errors='replace')
        return d


class PFSFilesystem:
    def __init__(self, decompressed_data: bytes):
        self.data = decompressed_data
        self.pfs_hdr = PFSHeader.parse(decompressed_data)
        self.pfs_hdr.validate()
        self.inodes = self._parse_inodes()

    def _parse_inodes(self) -> List[Inode]:
        inodes = []
        offset = self.pfs_hdr.blocksz
        for _ in range(self.pfs_hdr.ndinode):
            if offset + INODE_SIZE > len(self.data):
                break
            ino = Inode.parse(self.data[offset:offset + INODE_SIZE])
            inodes.append(ino)
            offset += INODE_SIZE
        return inodes

    def _get_block(self, block_no: int) -> bytes:
        if block_no <= 0:
            return b''
        start = self.pfs_hdr.blocksz * block_no
        end = start + self.pfs_hdr.blocksz
        if start >= len(self.data):
            return b''
        return self.data[start:min(end, len(self.data))]

    def _read_inode_data(self, ino: Inode) -> bytes:
        result = bytearray()
        remaining = ino.size
        for j in range(min(ino.blocks, DIRECT_BLOCKS)):
            block_no = ino.db[j]
            if block_no <= 0:
                continue
            block_data = self._get_block(block_no)
            to_read = min(len(block_data), remaining)
            result.extend(block_data[:to_read])
            remaining -= to_read
            if remaining <= 0:
                break
        if remaining > 0 and ino.ib[0] > 0:
            ind_block = self._get_block(ino.ib[0])
            for j in range(len(ind_block) // 4):
                if remaining <= 0:
                    break
                block_no = struct.unpack_from('<i', ind_block, j * 4)[0]
                if block_no <= 0:
                    continue
                block_data = self._get_block(block_no)
                to_read = min(len(block_data), remaining)
                result.extend(block_data[:to_read])
                remaining -= to_read
        return bytes(result[:ino.size])

    def _read_dir_data(self, ino: Inode) -> bytes:
        result = bytearray()
        for j in range(DIRECT_BLOCKS):
            block_no = ino.db[j]
            if block_no <= 0:
                continue
            result.extend(self._get_block(block_no))
        return bytes(result)

    def _parse_dirents(self, dir_data: bytes) -> List[Dirent]:
        dirents = []
        pos = 0
        while pos < dir_data:
            if pos + 16 > len(dir_data):
                break
            if struct.unpack_from('<i', dir_data, pos)[0] == 0:
                break
            d = Dirent.parse(dir_data, pos)
            if d is None:
                break
            dirents.append(d)
            pos += d.entsize
            if d.entsize == 0:
                break
        return dirents

    def _find_uroot(self) -> Optional[int]:
        if len(self.inodes) == 0:
            return None
        root_ino_idx = self.pfs_hdr.superroot_ino
        if root_ino_idx >= len(self.inodes):
            return None
        root_ino = self.inodes[root_ino_idx]
        if not root_ino.is_dir():
            return None
        root_dir_data = self._read_dir_data(root_ino)
        root_dirents = self._parse_dirents(root_dir_data)
        for d in root_dirents:
            if d.name == "uroot" and d.ino > 0 and d.ino < len(self.inodes):
                return d.ino
        return None

    def extract_all(self, output_dir: str) -> Tuple[int, int]:
        uroot_idx = self._find_uroot()
        if uroot_idx is None:
            print("  [WARN] Directorio uroot no encontrado")
            return 0, 1
        uroot_ino = self.inodes[uroot_idx]
        uroot_data = self._read_dir_data(uroot_ino)
        uroot_dirents = self._parse_dirents(uroot_data)
        extracted = 0
        errors = 0
        for d in uroot_dirents:
            if d.dtype in (Dirent.PFS_CURRENT, Dirent.PFS_PARENT):
                continue
            ext, err = self._extract_node(output_dir, d.name, d.ino)
            extracted += ext
            errors += err
        return extracted, errors

    def _extract_node(self, base: str, name: str, ino_idx: int) -> Tuple[int, int]:
        if ino_idx <= 0 or ino_idx >= len(self.inodes):
            return 0, 1
        ino = self.inodes[ino_idx]
        path = os.path.join(base, name)
        if ino.is_file():
            try:
                data = self._read_inode_data(ino)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'wb') as f:
                    f.write(data)
                print(f"  [OK]   {name} ({format_size(len(data))})")
                return 1, 0
            except Exception as e:
                print(f"  [ERR]  {name}: {e}")
                return 0, 1
        if ino.is_dir():
            os.makedirs(path, exist_ok=True)
            dir_data = self._read_dir_data(ino)
            dirents = self._parse_dirents(dir_data)
            extracted = 0
            errors = 0
            for d in dirents:
                if d.dtype in (Dirent.PFS_CURRENT, Dirent.PFS_PARENT):
                    continue
                ext, err = self._extract_node(path, d.name, d.ino)
                extracted += ext
                errors += err
            return extracted, errors
        return 0, 0


# ═══════════════════════════════════════════════════════════════
# PKG Operations
# ═══════════════════════════════════════════════════════════════

def print_info(info: PkgInfo):
    h = info.header
    print("=" * 60)
    print("PS4 PKG Info")
    print("=" * 60)
    print(f"  Content ID:     {h.content_id}")
    print(f"  CUSA Serial:    {h.get_cusa_serial()}")
    print(f"  Tipo:           {h.content_type_str()}")
    print(f"  DRM Type:       0x{h.drm_type:X}")
    print(f"  Tamano PKG:     {format_size(h.package_size)}")
    print(f"  PFS offset:     0x{h.pfs_image_offset:X}")
    print(f"  PFS size:       {format_size(h.pfs_image_size)}")
    print(f"  Entries:        {h.entry_count}")
    print(f"  Cifrado:        {'Si' if h.is_encrypted() else 'No'}")
    print("=" * 60)


def list_entries(info: PkgInfo):
    print(f"{'ID':<8} {'Nombre':<40} {'Tamano':>12} {'Cifrado':>8}")
    print("-" * 70)
    for entry in info.entries:
        enc = "Si" if entry.is_encrypted else "No"
        print(f"0x{entry.id:04X}  {entry.name:<40} {format_size(entry.size):>12} {enc:>8}")


def extract_metadata(info: PkgInfo, pkg_path: str, output_dir: str) -> Tuple[int, int]:
    os.makedirs(output_dir, exist_ok=True)
    extracted = 0
    skipped = 0
    with open(pkg_path, 'rb') as f:
        for entry in info.entries:
            if entry.id in (0x0001, 0x0010, 0x0020, 0x0080, 0x0100, 0x0200):
                skipped += 1
                continue
            if entry.is_encrypted:
                print(f"  [SKIP] {entry.name} - Cifrado")
                skipped += 1
                continue
            entry_path = os.path.join(output_dir, entry.name)
            os.makedirs(os.path.dirname(entry_path), exist_ok=True)
            try:
                f.seek(entry.offset)
                data = f.read(entry.size)
                with open(entry_path, 'wb') as out:
                    out.write(data)
                print(f"  [OK]   {entry.name} ({format_size(entry.size)})")
                extracted += 1
            except Exception as e:
                print(f"  [ERR]  {entry.name}: {e}")
    return extracted, skipped


def extract_pfs_full(info: PkgInfo, pkg_path: str, output_dir: str,
                     passcode: Optional[str] = None) -> bool:
    # Read pfs_cache_size * 2 bytes (matching shadPS4Plus)
    pfs_read_size = info.header.pfs_cache_size * 2
    if pfs_read_size <= 0 or pfs_read_size > info.header.pfs_image_size:
        pfs_read_size = info.header.pfs_image_size
    print(f"\nExtrayendo imagen PFS ({format_size(pfs_read_size)}, "
          f"cache_size=0x{info.header.pfs_cache_size:X})...")
    with open(pkg_path, 'rb') as f:
        f.seek(info.header.pfs_image_offset)
        pfs_data = f.read(pfs_read_size)

    pfsc_offset = find_pfsc(pfs_data)

    if pfsc_offset < 0:
        print("  PFSC no encontrado - imagen cifrada (XTS-AES)")
        print("  Intentando descifrado...")

        if not HAS_CRYPTO:
            print("  [ERROR] Se necesita 'cryptography': pip install cryptography")
            return False

        ekpfs = None
        if passcode:
            print(f"  Usando passcode proporcionado")
            content_id_bytes = info.header.content_id.encode('ascii')
            content_id_padded = content_id_bytes + b'\x00' * (0x30 - len(content_id_bytes))
            passcode_bytes = passcode.encode('ascii')
            if len(passcode_bytes) < 0x20:
                passcode_bytes = passcode_bytes + b'\x00' * (0x20 - len(passcode_bytes))
            ekpfs = hashlib.sha256(
                hashlib.sha256(struct.pack(">I", 1)).digest() +
                hashlib.sha256(content_id_padded).digest() +
                passcode_bytes
            ).digest()
            print(f"      ekpfs: {ekpfs.hex()[:32]}...")
        else:
            ekpfs = decrypt_ekpfs(info, pkg_path)

        if ekpfs:
            # Read crypt seed from PFS image
            seed = pfs_data[0x370:0x380]
            if len(seed) < 16:
                seed = seed + b'\x00' * (16 - len(seed))
            print(f"  Seed: {seed.hex()}")

            tweak_key, data_key = pfs_gen_crypto_key(ekpfs, seed)
            print(f"  tweakKey: {tweak_key.hex()}")
            print(f"  dataKey:  {data_key.hex()}")

            print(f"\n  Descifrando imagen PFS con AES-128-XTS...")
            print(f"  Primeros 64 bytes ANTES de descifrar: {pfs_data[:64].hex()}")
            xts = AES128XTS(tweak_key, data_key)
            decrypted_pfs = xts.decrypt(pfs_data)
            print(f"  Primeros 66 bytes DESPUES de descifrar: {decrypted_pfs[:64].hex()}")

            pfsc_offset = find_pfsc(decrypted_pfs)
            if pfsc_offset >= 0:
                print(f"  PFSC encontrado tras descifrado en 0x{pfsc_offset:X}")
                pfs_data = decrypted_pfs
            else:
                print("  [WARN] PFSC no encontrado tras descifrado")
                print(f"  Buscando en mas offsets...")
                for off in range(0, min(len(decrypted_pfs), 0x100000), 0x1000):
                    magic = struct.unpack_from('<I', decrypted_pfs, off)[0]
                    if magic == PFSC_MAGIC:
                        print(f"  PFSC encontrado en offset 0x{off:X}")
                        pfsc_offset = off
                        break
                if pfsc_offset < 0:
                    print(f"  PFSC realmente no encontrado. Guardando imagen cruda.")
                    pfsc_offset = 0
                pfs_data = decrypted_pfs
        else:
            print("  [ERROR] No se pudo obtener ekpfs")
            return False

    print(f"\nDescomprimiendo bloques PFSC...")
    try:
        decompressed = decompress_pfsc(pfs_data, pfsc_offset)
        print(f"  Datos descomprimidos: {format_size(len(decompressed))}")
    except Exception as e:
        print(f"  [ERROR] Error al descomprimir PFSC: {e}")
        return False

    try:
        pfs = PFSFilesystem(decompressed)
        print(f"\n  PFS Header:")
        print(f"    Version:     {pfs.pfs_hdr.version}")
        print(f"    Block size:  {pfs.pfs_hdr.blocksz}")
        print(f"    Inodes:      {pfs.pfs_hdr.ndinode}")
        print(f"    Superroot:   ino {pfs.pfs_hdr.superroot_ino}")
    except ValueError as e:
        print(f"  [ERROR] PFS no valido: {e}")
        return False

    print(f"\nExtrayendo archivos del filesystem PFS...")
    extracted, errors = pfs.extract_all(output_dir)
    print(f"\nResumen PFS: {extracted} archivos extraidos, {errors} errores")
    return True


def extract_for_shadps4(info: PkgInfo, pkg_path: str, output_dir: str,
                        passcode: Optional[str] = None):
    cusa = info.header.get_cusa_serial()
    game_dir = os.path.join(output_dir, cusa)

    print(f"\nExtraccion para shadps4 - CUSA: {cusa}")
    print(f"Directorio destino: {game_dir}")

    print("\n1. Extrayendo metadatos del PKG...")
    extract_metadata(info, pkg_path, game_dir)

    print("\n2. Extrayendo y descifrando imagen PFS...")
    success = extract_pfs_full(info, pkg_path, game_dir, passcode)

    print("\n3. Verificando estructura para shadps4...")
    checks = {
        "eboot.bin": os.path.exists(os.path.join(game_dir, "eboot.bin")),
        "sce_sys/param.sfo": os.path.exists(os.path.join(game_dir, "sce_sys", "param.sfo")),
        "sce_module/": os.path.isdir(os.path.join(game_dir, "sce_module")),
    }
    for name, ok in checks.items():
        print(f"  {'[OK]' if ok else '[WARN]'} {name}")

    print(f"\nCopia la carpeta '{cusa}' a tu directorio de juegos de shadps4")
    print(f"(normalmente ~/shadPS4/games/ o ~/.config/shadPS4/games/)")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="PS4 PKG Extractor - Extrae y descifra paquetes PKG de PS4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  %(prog)s archivo.pkg                    Extrae todo (metadatos + PFS descifrado)
  %(prog)s archivo.pkg -o salida/         Extrae a directorio especifico
  %(prog)s archivo.pkg --info             Muestra info del PKG
  %(prog)s archivo.pkg -l                 Lista entries del PKG
  %(prog)s archivo.pkg --passcode ABCD    Descifra con passcode especifico
  %(prog)s archivo.pkg --pfs-only         Solo extrae la imagen PFS completa
        """
    )
    parser.add_argument("pkg", help="Archivo PKG de PS4")
    parser.add_argument("-o", "--output", default=None, help="Directorio de salida")
    parser.add_argument("-l", "--list", action="store_true", help="Lista las entries")
    parser.add_argument("--info", action="store_true", help="Muestra info del PKG")
    parser.add_argument("--passcode", default=None, help="Passcode para descifrado")
    parser.add_argument("--pfs-only", action="store_true", help="Solo extrae la imagen PFS")

    args = parser.parse_args()

    if not os.path.isfile(args.pkg):
        print(f"Error: No se encuentra '{args.pkg}'", file=sys.stderr)
        sys.exit(1)

    try:
        info = parse_pkg(args.pkg)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print_info(info)

    if args.info:
        sys.exit(0)
    if args.list:
        list_entries(info)
        sys.exit(0)

    output_dir = args.output or Path(args.pkg).stem

    if args.pfs_only:
        extract_pfs_full(info, args.pkg, output_dir, args.passcode)
        sys.exit(0)

    extract_for_shadps4(info, args.pkg, output_dir, args.passcode)


if __name__ == "__main__":
    main()
