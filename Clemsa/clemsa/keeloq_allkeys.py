#!/usr/bin/env python3
"""
Keeloq - Try ALL known manufacturer keys with ALL interpretations.
Also try reverse_key variants.
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
    k1 = keeloq_decrypt(data | 0x20000000, key)
    k2 = keeloq_decrypt(data | 0x60000000, key)
    return (k2 << 32) | k1

def simple_learning(hop, key):
    return keeloq_decrypt(hop, key)

def reverse_key_64(key):
    return reverse_bits(key, 64)

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    known_keys = {
        "FAAC_RC,XT": 0xFAAC05600001FAAC,
        "FAAC_29bit": 0xFAAC05600002FAAC,
        "Clemsa_Mutancode": 0xE2B414B88AE7BC5E,
        "BFT": 0x4C6D4D7A55644F76,
        "NICE_Smilo": 0x54524D534543494E,
        "NICE_FLO": 0x54524D534543494E,
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
        "Chamberlain": 0x31D02AE5,
        "Chamberlain_61": 0x6133613361336133,
        "Linear": 0x4C494E454152445F,
        "LiftMaster": 0x4D41534741524533,
        "Marantec": 0x4D4152414E544543,
        "Soma": 0x534F4D415F534D41,
    }
    
    # Frame interpretations
    def nibrev(x):
        result = 0
        for i in range(8):
            b = (x >> (i * 8)) & 0xFF
            rb = 0
            for j in range(8):
                rb = (rb << 1) | ((b >> j) & 1)
            result |= (rb << (i * 8))
        return result
    
    frame_interps = {
        "direct": (frame1, frame2),
        "bitrev": (reverse_bits(frame1, 64), reverse_bits(frame2, 64)),
        "byterev": (reverse_bytes(frame1), reverse_bytes(frame2)),
        "nibrev": (nibrev(frame1), nibrev(frame2)),
        "swap": (((frame1 & 0xFFFFFFFF) << 32) | ((frame1 >> 32) & 0xFFFFFFFF),
                  ((frame2 & 0xFFFFFFFF) << 32) | ((frame2 >> 32) & 0xFFFFFFFF)),
    }
    
    results = []
    
    for mfg_name, mfg_key in sorted(known_keys.items()):
        # Try normal key and reversed key
        for key_name, key in [("normal", mfg_key), ("reversed", reverse_key_64(mfg_key))]:
            for iname, (f1, f2) in frame_interps.items():
                for lt_name, lt_func in [("normal", normal_learning), ("simple", simple_learning)]:
                    
                    if lt_name == "normal":
                        dk1 = lt_func((f1 >> 32) & 0xFFFFFFFF, key)
                        dk2 = lt_func((f2 >> 32) & 0xFFFFFFFF, key)
                    else:
                        dk1 = lt_func(f1 & 0xFFFFFFFF, key)
                        dk2 = lt_func(f2 & 0xFFFFFFFF, key)
                    
                    hop1 = f1 & 0xFFFFFFFF
                    hop2 = f2 & 0xFFFFFFFF
                    
                    dec1 = keeloq_decrypt(hop1, dk1)
                    dec2 = keeloq_decrypt(hop2, dk2)
                    
                    btn1 = (dec1 >> 28) & 0x0F
                    disc1 = (dec1 >> 16) & 0xFF
                    ctr1 = dec1 & 0xFFFF
                    ser1 = ((f1 >> 32) & 0xFFFFFFFF) & 0x0FFFFFFF
                    
                    btn2 = (dec2 >> 28) & 0x0F
                    disc2 = (dec2 >> 16) & 0xFF
                    ctr2 = dec2 & 0xFFFF
                    ser2 = ((f2 >> 32) & 0xFFFFFFFF) & 0x0FFFFFFF
                    
                    # Score: how many fields match known values
                    score = 0
                    if btn1 == btn2: score += 1
                    if ser1 == ser2: score += 2
                    if ctr1 < 10000: score += 1
                    if ctr2 < 10000: score += 1
                    if ctr1 == ctr2 - 1: score += 2  # consecutive counters
                    if disc1 == disc2: score += 1
                    
                    # Known values
                    if btn1 == 2 or btn2 == 2: score += 2
                    if disc1 == 53 or disc2 == 53: score += 3
                    if ctr1 == 950 or ctr2 == 950: score += 3
                    if ser1 == 0x02DC6E83 or ser2 == 0x02DC6E83: score += 3
                    
                    if score >= 5:
                        results.append((score, mfg_name, key_name, iname, lt_name,
                                       btn1, disc1, ctr1, ser1, btn2, disc2, ctr2, ser2))
    
    if results:
        results.sort(reverse=True)
        print("TOP RESULTS (score >= 5):")
        print("=" * 90)
        for score, mk, kn, fn, lt, b1, d1, c1, s1, b2, d2, c2, s2 in results[:30]:
            print(f"  Score={score:2d} | {mk:20s} key={kn:8s} interp={fn:8s} learn={lt:8s}")
            print(f"         F1: btn={b1} disc={d1} ctr={c1} serial=0x{s1:07x}")
            print(f"         F2: btn={b2} disc={d2} ctr={c2} serial=0x{s2:07x}")
    else:
        print("No results with score >= 5")
        
        # Show top 10 anyway
        results.sort(reverse=True)
        print("\nTOP 10 results:")
        for score, mk, kn, fn, lt, b1, d1, c1, s1, b2, d2, c2, s2 in results[:10]:
            print(f"  Score={score} | {mk} key={kn} interp={fn} learn={lt}")
            print(f"    F1: btn={b1} disc={d1} ctr={c1} serial=0x{s1:07x}")
            print(f"    F2: btn={b2} disc={d2} ctr={c2} serial=0x{s2:07x}")

if __name__ == "__main__":
    main()
