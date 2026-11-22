#!/usr/bin/env python3
"""
Keeloq Clemsa Mutancode - exhaustive test.
Clemsa uses: hop = btn<<28 | (serial & 0xFFF)<<16 | counter
Normal learning.
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

def normal_learning(fix, key):
    data = fix & 0x0FFFFFFF
    k1_input = data | 0x20000000
    k1 = keeloq_decrypt(k1_input, key)
    k2_input = data | 0x60000000
    k2 = keeloq_decrypt(k2_input, key)
    return (k2 << 32) | k1

def try_interpretation(name, frame, clemsa_key):
    """Try decrypting with this frame interpretation"""
    fix = (frame >> 32) & 0xFFFFFFFF
    hop = frame & 0xFFFFFFFF
    serial = fix & 0x0FFFFFFF
    btn_from_fix = (fix >> 28) & 0x0F
    
    dk = normal_learning(fix, clemsa_key)
    dec = keeloq_decrypt(hop, dk)
    
    btn = (dec >> 28) & 0x0F
    disc = (dec >> 16) & 0xFF
    ctr = dec & 0xFFFF
    
    return fix, hop, serial, btn_from_fix, dk, dec, btn, disc, ctr

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    clemsa_key = 0xE2B414B88AE7BC5E
    
    known_serial = 0x02DC6E83
    known_disc = 53
    known_counter = 950
    known_btn = 2
    
    # Generate all interpretations
    frames = {
        "direct": (frame1, frame2),
        "bitrev": (reverse_bits(frame1, 64), reverse_bits(frame2, 64)),
        "byterev": (int.from_bytes(frame1.to_bytes(8,'big')[::-1], 'big'),
                     int.from_bytes(frame2.to_bytes(8,'big')[::-1], 'big')),
    }
    
    # Add nibble-reversed
    def nibrev(x):
        result = 0
        for i in range(8):
            b = (x >> (i * 8)) & 0xFF
            rb = 0
            for j in range(8):
                rb = (rb << 1) | ((b >> j) & 1)
            result |= (rb << (i * 8))
        return result
    
    frames["nibrev"] = (nibrev(frame1), nibrev(frame2))
    
    # Add swap halves
    def swap(f):
        return ((f & 0xFFFFFFFF) << 32) | ((f >> 32) & 0xFFFFFFFF)
    frames["swap"] = (swap(frame1), swap(frame2))
    
    print("=" * 70)
    print("CLEMSA MUTANCODE - All interpretations")
    print("=" * 70)
    
    for iname, (f1, f2) in sorted(frames.items()):
        print(f"\n--- {iname} ---")
        
        for fn, fdata in [("F1", f1), ("F2", f2)]:
            fix, hop, serial, btn_fix, dk, dec, btn, disc, ctr = try_interpretation(fn, fdata, clemsa_key)
            
            print(f"  {fn}: Fix=0x{fix:08x} Hop=0x{hop:08x}")
            print(f"       Serial=0x{serial:07x} ({serial}) Btn_fix={btn_fix}")
            print(f"       Dec=0x{dec:08x} Btn={btn} Disc={disc} Ctr={ctr} ({hex(ctr)})")
            print(f"       DK=0x{dk:016x}")
            
            # Check matches
            if serial == known_serial:
                print(f"       *** SERIAL MATCH! ***")
            if disc == known_disc:
                print(f"       *** DISC MATCH! ***")
            if ctr == known_counter:
                print(f"       *** COUNTER MATCH! ***")
            if btn == known_btn:
                print(f"       *** BUTTON MATCH! ***")
    
    # Now try brute force: for each interpretation, try all btn (0-15) and ctr (0-65535)
    # to see if any combination produces the expected Clemsa hop format
    print("\n" + "=" * 70)
    print("BRUTE FORCE: For each interpretation, try encrypting expected plaintext")
    print("hop = btn<<28 | (serial & 0xFFF)<<16 | ctr")
    print("with each Clemsa interpretation's device key")
    print("=" * 70)
    
    for iname, (f1, f2) in sorted(frames.items()):
        for fn, fdata in [("F1", f1), ("F2", f2)]:
            fix = (fdata >> 32) & 0xFFFFFFFF
            hop = fdata & 0xFFFFFFFF
            serial = fix & 0x0FFFFFFF
            dk = normal_learning(fix, clemsa_key)
            
            serial_low12 = serial & 0xFFF
            
            # Try all btn and ctr
            for btn in range(16):
                for ctr in [known_counter, known_counter-1, known_counter+1, 
                           known_counter-2, known_counter+2,
                           0, 1, 2, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 30000, 40000, 50000, 60000, 65535]:
                    expected = (btn << 28) | (serial_low12 << 16) | ctr
                    encrypted = keeloq_encrypt(expected, dk)
                    
                    if encrypted == hop:
                        print(f"\n  [!!!] MATCH: {fn}_{iname} btn={btn} ctr={ctr} serial_low12=0x{serial_low12:03x}")
                        print(f"        Expected: 0x{expected:08x} Encrypted: 0x{encrypted:08x} == Hop: 0x{hop:08x}")
    
    # Also try standard disc format: hop = btn<<28 | disc<<16 | ctr
    print("\n" + "=" * 70)
    print("BRUTE FORCE: Standard disc format hop = btn<<28 | disc<<16 | ctr")
    print("=" * 70)
    
    for iname, (f1, f2) in sorted(frames.items()):
        for fn, fdata in [("F1", f1), ("F2", f2)]:
            fix = (fdata >> 32) & 0xFFFFFFFF
            hop = fdata & 0xFFFFFFFF
            dk = normal_learning(fix, clemsa_key)
            
            for btn in range(16):
                for disc in range(256):
                    for ctr in [known_counter, known_counter-1, known_counter+1]:
                        expected = (btn << 28) | (disc << 16) | ctr
                        encrypted = keeloq_encrypt(expected, dk)
                        if encrypted == hop:
                            print(f"\n  [!!!] MATCH: {fn}_{iname} btn={btn} disc={disc} ctr={ctr}")
                            print(f"        Encrypted: 0x{encrypted:08x} == Hop: 0x{hop:08x}")

if __name__ == "__main__":
    main()
