from machine import Pin, SPI
import time

# ----------------------------------------------------------------------
# Pines de conexion (RP2040-Zero, SPI0)
#   CC1101  |  RP2040-Zero
#   ------- |  ----------
#   SCK     |  GPIO 2
#   MOSI    |  GPIO 3
#   MISO    |  GPIO 0
#   CSn     |  GPIO 1
#   VCC     |  3V3
#   GND     |  GND
# ----------------------------------------------------------------------
SCK = 2
MOSI = 3
MISO = 0
CS = 1

# Registros de configuracion
IOCFG2 = 0x00
IOCFG1 = 0x01
IOCFG0 = 0x02
FIFOTHR = 0x03
SYNC1 = 0x04
SYNC0 = 0x05
PKTLEN = 0x06
PKTCTRL1 = 0x07
PKTCTRL0 = 0x08
ADDR = 0x09
CHANNR = 0x0A
FSCTRL1 = 0x0B
FSCTRL0 = 0x0C
FREQ2 = 0x0D
FREQ1 = 0x0E
FREQ0 = 0x0F
MDMCFG4 = 0x10
MDMCFG3 = 0x11
MDMCFG2 = 0x12
MDMCFG1 = 0x13
MDMCFG0 = 0x14
DEVIATN = 0x15
MCSM2 = 0x16
MCSM1 = 0x17
MCSM0 = 0x18
FOCCFG = 0x19
BSCFG = 0x1A
AGCCTRL2 = 0x1B
AGCCTRL1 = 0x1C
AGCCTRL0 = 0x1D
WOREVT1 = 0x1E
WOREVT0 = 0x1F
WORCTRL = 0x20
FREND1 = 0x21
FREND0 = 0x22
FSCAL3 = 0x23
FSCAL2 = 0x24
FSCAL1 = 0x25
FSCAL0 = 0x26
RCCTRL1 = 0x27
RCCTRL0 = 0x28
TEST2 = 0x2C
TEST1 = 0x2D
TEST0 = 0x2E

# Registros de estado
PARTNUM = 0x30
VERSION = 0x31
FREQEST = 0x32
LQI = 0x33
RSSI = 0x34
MARCSTATE = 0x35
PKTSTATUS = 0x38
TXBYTES = 0x3A
RXBYTES = 0x3B

# Comandos strobe
SRES = 0x30
SFSTXON = 0x31
SXOFF = 0x32
SCAL = 0x33
SRX = 0x34
STX = 0x35
SIDLE = 0x36
SWOR = 0x38
SPWD = 0x39
SFRX = 0x3A
SFTX = 0x3B

FIFO = 0x3F
PATABLE = 0x3E

READ = 0x80
BURST = 0x40

XTAL_HZ = 26000000
BASE_FREQ = 433920000

STATE_NAMES = {
    0x01: "IDLE",
    0x0D: "RX",
    0x1B: "TX",
    0x12: "FSTXON",
    0x10: "CALIBRATE",
    0x11: "SETTLING",
    0x16: "RX_OVERFLOW",
    0x25: "TX_UNDERFLOW",
}


