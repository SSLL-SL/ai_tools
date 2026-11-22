#include <furi.h>
#include <furi_hal.h>
#include <gui/gui.h>
#include <gui/view_dispatcher.h>
#include <gui/modules/submenu.h>
#include <gui/modules/widget.h>
#include <gui/modules/text_input.h>
#include <storage/storage.h>
#include <toolbox/level_duration.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "clemsa_keeloq.h"

#define TAG "ClemsaGen"
#define CLEMSA_KEY_MASTER 0xA1B58921A3A738AAULL
#define CLEMSA_FREQ 433920000UL
#define TX_TE 400
#define TX_PREAMBLE_PAIRS 10
#define TX_MAX (TX_PREAMBLE_PAIRS * 2 + 64 * 2)
#define CLEMSA_PROFILE_DIR "/ext/apps_data/clemsa_profiles"
#define RX_MAX_PULSES 1024
#define RX_CAPTURE_MS 5000

static const uint8_t ook650_preset_data[] = {
    0x02, 0x0D, 0x03, 0x07, 0x08, 0x32, 0x0B, 0x06,
    0x14, 0x00, 0x13, 0x00, 0x12, 0x30, 0x11, 0x32, 0x10, 0x17,
    0x18, 0x18, 0x19, 0x18,
    0x1D, 0x91, 0x1C, 0x00, 0x1B, 0x07,
    0x20, 0xFB, 0x22, 0x11, 0x21, 0xB6,
    0x00, 0x00,
    0x00, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

typedef enum {
    ClemsaItemSerial,
    ClemsaItemDisc,
    ClemsaItemCnt,
    ClemsaItemBtn,
    ClemsaItemGenerate,
    ClemsaItemSaveSub,
    ClemsaItemSendRf,
    ClemsaItemCaptureRf,
    ClemsaItemProfileName,
    ClemsaItemProfileSave,
    ClemsaItemProfileLoad,
    ClemsaItemProfileDelete,
    ClemsaItemCount,
} ClemsaMenuItem;

typedef enum {
    ClemsaViewMenu,
    ClemsaViewTextInput,
    ClemsaViewResult,
} ClemsaView;

typedef struct {
    Gui* gui;
    ViewDispatcher* view_dispatcher;
    Submenu* menu;
    TextInput* text_input;
    Widget* widget;
    bool capture_running;

    char serial_buf[16];
    char disc_buf[8];
    char cnt_buf[8];
    char btn_buf[8];
    char profile_buf[24];

    bool has_frame;
    uint64_t frame_air;
    uint32_t fix;
    uint32_t hop_encrypted;
    uint64_t man_key;
    uint32_t hop_plain;
    uint16_t disc;
    uint16_t cnt;
    uint8_t btn;
    uint32_t serial_hi;
    uint32_t serial_lo;

    uint32_t tx_durations[TX_MAX];
    uint8_t tx_levels[TX_MAX];
    size_t tx_count;
    size_t tx_index;

    bool rx_levels[RX_MAX_PULSES];
    uint32_t rx_durations[RX_MAX_PULSES];
    volatile size_t rx_count;
} ClemsaKeeloq;

static bool parse_serial(const char* in, uint32_t* out) {
    char clean[16];
    size_t n = 0;
    for(size_t i = 0; in[i] != 0 && n < 15; i++) {
        if(in[i] != ' ') clean[n++] = in[i];
    }
    clean[n] = 0;

    if(n == 9 && isdigit((unsigned char)clean[0]) && isdigit((unsigned char)clean[1]) &&
       isdigit((unsigned char)clean[2]) && isdigit((unsigned char)clean[3]) &&
       isdigit((unsigned char)clean[4]) && isdigit((unsigned char)clean[5]) &&
       isdigit((unsigned char)clean[6]) && isdigit((unsigned char)clean[7]) &&
       isdigit((unsigned char)clean[8])) {
        uint32_t hi = (uint32_t)strtoul(clean, NULL, 16) & 0xFFFF;
        uint32_t lo = (uint32_t)strtoul(clean + 4, NULL, 10) & 0xFFFF;
        *out = (hi << 16) | lo;
        return true;
    }

    char* end = NULL;
    unsigned long v = strtoul(clean, &end, 0);
    if(end == clean || *end != 0) return false;
    *out = (uint32_t)v;
    return true;
}

static bool parse_u16(const char* in, uint16_t* out) {
    char* end = NULL;
    unsigned long v = strtoul(in, &end, 10);
    if(end == in || *end != 0 || v > 0xFFFF) return false;
    *out = (uint16_t)v;
    return true;
}

static bool parse_u8(const char* in, uint8_t* out) {
    char* end = NULL;
    unsigned long v = strtoul(in, &end, 10);
    if(end == in || *end != 0 || v > 0xFF) return false;
    *out = (uint8_t)v;
    return true;
}

static void clemsa_show_text(ClemsaKeeloq* app, const char* text) {
    widget_reset(app->widget);
    widget_add_string_multiline_element(
        app->widget, 0, 2, AlignLeft, AlignTop, FontSecondary, text);
    view_dispatcher_switch_to_view(app->view_dispatcher, ClemsaViewResult);
}

static void clemsa_profile_path(const ClemsaKeeloq* app, char* path, size_t path_size) {
    char safe_name[sizeof(app->profile_buf)];
    size_t n = 0;

    for(size_t i = 0; app->profile_buf[i] != 0 && n < sizeof(safe_name) - 1; i++) {
        char c = app->profile_buf[i];
        if(isalnum((unsigned char)c) || c == '_' || c == '-') {
            safe_name[n++] = c;
        } else {
            safe_name[n++] = '_';
        }
    }
    safe_name[n] = 0;
    snprintf(path, path_size, CLEMSA_PROFILE_DIR "/%s.cfg", n ? safe_name : "default");
}

static void clemsa_save_profile(ClemsaKeeloq* app, Storage* storage) {
    char path[96];
    clemsa_profile_path(app, path, sizeof(path));
    storage_common_mkdir(storage, "/ext/apps_data");
    storage_common_mkdir(storage, CLEMSA_PROFILE_DIR);

    File* file = storage_file_alloc(storage);
    bool ok = storage_file_open(file, path, FSAM_WRITE, FSOM_CREATE_ALWAYS);
    if(ok) {
        char data[96];
        int length = snprintf(
            data,
            sizeof(data),
            "Serial=%s\nDisc=%s\nCnt=%s\nBtn=%s\n",
            app->serial_buf,
            app->disc_buf,
            app->cnt_buf,
            app->btn_buf);
        ok = length > 0 && (size_t)length < sizeof(data) &&
             storage_file_write(file, data, (size_t)length) == (size_t)length;
    }
    storage_file_free(file);
    clemsa_show_text(app, ok ? "Profile saved" : "Error saving profile");
}

static void clemsa_load_profile(ClemsaKeeloq* app, Storage* storage) {
    char path[96];
    char data[128] = {0};
    clemsa_profile_path(app, path, sizeof(path));

    File* file = storage_file_alloc(storage);
    bool ok = storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING);
    if(ok) {
        size_t read = storage_file_read(file, data, sizeof(data) - 1);
        data[read] = 0;
        char serial[sizeof(app->serial_buf)];
        char disc[sizeof(app->disc_buf)];
        char cnt[sizeof(app->cnt_buf)];
        char btn[sizeof(app->btn_buf)];
        ok = sscanf(
                 data,
                 "Serial=%15[^\n]\nDisc=%7[^\n]\nCnt=%7[^\n]\nBtn=%7[^\n]",
                 serial,
                 disc,
                 cnt,
                 btn) == 4;
        if(ok) {
            strcpy(app->serial_buf, serial);
            strcpy(app->disc_buf, disc);
            strcpy(app->cnt_buf, cnt);
            strcpy(app->btn_buf, btn);
            app->has_frame = false;
        }
    }
    storage_file_free(file);
    clemsa_show_text(app, ok ? "Profile loaded" : "Profile not found/invalid");
}

