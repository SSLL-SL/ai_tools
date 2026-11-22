#!/usr/bin/env python3
"""
Keeloq Analysis - Two frames comparison
Frame 1: 44803eb3468bd70b
Frame 2: 24803f36a5634e40
Discriminator: 53 (0x35)
Serial: 0480 16051
Counter: 950
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

def analyze_frame(frame_hex, label):
    data = int(frame_hex, 16)
    
    print(f"\n{'='*60}")
    print(f"[{label}] Frame: {frame_hex}")
    print(f"{'='*60}")
    
    # Show bytes
    bytes_list = [(data >> (56 - i*8)) & 0xFF for i in range(8)]
    print(f"Bytes: {' '.join(f'{b:02x}' for b in bytes_list)}")
    
    # Show binary for first 2 bytes
    print(f"Byte 0 binary: {bytes_list[0]:08b}")
    print(f"Byte 1 binary: {bytes_list[1]:08b}")
    
    # Method 1: Direct
    fix_direct = (data >> 32) & 0xFFFFFFFF
    hop_direct = data & 0xFFFFFFFF
    serial_direct = fix_direct & 0x0FFFFFFF
    btn_direct = (fix_direct >> 28) & 0x0F
    
    print(f"\n[Direct - no reversal]")
    print(f"  Fix: 0x{fix_direct:08x}")
    print(f"  Hop: 0x{hop_direct:08x}")
    print(f"  Serial: {serial_direct} (0x{serial_direct:07x})")
    print(f"  Button: {btn_direct} (0x{btn_direct:01x})")
    
    # Method 2: Full bit reversal
    data_rev = reverse_key(data, 64)
    fix_rev = (data_rev >> 32) & 0xFFFFFFFF
    hop_rev = data_rev & 0xFFFFFFFF
    serial_rev = fix_rev & 0x0FFFFFFF
    btn_rev = (fix_rev >> 28) & 0x0F
    
    print(f"\n[Full bit reversal]")
    print(f"  Fix: 0x{fix_rev:08x}")
    print(f"  Hop: 0x{hop_rev:08x}")
    print(f"  Serial: {serial_rev} (0x{serial_rev:07x})")
    print(f"  Button: {btn_rev} (0x{btn_rev:01x})")
    
    return {
        'direct': {'fix': fix_direct, 'hop': hop_direct, 'serial': serial_direct, 'btn': btn_direct},
        'reversed': {'fix': fix_rev, 'hop': hop_rev, 'serial': serial_rev, 'btn': btn_rev},
    }

def main():
    frame1 = "44803eb3468bd70b"
    frame2 = "24803f36a5634e40"
    
    disc = 53  # 0x35
    serial_dec = 48016051
    serial_hex = serial_dec & 0x0FFFFFFF
    counter = 950  # 0x03B6
    
    print("Known values:")
    print(f"  Discriminator: {disc} (0x{disc:02x})")
    print(f"  Serial (dec):  {serial_dec}")
    print(f"  Serial (hex):  0x{serial_hex:07x}")
    print(f"  Counter:       {counter} (0x{counter:04x})")
    
    # Expected decrypted hopping code structure
    print(f"\nExpected decrypted hopping code:")
    print(f"  Bits [31:28] = Button (4 bits)")
    print(f"  Bits [27:16] = Discriminator = 0x{disc:02x}")
    print(f"  Bits [15:0]  = Counter = 0x{counter:04x}")
    print(f"  So decrypted hop should be: ????{disc:02x}{counter:04x}")
    
    # Analyze both frames
    r1 = analyze_frame(frame1, "Frame 1")
    r2 = analyze_frame(frame2, "Frame 2")
    
    # Compare the two frames to find pattern
    print(f"\n{'='*60}")
    print(f"COMPARISON")
    print(f"{'='*60}")
    
    # Compare bytes
    data1 = int(frame1, 16)
    data2 = int(frame2, 16)
    
    bytes1 = [(data1 >> (56 - i*8)) & 0xFF for i in range(8)]
    bytes2 = [(data2 >> (56 - i*8)) & 0xFF for i in range(8)]
    
    print(f"Frame 1 bytes: {' '.join(f'{b:02x}' for b in bytes1)}")
    print(f"Frame 2 bytes: {' '.join(f'{b:02x}' for b in bytes2)}")
    print(f"Difference:    {' '.join(f'  ' if b1==b2 else f'{b1^b2:02x}' for b1,b2 in zip(bytes1, bytes2))}")
    
    # XOR the two frames
    xor = data1 ^ data2
    print(f"\nXOR of frames: 0x{xor:016x}")
    print(f"XOR binary:    {xor:064b}")
    
    # The XOR should reveal which bits change between frames
    # In Keeloq, only the counter changes between consecutive frames
    # So the XOR should show us the counter difference
    
    print(f"\nInterpreting XOR as counter difference:")
    xor_bytes = [(xor >> (56 - i*8)) & 0xFF for i in range(8)]
    print(f"XOR bytes: {' '.join(f'{b:02x}' for b in xor_bytes)}")

if __name__ == "__main__":
    main()
