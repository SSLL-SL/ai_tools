#!/usr/bin/env python3
"""
Keeloq Decryptor - Multi-manufacturer
Tries multiple manufacturer keys and learning types

Usage: python keeloq_decrypt.py <hex_frame>
Example: python keeloq_decrypt.py 44803eb3468bd70b
"""

import sys

MANUFACTURER_KEYS = {
    "FAAC_RC,XT":    {"key": 0xFAAC05600001FAAC, "type": 2},
    "Clemsa_Mutancode": {"key": 0xE2B414B88AE7BC5E, "type": 2},
    "BFT":           {"key": 0x4C6D4D7A55644F76, "type": 3},
    "NICE_Smilo":    {"key": 0x54524D534543494E, "type": 1},
    "NICE_MHOUSE":   {"key": 0x484D6C6D73545253, "type": 1},
    "Came_Space":    {"key": 0x96638C36C99C2C9B, "type": 1},
    "DTM_Neo":       {"key": 0xFC4DE22CD5370320, "type": 1},
    "Genius_Bravo":  {"key": 0xFAAC05600002FAAC, "type": 2},
    "Sommer":        {"key": 0x7BCBEED4376EDCBF, "type": 2},
    "Centurion":     {"key": 0x188B0544A9B1DF14, "type": 2},
    "Monarch":       {"key": 0x4292903083134583, "type": 2},
    "Steelmate":     {"key": 0xB3E5625A8CCD7139, "type": 2},
    "Cardin_S449":   {"key": 0x207DBBE59D386F44, "type": 2},
    "Stilmatic":     {"key": 0x0123456789ABCDEF, "type": 2},
}

KEELOQ_NLF = 0x3A5C742E

def bit(x, n):
    return (x >> n) & 1

def g5(x, a, b, c, d, e):
    return bit(x, a) + bit(x, b) * 2 + bit(x, c) * 4 + bit(x, d) * 8 + bit(x, e) * 16

def keeloq_encrypt(data, key):
    x = data
    for r in range(528):
        x = (x >> 1) ^ ((bit(x, 0) ^ bit(x, 16) ^ bit(key, r & 63) ^
                         bit(KEELOQ_NLF, g5(x, 1, 9, 20, 26, 31))) << 31)
    return x & 0xFFFFFFFF

def keeloq_decrypt(data, key):
    x = data
    for r in range(528):
        x = ((x << 1) ^ bit(x, 31) ^ bit(x, 15) ^
             bit(key, (15 - r) & 63) ^
             bit(KEELOQ_NLF, g5(x, 0, 8, 19, 25, 30))) & 0xFFFFFFFF
    return x

def reverse_key(key, bit_count):
    result = 0
    for i in range(bit_count):
        result = (result << 1) | ((key >> i) & 1)
    return result

def simple_learning(hop, key):
    return keeloq_decrypt(hop, key)

def normal_learning(fix, key):
    data = fix & 0x0FFFFFFF
    k1_input = data | 0x20000000
    k1 = keeloq_decrypt(k1_input, key)
    k2_input = data | 0x60000000
    k2 = keeloq_decrypt(k2_input, key)
    return (k2 << 32) | k1

def check_decrypt(decrypt, btn, end_serial):
    dec_btn = (decrypt >> 28) & 0x0F
    dec_disc = (decrypt >> 16) & 0xFF
    counter = decrypt & 0xFFFF
    if dec_btn == btn and (dec_disc == end_serial or dec_disc == 0):
        return True, counter
    return False, None

def try_decrypt(data, mfg_name, mfg_info):
    key_rev = reverse_key(data, 64)
    fix = (key_rev >> 32) & 0xFFFFFFFF
    hop = key_rev & 0xFFFFFFFF
    serial = fix & 0x0FFFFFFF
    btn = (fix >> 28) & 0x0F
    end_serial = fix & 0xFF

    mfg_key = mfg_info["key"]
    mfg_type = mfg_info["type"]

    results = []

    if mfg_type == 1:
        decrypt = simple_learning(hop, mfg_key)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Simple", mfg_key, decrypt, cnt))

    elif mfg_type == 2:
        man = normal_learning(fix, mfg_key)
        decrypt = keeloq_decrypt(hop, man)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Normal", man, decrypt, cnt))

    elif mfg_type == 3:
        man_rev = 0
        for i in range(0, 64, 8):
            byte_val = (mfg_key >> i) & 0xFF
            man_rev |= byte_val << (56 - i)

        decrypt = simple_learning(hop, mfg_key)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Simple", mfg_key, decrypt, cnt))

        decrypt = simple_learning(hop, man_rev)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Simple(rev)", man_rev, decrypt, cnt))

        man = normal_learning(fix, mfg_key)
        decrypt = keeloq_decrypt(hop, man)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Normal", man, decrypt, cnt))

        man = normal_learning(fix, man_rev)
        decrypt = keeloq_decrypt(hop, man)
        valid, cnt = check_decrypt(decrypt, btn, end_serial)
        if valid:
            results.append(("Normal(rev)", man, decrypt, cnt))

    return results

def main():
    if len(sys.argv) < 2:
        print("Usage: python keeloq_decrypt.py <hex_frame>")
        print("Example: python keeloq_decrypt.py 44803eb3468bd70b")
        sys.exit(1)

    hex_frame = sys.argv[1]
    data = int(hex_frame, 16)

    print(f"Keeloq Multi-manufacturer Decryptor")
    print(f"=" * 50)
    print(f"Input Frame: {hex_frame}")
    print()

    found_any = False
    for name, info in MANUFACTURER_KEYS.items():
        results = try_decrypt(data, name, info)
        if results:
            found_any = True
            for method, dev_key, decrypt, cnt in results:
                print(f"[+] FOUND: {name} ({method} Learning)")
                print(f"    Device Key: {hex(dev_key)}")
                print(f"    Decrypted:  {hex(decrypt)}")
                print(f"    Counter:    {cnt}")
                print()

    if not found_any:
        print("[-] No valid decryption found with any known manufacturer key.")
        print()
        print("Possible reasons:")
        print("  - Unknown manufacturer key")
        print("  - Incorrect frame data")
        print("  - Frame is not Keeloq protocol")

if __name__ == "__main__":
    main()