static void clemsa_delete_profile(ClemsaKeeloq* app, Storage* storage) {
    char path[96];
    clemsa_profile_path(app, path, sizeof(path));
    bool ok = storage_common_remove(storage, path) == FSE_OK;
    clemsa_show_text(app, ok ? "Profile deleted" : "Profile not found");
}

static LevelDuration clemsa_tx_callback(void* context) {
    ClemsaKeeloq* app = context;
    if(app->tx_index >= app->tx_count) return level_duration_reset();
    LevelDuration ld =
        level_duration_make(app->tx_levels[app->tx_index], app->tx_durations[app->tx_index]);
    app->tx_index++;
    return ld;
}

static void clemsa_build_tx(ClemsaKeeloq* app) {
    size_t n = 0;
    for(int i = 0; i < TX_PREAMBLE_PAIRS; i++) {
        app->tx_levels[n] = 1;
        app->tx_durations[n++] = TX_TE;
        app->tx_levels[n] = 0;
        app->tx_durations[n++] = TX_TE;
    }
    for(int i = 0; i < 64; i++) {
        uint8_t bit = (app->frame_air >> i) & 1U;
        if(bit == 0) {
            app->tx_levels[n] = 1;
            app->tx_durations[n++] = TX_TE;
            app->tx_levels[n] = 0;
            app->tx_durations[n++] = TX_TE * 2;
        } else {
            app->tx_levels[n] = 1;
            app->tx_durations[n++] = TX_TE * 2;
            app->tx_levels[n] = 0;
            app->tx_durations[n++] = TX_TE;
        }
    }
    app->tx_count = n;
}

