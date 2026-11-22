cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)

project(cc1101_rp2040 C CXX ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

pico_sdk_init()

# --- Firmware TX: envía paquetes cada 2s ---
add_executable(cc1101_tx
    main.c
    cc1101/cc1101.c
    ws2812.c
)
pico_generate_pio_header(cc1101_tx ${CMAKE_CURRENT_LIST_DIR}/ws2812.pio)
target_compile_definitions(cc1101_tx PRIVATE CC1101_TEST_MODE=CC1101_TEST_TX)
target_link_libraries(cc1101_tx pico_stdlib hardware_spi hardware_pio)
pico_enable_stdio_usb(cc1101_tx 1)
pico_enable_stdio_uart(cc1101_tx 0)
pico_add_extra_outputs(cc1101_tx)

# --- Firmware RX: escucha y muestra lo recibido ---
add_executable(cc1101_rx
    main.c
    cc1101/cc1101.c
    ws2812.c
)
pico_generate_pio_header(cc1101_rx ${CMAKE_CURRENT_LIST_DIR}/ws2812.pio)
target_compile_definitions(cc1101_rx PRIVATE CC1101_TEST_MODE=CC1101_TEST_RX)
target_link_libraries(cc1101_rx pico_stdlib hardware_spi hardware_pio)
pico_enable_stdio_usb(cc1101_rx 1)
pico_enable_stdio_uart(cc1101_rx 0)
pico_add_extra_outputs(cc1101_rx)
