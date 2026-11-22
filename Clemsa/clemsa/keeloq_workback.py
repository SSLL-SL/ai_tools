#!/usr/bin/env python3
"""
Keeloq - Work backwards from known values
Frame 1: 44803eb3468bd70b
Frame 2: 24803f36a5634e40
Discriminator: 53 (0x35)
Counter: 950 (0x03B6)
Button: 2
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

def simple_learning(hop, key):
    return keeloq_decrypt(hop, key)

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    disc = 0x35
    counter1 = 950  # 0x03B6
    
    print("Working backwards from known values")
    print("=" * 60)
    print(f"Frame 1: {hex(frame1)}")
    print(f"Frame 2: {hex(frame2)}")
    print(f"Discriminator: {disc} (0x{disc:02x})")
    print(f"Counter (frame1): {counter1} (0x{counter1:04x})")
    print()
    
    # Expected decrypted hopping code for button=2
    btn = 2
    expected_hop1 = (btn << 28) | (disc << 16) | counter1
    print(f"Expected decrypted hop (btn=2): 0x{expected_hop1:08x}")
    print(f"  Button: {(expected_hop1>>28)&0x0F}")
    print(f"  Disc:   {(expected_hop1>>16)&0xFF}")
    print(f"  Counter: {expected_hop1&0xFFFF}")
    print()
    
    # Try different frame interpretations
    interpretations = [
        ("Direct", frame1),
        ("Bit-reversed", reverse_key(frame1, 64)),
    ]
    
    for name, data in interpretations:
        print(f"\n{'='*60}")
        print(f"Interpretation: {name}")
        print(f"{'='*60}")
        
        fix = (data >> 32) & 0xFFFFFFFF
        hop = data & 0xFFFFFFFF
        serial = fix & 0x0FFFFFFF
        fix_btn = (fix >> 28) & 0x0F
        
        print(f"Fix: 0x{fix:08x}")
        print(f"Hop: 0x{hop:08x}")
        print(f"Serial from fix: 0x{serial:07x}")
        print(f"Button from fix: {fix_btn} (0x{fix_btn:01x})")
        
        # Try to encrypt expected plaintext with known keys
        known_keys = {
            "FAAC_RC,XT": 0xFAAC05600001FAAC,
            "Clemsa_Mutancode": 0xE2B414B88AE7BC5E,
            "BFT": 0x4C6D4D7A55644F76,
            "NICE_Smilo": 0x54524D534543494E,
            "Came_Space": 0x96638C36C99C2C9B,
            "DTM_Neo": 0xFC4DE22CD5370320,
            "Genius_Bravo": 0xFAAC05600002FAAC,
            "Sommer": 0x7BCBEED4376EDCBF,
            "Centurion": 0x188B0544A9B1DF14,
            "Monarch": 0x4292903083134583,
            "Steelmate": 0xB3E5625A8CCD7139,
            "Cardin_S449": 0x207DBBE59D386F44,
            "Stilmatic": 0x0123456789ABCDEF,
            "Motorline": 0x572768229476CAFF,
            "JCM_Tech": 0x89146E59537903B7,
            "Comunello": 0xF1A3E552C8647E55,
            "Normstahl": 0x9DA08153CF312BA7,
            "GSN": 0xA9748532B7655297,
        }
        
        print(f"\nTrying to encrypt expected plaintext with known keys...")
        
        for name_k, mfg_key in known_keys.items():
            # Try Normal Learning
            man = normal_learning(fix, mfg_key)
            encrypted = keeloq_encrypt(expected_hop1, man)
            
            if encrypted == hop:
                print(f"\n[!!!] MATCH FOUND: {name_k} (Normal Learning)")
                print(f"    Manufacturer Key: 0x{mfg_key:016x}")
                print(f"    Device Key: 0x{man:016x}")
                print(f"    Encrypted: 0x{encrypted:08x} == Hop: 0x{hop:08x}")
            
            # Try Simple Learning
            encrypted_s = keeloq_encrypt(expected_hop1, mfg_key)
            if encrypted_s == hop:
                print(f"\n[!!!] MATCH FOUND: {name_k} (Simple Learning)")
                print(f"    Manufacturer Key: 0x{mfg_key:016x}")
                print(f"    Encrypted: 0x{encrypted_s:08x} == Hop: 0x{hop:08x}")
        
        # Also try with button from fix
        for test_btn in range(16):
            test_hop = (test_btn << 28) | (disc << 16) | counter1
            for name_k, mfg_key in known_keys.items():
                man = normal_learning(fix, mfg_key)
                encrypted = keeloq_encrypt(test_hop, man)
                if encrypted == hop:
                    print(f"\n[!!!] MATCH: {name_k} btn={test_btn} (Normal)")
                    print(f"    Encrypted: 0x{encrypted:08x}")

if __name__ == "__main__":
    main()
