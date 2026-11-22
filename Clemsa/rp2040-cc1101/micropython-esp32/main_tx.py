from cc1101 import CC1101
from machine import Pin
import struct
import time

led = Pin(2, Pin.OUT)

radio = CC1101()
print("Inicializando CC1101...")
if not radio.init():
    print("ERROR: no se detecta el CC1101. Revisa el cableado.")
    raise SystemExit(1)
print("CC1101 OK  Estado=%s" % radio.state_name())

count = 0
while True:
    pkt = b"\xAA\x55" + struct.pack(">I", count) + b"Hola"
    led.value(1)
    if radio.send_packet(pkt):
        print("TX #%d  %d bytes -> FIFO_TX=%d" %
              (count, len(pkt), radio.get_tx_fifo_bytes()))
    else:
        print("TX #%d  FALLO" % count)
    led.value(0)
    count += 1
    time.sleep_ms(2000)
