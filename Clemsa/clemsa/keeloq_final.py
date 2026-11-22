#!/usr/bin/env python3
"""
Keeloq - FINAL CORRECTED TEST
F1 (btn=4): serial=0x04803EB3, disc=53, ctr=950
F2 (btn=2): serial=0x04803F36, disc=53, ctr=11

Try ALL known keys, ALL learning types, BOTH disc formats
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

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    # Corrected values
    fix1 = 0x44803EB3  # btn=4, serial=0x04803EB3
    hop1 = 0x468BD70B
    fix2 = 0x24803F36  # btn=2, serial=0x04803F36
    hop2 = 0xA5634E40
    
    disc = 53
    ctr1 = 950
    ctr2 = 11
    
    ser1 = fix1 & 0x0FFFFFFF  # 0x04803EB3
    ser2 = fix2 & 0x0FFFFFFF  # 0x04803F36
    
    # Expected plaintexts
    # Standard disc format
    exp1_std = (4 << 28) | (disc << 16) | ctr1  # 0x403503B6
    exp2_std = (2 << 28) | (disc << 16) | ctr2  # 0x2035000B
    
    # 12-bit serial disc format (Clemsa)
    exp1_12 = (4 << 28) | ((ser1 & 0xFFF) << 16) | ctr1  # 0x4EB303B6
    exp2_12 = (2 << 28) | ((ser2 & 0xFFF) << 16) | ctr2  # 0x2F36000B
    
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
    
    print(f"Expected hop1 (std disc): 0x{exp1_std:08x}")
    print(f"Expected hop2 (std disc): 0x{exp2_std:08x}")
    print(f"Expected hop1 (12bit):    0x{exp1_12:08x}")
    print(f"Expected hop2 (12bit):    0x{exp2_12:08x}")
    print(f"Actual hop1:              0x{hop1:08x}")
    print(f"Actual hop2:              0x{hop2:08x}")
    print()
    
    found = False
    for mfg_name, mfg_key in sorted(known_keys.items()):
        for rev in [False, True]:
            key = reverse_bits(mfg_key, 64) if rev else mfg_key
            rev_str = " (rev)" if rev else ""
            
            # Try Normal Learning
            dk1 = normal_learning(fix1, key)
            dk2 = normal_learning(fix2, key)
            
            for exp_name, exp1, exp2 in [
                ("std", exp1_std, exp2_std),
                ("12bit", exp1_12, exp2_12),
            ]:
                enc1 = keeloq_encrypt(exp1, dk1)
                enc2 = keeloq_encrypt(exp2, dk2)
                
                if enc1 == hop1 and enc2 == hop2:
                    print(f"\n[!!!] FULL MATCH: {mfg_name}{rev_str} Normal({exp_name})")
                    print(f"      F1: enc=0x{enc1:08x}==0x{hop1:08x}  F2: enc=0x{enc2:08x}==0x{hop2:08x}")
                    print(f"      Key: 0x{key:016x}")
                    print(f"      DK1: 0x{dk1:016x}  DK2: 0x{dk2:016x}")
                    found = True
                
                if enc1 == hop1:
                    print(f"  F1 match: {mfg_name}{rev_str} Normal({exp_name}) enc=0x{enc1:08x}")
                if enc2 == hop2:
                    print(f"  F2 match: {mfg_name}{rev_str} Normal({exp_name}) enc=0x{enc2:08x}")
            
            # Try Simple Learning
            for exp_name, exp1, exp2 in [
                ("std", exp1_std, exp2_std),
                ("12bit", exp1_12, exp2_12),
            ]:
                enc1 = keeloq_encrypt(exp1, key)
                enc2 = keeloq_encrypt(exp2, key)
                
                if enc1 == hop1 and enc2 == hop2:
                    print(f"\n[!!!] FULL MATCH: {mfg_name}{rev_str} Simple({exp_name})")
                    print(f"      F1: enc=0x{enc1:08x}==0x{hop1:08x}  F2: enc=0x{enc2:08x}==0x{hop2:08x}")
                    print(f"      Key: 0x{key:016x}")
                    found = True
                
                if enc1 == hop1:
                    print(f"  F1 match: {mfg_name}{rev_str} Simple({exp_name}) enc=0x{enc1:08x}")
                if enc2 == hop2:
                    print(f"  F2 match: {mfg_name}{rev_str} Simple({exp_name}) enc=0x{enc2:08x}")
    
    if not found:
        print("\nNo full match found with any known key.")
        print("The Clemsa key in the Flipper database may be encrypted/wrong,")
        print("or this centralita uses a different key not in any public database.")

if __name__ == "__main__":
    main()
