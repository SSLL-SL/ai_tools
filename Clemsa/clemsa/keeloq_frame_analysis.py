#!/usr/bin/env python3
"""
Keeloq Clemsa - Analyze frame structure.
Lower 16 bits of Fix1 = 0x3EB3 = 16051 (matches JMA serial part!)
This means the frame format is NOT standard KeeLoq.
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

def main():
    frame1 = 0x44803eb3468bd70b
    frame2 = 0x24803f36a5634e40
    clemsa_key = 0xE2B414B88AE7BC5E
    
    print("=" * 70)
    print("FRAME STRUCTURE ANALYSIS")
    print("=" * 70)
    
    # Byte-level comparison
    f1_bytes = frame1.to_bytes(8, 'big')
    f2_bytes = frame2.to_bytes(8, 'big')
    
    print("\nByte-by-byte comparison:")
    print("Byte | F1      | F2      | Diff")
    print("-" * 45)
    for i in range(8):
        d = f1_bytes[i] ^ f2_bytes[i]
        match = "SAME" if d == 0 else f"XOR=0x{d:02x}"
        print(f"  {i}  | 0x{f1_bytes[i]:02x}    | 0x{f2_bytes[i]:02x}    | {match}")
    
    # Key observations
    print("\nKey observations:")
    print(f"  Byte 1: both 0x80 (constant)")
    print(f"  Byte 2: 0x3e vs 0x3f (differs by 1)")
    print(f"  Byte 0: 0x44 vs 0x24 (button? 4 vs 2)")
    
    # Lower 16 bits of each half
    fix1 = (frame1 >> 32) & 0xFFFFFFFF
    hop1 = frame1 & 0xFFFFFFFF
    fix2 = (frame2 >> 32) & 0xFFFFFFFF
    hop2 = frame2 & 0xFFFFFFFF
    
    print(f"\n  Fix1 lower 16: 0x{fix1 & 0xFFFF:04x} ({fix1 & 0xFFFF}) = JMA serial 16051? YES!")
    print(f"  Fix2 lower 16: 0x{fix2 & 0xFFFF:04x} ({fix2 & 0xFFFF})")
    print(f"  Difference: {(fix2 & 0xFFFF) - (fix1 & 0xFFFF)}")
    
    # Try different frame split points
    print("\n" + "=" * 70)
    print("TRYING DIFFERENT FRAME SPLITS")
    print("=" * 70)
    
    # Try: byte 0 = button, bytes 1-7 = encrypted
    print("\n--- Split: byte0=button, bytes1-7=encrypted (56 bits) ---")
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        b = frame.to_bytes(8, 'big')
        btn_byte = b[0]
        enc = int.from_bytes(b[1:8], 'big')
        print(f"  {name}: btn_byte=0x{btn_byte:02x} enc=0x{enc:014x}")
        # Try decrypt with clemsa key directly
        dec = keeloq_decrypt(enc >> 24, clemsa_key)  # Only 32 bits can be decrypted
        print(f"         dec32=0x{dec:08x}")
    
    # Try: the entire frame is encrypted with clemsa key as 2x32-bit blocks
    print("\n--- Split: fix=encrypt(block0), hop=encrypt(block1) ---")
    print("    (decrypt both halves with clemsa key directly)")
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        fix = (frame >> 32) & 0xFFFFFFFF
        hop = frame & 0xFFFFFFFF
        dec_fix = keeloq_decrypt(fix, clemsa_key)
        dec_hop = keeloq_decrypt(hop, clemsa_key)
        print(f"  {name}:")
        print(f"    Fix:  0x{fix:08x} -> 0x{dec_fix:08x}")
        print(f"    Hop:  0x{hop:08x} -> 0x{dec_hop:08x}")
        print(f"    dec_fix: btn={(dec_fix>>28)&0xF} serial=0x{dec_fix&0x0FFFFFFF:07x}")
        print(f"    dec_hop: btn={(dec_hop>>28)&0xF} disc={(dec_hop>>16)&0xFF} ctr={dec_hop&0xFFFF}")
    
    # Try: bytes 0-1 = header, bytes 2-5 = encrypted, bytes 6-7 = something
    print("\n--- Various split attempts ---")
    for split in [2, 3, 4, 5, 6]:
        for name, frame in [("F1", frame1), ("F2", frame2)]:
            b = frame.to_bytes(8, 'big')
            header = int.from_bytes(b[:split], 'big')
            enc = int.from_bytes(b[split:split+4], 'big') if split+4 <= 8 else 0
            remaining = int.from_bytes(b[split+4:], 'big') if split+4 < 8 else 0
            
        # Just show the split
        pass
    
    # Most promising: try byte 0 = button, bytes 1 = 0x80 constant, bytes 2-3 = serial, bytes 4-7 = hop
    print("\n--- Format: [button:1][0x80:1][serial:2][hop:4] ---")
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        b = frame.to_bytes(8, 'big')
        btn_nibble = (b[0] >> 4) & 0x0F
        flags = b[0] & 0x0F
        constant = b[1]
        serial16 = int.from_bytes(b[2:4], 'big')
        hop32 = int.from_bytes(b[4:8], 'big')
        
        print(f"  {name}: btn={btn_nibble} flags=0x{flags:01x} const=0x{constant:02x} serial16=0x{serial16:04x}({serial16}) hop=0x{hop32:08x}")
    
    # Try: button in lower nibble
    print("\n--- Format: [flags:1][button:1][0x80:1][serial:2][hop:3] ---")
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        b = frame.to_bytes(8, 'big')
        flags = (b[0] >> 4) & 0x0F
        btn_nibble = b[0] & 0x0F
        constant = b[1]
        serial16 = int.from_bytes(b[2:4], 'big')
        remaining = int.from_bytes(b[4:], 'big')
        
        print(f"  {name}: flags=0x{flags:01x} btn={btn_nibble} const=0x{constant:02x} serial16=0x{serial16:04x}({serial16}) rem=0x{remaining:08x}")
    
    # With button=2 (lower nibble), both frames have button=4
    # With button=2 (upper nibble), F2 has button=2 but F1 has button=4
    # What if byte0 encodes differently?
    # 0x44 = 0100 0100, 0x24 = 0010 0100
    # XOR = 0110 0000 = 0x60
    # If button 2 = 0010 xxxx, then F2 matches
    # If button 4 = 0100 xxxx, then F1 matches
    # This suggests different buttons were pressed!
    
    print("\n--- If upper nibble = button: F1=btn4, F2=btn2 ---")
    print("    These could be two different button presses!")
    print("    User might have pressed btn4 THEN btn2")
    
    # Let's check: with button=4 for F1 and button=2 for F2,
    # does the serial match?
    # F1: fix=0x44803EB3, serial=0x4803EB3
    # F2: fix=0x24803F36, serial=0x4803F36
    # Serials differ: 0x4803EB3 vs 0x4803F36
    # Difference in lower 12 bits: 0xEB3 vs 0xF36 = 0x83 = 131
    # These lower 12 bits ARE the discriminator in Clemsa!
    # 0xEB3 = 3763, 0xF36 = 3894
    # Discriminator should be the same... unless it's NOT the discriminator
    
    print("\n--- Standard KeeLoq interpretation ---")
    print("  F1: fix=0x44803EB3 -> btn=4 serial=0x4803EB3")
    print("  F2: fix=0x24803F36 -> btn=2 serial=0x4803F36")
    print("  Serials differ! Lower 12 bits: 0xEB3 vs 0xF36 (diff=0x83=131)")
    print("  This suggests the lower 12 bits are NOT part of the serial")
    print("  They might be the COUNTER or another field!")
    
    # What if the fixed part is: [button:4][constant:8][counter_or_serial:20]
    # Or: [button:4][counter:8][serial:20]
    # F1: btn=4, field=0x803E, serial=0xB3 (8 bits only - too small)
    
    # What about: bytes 0-1 are one field, bytes 2-3 are another
    # F1: 0x4480, 0x3EB3
    # F2: 0x2480, 0x3F36
    # Bytes 1 are same (0x80), bytes 2 differ by 1 (0x3E vs 0x3F)
    # This is very suggestive of: byte0=button, byte1=constant, byte2=counter_high, byte3=counter_low
    
    print("\n--- Format: [button:4][constant:4][counter:8][counter_low:8][enc:32] ---")
    for name, frame in [("F1", frame1), ("F2", frame2)]:
        b = frame.to_bytes(8, 'big')
        btn = (b[0] >> 4) & 0x0F
        const_low = b[0] & 0x0F
        const = b[1]
        ctr_high = b[2]
        ctr_low = b[3]
        enc = int.from_bytes(b[4:8], 'big')
        
        print(f"  {name}: btn={btn} const_low=0x{const_low:01x} const=0x{const:02x} ctr=0x{ctr_high:02x}{ctr_low:02x}({ctr_high*256+ctr_low}) enc=0x{enc:08x}")
    
    # F1 counter: 0x3EB3 = 16051
    # F2 counter: 0x3F36 = 16182
    # Diff: 131
    # User says counter = 950... not matching
    
    # What if bytes 2-3 are NOT counter but serial?
    # F1 serial: 0x3EB3 = 16051
    # F2 serial: 0x3F36 = 16182
    # But serial should be the same!
    
    # Unless... these ARE the serial and they're DIFFERENT because
    # JMA M-BT generates different serials for each button!
    # User pressed btn4 (F1) and btn2 (F2) - different buttons, different serials?
    
    print("\n" + "=" * 70)
    print("HYPOTHESIS: JMA M-BT assigns different serials per button")
    print("=" * 70)
    print("  F1 (btn=4): serial = 0x3EB3 = 16051")
    print("  F2 (btn=2): serial = 0x3F36 = 16182")
    print("  JMA displays serial for the LAST button pressed (btn2)")
    print("  '0480 16051' might be the FULL 28-bit serial for btn4")

if __name__ == "__main__":
    main()