static bool clemsa_send_rf(ClemsaKeeloq* app) {
    if(!app->has_frame) return false;
    clemsa_build_tx(app);
    app->tx_index = 0;

    furi_hal_subghz_reset();
    furi_hal_subghz_load_custom_preset(ook650_preset_data);
    furi_hal_subghz_set_frequency_and_path(CLEMSA_FREQ);

    if(!furi_hal_subghz_start_async_tx(clemsa_tx_callback, app)) {
        furi_hal_subghz_idle();
        return false;
    }
    while(!furi_hal_subghz_is_async_tx_complete()) {
        furi_delay_ms(10);
    }
    furi_hal_subghz_stop_async_tx();
    furi_hal_subghz_idle();
    return true;
}

static void clemsa_rx_callback(bool level, uint32_t duration, void* context) {
    ClemsaKeeloq* app = context;
    size_t count = app->rx_count;
    if(count < RX_MAX_PULSES) {
        app->rx_levels[count] = level;
        app->rx_durations[count] = duration;
        app->rx_count = count + 1;
    }
}

static bool clemsa_duration_near(uint32_t duration, uint32_t expected) {
    return duration >= expected - 230 && duration <= expected + 230;
}

static bool clemsa_decode_capture(ClemsaKeeloq* app, uint64_t* frame) {
    size_t required = TX_PREAMBLE_PAIRS * 2 + 64 * 2;
    for(size_t start = 0; start + required <= app->rx_count; start++) {
        bool preamble = true;
        for(size_t i = 0; i < TX_PREAMBLE_PAIRS * 2; i++) {
            bool expected_level = (i & 1U) == 0;
            if(app->rx_levels[start + i] != expected_level ||
               !clemsa_duration_near(app->rx_durations[start + i], TX_TE)) {
                preamble = false;
                break;
            }
        }
        if(!preamble) continue;

        uint64_t decoded = 0;
        bool valid = true;
        size_t data_start = start + TX_PREAMBLE_PAIRS * 2;
        for(size_t bit = 0; bit < 64; bit++) {
            size_t pulse = data_start + bit * 2;
            uint32_t high = app->rx_durations[pulse];
            uint32_t low = app->rx_durations[pulse + 1];
            if(!app->rx_levels[pulse] || app->rx_levels[pulse + 1]) {
                valid = false;
                break;
            }
            if(clemsa_duration_near(high, TX_TE) && clemsa_duration_near(low, TX_TE * 2)) {
                // Bit 0 is represented by the short-high/long-low pair.
            } else if(clemsa_duration_near(high, TX_TE * 2) && clemsa_duration_near(low, TX_TE)) {
                decoded |= 1ULL << bit;
            } else {
                valid = false;
                break;
            }
        }
        if(valid) {
            *frame = decoded;
            return true;
        }
    }
    return false;
}