class CC1101:
    def __init__(self, sck=SCK, mosi=MOSI, miso=MISO, cs=CS, baudrate=1000000):
        self.cs = Pin(cs, Pin.OUT, value=1)
        self.spi = SPI(0, baudrate=baudrate, polarity=0, phase=0,
                       firstbit=SPI.MSB, sck=Pin(sck), mosi=Pin(mosi),
                       miso=Pin(miso))
        self.last_rssi = 0
        self.last_lqi = 0

    def _transfer(self, data):
        buf = bytearray(data)
        self.cs.value(0)
        self.spi.write_readinto(buf, buf)
        self.cs.value(1)
        return bytes(buf)

    def _strobe(self, cmd):
        self._transfer([cmd])

    def _read_reg(self, reg):
        return self._transfer([reg | READ, 0x00])[1]

    def _write_reg(self, reg, value):
        self._transfer([reg & 0x3F, value])

    def _read_burst(self, reg, n):
        self.cs.value(0)
        self.spi.write(bytearray([reg | READ | BURST]))
        res = bytearray(n)
        self.spi.readinto(res)
        self.cs.value(1)
        return bytes(res)

    def _write_burst(self, reg, buf):
        self.cs.value(0)
        self.spi.write(bytearray([reg & 0x3F | BURST]))
        self.spi.write(bytearray(buf))
        self.cs.value(1)

    def set_frequency_hz(self, hz):
        freq = (hz * (1 << 16)) // XTAL_HZ
        self._write_reg(FREQ2, (freq >> 16) & 0xFF)
        self._write_reg(FREQ1, (freq >> 8) & 0xFF)
        self._write_reg(FREQ0, freq & 0xFF)

    def set_channel(self, ch):
        self._write_reg(CHANNR, ch)

    def init(self):
        self._strobe(SRES)
        time.sleep_ms(10)
        if self._read_reg(VERSION) != 0x14:
            return False
        self._strobe(SIDLE)
        # Configuracion SmartRF Studio: 868.3 MHz, GFSK, 38.4 kBaud
        config = [
            (IOCFG2, 0x07), (IOCFG1, 0x2E), (IOCFG0, 0x80), (FIFOTHR, 0x07),
            (SYNC1, 0xD3), (SYNC0, 0x91), (PKTLEN, 0x05), (PKTCTRL1, 0x04),
            (PKTCTRL0, 0x05), (ADDR, 0x00), (CHANNR, 0x00), (FSCTRL1, 0x0C),
            (FSCTRL0, 0x00), (FREQ2, 0x1F), (FREQ1, 0x0B), (FREQ0, 0x5A),
            (MDMCFG4, 0x5C), (MDMCFG3, 0xC8), (MDMCFG2, 0x93),
            (MDMCFG1, 0x22), (MDMCFG0, 0xB8), (DEVIATN, 0x35),
            (MCSM2, 0x07), (MCSM1, 0x30), (MCSM0, 0x18), (FOCCFG, 0x16),
            (BSCFG, 0x6C), (AGCCTRL2, 0x03), (AGCCTRL1, 0x40),
            (AGCCTRL0, 0x91), (WOREVT1, 0x87), (WOREVT0, 0x6B),
            (WORCTRL, 0xFB), (FREND1, 0x56), (FREND0, 0x11),
            (FSCAL3, 0xF8), (FSCAL2, 0xAF), (FSCAL1, 0x15), (FSCAL0, 0x1E),
            (RCCTRL1, 0x2C), (RCCTRL0, 0x0C), (TEST2, 0x01), (TEST1, 0x02),
            (TEST0, 0x81),
        ]
        for reg, value in config:
            self._write_reg(reg, value)
        self._write_burst(PATABLE, bytes([0x2D]))
        self.set_frequency_hz(BASE_FREQ)
        self._strobe(SCAL)
        time.sleep_ms(10)
        return True

    def get_state(self):
        return self._read_reg(MARCSTATE)

    def state_name(self):
        return STATE_NAMES.get(self.get_state(), "ERROR")

    def read_rssi_dbm(self):
        rssi = self._read_reg(RSSI)
        if rssi >= 128:
            return (rssi - 256) / 2 - 74
        return rssi / 2 - 74

    def read_lqi(self):
        return self._read_reg(LQI)

    def get_rx_fifo_bytes(self):
        return self._read_reg(RXBYTES) & 0x7F

    def get_tx_fifo_bytes(self):
        return self._read_reg(TXBYTES) & 0x7F

    def enter_idle(self):
        self._strobe(SIDLE)

    def enter_rx(self):
        self._strobe(SIDLE)
        self._strobe(SFRX)
        self._strobe(SRX)

    def send_packet(self, data):
        if not data or len(data) > 64:
            return False
        self._strobe(SIDLE)
        self._strobe(SFTX)
        self._write_burst(FIFO, data)
        self._strobe(STX)
        t0 = time.ticks_ms()
        while self.get_tx_fifo_bytes() != 0:
            if time.ticks_diff(time.ticks_ms(), t0) > 1000:
                break
            time.sleep_ms(1)
        self._strobe(SIDLE)
        return True

    def receive_packet(self, max_len=64):
        rx = self.get_rx_fifo_bytes()
        if rx == 0:
            return None
        # En PKTCTRL1=0x04 los 2 ultimos bytes son RSSI y LQI
        payload = min(rx - 2, max_len) if rx >= 2 else 0
        data = b""
        if payload > 0:
            data = self._read_burst(FIFO, payload)
        if rx >= 2:
            status = self._read_burst(FIFO, 2)
            self.last_rssi = status[0]
            self.last_lqi = status[1]
        if self.get_rx_fifo_bytes() > 0:
            self._strobe(SFRX)
        return data
