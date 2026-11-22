#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "ws2812.pio.h"

#define WS2812_PIN 16
#define WS2812_PIO pio0
#define WS2812_SM 0

static inline uint32_t urgb_u32(uint8_t r, uint8_t g, uint8_t b) {
    return ((uint32_t)(r) << 8) | ((uint32_t)(g) << 16) | (uint32_t)(b);
}

static inline void ws2812_put_pixel(uint32_t pixel_grb) {
    pio_sm_put_blocking(WS2812_PIO, WS2812_SM, pixel_grb << 8u);
}

void ws2812_init(void) {
    uint offset = pio_add_program(WS2812_PIO, &ws2812_program);
    ws2812_program_init(WS2812_PIO, WS2812_SM, offset, WS2812_PIN, 800000, false);
}

void ws2812_set(uint8_t r, uint8_t g, uint8_t b) {
    ws2812_put_pixel(urgb_u32(r, g, b));
}

void ws2812_off(void) {
    ws2812_put_pixel(0);
}
