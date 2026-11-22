#include "cc1101.h"

#include <string.h>

#include "hardware/spi.h"
#include "pico/stdlib.h"

/* Frecuencia base por defecto: 868.3 MHz */
#define CC1101_XTAL_HZ   26000000u
#define CC1101_BASE_FREQ 433920000u

/* Configuración SmartRF Studio: 868.3 MHz, GFSK, 38.4 kBaud.
 * FSTEST (0x29), PTEST (0x2A) y AGCTEST (0x2B) no se configuran. */
static const uint8_t cc1101_config[47] = {
    0x07, 0x2E, 0x80, 0x07, 0xD3, 0x91, 0x05, 0x04, 0x05, 0x00,
    0x00, 0x0C, 0x00, 0x1F, 0x0B, 0x5A, 0x5C, 0xC8, 0x93, 0x22,
    0xB8, 0x35, 0x07, 0x30, 0x18, 0x16, 0x6C, 0x03, 0x40, 0x91,
    0x87, 0x6B, 0xFB, 0x56, 0x11, 0xF8, 0xAF, 0x15, 0x1E, 0x2C,
    0x0C, 0x01, 0x02, 0x81,
};

static uint8_t cc1101_last_rssi;
static uint8_t cc1101_last_lqi;

/* ------------------------------------------------------------------ */
/* Primitivas SPI                                                      */
/* ------------------------------------------------------------------ */

static void cc1101_cs_low(void) {
    gpio_put(CC1101_PIN_CS, 0);
}

static void cc1101_cs_high(void) {
    gpio_put(CC1101_PIN_CS, 1);
}

static uint8_t cc1101_transfer(uint8_t byte) {
    uint8_t rx;
    spi_write_read_blocking(CC1101_SPI, &byte, &rx, 1);
    return rx;
}

/* ------------------------------------------------------------------ */
/* Registros                                                           */
/* ------------------------------------------------------------------ */

uint8_t cc1101_strobe(uint8_t cmd) {
    cc1101_cs_low();
    uint8_t res = cc1101_transfer(cmd);
    cc1101_cs_high();
    return res;
}

uint8_t cc1101_read_reg(uint8_t reg) {
    cc1101_cs_low();
    cc1101_transfer(reg | CC1101_READ);
    uint8_t val = cc1101_transfer(0x00);
    cc1101_cs_high();
    return val;
}

void cc1101_write_reg(uint8_t reg, uint8_t value) {
    cc1101_cs_low();
    cc1101_transfer(reg | CC1101_WRITE);
    cc1101_transfer(value);
    cc1101_cs_high();
}

static void cc1101_read_burst(uint8_t reg, uint8_t *buf, uint8_t len) {
    cc1101_cs_low();
    cc1101_transfer(reg | CC1101_READ | CC1101_BURST);
    for (uint8_t i = 0; i < len; i++) {
        buf[i] = cc1101_transfer(0x00);
    }
    cc1101_cs_high();
}

static void cc1101_write_burst(uint8_t reg, const uint8_t *buf, uint8_t len) {
    cc1101_cs_low();
    cc1101_transfer(reg | CC1101_WRITE | CC1101_BURST);
    for (uint8_t i = 0; i < len; i++) {
        cc1101_transfer(buf[i]);
    }
    cc1101_cs_high();
}

/* ------------------------------------------------------------------ */
/* Estado                                                              */
/* ------------------------------------------------------------------ */

cc1101_state_t cc1101_get_state(void) {
    uint8_t marc = cc1101_read_reg(CC1101_MARCSTATE);
    switch (marc) {
        case 0x01: return CC1101_STATE_IDLE;
        case 0x0D: return CC1101_STATE_RX;
        case 0x1B: return CC1101_STATE_TX;
        case 0x12: return CC1101_STATE_FSTXON;
        case 0x10: return CC1101_STATE_CALIBRATE;
        case 0x11: return CC1101_STATE_SETTLING;
        case 0x16: return CC1101_STATE_RX_OVERFLOW;
        case 0x25: return CC1101_STATE_TX_UNDERFLOW;
        default:   return CC1101_STATE_ERROR;
    }
}

uint8_t cc1101_read_partnum(void) {
    return cc1101_read_reg(CC1101_PARTNUM);
}

uint8_t cc1101_read_version(void) {
    return cc1101_read_reg(CC1101_VERSION);
}

