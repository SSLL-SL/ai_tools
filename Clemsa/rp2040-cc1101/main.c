#include <stdio.h>
#include <string.h>

#include "cc1101/cc1101.h"
#include "pico/stdlib.h"

void ws2812_init(void);
void ws2812_set(uint8_t r, uint8_t g, uint8_t b);
void ws2812_off(void);

#define CC1101_TEST_TX 0
#define CC1101_TEST_RX 1

#ifndef CC1101_TEST_MODE
#define CC1101_TEST_MODE CC1101_TEST_RX
#endif

static const char *cc1101_state_name(cc1101_state_t st) {
    switch (st) {
        case CC1101_STATE_IDLE: return "IDLE";
        case CC1101_STATE_RX: return "RX";
        case CC1101_STATE_TX: return "TX";
        case CC1101_STATE_FSTXON: return "FSTXON";
        case CC1101_STATE_CALIBRATE: return "CALIBRATE";
        case CC1101_STATE_SETTLING: return "SETTLING";
        case CC1101_STATE_RX_OVERFLOW: return "RX_OVERFLOW";
        case CC1101_STATE_TX_UNDERFLOW: return "TX_UNDERFLOW";
        default: return "ERROR";
    }
}

int main(void) {
    stdio_init_all();

    /* LED onboard de la RP2040-Zero (WS2812 en GPIO16) */
    ws2812_init();
    ws2812_set(0, 40, 0);

    /* Esperar a que se abra la consola USB */
    for (int i = 0; i < 10 && !stdio_usb_connected(); i++) {
        sleep_ms(100);
    }

    printf("\n=== RP2040-Zero + CC1101 ===\n");
    printf("Frecuencia: 433.92 MHz  GFSK 38.4 kbaud\n");

    if (!cc1101_init()) {
        printf("[ERROR] No se pudo comunicar con el CC1101.\n");
        printf("Revisa el cableado y la alimentacion (3.3V).\n");
        ws2812_set(50, 0, 0);
        while (true) {
            tight_loop_contents();
        }
    }

    printf("CC1101 OK  Part#=0x%02X  Version=0x%02X  Estado=%s\n",
           cc1101_read_partnum(), cc1101_read_version(),
           cc1101_state_name(cc1101_get_state()));

#if CC1101_TEST_MODE == CC1101_TEST_TX
    printf("MODO: TX (envia un paquete cada 2 s)\n");
    uint32_t count = 0;
    while (true) {
        uint8_t pkt[12];
        pkt[0] = 0xAA;
        pkt[1] = 0x55;
        pkt[2] = (count >> 24) & 0xFF;
        pkt[3] = (count >> 16) & 0xFF;
        pkt[4] = (count >> 8) & 0xFF;
        pkt[5] = count & 0xFF;
        snprintf((char *)pkt + 6, sizeof(pkt) - 6, "Hola");
        uint8_t len = 6 + 4;

        ws2812_set(0, 0, 50);
        if (cc1101_send_packet(pkt, len)) {
            printf("TX #%lu  %d bytes -> FIFO_TX=%d\n",
                   (unsigned long)count, len, cc1101_get_tx_fifo_bytes());
        } else {
            printf("TX #%lu  FALLO\n", (unsigned long)count);
        }
        ws2812_off();

        count++;
        sleep_ms(2000);
    }
#else
    printf("MODO: RX (escuchando...)\n");
    cc1101_enter_rx();
    while (true) {
        uint8_t buf[64];
        uint8_t n = cc1101_receive_packet(buf, sizeof(buf));
        if (n > 0) {
            printf("RX %d bytes | ", n);
            for (uint8_t i = 0; i < n; i++) {
                printf("%02X ", buf[i]);
            }
            printf("| RSSI=%d dBm  LQI=%u\n",
                   cc1101_read_rssi_dbm(), cc1101_read_lqi());
            ws2812_set(0, 50, 0);
            sleep_ms(50);
            ws2812_off();
        }
        sleep_ms(1);
    }
#endif
}
