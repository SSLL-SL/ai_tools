#!/usr/bin/env python3
"""
Keeloq Clemsa exhaustive search.
Tries ALL possible frame interpretations with the Clemsa key,
and tries buttons 0-15, counter range around 950.
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
        # reverse bits within byte
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

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    clemsa_key = 0xE2B414B88AE7BC5E
    
    known_serial = 0x02DC6E83  # 48016051
    known_disc = 53  # 0x35
    known_counter = 950  # 0x03B6
    
    print("Keeloq Clemsa Exhaustive Search")
    print("=" * 70)
    print(f"Clemsa key: 0x{clemsa_key:016x}")
    print(f"Known serial: {known_serial} (0x{known_serial:08x})")
    print(f"Known disc: {known_disc}")
    print(f"Known counter: {known_counter}")
    print()
    
    # Generate all frame interpretations
    interpretations = {}
    
    for frame_num, frame in enumerate([frame1, frame2], 1):
        interpretations[f"Frame{frame_num}_direct"] = frame
        interpretations[f"Frame{frame_num}_bitrev"] = reverse_bits(frame, 64)
        interpretations[f"Frame{frame_num}_byterev"] = reverse_bytes(frame)
        interpretations[f"Frame{frame_num}_nibrev"] = reverse_nibbles_per_byte(frame)
        # Swap fix/hop halves
        fix = (frame >> 32) & 0xFFFFFFFF
        hop = frame & 0xFFFFFFFF
        interpretations[f"Frame{frame_num}_swap_halves"] = (hop << 32) | fix
    
    # For each interpretation of frame 1, try all buttons and counter values
    results = []
    
    frame1_interps = {k: v for k, v in interpretations.items() if "Frame1" in k}
    frame2_interps = {k: v for k, v in interpretations.items() if "Frame2" in k}
    
    for name1, data1 in sorted(frame1_interps.items()):
        fix1 = (data1 >> 32) & 0xFFFFFFFF
        hop1 = data1 & 0xFFFFFFFF
        serial1 = fix1 & 0x0FFFFFFF
        
        for btn in range(16):
            # Try counter values near 950
            for ctr in range(948, 955):
                disc_from_hop = (hop1 >> 16) & 0xFF
                ctr_from_hop = hop1 & 0xFFFF
                btn_from_hop = (hop1 >> 28) & 0x0F
                
                # Build expected plaintext
                expected = (btn << 28) | (known_disc << 16) | ctr
                
                # Encrypt with normal learning
                dev_key = normal_learning(fix1, clemsa_key)
                encrypted = keeloq_encrypt(expected, dev_key)
                
                if encrypted == hop1:
                    # Verify with frame 2
                    for name2, data2 in frame2_interps.items():
                        fix2 = (data2 >> 32) & 0xFFFFFFFF
                        hop2 = data2 & 0xFFFFFFFF
                        dev_key2 = normal_learning(fix2, clemsa_key)
                        encrypted2 = keeloq_encrypt(expected, dev_key2)
                        if encrypted2 == hop2:
                            results.append((name1, name2, btn, ctr, serial1, dev_key))
        
        # Also try the actual hop values from frame 2 directly
        for name2, data2 in frame2_interps.items():
            fix2 = (data2 >> 32) & 0xFFFFFFFF
            hop2 = data2 & 0xFFFFFFFF
            
            # Check if both fixes give the same serial
            serial2 = fix2 & 0x0FFFFFFF
            
            # Both fixes should derive the same device key
            dk1 = normal_learning(fix1, clemsa_key)
            dk2 = normal_learning(fix2, clemsa_key)
            
            # Decrypt hop1 with dk1
            dec1 = keeloq_decrypt(hop1, dk1)
            # Decrypt hop2 with dk2
            dec2 = keeloq_decrypt(hop2, dk2)
            
            btn1 = (dec1 >> 28) & 0x0F
            disc1 = (dec1 >> 16) & 0xFF
            ctr1 = dec1 & 0xFFFF
            ser1 = fix1 & 0x0FFFFFFF
            
            btn2 = (dec2 >> 28) & 0x0F
            disc2 = (dec2 >> 16) & 0xFF
            ctr2 = dec2 & 0xFFFF
            ser2 = fix2 & 0x0FFFFFFF
            
            # Check if both decrypt to plausible values
            if (disc1 == known_disc or disc2 == known_disc or 
                ctr1 == known_counter or ctr2 == known_counter or
                ser1 == known_serial or ser2 == known_serial):
                print(f"\n*** PARTIAL MATCH: {name1} + {name2} ***")
                print(f"  Fix1: 0x{fix1:08x} Serial1: 0x{ser1:07x}")
                print(f"  Hop1 dec: 0x{dec1:08x} btn={btn1} disc={disc1}(0x{disc1:02x}) ctr={ctr1}")
                print(f"  Fix2: 0x{fix2:08x} Serial2: 0x{ser2:07x}")
                print(f"  Hop2 dec: 0x{dec2:08x} btn={btn2} disc={disc2}(0x{disc2:02x}) ctr={ctr2}")
                print(f"  DK1: 0x{dk1:016x}")
                print(f"  DK2: 0x{dk2:016x}")
    
    if results:
        print("\n" + "=" * 70)
        print("MATCHES FOUND:")
        print("=" * 70)
        for r in results:
            print(f"  {r[0]} + {r[1]}, btn={r[2]}, ctr={r[3]}, serial=0x{r[4]:07x}, dk=0x{r[5]:016x}")
    else:
        print("\n\nNo exact matches found. Let me show ALL decryption results...")
        print("=" * 70)
        
        # Show ALL results for every interpretation
        for name1 in sorted(frame1_interps.keys()):
            data1 = frame1_interps[name1]
            fix1 = (data1 >> 32) & 0xFFFFFFFF
            hop1 = data1 & 0xFFFFFFFF
            
            dk = normal_learning(fix1, clemsa_key)
            dec1 = keeloq_decrypt(hop1, dk)
            
            btn1 = (dec1 >> 28) & 0x0F
            disc1 = (dec1 >> 16) & 0xFF
            ctr1 = dec1 & 0xFFFF
            ser1 = fix1 & 0x0FFFFFFF
            
            print(f"\n{name1}:")
            print(f"  Fix: 0x{fix1:08x}  Hop: 0x{hop1:08x}")
            print(f"  Decrypted: 0x{dec1:08x}")
            print(f"  Button: {btn1}  Serial: 0x{ser1:07x} ({ser1})  Disc: {disc1}  Counter: {ctr1} ({hex(ctr1)})")
        
        for name2 in sorted(frame2_interps.keys()):
            data2 = frame2_interps[name2]
            fix2 = (data2 >> 32) & 0xFFFFFFFF
            hop2 = data2 & 0xFFFFFFFF
            
            dk = normal_learning(fix2, clemsa_key)
            dec2 = keeloq_decrypt(hop2, dk)
            
            btn2 = (dec2 >> 28) & 0x0F
            disc2 = (dec2 >> 16) & 0xFF
            ctr2 = dec2 & 0xFFFF
            ser2 = fix2 & 0x0FFFFFFF
            
            print(f"\n{name2}:")
            print(f"  Fix: 0x{fix2:08x}  Hop: 0x{hop2:08x}")
            print(f"  Decrypted: 0x{dec2:08x}")
            print(f"  Button: {btn2}  Serial: 0x{ser2:07x} ({ser2})  Disc: {disc2}  Counter: {ctr2} ({hex(ctr2)})")

if __name__ == "__main__":
    main()
