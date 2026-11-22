from cc1101 import CC1101
import time

try:
    from neopixel import NeoPixel
    np = NeoPixel(__import__("machine").Pin(16), 1)
except Exception:
    np = None


def led(r, g, b):
    if np is not None:
        np[0] = (r, g, b)
        np.write()


radio = CC1101()
print("Inicializando CC1101...")
if not radio.init():
    print("ERROR: no se detecta el CC1101. Revisa el cableado.")
    led(255,0,0)
    raise SystemExit(1)
print("CC1101 OK  Estado=%s" % radio.state_name())
print("Escuchando en 868.3 MHz...")

radio.enter_rx()
while True:
    data = radio.receive_packet()
    if data is not None:
        hexstr = " ".join("%02X" % b for b in data)
        print("RX %d bytes | %s | RSSI=%d dBm  LQI=%d" %
              (len(data), hexstr, radio.read_rssi_dbm(), radio.read_lqi()))
        led(0, 50, 0)
        time.sleep_ms(50)
        led(0, 0, 0)
    time.sleep_ms(5)