uint8_t cc1101_read_rssi_dec(void) {
    return cc1101_read_reg(CC1101_RSSI);
}

int16_t cc1101_read_rssi_dbm(void) {
    cc1101_last_rssi = cc1101_read_reg(CC1101_RSSI);
    if (cc1101_last_rssi >= 128) {
        return (int16_t)((cc1101_last_rssi - 256) / 2) - 74;
    }
    return (int16_t)(cc1101_last_rssi / 2) - 74;
}

uint8_t cc1101_read_lqi(void) {
    cc1101_last_lqi = cc1101_read_reg(CC1101_LQI);
    return cc1101_last_lqi;
}

uint8_t cc1101_get_rx_fifo_bytes(void) {
    return cc1101_read_reg(CC1101_RXBYTES) & 0x7F;
}

uint8_t cc1101_get_tx_fifo_bytes(void) {
    return cc1101_read_reg(CC1101_TXBYTES) & 0x7F;
}

void cc1101_flush_rx_fifo(void) {
    cc1101_strobe(CC1101_SFRX);
}

void cc1101_flush_tx_fifo(void) {
    cc1101_strobe(CC1101_SFTX);
}

/* ------------------------------------------------------------------ */
/* Ajustes                                                             */
/* ------------------------------------------------------------------ */

void cc1101_set_frequency_hz(uint32_t hz) {
    uint32_t freq = ((uint64_t)hz << 16) / CC1101_XTAL_HZ;
    cc1101_write_reg(CC1101_FREQ2, (freq >> 16) & 0xFF);
    cc1101_write_reg(CC1101_FREQ1, (freq >> 8) & 0xFF);
    cc1101_write_reg(CC1101_FREQ0, freq & 0xFF);
}

void cc1101_set_channel(uint8_t ch) {
    cc1101_write_reg(CC1101_CHANNR, ch);
}

/* ------------------------------------------------------------------ */
/* Inicialización                                                      */
/* ------------------------------------------------------------------ */