static bool clemsa_capture_rf(ClemsaKeeloq* app) {
    app->rx_count = 0;
    furi_hal_subghz_reset();
    furi_hal_subghz_load_custom_preset(ook650_preset_data);
    furi_hal_subghz_set_frequency_and_path(CLEMSA_FREQ);
    furi_hal_subghz_rx();
    furi_hal_subghz_start_async_rx(clemsa_rx_callback, app);
    furi_delay_ms(RX_CAPTURE_MS);
    furi_hal_subghz_stop_async_rx();

    uint64_t frame = 0;
    if(!clemsa_decode_capture(app, &frame)) return false;
    app->frame_air = frame;
    app->has_frame = true;
    return true;
}

static void clemsa_save_sub_protocol(ClemsaKeeloq* app, Storage* storage) {
    FuriString* path =
        furi_string_alloc_printf("/ext/subghz/Clemsa_Mutancode_%04lX%05lu_B%u.sub",
                                 (unsigned long)app->serial_hi,
                                 (unsigned long)app->serial_lo,
                                 app->btn);
    FuriString* content = furi_string_alloc();
    furi_string_printf(
        content,
        "Filetype: Flipper SubGhz Key File\n"
        "Version: 1\n"
        "# Clemsa Mutancode - Boton %u\n"
        "Protocol: KeeLoq\n"
        "Bit: 64\n"
        "Key: ",
        app->btn);
    for(int b = 7; b >= 0; b--) {
        furi_string_cat_printf(
            content, "%s%02X", (b == 7) ? "" : " ", (unsigned)((app->frame_air >> (b * 8)) & 0xFF));
    }
    furi_string_cat_printf(content, "\n");

    File* file = storage_file_alloc(storage);
    bool ok =
        storage_file_open(file, furi_string_get_cstr(path), FSAM_WRITE, FSOM_CREATE_ALWAYS);
    if(ok) {
        size_t size = furi_string_size(content);
        ok = storage_file_write(file, (const uint8_t*)furi_string_get_cstr(content), (uint16_t)size) == (uint16_t)size;
    }
    storage_file_free(file);

    clemsa_show_text(
        app, ok ? "Protocol .sub saved OK" : "ERROR writing protocol .sub");
    furi_string_free(path);
    furi_string_free(content);
}

