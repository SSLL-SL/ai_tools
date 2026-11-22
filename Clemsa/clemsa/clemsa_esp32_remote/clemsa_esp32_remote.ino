/*
 * Clemsa Mutancode - Mando fijo con ESP32 + CC1101
 * 
 * Transmite SIEMPRE la misma trama KeeLoq al pulsar el botón.
 * El receptor no valida el counter, así que usamos counter=0.
 *
 * Hardware:
 *   ESP32 (C3, S3, o qualquer) + módulo CC1101 433MHz
 *
 * Conexiones CC1101 → ESP32:
 *   CS/SS  → GPIO5
 *   SCK    → GPIO18
 *   MISO   → GPIO19
 *   MOSI   → GPIO23
 *   GDO0   → GPIO2 (opcional, no necesario para TX)
 *
 * Instalar librería: ELECHOUSE_CC1101 (Library Manager)
 *
 * Uso:
 *   1. Genera la trama RAW con el script Python:
 *      python3 clemsa_mutancode_gen.py "0480 16051" 53 0 4 --raw
 *   2. Copia los valores de RAW_Data al array 'raw_data' de abajo
 *   3. Sube al ESP32
 *   4. Pulsa el botón → transmite siempre la misma trama
 */

#include <ELECHOUSE_CC1101.h>

// ============ CONFIGURACIÓN ============

#define CC1101_CS    5    // Pin CS del CC1101
#define BTN_PIN      4    // Pin del botón (GPIO4)
#define LED_PIN      2    // Pin del LED integrado (GPIO2)
#define FREQ         433.92  // Frecuencia en MHz

// Tiempos en microsegundos (protocolo KeeLoq / Clemsa Mutancode)
#define TE           400   // Time element base

// ============ TRAMA RAW ============
// Pegar aquí los valores RAW_Data del script Python
// Formato: duraciones en microsegundos (+alto, -bajo)
// Ejemplo generado con: clemsa_mutancode_gen.py "0480 16051" 53 0 4 --raw

const int raw_data[] = {
  // Preamble: 10 pares de alto/bajo
  +TE, -TE, +TE, -TE, +TE, -TE, +TE, -TE, +TE, -TE,
  +TE, -TE, +TE, -TE, +TE, -TE, +TE, -TE, +TE, -TE,
  // Datos: 64 bits (LSB first)
  // Pegar aquí los valores del script Python después de "RAW_Data: "
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE, -TE*2,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE, -TE*2,
  +TE*2, -TE, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE, -TE*2,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE, -TE*2, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE, -TE*2,
  +TE*2, -TE, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE*2, -TE, +TE*2, -TE,
  +TE, -TE*2, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE*2, -TE, +TE, -TE*2, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE*2, -TE,
  +TE*2, -TE, +TE, -TE*2, +TE*2, -TE, +TE, -TE*2,
  +TE*2, -TE, +TE*2, -TE, +TE*2, -TE, +TE, -TE*2,
};

const int raw_len = sizeof(raw_data) / sizeof(raw_data[0]);

// ============ BOTÓN CON DEBOUNCE ============

bool lastBtn = HIGH;
unsigned long lastDebounce = 0;
#define DEBOUNCE_MS 50

bool checkButton() {
  bool reading = digitalRead(BTN_PIN);
  if (reading != lastBtn) {
    lastDebounce = millis();
  }
  lastBtn = reading;
  if ((millis() - lastDebounce) > DEBOUNCE_MS) {
    if (reading == LOW) {  // Botón pulsado (pull-up)
      return true;
    }
  }
  return false;
}

// ============ TRANSMISIÓN RAW ============

void transmitRaw() {
  ELECHOUSE_CC1101.setFsThreshold(0);  // Reset
  ELECHOUSE_CC1101.setChannel(0);
  ELECHOUSE_CC1101.setModulation(2);   // ASK/OOK
  ELECHOUSE_CC1101.setPA(10);          // Potencia +10 dBm
  ELECHOUSE_CC1101.setMHZ(FREQ);
  ELECHOUSE_CC1101.setCCMode(0);       // Modo raw
  ELECHOUSE_CC1101.SetTx();
  delayMicroseconds(100);

  for (int i = 0; i < raw_len; i++) {
    int dur = raw_data[i];
    if (dur > 0) {
      // Alto: encender portadora
      digitalWrite(ELECHOUSE_CC1101.sdoPin, HIGH);
      delayMicroseconds(dur);
    } else {
      // Bajo: apagar portadora
      digitalWrite(ELECHOUSE_CC1101.sdoPin, LOW);
      delayMicroseconds(-dur);
    }
  }

  // Apagar portadora al final
  digitalWrite(ELECHOUSE_CC1101.sdoPin, LOW);
  ELECHOUSE_CC1101.setSidle();
}

// ============ SETUP ============

void setup() {
  pinMode(BTN_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  ELECHOUSE_CC1101.Init();
  ELECHOUSE_CC1101.setGDO(ELECHOUSE_CC1101.sdoPin);
  ELECHOUSE_CC1101.setSidle();

  Serial.begin(115200);
  Serial.println("Clemsa Mutancode - Mando Fijo");
  Serial.println("Pulsa el botón para transmitir");
}

// ============ LOOP ============

void loop() {
  if (checkButton()) {
    Serial.println("Transmitiendo...");
    digitalWrite(LED_PIN, HIGH);
    transmitRaw();
    digitalWrite(LED_PIN, LOW);
    Serial.println("Listo");
    delay(500);  // Anti-rebote extra
  }
}
