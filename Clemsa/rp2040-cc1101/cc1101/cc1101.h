#ifndef CC1101_H
#define CC1101_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ */
/* Pines de conexión (ajusta al cableado de tu placa)                 */
/* RP2040-Zero: SPI0 en GPIO0(MISO) 1(CS) 2(SCK) 3(MOSI)             */
/*                                                                     */
/*   CC1101  |  RP2040-Zero                                            */
/*   ------- |  ----------                                             */
/*   GDO0    |  (opcional, no usado)                                   */
/*   SCK     |  GPIO 2                                                 */
/*   MISO    |  GPIO 0                                                 */
/*   MOSI    |  GPIO 3                                                 */
/*   CSn     |  GPIO 1                                                 */
/*   VCC     |  3V3 (el CC1101 funciona a 3.3V)                        */
/*   GND     |  GND                                                    */
/* ------------------------------------------------------------------ */
#define CC1101_SPI         spi0
#define CC1101_PIN_SCK     2
#define CC1101_PIN_MOSI    3
#define CC1101_PIN_MISO    0
#define CC1101_PIN_CS      1
#define CC1101_SPI_BAUD    1000000

/* Registros de configuración */
#define CC1101_IOCFG2     0x00
#define CC1101_IOCFG1     0x01
#define CC1101_IOCFG0     0x02
#define CC1101_FIFOTHR    0x03
#define CC1101_SYNC1      0x04
#define CC1101_SYNC0      0x05
#define CC1101_PKTLEN     0x06
#define CC1101_PKTCTRL1   0x07
#define CC1101_PKTCTRL0   0x08
#define CC1101_ADDR       0x09
#define CC1101_CHANNR     0x0A
#define CC1101_FSCTRL1    0x0B
#define CC1101_FSCTRL0    0x0C
#define CC1101_FREQ2      0x0D
#define CC1101_FREQ1      0x0E
#define CC1101_FREQ0      0x0F
#define CC1101_MDMCFG4    0x10
#define CC1101_MDMCFG3    0x11
#define CC1101_MDMCFG2    0x12
#define CC1101_MDMCFG1    0x13
#define CC1101_MDMCFG0    0x14
#define CC1101_DEVIATN    0x15
#define CC1101_MCSM2      0x16
#define CC1101_MCSM1      0x17
#define CC1101_MCSM0      0x18
#define CC1101_FOCCFG     0x19
#define CC1101_BSCFG      0x1A
#define CC1101_AGCCTRL2   0x1B
#define CC1101_AGCCTRL1   0x1C
#define CC1101_AGCCTRL0   0x1D
#define CC1101_WOREVT1    0x1E
#define CC1101_WOREVT0    0x1F
#define CC1101_WORCTRL    0x20
#define CC1101_FREND1     0x21
#define CC1101_FREND0     0x22
#define CC1101_FSCAL3     0x23
#define CC1101_FSCAL2     0x24
#define CC1101_FSCAL1     0x25
#define CC1101_FSCAL0     0x26
#define CC1101_RCCTRL1    0x27
#define CC1101_RCCTRL0    0x28
#define CC1101_TEST2      0x2C
#define CC1101_TEST1      0x2D
#define CC1101_TEST0      0x2E

/* Registros de estado (lectura) */
#define CC1101_PARTNUM    0x30
#define CC1101_VERSION    0x31
#define CC1101_FREQEST    0x32
#define CC1101_LQI        0x33
#define CC1101_RSSI       0x34
#define CC1101_MARCSTATE  0x35
#define CC1101_WORTIME1   0x36
#define CC1101_WORTIME0   0x37
#define CC1101_PKTSTATUS  0x38
#define CC1101_VCO_VC_DAC 0x39
#define CC1101_TXBYTES    0x3A
#define CC1101_RXBYTES    0x3B

/* Comandos strobe */
#define CC1101_SRES       0x30
#define CC1101_SFSTXON    0x31
#define CC1101_SXOFF      0x32
#define CC1101_SCAL       0x33
#define CC1101_SRX        0x34
#define CC1101_STX        0x35
#define CC1101_SIDLE      0x36
#define CC1101_SWOR       0x38
#define CC1101_SPWD       0x39
#define CC1101_SFRX       0x3A
#define CC1101_SFTX       0x3B
#define CC1101_SWORRST    0x3C
#define CC1101_SNOP       0x3D

/* Bits de cabecera SPI */
#define CC1101_WRITE      0x00
#define CC1101_READ       0x80
#define CC1101_BURST      0x40

/* FIFO */
#define CC1101_FIFO       0x3F
#define CC1101_PATABLE    0x3E

#define CC1101_TX_FIFO_MAX 64
#define CC1101_RX_FIFO_MAX 64

typedef enum {
    CC1101_STATE_IDLE = 0x01,
    CC1101_STATE_RX = 0x0D,
    CC1101_STATE_TX = 0x1B,
    CC1101_STATE_FSTXON = 0x12,
    CC1101_STATE_CALIBRATE = 0x10,
    CC1101_STATE_SETTLING = 0x11,
    CC1101_STATE_RX_OVERFLOW = 0x16,
    CC1101_STATE_TX_UNDERFLOW = 0x25,
    CC1101_STATE_ERROR = 0xFF,
} cc1101_state_t;

bool cc1101_init(void);
uint8_t cc1101_read_reg(uint8_t reg);
void cc1101_write_reg(uint8_t reg, uint8_t value);
uint8_t cc1101_strobe(uint8_t cmd);
cc1101_state_t cc1101_get_state(void);
uint8_t cc1101_read_partnum(void);
uint8_t cc1101_read_version(void);
uint8_t cc1101_read_rssi_dec(void);
int16_t cc1101_read_rssi_dbm(void);
uint8_t cc1101_read_lqi(void);
uint8_t cc1101_get_last_rssi_dec(void);
uint8_t cc1101_get_last_lqi(void);
uint8_t cc1101_get_rx_fifo_bytes(void);
uint8_t cc1101_get_tx_fifo_bytes(void);
void cc1101_flush_rx_fifo(void);
void cc1101_flush_tx_fifo(void);
void cc1101_set_frequency_hz(uint32_t hz);
void cc1101_set_channel(uint8_t ch);
void cc1101_enter_rx(void);
void cc1101_enter_idle(void);
bool cc1101_send_packet(const uint8_t *data, uint8_t len);
uint8_t cc1101_receive_packet(uint8_t *buf, uint8_t max_len);

#ifdef __cplusplus
}
#endif

#endif /* CC1101_H */
