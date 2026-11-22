#!/usr/bin/env python3
"""
Keeloq - Verify serial and find manufacturer key
"""

KEELOQ_NLF = 0x3A5C742E

def bit(x, n):
    return (x >> n) & 1

def g5(x, a, b, c, d, e):
    return bit(x, a) + bit(x, b) * 2 + bit(x, c) * 4 + bit(x, d) * 8 + bit(x, e) * 16

def keeloq_decrypt(data, key):
    x = data
    for r in range(528):
        x = ((x << 1) ^ bit(x, 31) ^ bit(x, 15) ^
             bit(key, (15 - r) & 63) ^
             bit(KEELOQ_NLF, g5(x, 0, 8, 19, 25, 30))) & 0xFFFFFFFF
    return x

def keeloq_encrypt(data, key):
    x = data
    for r in range(528):
        x = (x >> 1) ^ ((bit(x, 0) ^ bit(x, 16) ^ bit(key, r & 63) ^
                         bit(KEELOQ_NLF, g5(x, 1, 9, 20, 26, 31))) << 31)
    return x & 0xFFFFFFFF

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
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    
    disc = 0x35
    counter = 950  # 0x03B6
    
    print("Analysis of frame structure")
    print("=" * 60)
    
    # Parse frame 1 directly
    print("\nFrame 1: 44803eb3468bd70b")
    print(f"  Byte 0: 0x{(frame1>>56)&0xFF:02x} = {(frame1>>56)&0xFF:08b}")
    print(f"  Byte 1: 0x{(frame1>>48)&0xFF:02x} = {(frame1>>48)&0xFF:08b}")
    print(f"  Byte 2: 0x{(frame1>>40)&0xFF:02x} = {(frame1>>40)&0xFF:08b}")
    print(f"  Byte 3: 0x{(frame1>>32)&0xFF:02x} = {(frame1>>32)&0xFF:08b}")
    
    # The user said serial is 0480 16051
    # 16051 decimal = 0x3EB3
    # 0480 decimal = 0x01E0
    # So the full serial might be 0x01E03EB3 or similar
    
    serial_from_user = 48016051  # decimal
    serial_hex = serial_from_user & 0x0FFFFFFF
    
    print(f"\nUser's serial: {serial_from_user} = 0x{serial_hex:07x}")
    print(f"  0480 = 0x{480:04x}")
    print(f"  16051 = 0x{16051:04x}")
    
    # Check if 16051 (0x3EB3) appears in frame
    print(f"\n0x3EB3 in frame 1: {hex(0x3EB3)}")
    print(f"Frame 1 bytes: 44 80 3e b3 46 8b d7 0b")
    print(f"                ^^    ^^^^")
    print(f"                44    3eb3  <- This matches!")
    
    # Try interpretation: frame is NOT bit-reversed
    # Structure: [discriminator(8)][serial(28)][hop(32)]  <- no, this doesn't fit
    
    # Try: frame structure is [button(4)][discriminator(8)][serial(20?)][hop(32)]
    # But that's only 64 bits total
    
    # Actually, looking at the bytes:
    # 44 80 3e b3 46 8b d7 0b
    # The serial 048016051 might be split across the frame
    
    # Let me try: the "serial" the user has might be from the receiver's memory
    # not from the RF frame directly
    
    # In standard Keeloq:
    # Fix = button(4) + serial(28)
    # Hop = encrypted(counter(16) + discriminator(8) + button(4))
    
    # Expected decrypted hop:
    expected_hop = (disc << 16) | counter
    print(f"\nExpected decrypted hop (without button): 0x{expected_hop:08x}")
    
    # Try with button values from frame
    for btn in range(16):
        expected_full = (btn << 28) | expected_hop
        print(f"  If button={btn}: expected decrypt = 0x{expected_full:08x}")
    
    # Now try to find manufacturer key
    # We need: keeloq_decrypt(hop_encrypted, device_key) = expected_decrypted
    
    # Let's try direct interpretation (no bit reversal)
    hop1_direct = frame1 & 0xFFFFFFFF
    fix1_direct = (frame1 >> 32) & 0xFFFFFFFF
    
    print(f"\nDirect interpretation:")
    print(f"  Fix1: 0x{fix1_direct:08x}")
    print(f"  Hop1: 0x{hop1_direct:08x}")
    print(f"  Serial from fix: {fix1_direct & 0x0FFFFFFF} (0x{fix1_direct & 0x0FFFFFFF:07x})")
    
    # Check if 0x3EB3 is in the fix
    if (fix1_direct & 0xFFFF) == 0x3EB3:
        print(f"  ✓ Lower 16 bits of fix match 0x3EB3!")
    
    # Try the approach: iterate possible manufacturer keys
    # This is too slow for full 64-bit keys, but let's try known ones
    
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
    
    print(f"\nTrying known manufacturer keys with direct interpretation...")
    print("=" * 60)
    
    for name, mfg_key in known_keys.items():
        # Try Normal Learning
        man = normal_learning(fix1_direct, mfg_key)
        decrypt = keeloq_decrypt(hop1_direct, man)
        
        dec_btn = (decrypt >> 28) & 0x0F
        dec_disc = (decrypt >> 16) & 0xFF
        dec_cnt = decrypt & 0xFFFF
        
        if dec_disc == disc or dec_disc == 0:
            print(f"\n[+] {name} (Normal Learning)")
            print(f"    Decrypt: 0x{decrypt:08x}")
            print(f"    Button: {dec_btn}, Disc: {dec_disc}, Counter: {dec_cnt}")
        
        # Try Simple Learning
        decrypt_s = keeloq_decrypt(hop1_direct, mfg_key)
        dec_disc_s = (decrypt_s >> 16) & 0xFF
        if dec_disc_s == disc or dec_disc_s == 0:
            print(f"\n[+] {name} (Simple Learning)")
            print(f"    Decrypt: 0x{decrypt_s:08x}")
            print(f"    Button: {(decrypt_s>>28)&0x0F}, Disc: {dec_disc_s}, Counter: {decrypt_s&0xFFFF}")

    # Try with bit reversal
    print(f"\n\nTrying with bit reversal...")
    print("=" * 60)
    
    frame1_rev = reverse_key(frame1, 64)
    hop1_rev = frame1_rev & 0xFFFFFFFF
    fix1_rev = (frame1_rev >> 32) & 0xFFFFFFFF
    
    print(f"  Reversed Fix: 0x{fix1_rev:08x}")
    print(f"  Reversed Hop: 0x{hop1_rev:08x}")
    
    for name, mfg_key in known_keys.items():
        man = normal_learning(fix1_rev, mfg_key)
        decrypt = keeloq_decrypt(hop1_rev, man)
        
        dec_disc = (decrypt >> 16) & 0xFF
        if dec_disc == disc or dec_disc == 0:
            print(f"\n[+] {name} (Normal Learning, reversed)")
            print(f"    Decrypt: 0x{decrypt:08x}")
            print(f"    Button: {(decrypt>>28)&0x0F}, Disc: {dec_disc}, Counter: {decrypt&0xFFFF}")
        
        decrypt_s = keeloq_decrypt(hop1_rev, mfg_key)
        dec_disc_s = (decrypt_s >> 16) & 0xFF
        if dec_disc_s == disc or dec_disc_s == 0:
            print(f"\n[+] {name} (Simple Learning, reversed)")
            print(f"    Decrypt: 0x{decrypt_s:08x}")
            print(f"    Button: {(decrypt_s>>28)&0x0F}, Disc: {dec_disc_s}, Counter: {decrypt_s&0xFFFF}")

if __name__ == "__main__":
    main()