bool cc1101_init(void) {
    /* SPI */
    spi_init(CC1101_SPI, CC1101_SPI_BAUD);
    gpio_set_function(CC1101_PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(CC1101_PIN_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(CC1101_PIN_MISO, GPIO_FUNC_SPI);

    /* Chip select */
    gpio_init(CC1101_PIN_CS);
    gpio_set_dir(CC1101_PIN_CS, GPIO_OUT);
    cc1101_cs_high();

    /* Reset por hardware: esperar 30 us */
    busy_wait_us(30);

    /* Reset por strobe */
    cc1101_strobe(CC1101_SRES);
    busy_wait_us(100);

    /* Verificar comunicación leyendo version */
    if (cc1101_read_version() != 0x14) {
        return false;
    }

    cc1101_strobe(CC1101_SIDLE);

    /* Escribir configuración */
    cc1101_write_reg(CC1101_IOCFG2, cc1101_config[0]);
    cc1101_write_reg(CC1101_IOCFG1, cc1101_config[1]);
    cc1101_write_reg(CC1101_IOCFG0, cc1101_config[2]);
    cc1101_write_reg(CC1101_FIFOTHR, cc1101_config[3]);
    cc1101_write_reg(CC1101_PKTLEN, cc1101_config[6]);
    cc1101_write_reg(CC1101_PKTCTRL1, cc1101_config[7]);
    cc1101_write_reg(CC1101_PKTCTRL0, cc1101_config[8]);
    cc1101_write_reg(CC1101_FSCTRL1, cc1101_config[11]);
    cc1101_write_reg(CC1101_FSCTRL0, cc1101_config[12]);
    cc1101_set_frequency_hz(CC1101_BASE_FREQ);
    cc1101_write_reg(CC1101_MDMCFG4, cc1101_config[16]);
    cc1101_write_reg(CC1101_MDMCFG3, cc1101_config[17]);
    cc1101_write_reg(CC1101_MDMCFG2, cc1101_config[18]);
    cc1101_write_reg(CC1101_MDMCFG1, cc1101_config[19]);
    cc1101_write_reg(CC1101_MDMCFG0, cc1101_config[20]);
    cc1101_write_reg(CC1101_DEVIATN, cc1101_config[21]);
    cc1101_write_reg(CC1101_MCSM2, cc1101_config[22]);
    cc1101_write_reg(CC1101_MCSM1, cc1101_config[23]);
    cc1101_write_reg(CC1101_MCSM0, cc1101_config[24]);
    cc1101_write_reg(CC1101_FOCCFG, cc1101_config[25]);
    cc1101_write_reg(CC1101_BSCFG, cc1101_config[26]);
    cc1101_write_reg(CC1101_AGCCTRL2, cc1101_config[27]);
    cc1101_write_reg(CC1101_AGCCTRL1, cc1101_config[28]);
    cc1101_write_reg(CC1101_AGCCTRL0, cc1101_config[29]);
    cc1101_write_reg(CC1101_WOREVT1, cc1101_config[30]);
    cc1101_write_reg(CC1101_WOREVT0, cc1101_config[31]);
    cc1101_write_reg(CC1101_WORCTRL, cc1101_config[32]);
    cc1101_write_reg(CC1101_FREND1, cc1101_config[33]);
    cc1101_write_reg(CC1101_FREND0, cc1101_config[34]);
    cc1101_write_reg(CC1101_FSCAL3, cc1101_config[35]);
    cc1101_write_reg(CC1101_FSCAL2, cc1101_config[36]);
    cc1101_write_reg(CC1101_FSCAL1, cc1101_config[37]);
    cc1101_write_reg(CC1101_FSCAL0, cc1101_config[38]);
    cc1101_write_reg(CC1101_RCCTRL1, cc1101_config[39]);
    cc1101_write_reg(CC1101_RCCTRL0, cc1101_config[40]);
    cc1101_write_reg(CC1101_TEST2, cc1101_config[41]);
    cc1101_write_reg(CC1101_TEST1, cc1101_config[42]);
    cc1101_write_reg(CC1101_TEST0, cc1101_config[43]);

    /* Tabla de potencia: 0x2D (~0 dBm) */
    cc1101_cs_low();
    cc1101_transfer(CC1101_PATABLE | CC1101_WRITE | CC1101_BURST);
    cc1101_transfer(0x2D);
    cc1101_cs_high();

    cc1101_strobe(CC1101_SCAL);
    busy_wait_us(100);

    return true;
}

/* ------------------------------------------------------------------ */
/* TX / RX                                                             */
/* ------------------------------------------------------------------ */

void cc1101_enter_idle(void) {
    cc1101_strobe(CC1101_SIDLE);
}

void cc1101_enter_rx(void) {
    cc1101_strobe(CC1101_SIDLE);
    cc1101_strobe(CC1101_SFRX);
    cc1101_strobe(CC1101_SRX);
}

bool cc1101_send_packet(const uint8_t *data, uint8_t len) {
    if (len == 0 || len > CC1101_TX_FIFO_MAX) {
        return false;
    }

    cc1101_strobe(CC1101_SIDLE);
    cc1101_strobe(CC1101_SFTX);

    cc1101_write_burst(CC1101_FIFO, data, len);

    cc1101_strobe(CC1101_STX);

    /* Esperar a que se vacíe la FIFO de TX (con timeout) */
    for (int i = 0; i < 10000; i++) {
        if (cc1101_get_tx_fifo_bytes() == 0) {
            break;
        }
        busy_wait_us(100);
    }

    cc1101_strobe(CC1101_SIDLE);
    return true;
}

uint8_t cc1101_receive_packet(uint8_t *buf, uint8_t max_len) {
    uint8_t rx_bytes = cc1101_get_rx_fifo_bytes();
    if (rx_bytes == 0) {
        return 0;
    }

    /* En PKTCTRL1=0x04 (append status), los 2 últimos bytes son
     * RSSI y LQI. */
    uint8_t payload = (rx_bytes >= 2) ? (rx_bytes - 2) : 0;
    if (payload > max_len) {
        payload = max_len;
    }

    if (payload > 0) {
        cc1101_read_burst(CC1101_FIFO, buf, payload);
    }

    /* Leer RSSI/LQI adjuntos */
    if (rx_bytes >= 2) {
        uint8_t status[2];
        cc1101_read_burst(CC1101_FIFO, status, 2);
        cc1101_last_rssi = status[0];
        cc1101_last_lqi = status[1];
    }

    if (cc1101_get_rx_fifo_bytes() > 0) {
        cc1101_flush_rx_fifo();
    }

    return payload;
}

uint8_t cc1101_get_last_rssi_dec(void) {
    return cc1101_last_rssi;
}

uint8_t cc1101_get_last_lqi(void) {
    return cc1101_last_lqi;
}
