#!/usr/bin/env python3
"""
Keeloq Clemsa Mutancode - CORRECTED VALUES
Frame 1 (btn=4): serial 0480 16051, counter=950, disc=53
Frame 2 (btn=2): serial 0480 16182, counter=11, disc=53
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
    k1 = keeloq_decrypt(data | 0x20000000, key)
    k2 = keeloq_decrypt(data | 0x60000000, key)
    return (k2 << 32) | k1

def simple_learning(hop, key):
    return keeloq_decrypt(hop, key)

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    clemsa_key = 0xE2B414B88AE7BC5E
    
    # CORRECTED values from user
    # Frame 1 (button 4)
    ser1 = 0x04803EB3  # 0480 16051
    btn1 = 4
    disc = 53  # 0x35
    ctr1 = 950  # 0x03B6
    
    # Frame 2 (button 2)
    ser2 = 0x04803F36  # 0480 16182
    btn2 = 2
    ctr2 = 11  # 0x000B
    
    print("=" * 70)
    print("CORRECTED VALUES")
    print("=" * 70)
    print(f"Frame 1: btn={btn1} serial=0x{ser1:08x} disc={disc} ctr={ctr1}")
    print(f"Frame 2: btn={btn2} serial=0x{ser2:08x} disc={disc} ctr={ctr2}")
    print()
    
    # Expected decrypted hops
    # Standard KeeLoq: hop = btn<<28 | disc<<16 | ctr
    exp1 = (btn1 << 28) | (disc << 16) | ctr1
    exp2 = (btn2 << 28) | (disc << 16) | ctr2
    print(f"Expected hop 1 (standard): 0x{exp1:08x}")
    print(f"Expected hop 2 (standard): 0x{exp2:08x}")
    print()
    
    # Clemsa Mutancode: hop = btn<<28 | (serial & 0xFFF)<<16 | ctr
    exp1_clemsa = (btn1 << 28) | ((ser1 & 0xFFF) << 16) | ctr1
    exp2_clemsa = (btn2 << 28) | ((ser2 & 0xFFF) << 16) | ctr2
    print(f"Expected hop 1 (Clemsa 12bit): 0x{exp1_clemsa:08x}")
    print(f"Expected hop 2 (Clemsa 12bit): 0x{exp2_clemsa:08x}")
    print()
    
    # Try with Clemsa key - Normal Learning
    print("=" * 70)
    print("CLEMSA KEY - Normal Learning")
    print("=" * 70)
    
    for name, frame, ser, btn, exp, exp_c in [
        ("F1", frame1, ser1, btn1, exp1, exp1_clemsa),
        ("F2", frame2, ser2, btn2, exp2, exp2_clemsa),
    ]:
        fix = (frame >> 32) & 0xFFFFFFFF
        hop = frame & 0xFFFFFFFF
        
        dk = normal_learning(fix, clemsa_key)
        dec = keeloq_decrypt(hop, dk)
        
        print(f"\n{name}:")
        print(f"  Fix: 0x{fix:08x}  Hop: 0x{hop:08x}")
        print(f"  Serial from fix: 0x{fix & 0x0FFFFFFF:08x}")
        print(f"  Device Key: 0x{dk:016x}")
        print(f"  Decrypted: 0x{dec:08x}")
        print(f"  btn={(dec>>28)&0xF} disc={(dec>>16)&0xFF} ctr={dec&0xFFFF}")
        
        # Try encrypting expected values
        enc_std = keeloq_encrypt(exp, dk)
        enc_clemsa = keeloq_encrypt(exp_c, dk)
        
        print(f"  Encrypt(expected standard): 0x{enc_std:08x} {'MATCH!' if enc_std == hop else ''}")
        print(f"  Encrypt(expected clemsa):  0x{enc_clemsa:08x} {'MATCH!' if enc_clemsa == hop else ''}")
    
    # Also try with all manufacturer keys
    print("\n" + "=" * 70)
    print("ALL MANUFACTURER KEYS - Try encrypting expected plaintext")
    print("=" * 70)
    
    known_keys = {
        "Clemsa_Mutancode": 0xE2B414B88AE7BC5E,
        "FAAC_RC,XT": 0xFAAC05600001FAAC,
        "FAAC_29bit": 0xFAAC05600002FAAC,
        "BFT": 0x4C6D4D7A55644F76,
        "NICE_Smilo": 0x54524D534543494E,
        "Came_Space": 0x96638C36C99C2C9B,
        "DTM_Neo": 0xFC4DE22CD5370320,
        "Genius_Bravo": 0xFAAC05600002FAAC,
        "Sommer": 0x7BCBEED4376EDCBF,
        "Centurion": 0x188B0544A9B1DF14,
        "Monarch": 0x4292903083134583,
        "JCM_Tech": 0x89146E59537903B7,
        "Comunello": 0xF1A3E552C8647E55,
        "Cardin_S449": 0x207DBBE59D386F44,
        "Steelmate": 0xB3E5625A8CCD7139,
        "Motorline": 0x572768229476CAFF,
        "Normstahl": 0x9DA08153CF312BA7,
        "GSN": 0xA9748532B7655297,
    }
    
    for mfg_name, mfg_key in sorted(known_keys.items()):
        for rev in [False, True]:
            key = reverse_bits(mfg_key, 64) if rev else mfg_key
            rev_str = " (rev)" if rev else ""
            
            for name, frame, ser, btn, exp, exp_c in [
                ("F1", frame1, ser1, btn1, exp1, exp1_clemsa),
                ("F2", frame2, ser2, btn2, exp2, exp2_clemsa),
            ]:
                fix = (frame >> 32) & 0xFFFFFFFF
                hop = frame & 0xFFFFFFFF
                
                # Normal learning
                dk = normal_learning(fix, key)
                enc_std = keeloq_encrypt(exp, dk)
                enc_clemsa = keeloq_encrypt(exp_c, dk)
                
                if enc_std == hop:
                    print(f"\n  [!!!] MATCH: {mfg_name}{rev_str} {name} Normal(std)!")
                    print(f"        Key: 0x{key:016x} DK: 0x{dk:016x}")
                if enc_clemsa == hop:
                    print(f"\n  [!!!] MATCH: {mfg_name}{rev_str} {name} Normal(12bit)!")
                    print(f"        Key: 0x{key:016x} DK: 0x{dk:016x}")
                
                # Simple learning (hop encrypted with mfg key directly)
                enc_simple = keeloq_encrypt(exp, key)
                enc_simple_c = keeloq_encrypt(exp_c, key)
                
                if enc_simple == hop:
                    print(f"\n  [!!!] MATCH: {mfg_name}{rev_str} {name} Simple(std)!")
                    print(f"        Key: 0x{key:016x}")
                if enc_simple_c == hop:
                    print(f"\n  [!!!] MATCH: {mfg_name}{rev_str} {name} Simple(12bit)!")
                    print(f"        Key: 0x{key:016x}")
    
    # Also try with disc = low 12 bits of serial
    print("\n" + "=" * 70)
    print("Try disc = serial & 0xFFF (KeeLoq standard)")
    print("=" * 70)
    
    disc1_12 = ser1 & 0xFFF  # 0xEB3 = 3763
    disc2_12 = ser2 & 0xFFF  # 0xF36 = 3894
    
    exp1_12 = (btn1 << 28) | (disc1_12 << 16) | ctr1
    exp2_12 = (btn2 << 28) | (disc2_12 << 16) | ctr2
    
    print(f"F1: disc=0x{disc1_12:03x}({disc1_12}) expected=0x{exp1_12:08x}")
    print(f"F2: disc=0x{disc2_12:03x}({disc2_12}) expected=0x{exp2_12:08x}")
    
    for mfg_name, mfg_key in sorted(known_keys.items()):
        for name, frame, exp in [("F1", frame1, exp1_12), ("F2", frame2, exp2_12)]:
            fix = (frame >> 32) & 0xFFFFFFFF
            hop = frame & 0xFFFFFFFF
            dk = normal_learning(fix, mfg_key)
            enc = keeloq_encrypt(exp, dk)
            
            if enc == hop:
                print(f"\n  [!!!] MATCH: {mfg_name} {name} Normal(12bit disc)!")
                print(f"        Key: 0x{mfg_key:016x} DK: 0x{dk:016x}")

if __name__ == "__main__":
    main()