static void clemsa_save_sub_raw(ClemsaKeeloq* app, Storage* storage) {
    FuriString* path =
        furi_string_alloc_printf("/ext/subghz/Clemsa_Mutancode_%04lX%05lu_B%u_RAW.sub",
                                 (unsigned long)app->serial_hi,
                                 (unsigned long)app->serial_lo,
                                 app->btn);
    FuriString* content = furi_string_alloc();
    furi_string_printf(
        content,
        "Filetype: Flipper SubGhz RAW File\n"
        "Version: 1\n"
        "# Clemsa Mutancode - Boton %u\n"
        "Protocol: Raw\n"
        "Frequency: 433920000\n"
        "Preset: FuriHalSubGhzPresetOok650Async\n"
        "RAW_Data: ",
        app->btn);

    FuriString* raw = furi_string_alloc();
    for(int i = 0; i < TX_PREAMBLE_PAIRS; i++) {
        furi_string_cat_printf(raw, "+%d -%d ", TX_TE, TX_TE);
    }
    for(int i = 0; i < 64; i++) {
        uint8_t bit = (app->frame_air >> i) & 1U;
        if(bit == 0) {
            furi_string_cat_printf(raw, "+%d -%d ", TX_TE, TX_TE * 2);
        } else {
            furi_string_cat_printf(raw, "+%d -%d ", TX_TE * 2, TX_TE);
        }
    }
    furi_string_trim(raw);
    furi_string_cat(content, furi_string_get_cstr(raw));
    furi_string_cat_printf(content, "\n");

    File* file = storage_file_alloc(storage);
    bool ok =
        storage_file_open(file, furi_string_get_cstr(path), FSAM_WRITE, FSOM_CREATE_ALWAYS);
    if(ok) {
        size_t size = furi_string_size(content);
        ok = storage_file_write(file, (const uint8_t*)furi_string_get_cstr(content), (uint16_t)size) == (uint16_t)size;
    }
    storage_file_free(file);

    clemsa_show_text(
        app, ok ? "RAW .sub saved OK" : "ERROR writing RAW .sub");
    furi_string_free(path);
    furi_string_free(content);
    furi_string_free(raw);
}

static void clemsa_generate(ClemsaKeeloq* app) {
    uint32_t serial;
    uint16_t disc;
    uint16_t cnt;
    uint8_t btn;

    if(!parse_serial(app->serial_buf, &serial)) {
        clemsa_show_text(
            app,
            "Serial invalid.\nFormats: 75513523 | 4803EB3\n| 0480 16051\n(0x or decimal)");
        return;
    }
    if(!parse_u16(app->disc_buf, &disc)) disc = 53;
    if(!parse_u16(app->cnt_buf, &cnt)) cnt = 0;
    if(!parse_u8(app->btn_buf, &btn)) btn = 1;

    if(serial > 0x0FFFFFFF) {
        clemsa_show_text(app, "Serial must be 28 bits (0-0x0FFFFFFF)");
        return;
    }
    if(disc > 0xFFF) {
        clemsa_show_text(app, "Disc must be 12 bits (0-4095)");
        return;
    }
    if(btn < 1 || btn > 4) {
        clemsa_show_text(app, "Btn must be 1-4");
        return;
    }

    app->disc = disc;
    app->cnt = cnt;
    app->btn = btn;
    app->serial_hi = (serial >> 16) & 0xFFFF;
    app->serial_lo = serial & 0xFFFF;

    app->fix = ((uint32_t)btn << 28) | serial;
    app->hop_plain = ((uint32_t)btn << 28) | ((uint32_t)disc << 16) | cnt;
    app->man_key = keeloq_normal_learning(app->fix, CLEMSA_KEY_MASTER);
    app->hop_encrypted = keeloq_encrypt(app->hop_plain, app->man_key);
    uint64_t frame_internal = ((uint64_t)app->fix << 32) | app->hop_encrypted;
    app->frame_air = keeloq_reverse_bits64(frame_internal);
    app->has_frame = true;

    FuriString* text = furi_string_alloc();
    furi_string_printf(
        text,
        "Frame: %016llX\n"
        "Fix: %08lX Hop: %08lX\n"
        "Man: %016llX\n"
        "B: %u D: %u C: %u\n"
        "Ser: %04lX %05lu\n"
        "OK. Back for save/send.",
        (unsigned long long)app->frame_air,
        (unsigned long)app->fix,
        (unsigned long)app->hop_encrypted,
        (unsigned long long)app->man_key,
        app->btn,
        app->disc,
        app->cnt,
        (unsigned long)app->serial_hi,
        (unsigned long)app->serial_lo);
    clemsa_show_text(app, furi_string_get_cstr(text));
    furi_string_free(text);
}

static void clemsa_text_input_callback(void* context) {
    furi_assert(context);
    ClemsaKeeloq* app = context;
    view_dispatcher_switch_to_view(app->view_dispatcher, ClemsaViewMenu);
}

