#!/usr/bin/env python3
"""
Keeloq Decryptor - Using known values
Serial: 0480 16051 (decimal 48016051)
Counter: 950 (decimal 0x03B6)
Customization code: 53 (0x35)
"""

import sys

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

def normal_learning(fix, key):
    data = fix & 0x0FFFFFFF
    k1_input = data | 0x20000000
    k1 = keeloq_decrypt(k1_input, key)
    k2_input = data | 0x60000000
    k2 = keeloq_decrypt(k2_input, key)
    return (k2 << 32) | k1

def main():
    frame_hex = "44803eb3468bd70b"
    data = int(frame_hex, 16)
    
    serial = 48016051  # decimal
    serial_hex = serial & 0x0FFFFFFF  # 28 bits
    
    customization = 53  # decimal
    counter = 950  # decimal
    
    print("Known values:")
    print(f"  Frame:          {frame_hex}")
    print(f"  Serial (dec):   {serial}")
    print(f"  Serial (hex):   {hex(serial_hex)}")
    print(f"  Customization:  {customization} (0x{customization:02x})")
    print(f"  Counter:        {counter} (0x{counter:04x})")
    print()
    
    # Try different frame interpretations
    print("Testing different frame interpretations:")
    print("=" * 60)
    
    # Method 1: Direct (no reversal)
    fix_direct = (data >> 32) & 0xFFFFFFFF
    hop_direct = data & 0xFFFFFFFF
    print(f"\n[1] Direct (no reversal):")
    print(f"    Fix: {hex(fix_direct)}")
    print(f"    Hop: {hex(hop_direct)}")
    print(f"    Serial from fix: {fix_direct & 0x0FFFFFFF} (hex: {hex(fix_direct & 0x0FFFFFFF)})")
    
    # Method 2: Full bit reversal
    data_rev = reverse_key(data, 64)
    fix_rev = (data_rev >> 32) & 0xFFFFFFFF
    hop_rev = data_rev & 0xFFFFFFFF
    print(f"\n[2] Full bit reversal:")
    print(f"    Fix: {hex(fix_rev)}")
    print(f"    Hop: {hex(hop_rev)}")
    print(f"    Serial from fix: {fix_rev & 0x0FFFFFFF} (hex: {hex(fix_rev & 0x0FFFFFFF)})")
    
    # Method 3: Byte reversal
    data_bytes = bytearray(data.to_bytes(8, 'big'))
    data_bytes.reverse()
    data_byte_rev = int.from_bytes(data_bytes, 'big')
    fix_byte_rev = (data_byte_rev >> 32) & 0xFFFFFFFF
    hop_byte_rev = data_byte_rev & 0xFFFFFFFF
    print(f"\n[3] Byte reversal:")
    print(f"    Fix: {hex(fix_byte_rev)}")
    print(f"    Hop: {hex(hop_byte_rev)}")
    print(f"    Serial from fix: {fix_byte_rev & 0x0FFFFFFF} (hex: {hex(fix_byte_rev & 0x0FFFFFFF)})")
    
    # Method 4: Bit reversal within each byte
    data_nibble_rev = 0
    for i in range(8):
        byte = (data >> (i * 8)) & 0xFF
        rev_byte = 0
        for b in range(8):
            if byte & (1 << b):
                rev_byte |= 1 << (7 - b)
        data_nibble_rev |= rev_byte << (i * 8)
    fix_nibble_rev = (data_nibble_rev >> 32) & 0xFFFFFFFF
    hop_nibble_rev = data_nibble_rev & 0xFFFFFFFF
    print(f"\n[4] Bit reversal within each byte:")
    print(f"    Fix: {hex(fix_nibble_rev)}")
    print(f"    Hop: {hex(hop_nibble_rev)}")
    print(f"    Serial from fix: {fix_nibble_rev & 0x0FFFFFFF} (hex: {hex(fix_nibble_rev & 0x0FFFFFFF)})")
    
    # Check which interpretation matches the known serial
    print("\n" + "=" * 60)
    print("Checking which interpretation matches serial:", hex(serial_hex))
    print("=" * 60)
    
    interpretations = [
        ("Direct", fix_direct),
        ("Full bit reversal", fix_rev),
        ("Byte reversal", fix_byte_rev),
        ("Nibble reversal", fix_nibble_rev),
    ]
    
    for name, fix in interpretations:
        serial_from_fix = fix & 0x0FFFFFFF
        if serial_from_fix == serial_hex:
            print(f"\n[+] MATCH FOUND: {name}")
            print(f"    Fix: {hex(fix)}")
            print(f"    Serial: {hex(serial_from_fix)}")
    
    # Also show the expected fix structure
    print("\n" + "=" * 60)
    print("Expected fix structure (if serial = 0x{:07x}):".format(serial_hex))
    print("=" * 60)
    print("  Upper 4 bits: button/customization (should be 0x3 or similar)")
    print("  Lower 28 bits: serial (0x{:07x})".format(serial_hex))
    print()
    
    # Try with button = customization code
    btn = customization & 0x0F  # 4 bits
    expected_fix = (btn << 28) | serial_hex
    print(f"  If button = {btn} (0x{btn:01x}):")
    print(f"    Expected fix: {hex(expected_fix)}")
    print()

if __name__ == "__main__":
    main()
