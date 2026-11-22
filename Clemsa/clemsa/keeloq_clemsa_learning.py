#!/usr/bin/env python3
"""
Keeloq Clemsa - Try ALL learning types.
Type 1: Simple Learning
Type 2: Normal Learning (already tried)
Type 3: Byte-reversed Simple Learning
"""

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

def reverse_bits(x, n):
    result = 0
    for i in range(n):
        result = (result << 1) | ((x >> i) & 1)
    return result

def reverse_bytes(x):
    return int.from_bytes(x.to_bytes(8, 'big')[::-1], 'big')

def reverse_nibbles_per_byte(x):
    result = 0
    for i in range(8):
        b = (x >> (i * 8)) & 0xFF
        rb = 0
        for j in range(8):
            rb = (rb << 1) | ((b >> j) & 1)
        result |= (rb << (i * 8))
    return result

def normal_learning(fix, key):
    data = fix & 0x0FFFFFFF
    k1_input = data | 0x20000000
    k1 = keeloq_decrypt(k1_input, key)
    k2_input = data | 0x60000000
    k2 = keeloq_decrypt(k2_input, key)
    return (k2 << 32) | k1

def simple_learning(hop, key):
    return keeloq_decrypt(hop, key)

def byte_rev_simple_learning(hop, key):
    # Reverse bytes of hop, then decrypt
    hop_rev = int.from_bytes(hop.to_bytes(4, 'big')[::-1], 'big')
    return keeloq_decrypt(hop_rev, key)

def get_device_keys(frame_data, clemsa_key):
    """Get device key using all 3 learning types"""
    fix = (frame_data >> 32) & 0xFFFFFFFF
    hop = frame_data & 0xFFFFFFFF
    
    dk_normal = normal_learning(fix, clemsa_key)
    dk_simple = simple_learning(hop, clemsa_key)
    dk_byte_rev = byte_rev_simple_learning(hop, clemsa_key)
    
    return {
        'normal': dk_normal,
        'simple': dk_simple,
        'byte_rev_simple': dk_byte_rev,
    }

def try_decrypt(frame_data, dk, learning_type):
    """Decrypt and return all fields"""
    hop = frame_data & 0xFFFFFFFF
    fix = (frame_data >> 32) & 0xFFFFFFFF
    
    dec = keeloq_decrypt(hop, dk)
    
    btn = (dec >> 28) & 0x0F
    disc = (dec >> 16) & 0xFF
    ctr = dec & 0xFFFF
    serial = fix & 0x0FFFFFFF
    btn_fix = (fix >> 28) & 0x0F
    
    return btn, disc, ctr, serial, btn_fix

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    clemsa_key = 0xE2B414B88AE7BC5E
    
    # Generate all frame interpretations
    interpretations = {
        "direct": (frame1, frame2),
        "bitrev": (reverse_bits(frame1, 64), reverse_bits(frame2, 64)),
        "byterev": (reverse_bytes(frame1), reverse_bytes(frame2)),
        "nibrev": (reverse_nibbles_per_byte(frame1), reverse_nibbles_per_byte(frame2)),
        "swap": (((frame1 & 0xFFFFFFFF) << 32) | ((frame1 >> 32) & 0xFFFFFFFF),
                  ((frame2 & 0xFFFFFFFF) << 32) | ((frame2 >> 32) & 0xFFFFFFFF)),
    }
    
    learning_types = ["normal", "simple", "byte_rev_simple"]
    
    print("=" * 70)
    print("CLEMSA - All Learning Types + All Interpretations")
    print("=" * 70)
    
    for iname, (f1, f2) in sorted(interpretations.items()):
        for lt in learning_types:
            dk1 = get_device_keys(f1, clemsa_key)[lt]
            dk2 = get_device_keys(f2, clemsa_key)[lt]
            
            btn1, disc1, ctr1, ser1, btn_fix1 = try_decrypt(f1, dk1, lt)
            btn2, disc2, ctr2, ser2, btn_fix2 = try_decrypt(f2, dk2, lt)
            
            # Check if results are reasonable
            issues = []
            if btn1 != btn2:
                issues.append(f"btn mismatch: {btn1} vs {btn2}")
            if ser1 != ser2:
                issues.append(f"serial mismatch: 0x{ser1:07x} vs 0x{ser2:07x}")
            if ctr1 > 10000 and ctr2 > 10000:
                issues.append(f"both ctrs very large: {ctr1}, {ctr2}")
            
            # Only print if there's something interesting
            if (btn1 == 2 or btn2 == 2 or 
                disc1 == 53 or disc2 == 53 or 
                ctr1 == 950 or ctr2 == 950 or
                ser1 == 0x02DC6E83 or ser2 == 0x02DC6E83 or
                btn1 == btn2 or not issues):
                
                status = "OK" if not issues else "ISSUES: " + "; ".join(issues)
                
                print(f"\n{iname} + {lt}: {status}")
                print(f"  F1: btn={btn1} disc={disc1} ctr={ctr1} serial=0x{ser1:07x} btn_fix={btn_fix1}")
                print(f"  F2: btn={btn2} disc={disc2} ctr={ctr2} serial=0x{ser2:07x} btn_fix={btn_fix2}")
                print(f"  DK1: 0x{dk1:016x}")
                print(f"  DK2: 0x{dk2:016x}")

if __name__ == "__main__":
    main()