static const char* clemsa_field_header(ClemsaMenuItem item) {
    switch(item) {
    case ClemsaItemSerial:
        return "Serial (e.g. 0480 16051 | 4803EB3 | 75513523)";
    case ClemsaItemDisc:
        return "Discriminador (12 bits, default 53)";
    case ClemsaItemCnt:
        return "Contador (16 bits, 0-65535)";
    case ClemsaItemBtn:
        return "Boton (1-4)";
    case ClemsaItemProfileName:
        return "Nombre del perfil";
    default:
        return "";
    }
}

static char* clemsa_field_buffer(ClemsaKeeloq* app, ClemsaMenuItem item) {
    switch(item) {
    case ClemsaItemSerial:
        return app->serial_buf;
    case ClemsaItemDisc:
        return app->disc_buf;
    case ClemsaItemCnt:
        return app->cnt_buf;
    case ClemsaItemBtn:
        return app->btn_buf;
    case ClemsaItemProfileName:
        return app->profile_buf;
    default:
        return NULL;
    }
}

static uint32_t clemsa_field_buffer_size(ClemsaMenuItem item) {
    switch(item) {
    case ClemsaItemSerial:
        return 15;
    case ClemsaItemDisc:
    case ClemsaItemCnt:
        return 6;
    case ClemsaItemBtn:
        return 2;
    case ClemsaItemProfileName:
        return sizeof(((ClemsaKeeloq*)0)->profile_buf) - 1;
    default:
        return 0;
    }
}

static void clemsa_menu_callback(void* context, uint32_t index) {
    ClemsaKeeloq* app = context;
    (void)index;
    UNUSED(index);
    switch(index) {
    case ClemsaItemGenerate:
        clemsa_generate(app);
        break;
    case ClemsaItemSaveSub:
        if(app->has_frame) {
            Storage* storage = furi_record_open(RECORD_STORAGE);
            clemsa_save_sub_protocol(app, storage);
            clemsa_save_sub_raw(app, storage);
            furi_record_close(RECORD_STORAGE);
        } else {
            clemsa_show_text(app, "Generate first");
        }
        break;
    case ClemsaItemSendRf:
        if(app->has_frame) {
            clemsa_show_text(
                app, clemsa_send_rf(app) ? "Frame sent via RF" : "TX error");
        } else {
            clemsa_show_text(app, "Generate first");
        }
        break;
    case ClemsaItemCaptureRf:
        if(clemsa_capture_rf(app)) {
            char captured[64];
            snprintf(
                captured,
                sizeof(captured),
                "Frame captured\n%016llX\nReady to save/send",
                (unsigned long long)app->frame_air);
            clemsa_show_text(app, captured);
        } else {
            clemsa_show_text(app, "No Clemsa frame found");
        }
        break;
    case ClemsaItemProfileSave:
    case ClemsaItemProfileLoad:
    case ClemsaItemProfileDelete: {
        Storage* storage = furi_record_open(RECORD_STORAGE);
        if(index == ClemsaItemProfileSave) {
            clemsa_save_profile(app, storage);
        } else if(index == ClemsaItemProfileLoad) {
            clemsa_load_profile(app, storage);
        } else {
            clemsa_delete_profile(app, storage);
        }
        furi_record_close(RECORD_STORAGE);
        break;
    }
    default:
        if(index <= ClemsaItemBtn || index == ClemsaItemProfileName) {
            char* buffer = clemsa_field_buffer(app, (ClemsaMenuItem)index);
            uint32_t size = clemsa_field_buffer_size((ClemsaMenuItem)index);
            if(buffer && size) {
                text_input_set_header_text(app->text_input, clemsa_field_header((ClemsaMenuItem)index));
                text_input_set_result_callback(
                    app->text_input,
                    clemsa_text_input_callback,
                    app,
                    buffer,
                    size,
                    true);
                view_dispatcher_switch_to_view(app->view_dispatcher, ClemsaViewTextInput);
            }
        }
        break;
    }
}

