#pragma once

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint64_t frame;
    uint32_t fix;
    uint32_t hop_encrypted;
    uint8_t button;
    uint32_t serial;
    uint32_t serial_hi;
    uint32_t serial_lo;
    uint64_t man_key;
    uint32_t decrypted_hop;
    uint8_t dec_btn;
    uint16_t disc12;
    uint16_t disc8;
    uint16_t cnt;
    bool valid;
} ClemsaKeeloqFrame;

#define KEELOQ_NLF 0x3A5C742E
#define KEELOQ_ROUNDS 528

static inline uint64_t keeloq_reverse_bits64(uint64_t value) {
    uint64_t result = 0;
    for (uint8_t i = 0; i < 64; i++) {
        result = (result << 1) | ((value >> i) & 1U);
    }
    return result;
}

static inline uint8_t keeloq_bit(uint32_t x, uint8_t n) {
    return (x >> n) & 1U;
}

static inline uint32_t keeloq_encrypt(uint32_t data, uint64_t key) {
    uint32_t x = data;
    for (uint16_t r = 0; r < KEELOQ_ROUNDS; r++) {
        uint8_t g = keeloq_bit(x, 1) + keeloq_bit(x, 9) * 2 + keeloq_bit(x, 20) * 4 +
                    keeloq_bit(x, 26) * 8 + keeloq_bit(x, 31) * 16;
        uint8_t f = keeloq_bit(x, 0) ^ keeloq_bit(x, 16) ^ (uint8_t)((key >> (r & 63)) & 1U) ^
                    (uint8_t)((KEELOQ_NLF >> g) & 1U);
        x = ((x >> 1) | ((uint32_t)f << 31)) & 0xFFFFFFFF;
    }
    return x;
}

static inline uint32_t keeloq_decrypt(uint32_t data, uint64_t key) {
    uint32_t x = data;
    for (uint16_t r = 0; r < KEELOQ_ROUNDS; r++) {
        uint8_t g = keeloq_bit(x, 0) + keeloq_bit(x, 8) * 2 + keeloq_bit(x, 19) * 4 +
                    keeloq_bit(x, 25) * 8 + keeloq_bit(x, 30) * 16;
        uint8_t f = keeloq_bit(x, 31) ^ keeloq_bit(x, 15) ^
                    (uint8_t)((key >> ((15 - r) & 63)) & 1U) ^
                    (uint8_t)((KEELOQ_NLF >> g) & 1U);
        x = ((x << 1) | f) & 0xFFFFFFFF;
    }
    return x;
}

static inline uint64_t keeloq_normal_learning(uint32_t fix, uint64_t key) {
    uint32_t d = fix & 0x0FFFFFFF;
    uint32_t k1 = keeloq_decrypt(d | 0x20000000, key);
    uint32_t k2 = keeloq_decrypt(d | 0x60000000, key);
    return ((uint64_t)k2 << 32) | k1;
}