/* ===========================================================================
   relaylink.ino  --  Emisor de DOS LUCES  (v3.0)
   Sistema de Comunicacion Simple - Redes de Computadores I - UdeA 2026-2

   El Arduino es TONTO a proposito: solo recibe una lista de estados y los
   sostiene T_SIMBOLO_US cada uno. Toda la codificacion vive en el PC, en
   codigo_manual.py. Asi se puede cambiar el codigo sin volver a programar
   la placa.

   Este sketch es OPCIONAL: tx_manual.py funciona igual sin el, diciendole a
   una persona que luces prender. El Arduino solo automatiza esa parte.

     D9  -> luz A (roja)     por rele, MOSFET o resistencia, segun el montaje
     D10 -> luz B (verde)
     D13 -> LED de la placa, sigue a la luz A (para probar sin montaje)

   LOS CUATRO ESTADOS
   ------------------
       0 = las dos apagadas  (separador)   2 = solo la luz B  (digito 1)
       1 = solo la luz A     (digito 0)    3 = las dos        (digito 2)

   COMO CONECTAR SEGUN LA LUZ QUE TENGAS
   -------------------------------------
     LED bala de 5 mm (2 V, 20 mA):  pin -> resistencia 220 ohm -> LED -> GND.
        DIRECTO AL PIN, sin rele. Conmuta en nanosegundos.
     LED de potencia 12 V:  pin -> gate de un IRLZ44N (10 kohm de gate a GND),
        drenador a la luz, fuente de 12 V aparte con GND comun.
     Bombilla de 110 V:  pin -> modulo de rele. Funciona, pero la bombilla
        tarda 100-300 ms en encender y apagar. En modo manual da igual: ahi
        cada simbolo dura un segundo entero.

   PROTOCOLO SERIAL (115200 8N1)
   -----------------------------
     PC -> Arduino:
        X:<nsim>:<HEX>  emitir esa lista de estados (2 bits por simbolo,
                        4 simbolos por byte, el primero en los bits altos)
        S:<us>          periodo de simbolo en microsegundos
        A               patron de ATENCION: 3 destellos largos de las dos luces
        B:0 | B:2       las dos luces apagadas / las dos encendidas (montaje)
        P               ping
     Arduino -> PC:
        OKX <nsim>      lista emitida
        OKS ...  OKB  OKA  PONG  READY
   =========================================================================== */

#include <Arduino.h>

const uint8_t PIN_LUZ_A = 9;
const uint8_t PIN_LUZ_B = 10;
const uint8_t PIN_LED = 13;

// Sin rele el limite lo pone la camara, no la electronica. Se deja un piso muy
// bajo para no estorbar y un techo alto para el modo manual.
const unsigned long MIN_T_SIMBOLO_US = 1000UL;        // 1000 simbolos/s
const unsigned long MAX_T_SIMBOLO_US = 5000000UL;     // 1 simbolo cada 5 s
unsigned long T_SIMBOLO_US = 200000UL;                // arranque: 5 simbolos/s

const uint16_t MAX_SIMBOLOS = 512;
uint8_t bufSim[MAX_SIMBOLOS / 4];

char linea[300];
uint16_t iLinea = 0;

void fijarLuces(uint8_t estado) {
  digitalWrite(PIN_LUZ_A, (estado & 1) ? HIGH : LOW);
  digitalWrite(PIN_LUZ_B, (estado & 2) ? HIGH : LOW);
  digitalWrite(PIN_LED, (estado & 1) ? HIGH : LOW);
}

/* Espera larga con las interrupciones ACTIVAS. delayMicroseconds() no sirve
   por encima de 16383 us, y micros() solo avanza si el Timer0 puede
   interrumpir: por eso NO se usa noInterrupts() aqui. */
void esperarHasta(unsigned long t0, unsigned long objetivo) {
  while ((unsigned long)(micros() - t0) < objetivo) { }
}

void emitir(uint16_t nsim) {
  unsigned long t0 = micros();
  for (uint16_t i = 0; i < nsim; i++) {
    uint8_t estado = (bufSim[i >> 2] >> (6 - 2 * (i & 3))) & 0x03;
    fijarLuces(estado);
    esperarHasta(t0, T_SIMBOLO_US);
    t0 += T_SIMBOLO_US;
  }
  fijarLuces(0);                       // reposo: las dos apagadas
}

void patronAtencion() {
  // Tres destellos largos de las dos luces. Le dice al receptor "preparate";
  // no se puede confundir con datos porque el codigo de linea nunca repite
  // un estado y esto sostiene el mismo estado mucho tiempo.
  for (uint8_t k = 0; k < 3; k++) {
    fijarLuces(3);
    delay(400);
    fijarLuces(0);
    delay(400);
  }
}

uint8_t hexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return 0;
}

void fijarVelocidad(unsigned long us) {
  if (us < MIN_T_SIMBOLO_US) us = MIN_T_SIMBOLO_US;
  if (us > MAX_T_SIMBOLO_US) us = MAX_T_SIMBOLO_US;
  T_SIMBOLO_US = us;
}

void procesarLinea() {
  linea[iLinea] = 0;

  if (linea[0] == 'X' && linea[1] == ':') {
    char *p1 = strchr(linea + 2, ':');
    if (!p1) { Serial.println(F("ERR formato")); Serial.println(F("OKX 0")); return; }
    *p1 = 0;
    uint16_t nsim = atoi(linea + 2);
    const char *hx = p1 + 1;
    if (nsim > MAX_SIMBOLOS) nsim = MAX_SIMBOLOS;
    uint16_t nby = (nsim + 3) / 4;
    for (uint16_t i = 0; i < nby; i++)
      bufSim[i] = (hexVal(hx[2 * i]) << 4) | hexVal(hx[2 * i + 1]);
    emitir(nsim);
    Serial.print(F("OKX ")); Serial.println(nsim);
    return;
  }

  if (linea[0] == 'S' && linea[1] == ':') {
    fijarVelocidad(atol(linea + 2));
    Serial.print(F("OKS T_SIMBOLO_US=")); Serial.println(T_SIMBOLO_US);
    return;
  }

  if (linea[0] == 'A') { patronAtencion(); Serial.println(F("OKA")); return; }

  if (linea[0] == 'B' && linea[1] == ':') {
    fijarLuces(linea[2] == '2' ? 3 : 0);
    Serial.println(F("OKB"));
    return;
  }

  if (linea[0] == 'L' && linea[1] == '?') { Serial.println(F("L:0:0")); return; }
  if (linea[0] == 'P') { Serial.println(F("PONG")); return; }
}

void setup() {
  pinMode(PIN_LUZ_A, OUTPUT);
  pinMode(PIN_LUZ_B, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  fijarLuces(0);
  Serial.begin(115200);
  Serial.print(F("READY luces2 v3.0 T_SIMBOLO_US=")); Serial.println(T_SIMBOLO_US);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (iLinea > 0) { procesarLinea(); iLinea = 0; }
    } else if (iLinea < sizeof(linea) - 1) {
      linea[iLinea++] = c;
    }
  }
}
