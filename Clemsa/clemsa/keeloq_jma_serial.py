#!/usr/bin/env python3
"""
Keeloq - Try JMA M-BT serial interpretation.
Also try ALL manufacturer keys with Simple learning.
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
    
    clemsa_key = 0xE2B414B88AE7BC5E
    
    # JMA displays "0480 16051" - try different interpretations
    serial_options = [
        0x02DCAAB3,  # 48016051 decimal
        0x02DC6E83,  # from context (but this = 48000643)
        0x04803EB3,  # 0480 as hex prefix + 16051 decimal
        0x04803F36,  # same pattern for frame 2
        0x0003EB3,   # just 16051 decimal = 0x3EB3, zero-extended
        0x0003F36,   # just 16182 decimal for frame 2
    ]
    
    print("Frame data analysis:")
    print(f"Frame 1: {hex(frame1)}")
    print(f"Frame 2: {hex(frame2)}")
    print()
    
    # Direct interpretation
    fix1 = (frame1 >> 32) & 0xFFFFFFFF
    hop1 = frame1 & 0xFFFFFFFF
    fix2 = (frame2 >> 32) & 0xFFFFFFFF
    hop2 = frame2 & 0xFFFFFFFF
    
    print(f"Direct: Fix1=0x{fix1:08x} Hop1=0x{hop1:08x}")
    print(f"Direct: Fix2=0x{fix2:08x} Hop2=0x{hop2:08x}")
    print()
    
    # Check if the lower 16 bits of fix match JMA serial
    print("Checking lower 16 bits of fix vs JMA serial 16051 (0x3EB3):")
    print(f"  Fix1 lower 16: 0x{fix1 & 0xFFFF:04x} ({fix1 & 0xFFFF}) {'MATCH' if (fix1 & 0xFFFF) == 0x3EB3 else ''}")
    print(f"  Fix2 lower 16: 0x{fix2 & 0xFFFF:04x} ({fix2 & 0xFFFF}) {'MATCH' if (fix2 & 0xFFFF) == 0x3EB3 else ''}")
    print()
    
    # Try Simple Learning (type 1) with Clemsa key
    print("=" * 70)
    print("Simple Learning with Clemsa key (hop encrypted with mfg key)")
    print("=" * 70)
    
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        hop = frame & 0xFFFFFFFF
        fix = (frame >> 32) & 0xFFFFFFFF
        
        # Simple learning: device_key = decrypt(hop, mfg_key)
        dk = keeloq_decrypt(hop, clemsa_key)
        # Then decrypt hop with device_key
        dec = keeloq_decrypt(hop, dk)
        
        btn = (dec >> 28) & 0x0F
        disc = (dec >> 16) & 0xFF
        ctr = dec & 0xFFFF
        
        print(f"  {name}: DK=0x{dk:016x}")
        print(f"       Dec: 0x{dec:08x} btn={btn} disc={disc} ctr={ctr}")
        
        # Also try: first hop encrypted with mfg key directly
        dec_direct = keeloq_decrypt(hop, clemsa_key)
        btn_d = (dec_direct >> 28) & 0x0F
        disc_d = (dec_direct >> 16) & 0xFF
        ctr_d = dec_direct & 0xFFFF
        print(f"       Direct decrypt: 0x{dec_direct:08x} btn={btn_d} disc={disc_d} ctr={ctr_d}")
    
    print()
    
    # Try ALL manufacturer keys with BOTH normal and simple learning
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
        "JCM_Tech": 0x89146E59537903B7,
        "Comunello": 0xF1A3E552C8647E55,
    }
    
    print("=" * 70)
    print("ALL KEYS - Simple Learning (hop = encrypt(plain, mfg_key))")
    print("=" * 70)
    
    for mfg_name, mfg_key in sorted(known_keys.items()):
        for name, frame in [("F1", frame1), ("F2", frame2)]:
            hop = frame & 0xFFFFFFFF
            
            # Try: plain decrypt of hop with mfg key
            dec = keeloq_decrypt(hop, mfg_key)
            btn = (dec >> 28) & 0x0F
            disc = (dec >> 16) & 0xFF
            ctr = dec & 0xFFFF
            
            # Check if any field matches known values
            if (btn == 2 or disc == 53 or ctr == 950 or ctr == 951 or
                disc == 0x35):
                print(f"  {mfg_name} {name}: dec=0x{dec:08x} btn={btn} disc={disc} ctr={ctr}")
    
    print()
    print("=" * 70)
    print("Try encrypting known plaintext with ALL keys (both normal and simple)")
    print("=" * 70)
    
    known_btn = 2
    known_disc = 53
    known_ctr = 950
    
    plaintext = (known_btn << 28) | (known_disc << 16) | known_ctr
    print(f"Expected plaintext: 0x{plaintext:08x}")
    
    for mfg_name, mfg_key in sorted(known_keys.items()):
        # Normal learning with each interpretation
        for iname, frame in [("direct_F1", frame1), ("direct_F2", frame2),
                              ("bitrev_F1", reverse_bits(frame1, 64)),
                              ("bitrev_F2", reverse_bits(frame2, 64))]:
            fix = (frame >> 32) & 0xFFFFFFFF
            hop = frame & 0xFFFFFFFF
            
            dk = normal_learning(fix, mfg_key)
            enc = keeloq_encrypt(plaintext, dk)
            
            if enc == hop:
                print(f"  [!!!] MATCH: {mfg_name} {iname} Normal learning!")
                print(f"        Encrypted: 0x{enc:08x} == Hop: 0x{hop:08x}")
        
        # Simple learning: dk = decrypt(hop, mfg_key), then encrypt(plain, dk) should equal hop
        # Actually in simple learning, the FIRST transmission is encrypted with mfg_key directly
        for iname, frame in [("direct_F1", frame1), ("direct_F2", frame2),
                              ("bitrev_F1", reverse_bits(frame1, 64)),
                              ("bitrev_F2", reverse_bits(frame2, 64))]:
            hop = frame & 0xFFFFFFFF
            enc = keeloq_encrypt(plaintext, mfg_key)
            
            if enc == hop:
                print(f"  [!!!] MATCH: {mfg_name} {iname} Simple learning (direct)!")
                print(f"        Encrypted: 0x{enc:08x} == Hop: 0x{hop:08x}")
        
        # Try reversed key
        rev_key = reverse_bits(mfg_key, 64)
        for iname, frame in [("direct_F1", frame1), ("direct_F2", frame2)]:
            fix = (frame >> 32) & 0xFFFFFFFF
            hop = frame & 0xFFFFFFFF
            
            dk = normal_learning(fix, rev_key)
            enc = keeloq_encrypt(plaintext, dk)
            
            if enc == hop:
                print(f"  [!!!] MATCH: {mfg_name} {iname} Normal learning (reversed key)!")
                print(f"        Encrypted: 0x{enc:08x} == Hop: 0x{hop:08x}")
            
            enc_s = keeloq_encrypt(plaintext, rev_key)
            if enc_s == hop:
                print(f"  [!!!] MATCH: {mfg_name} {iname} Simple learning (reversed key)!")
                print(f"        Encrypted: 0x{enc_s:08x} == Hop: 0x{hop:08x}")

if __name__ == "__main__":
    main()
