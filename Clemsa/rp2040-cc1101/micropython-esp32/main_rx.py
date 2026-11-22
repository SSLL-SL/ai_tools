from cc1101 import CC1101
from machine import Pin
import time

led = Pin(2, Pin.OUT)

radio = CC1101()
print("Inicializando CC1101...")
if not radio.init():
    print("ERROR: no se detecta el CC1101. Revisa el cableado.")
    raise SystemExit(1)
print("CC1101 OK  Estado=%s" % radio.state_name())
print("Escuchando en 433.92 MHz...")

radio.enter_rx()
while True:
    data = radio.receive_packet()
    if data is not None:
        hexstr = " ".join("%02X" % b for b in data)
        print("RX %d bytes | %s | RSSI=%d dBm  LQI=%d" %
              (len(data), hexstr, radio.read_rssi_dbm(), radio.read_lqi()))
        led.value(1)
        time.sleep_ms(50)
        led.value(0)
    time.sleep_ms(5)