static uint32_t clemsa_back_from_result(void* context) {
    UNUSED(context);
    return ClemsaViewMenu;
}
static uint32_t clemsa_back_from_text_input(void* context) {
    UNUSED(context);
    return ClemsaViewMenu;
}
static uint32_t clemsa_back_from_menu(void* context) {
    UNUSED(context);
    return VIEW_NONE;
}

static void clemsa_set_defaults(ClemsaKeeloq* app) {
    strcpy(app->serial_buf, "75513523");
    strcpy(app->disc_buf, "53");
    strcpy(app->cnt_buf, "948");
    strcpy(app->btn_buf, "4");
    strcpy(app->profile_buf, "default");
}

static ClemsaKeeloq* clemsa_keeloq_alloc(void) {
    ClemsaKeeloq* app = malloc(sizeof(ClemsaKeeloq));
    if(!app) return NULL;
    memset(app, 0, sizeof(ClemsaKeeloq));
    clemsa_set_defaults(app);

    app->gui = furi_record_open(RECORD_GUI);
    app->view_dispatcher = view_dispatcher_alloc();
    view_dispatcher_attach_to_gui(app->view_dispatcher, app->gui, ViewDispatcherTypeFullscreen);
    view_dispatcher_set_event_callback_context(app->view_dispatcher, app);

    app->menu = submenu_alloc();
    submenu_set_header(app->menu, "Clemsa Mutancode");
    submenu_add_item(app->menu, "Serial", ClemsaItemSerial, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Disc (12b)", ClemsaItemDisc, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Cnt (16b)", ClemsaItemCnt, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Btn (1-4)", ClemsaItemBtn, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Generate & Show", ClemsaItemGenerate, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Save .sub", ClemsaItemSaveSub, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Send via RF", ClemsaItemSendRf, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Capture via RF (5s)", ClemsaItemCaptureRf, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Profile name", ClemsaItemProfileName, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Save profile", ClemsaItemProfileSave, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Load profile", ClemsaItemProfileLoad, clemsa_menu_callback, app);
    submenu_add_item(app->menu, "Delete profile", ClemsaItemProfileDelete, clemsa_menu_callback, app);
    view_set_previous_callback(submenu_get_view(app->menu), clemsa_back_from_menu);
    view_dispatcher_add_view(app->view_dispatcher, ClemsaViewMenu, submenu_get_view(app->menu));

    app->text_input = text_input_alloc();
    view_set_previous_callback(text_input_get_view(app->text_input), clemsa_back_from_text_input);
    view_dispatcher_add_view(app->view_dispatcher, ClemsaViewTextInput, text_input_get_view(app->text_input));

    app->widget = widget_alloc();
    view_set_previous_callback(widget_get_view(app->widget), clemsa_back_from_result);
    view_dispatcher_add_view(app->view_dispatcher, ClemsaViewResult, widget_get_view(app->widget));

    return app;
}

static void clemsa_keeloq_free(ClemsaKeeloq* app) {
    view_dispatcher_remove_view(app->view_dispatcher, ClemsaViewMenu);
    view_dispatcher_remove_view(app->view_dispatcher, ClemsaViewTextInput);
    view_dispatcher_remove_view(app->view_dispatcher, ClemsaViewResult);

    submenu_free(app->menu);
    text_input_free(app->text_input);
    widget_free(app->widget);
    view_dispatcher_free(app->view_dispatcher);
    furi_record_close(RECORD_GUI);

    free(app);
}

int32_t clemsa_keeloq_app(void* p) {
    UNUSED(p);
    ClemsaKeeloq* app = clemsa_keeloq_alloc();
    if(!app) return -1;
    view_dispatcher_switch_to_view(app->view_dispatcher, ClemsaViewMenu);
    view_dispatcher_run(app->view_dispatcher);
    clemsa_keeloq_free(app);
    return 0;
}
