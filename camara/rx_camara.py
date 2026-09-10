# -*- coding: utf-8 -*-
"""Receptor por camara del sistema de dos luces.

Redes de Computadores I, UdeA 2026-2, Proyecto 01. Lee las dos luces de un
video o de la camara en vivo y reconstruye el bloque de celdas.

Sin argumentos pregunta que analizar. Solo necesita numpy y opencv-python.

    python rx_camara.py --video "toma.mp4"
    python rx_camara.py --camara 1
    python rx_camara.py --camaras                 lista las camaras del PC
    python rx_camara.py --simular-vivo "toma.mp4"  un video, como si fuera
                                                  la camara en vivo
    python rx_camara.py --autoprueba              revisa el codigo sin camara

Secciones. Se leen de arriba abajo y cada una usa solo las anteriores, asi
que se puede entrar por cualquiera sin haber leido lo de abajo:

    0. PARAMETROS      lo ajustable, todo junto.
    1. EL CODIGO       bits <-> celdas.
    2. PDI             imagen -> donde estan las luces y cual esta prendida.
         2.1 medir un recuadro      pixeles  -> numeros
         2.2 de numeros a estados   numeros  -> que luz esta prendida
         2.3 encontrar las luces    imagen   -> coordenadas
    3. DECODIFICADOR   estados en el tiempo -> bloque de celdas.
    4. MEDIR           archivo o camara, por el mismo camino.
         4.1 lo que se mide de una pareja      4.4 abrir la camara
         4.2 de lo medido al bloque            4.5 la camara en vivo
         4.3 un archivo de video
    5. INTERFAZ        elegir la fuente y pintar el resultado.
    6. ARRANQUE

Las 1 y 3 son puro calculo y --autoprueba las prueba enteras; la 2 es la unica
que toca pixeles y la 5 la unica que abre ventanas.

Cosas a tener en cuenta:

- Cual luz esta prendida se decide por posicion (dos puntos separados, sirve
  con luces iguales) o por color (si se funden en un punto, hacen falta colores
  distintos). Se prueban las dos.
- La velocidad maxima es fps/3: 10 simbolos/s a 30 fps, 20 a 60. Reexportar un
  video a menos fps se come el margen.
- La camara tiene que estar quieta. Para tomas a pulso esta
  rx_camara_con_seguimiento.py, que sigue las luces cuadro a cuadro.
- Un celular a 60 fps por IP Webcam es lo mejor (--camara
  http://IP:8080/video); tambien vale DroidCam, Iriun, EpocCam o el Enlace
  movil de Windows. Imagen
  negra = tapa de privacidad, otra app usando la camara, o exposicion baja.
"""

import argparse
import math
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# OpenCV avisa por cada cuadro al pedir el video sin convertir a color
# ("Unknown/unsupported picture format: yuv420p", ver abrir_video) y llena la
# consola. Hay que callarlo antes de importar cv2, que es cuando lee el nivel.
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "0")

import cv2
import numpy as np

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


# ##########################################################################
#  0. PARAMETROS
# ##########################################################################

# --- LAS LUCES ---------------------------------------------------------------
# Cual luz es la "A": None prueba las dos y se queda con la del CRC valido.
# Fijarlo ahorra la mitad del trabajo si ya se sabe el cableado.
LUZ_A_ES_LA_MAS_ROJA = None

# Separacion entre las dos luces (min, max), en pixeles del cuadro original.
# En el cuarto quedan a 36-40 px sobre 1920, al aire libre a unos 52.
SEPARACION_LUCES_PX = (14.0, 520.0)

# --- VELOCIDAD --------------------------------------------------------------
# Simbolos/s del transmisor; None = medirlo sobre la señal.
SIMBOLOS_POR_SEGUNDO = None

# Las que se prueban si la medida no cuadra.
VELOCIDADES_TIPICAS = (5, 4, 6, 3, 8, 2, 10, 1, 12.5, 15, 20)

# Menos cuadros por simbolo que esto y la grabacion no sirve (medido).
CUADROS_POR_SIMBOLO_MIN = 3.0

# --- BUSCAR LAS LUCES ------------------------------------------------------
# Banda de parpadeo (Hz). Distingue un LED de la gente o las hojas, que van por
# debajo de 2 Hz.
BANDA_PARPADEO = (2.0, 25.0)

# Ancho al que se reduce el cuadro solo para buscar (medir va sin reducir). No
# bajarlo: a menos resolucion las dos luces del cuarto se pegan y picos_de_luz,
# al borrar la primera, se lleva tambien la segunda.
ANCHO_BUSQUEDA = 640

# Cuadros seguidos para la FFT: 90 son 1,5 s a 60 fps.
CUADROS_BUSQUEDA = 90

# Fraccion de pixeles -los mas brillantes- sobre los que se calcula la FFT.
#
# El mapa acaba multiplicado por brillo^2, asi que todo lo oscuro sale cero de
# todas formas: transformar solo lo que alumbra da EL MISMO resultado mucho mas
# rapido. Medido sobre un tramo real de 90 cuadros de 640x360:
#
#       imagen entera (230.400 px)  1565 ms
#       el 2% mas brillante          128 ms   <- picos identicos
#
# La busqueda era el 75% del tiempo de descifrar un archivo, asi que esto es lo
# que mas se nota. Subirlo es mas seguro y mas lento; 1.0 lo desactiva.
FRACCION_PIXELES_FFT = 0.02

# Tramos del video de donde se sacan candidatas. Saltar de tramo en tramo es lo
# que hace rapida la busqueda.
TRAMOS_BUSQUEDA = 10

# Parejas que se miden a la vez en un archivo: ocho cuestan casi como una.
MAX_PAREJAS_ARCHIVO = 8

# Cuanto se tienen que mover las luces entre tramos para creer que la camara se
# movio. Por debajo es temblor de la rejilla (1 px reducido = 3 del original).
DERIVA_MINIMA_PX = 10.0

# Cuando dos propuestas de la busqueda son la misma pareja. La SEPARACION es
# la que identifica al montaje, porque es fija; el punto puede bailar mas, ya
# que la busqueda trabaja sobre el cuadro reducido.
TOLERANCIA_SEPARACION_PX = 14.0
TOLERANCIA_PUNTO_PX = 90.0

# --- MEDIR ----------------------------------------------------------------
# A partir de que valor un pixel cuenta como quemado (ver saturados()).
#
# Son DOS valores, y hace falta que lo sean: el receptor lee de dos maneras y
# NO usan la misma escala.
#
#   BGR       blanco pleno = 255.  240 va bien.
#   plano Y   el video de consumo va en rango LIMITADO (TV): el blanco pleno
#             es 235, no 255.  Con 240 la cuenta sale SIEMPRE cero y el modo
#             por quemados -el que mas manda de dia- queda MUERTO sin avisar.
#             Medido sobre una luz totalmente saturada: el nucleo llega a 239.
#
# El camino rapido de archivo (abrir_video con solo_luz) entrega el plano Y, y
# la camara en vivo entrega BGR, asi que cada uno usa el suyo.
UMBRAL_SATURADO_BGR = 240
UMBRAL_SATURADO_LUZ = 230
UMBRAL_SATURADO = UMBRAL_SATURADO_BGR      # el de siempre, para quien lo use

# Como se mide el COLOR dentro del recuadro (solo importa en el modo por color,
# el de las luces fundidas en un punto):
#
#   "ponderado"  media de todo el recuadro pesada por el brillo. Las DOS luces
#                aportan, asi que el estado "las dos encendidas" cae de verdad
#                en medio.  RECOMENDADO.
#   "picos"      solo los N pixeles mas brillantes (lo que se hacia antes). Si
#                un LED se ve mas brillante que el otro, "las dos encendidas"
#                se lee como si estuviera solo el brillante y no descifra.
MODO_CROMA = "ponderado"

# Nada se decide con valores absolutos: una luz esta "prendida" cuando pasa de
# esta fraccion de su propio recorrido, y solo si el recorrido llega al margen.
# Subir el margen ignora luces debiles; bajarlo hace caso a cualquier sombra.
MARGEN_PARPADEO = 4.0
FRAC_ENCENDIDO = 0.45

# Muestras a cada lado para los percentiles moviles (~4 s a 60 fps). Tiene que
# cubrir varias copias del bloque, no un simbolo.
VENTANA_UMBRALES = 260

# Cada cuantas muestras se recalculan esos percentiles; en medio se interpolan.
# Casi no se mueven, asi que calcularlos uno a uno era 40 veces mas caro.
PASO_UMBRALES = 20

# Rachas mas cortas que esta fraccion del simbolo se tiran: glitch de que las
# dos lamparas no cambian a la vez.
FRAC_GLITCH = 0.45

# Factores del periodo de simbolo que se prueban si el nominal no cuadra.
BARRIDO = [0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1]

# --- CAMARA EN VIVO -----------------------------------------------------
# Cual camara: numero (0 = la primera), parte del nombre ("iriun") o URL
# http/rtsp. Se cambia con --camara.
CAMARA = 0

# fps que se le piden. Pedir 60 es lo importante.
FPS_CAMARA = 60.0

# None deja decidir a la camara (empezar asi). Un valor como -7 baja la
# exposicion y conserva el color, pero deja la imagen casi negra. En vivo se
# ajusta con + y -.
EXPOSICION_CAMARA = None

# Cada cuantos segundos se reintenta descifrar mientras escucha.
REINTENTO_VIVO_S = 2.0

# Medidas de historia que se guardan (a 60 fps, 3600 = 1 min). No son imagenes,
# son cuatro numeros por cuadro.
HISTORIA_VIVO_CUADROS = 3600

# Cuadros reducidos que se guardan para precargar una pareja nueva con lo ya
# ocurrido. Sin esto la escucha nace 2-3 s tarde, encima del preambulo, y
# pierde su propia transmision. Van en gris para que quepan.
CUADROS_PRECARGA_VIVO = 240

# Segundos sin ver parpadeo antes de soltar una pareja. Mas que el hueco entre
# dos copias del bloque.
PACIENCIA_VIVO_S = 8.0

# Parejas que se siguen a la vez en vivo.
MAX_CANDIDATOS_VIVO = 8

# Cada cuanto se vuelve a buscar mientras no salga el bloque.
BUSQUEDA_CADA_S = 3.0

# --- LA VENTANA DE LA CAMARA EN VIVO -------------------------------------
# Ancho al que se muestra la imagen. Solo afecta a lo que se ve, no a lo que
# se mide: medir siempre va sobre el cuadro original.
ANCHO_VENTANA_VIVO = 960

# LUPA: un recuadro en una esquina con la zona ampliada, para poder apuntar
# las luces sin acercarse a la pantalla. Ampliia, por este orden de
# preferencia: la pareja que mas pinta de transmisor, o el recuadro marcado a
# mano con la tecla m.
LUPA_ACTIVA = True
LUPA_LADO_PX = 240                    # lado del recuadro de la lupa, en pantalla
LUPA_ESQUINA = "superior-derecha"     # superior/inferior + derecha/izquierda
LUPA_AUMENTO_MAX = 10.0               # tope, para que no salga un mosaico
LUPA_MARGEN_PX = 12                   # separacion respecto al borde

# Panel de teclas: el rotulo con lo que se puede pulsar.
PANEL_TECLAS = True

# Una vez fijados, los recuadros de una pareja no se mueven. Moverlos empeora:
# un servo de brillo se va solo hacia el halo de la luz encendida, y saltar a
# la siguiente busqueda deja un escalon de brillo en mitad de la trama. Si las
# luces se mueven de verdad, en vivo entra una pareja nueva y en archivo se
# interpola entre tramos (ver trayectoria_de).


# ##########################################################################
#  1. EL CODIGO
#     Cuadricula de celdas <-> estados de las dos luces. Solo bits.
# ##########################################################################

# --------------------------------------------------------- alfabeto -------
ALFABETO = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"   # 27 letras del alfabeto espanol
NEGRO = "#"      # recuadro negro
BLANCO = "_"     # recuadro blanco vacio


def celda_a_bits(c):
    """Codigo de prefijo:  00 = negro | 01 = blanco | 1 + 5 bits = letra.

    Los recuadros son mucho mas frecuentes que las letras en un dibujo, asi
    que se les da el codigo corto: un bloque de puros recuadros ocupa un
    tercio de lo que ocuparia con 6 bits fijos por celda.
    """
    c = c.upper()
    if c == NEGRO:
        return "00"
    if c in (BLANCO, " ", ""):
        return "01"
    idx = ALFABETO.find(c)
    if idx < 0:
        raise ValueError("Caracter no valido en la celda: %r" % c)
    return "1" + format(idx, "05b")


def bits_a_celdas(bits, n_celdas):
    """Inverso. Devuelve (lista_de_celdas, cuantos_bits_se_usaron)."""
    out, i = [], 0
    for _ in range(n_celdas):
        if i >= len(bits):
            raise ValueError("bits insuficientes")
        if bits[i] == "0":
            if i + 2 > len(bits):
                raise ValueError("bits insuficientes")
            out.append(NEGRO if bits[i + 1] == "0" else BLANCO)
            i += 2
        else:
            if i + 6 > len(bits):
                raise ValueError("bits insuficientes")
            idx = int(bits[i + 1:i + 6], 2)
            if idx >= len(ALFABETO):
                raise ValueError("indice de letra invalido")
            out.append(ALFABETO[idx])
            i += 6
    return out, i


# --------------------------------------------------- sumas de control -----
def crc8(bits):
    """CRC-8/ATM (polinomio 0x07) sobre bits. Protege la cabecera."""
    crc = 0
    for i in range(0, len(bits), 8):
        byte = int((bits[i:i + 8] + "0" * 8)[:8], 2)
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE (0x1021, init 0xFFFF). Protege la trama entera."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _crc16_bits(bits):
    relleno = bits + "0" * ((-len(bits)) % 8)
    datos = bytes(int(relleno[i:i + 8], 2) for i in range(0, len(relleno), 8))
    return crc16(datos)


# --------------------------------------------- codigo de linea (4 estados) -
#     estado 0 = las dos apagadas
#     estado 1 = solo la luz A (roja)
#     estado 2 = solo la luz B (verde)
#     estado 3 = las dos encendidas
APAGADO, LUZ_A, LUZ_B, AMBAS = 0, 1, 2, 3
NOMBRES_ESTADO = {APAGADO: "--", LUZ_A: "A-", LUZ_B: "-B", AMBAS: "AB"}

# LA REGLA: dos simbolos consecutivos NUNCA son iguales. Desde un estado hay 3
# destinos posibles, asi que cada simbolo lleva un digito en base 3 (un trit).
# Consecuencia importante: cada frontera de simbolo se ve como un CAMBIO, y el
# receptor no tiene que recuperar el reloj ni saber la velocidad. Es inmune a
# que la camara pierda cuadros y a que la tasa fluctue.
#
# 3 bits caben en 2 trits (0..7 dentro de 0..8): 1,5 bits por simbolo. El
# limite teorico es log2(3) = 1,585, o sea que se aprovecha el 95%.
BITS_POR_GRUPO = 3
TRITS_POR_GRUPO = 2

# Preambulo: alternancia A,B,A,B... Es inconfundible (nunca las dos, nunca
# ninguna) y sirve para detectar que hay alguien transmitiendo.
SIMBOLOS_PREAMBULO = 12
PREAMBULO = [LUZ_A if i % 2 == 0 else LUZ_B for i in range(SIMBOLOS_PREAMBULO)]

# Delimitador de inicio: usa justo los dos estados que el preambulo no toca,
# asi que no puede confundirse con el.
SFD = [AMBAS, APAGADO]


def destinos_desde(estado):
    """Los 3 estados a los que se puede saltar desde 'estado', en orden."""
    return [e for e in (APAGADO, LUZ_A, LUZ_B, AMBAS) if e != estado]


def bits_a_trits(bits):
    """Bits -> digitos en base 3, de 3 en 3. Rellena el ultimo grupo."""
    relleno = bits + "0" * ((-len(bits)) % BITS_POR_GRUPO)
    trits = []
    for i in range(0, len(relleno), BITS_POR_GRUPO):
        v = int(relleno[i:i + BITS_POR_GRUPO], 2)
        trits.append(v // 3)
        trits.append(v % 3)
    return trits


def trits_a_bits(trits, nbits=None):
    """Inverso de bits_a_trits. 'nbits' recorta el relleno del final."""
    bits = []
    for i in range(0, len(trits) - 1, TRITS_POR_GRUPO):
        v = trits[i] * 3 + trits[i + 1]
        if v > 7:
            v = 7                     # grupo corrompido; el CRC lo detectara
        bits.append(format(v, "03b"))
    salida = "".join(bits)
    return salida[:nbits] if nbits is not None else salida


def trits_a_simbolos(trits, estado_inicial=APAGADO):
    """Aplica la regla de transicion: cada trit dice a cual de los 3 estados
    distintos del actual hay que saltar."""
    simbolos, estado = [], estado_inicial
    for t in trits:
        estado = destinos_desde(estado)[t % 3]
        simbolos.append(estado)
    return simbolos


def simbolos_a_trits(simbolos, estado_inicial=APAGADO):
    """Inverso. Un estado repetido no puede ser un simbolo valido, asi que se
    trata como el mismo simbolo visto dos veces y se ignora."""
    trits, estado = [], estado_inicial
    for s in simbolos:
        if s == estado:
            continue
        trits.append(destinos_desde(estado).index(s))
        estado = s
    return trits


def codificar_linea(bits):
    """Cadena de bits -> lista completa de estados, con preambulo y SFD."""
    simbolos = list(PREAMBULO) + list(SFD)
    simbolos += trits_a_simbolos(bits_a_trits(bits),
                                 estado_inicial=simbolos[-1])
    return simbolos


def colapsar(simbolos):
    """Quita estados repetidos consecutivos.

    La regla de transicion prohibe dos simbolos seguidos iguales, asi que toda
    repeticion viene de que la camara vio el mismo estado en varios cuadros.
    Colapsar siempre es correcto.
    """
    salida = []
    for s in simbolos:
        if not salida or salida[-1] != s:
            salida.append(s)
    return salida


def decodificar_linea(simbolos, nbits=None):
    """Estados observados -> bits. Busca el preambulo seguido del SFD.

    Devuelve (bits, indice) o (None, -1). Se exige que el SFD venga precedido
    de al menos 4 alternancias A/B, o cualquier cambio a AMBAS-APAGADO dentro
    de los datos se tomaria por un arranque de trama.
    """
    simbolos = colapsar(simbolos)
    for i in range(len(simbolos) - 1):
        if simbolos[i] != AMBAS or simbolos[i + 1] != APAGADO:
            continue
        alternancia, j = 0, i - 1
        while j >= 0 and simbolos[j] in (LUZ_A, LUZ_B):
            if j + 1 <= i - 1 and simbolos[j] == simbolos[j + 1]:
                break
            alternancia += 1
            j -= 1
        if alternancia < 4:
            continue
        trits = simbolos_a_trits(simbolos[i + 2:], estado_inicial=APAGADO)
        return trits_a_bits(trits, nbits), i + 2
    return None, -1


def simbolos_necesarios(nbits):
    """Cuantos simbolos ocupa en el canal una carga de 'nbits' bits."""
    grupos = int(math.ceil(nbits / float(BITS_POR_GRUPO)))
    return len(PREAMBULO) + len(SFD) + grupos * TRITS_POR_GRUPO


# ------------------------------------------------------------ la trama ----
# Todo el bloque va en UNA trama. El protocolo optico original mandaba una
# trama por fila, y cada una arrastraba 88 bits fijos para llevar unos 38
# utiles: 78% de lastre. Con luces a unos pocos simbolos por segundo cada bit
# cuesta cientos de milisegundos y ese lastre es el problema dominante.
#
#     CABECERA (32 bits)          con su propio CRC-8
#       TIPO    4 bits
#       FILAS   5 bits   (1..31)
#       COLS    5 bits   (1..31)
#       NBITS  10 bits   (longitud del payload en bits)
#       CRC8    8 bits   (de los 24 anteriores)
#     PAYLOAD  NBITS bits         celdas con el codigo de prefijo
#     CRC16    16 bits            de cabecera + payload
#
# La cabecera lleva CRC propio para que, si el payload se corrompe, el receptor
# todavia sepa las dimensiones y pueda pintar lo que si llego.
#
# Los tres tipos son los del protocolo, aunque este receptor solo arme tramas
# de bloque: los otros dos los manda el transmisor y estan aqui para que la
# tabla del campo TIPO quede completa en un solo sitio.
TIPO_BLOQUE, TIPO_ATENCION, TIPO_REINICIO = 1, 2, 3
BITS_CABECERA, BITS_CRC = 32, 16
MAX_FILAS = MAX_COLS = 31
MAX_NBITS = 1023


def celdas_a_bits(grid):
    """La cuadricula entera, fila por fila, en bits."""
    return "".join(celda_a_bits(c) for fila in grid for c in fila)


def construir_trama(tipo, filas, cols, payload_bits=""):
    """Arma la trama completa (cabecera + payload + CRC-16) como bits."""
    if filas > MAX_FILAS or cols > MAX_COLS:
        raise ValueError("dimensiones fuera de rango (max %dx%d)"
                         % (MAX_FILAS, MAX_COLS))
    if len(payload_bits) > MAX_NBITS:
        raise ValueError("payload de %d bits, maximo %d"
                         % (len(payload_bits), MAX_NBITS))
    cab = (format(tipo, "04b") + format(filas, "05b") +
           format(cols, "05b") + format(len(payload_bits), "010b"))
    cab += format(crc8(cab), "08b")
    cuerpo = cab + payload_bits
    return cuerpo + format(_crc16_bits(cuerpo), "016b")


def leer_cabecera(bits):
    """(tipo, filas, cols, nbits) si el CRC-8 cuadra, o None."""
    if len(bits) < BITS_CABECERA:
        return None
    cab, crc = bits[:24], bits[24:32]
    if crc8(cab) != int(crc, 2):
        return None
    return (int(cab[0:4], 2), int(cab[4:9], 2),
            int(cab[9:14], 2), int(cab[14:24], 2))


def analizar_trama(bits):
    """Decodifica una trama. Devuelve lo que se haya podido rescatar.

    'crc_ok' False con 'cabecera_ok' True significa que las dimensiones son
    fiables pero el contenido puede tener errores: aun asi se entrega, porque
    pintar 78 de 80 celdas bien vale mas que no pintar nada.
    """
    cab = leer_cabecera(bits)
    if cab is None:
        return {"cabecera_ok": False, "crc_ok": False}
    tipo, filas, cols, nbits = cab
    fin = BITS_CABECERA + nbits
    payload = bits[BITS_CABECERA:fin]
    crc_ok = False
    if len(bits) >= fin + BITS_CRC and len(payload) == nbits:
        crc_ok = _crc16_bits(bits[:fin]) == int(bits[fin:fin + BITS_CRC], 2)
    return {"cabecera_ok": True, "crc_ok": crc_ok, "tipo": tipo,
            "filas": filas, "cols": cols, "nbits": nbits, "payload": payload}


# ##########################################################################
#  2. PDI
#     La unica parte que toca pixeles, en el orden en que se usa:
#
#       2.1  de un recuadro salen numeros    brillo, quemados, croma
#       2.2  de los numeros sale un estado   que luz esta prendida
#       2.3  de una imagen salen coordenadas donde estan las luces
#
#     Las dos primeras miran un sitio que ya se conoce; la tercera es la que
#     lo encuentra. Ninguna guarda imagenes: de cada cuadro salen cuatro
#     numeros y el cuadro se tira.
# ##########################################################################

# ---------------------------------------------- 2.1 medir un recuadro -----

def suavizar(img, k=5):
    """GaussianBlur que nunca revienta.

    Con recuadros diminutos, o si OpenCV se queda sin memoria, GaussianBlur
    lanza una excepcion de C++ sin mensaje. En vivo eso tumbaba una escucha de
    un minuto por un solo cuadro raro; sin suavizar se mide algo peor, pero no
    se pierde la toma.
    """
    if img.size == 0:
        return img
    try:
        return cv2.GaussianBlur(img, (k, k), 0)
    except cv2.error:
        return img


def recorte_centrado(f, centro, lado):
    """El cuadradito de una luz, siempre dentro de la imagen."""
    alto, ancho = f.shape[:2]
    d = int(np.clip(lado, 1, max(1, min(alto, ancho) // 2 - 1)))
    x = int(np.clip(round(centro[0]), d, ancho - d - 1))
    y = int(np.clip(round(centro[1]), d, alto - d - 1))
    return np.ascontiguousarray(f[y - d:y + d, x - d:x + d])


def recorte_caja(f, caja):
    """Un recuadro (x, y, ancho, alto) cualquiera, recortado a la imagen."""
    alto, ancho = f.shape[:2]
    x0, y0, w, h = caja
    x0 = int(np.clip(x0, 0, max(0, ancho - 6)))
    y0 = int(np.clip(y0, 0, max(0, alto - 6)))
    x1 = int(np.clip(x0 + w, x0 + 6, ancho))
    y1 = int(np.clip(y0 + h, y0 + 6, alto))
    return np.ascontiguousarray(f[y0:y1, x0:x1])


def brillo_de(roi):
    """Luminancia media del 5% de pixeles mas brillantes del recuadro.

    Promediar el recuadro entero diluye una luz pequeña hasta borrarla, asi
    que solo cuenta la parte que alumbra.
    """
    if roi.size == 0:
        return 0.0
    suave = suavizar(roi).astype(np.float32)
    plano = (suave.mean(2) if suave.ndim == 3 else suave).ravel()
    n = max(6, int(plano.size * 0.05))
    return float(np.sort(plano)[-n:].mean())


def saturados(roi, umbral=UMBRAL_SATURADO):
    """Cuantos pixeles del recuadro estan quemados. Otra forma de "prendida".

    De dia el brillo casi no sirve: la escena esta iluminada y el LED nunca se
    ve oscuro (223 a 251 al aire libre, que se lo come cualquier sombra),
    mientras que esta cuenta va de 0 a 350. Lo que desaparece al apagarse no
    es el NIVEL del nucleo sino su AREA, y por eso el umbral es fijo.

    No sustituye al brillo, que es el que gana cuando el LED no satura -de
    noche, o tan lejos que el punto mide cuatro pixeles- y aqui sale cero.
    """
    if roi.size == 0:
        return 0.0
    gris = roi.mean(2) if roi.ndim == 3 else roi
    return float(np.count_nonzero(gris > umbral))


def lum_y_croma(roi, modo=None):
    """(luminancia, croma) de un recuadro BGR.

    croma = (R-G)/(R+G): positivo = luz roja, negativo = verde, ~0 = las dos
    (o ninguna, que se distingue por la luminancia). Dividir por (R+G) lo hace
    independiente de la exposicion.

    En los dos modos se descartan primero los pixeles SATURADOS, y eso importa:
    de cerca el nucleo satura en R=G=B=255 y ahi ya no hay color. El color vive
    en el halo. Promediar el recuadro entero a secas tampoco vale, porque
    diluye la luz en el fondo.

    Lo que cambia entre los dos modos es COMO se juntan los pixeles que quedan:

      "ponderado"  media de todo el recuadro pesada por brillo^2. Las DOS luces
                   aportan a la vez, cada una segun lo que alumbre.
      "picos"      solo los N mas brillantes.

    Y esa diferencia decide si el modo por color funciona o no. Con "picos",
    cuando las dos luces estan encendidas, gana la que se vea mas brillante y
    el par se lee como si solo estuviera esa: medido sobre una toma con un LED
    un 20% mas luminoso que el otro, el estado "las dos" se leia como "solo la
    verde" el 100% de las veces, y el CRC no cerraba nunca. Con "ponderado", el
    mismo caso acierta el 100% de los cuadros.
    """
    if roi.size == 0:
        return 0.0, 0.0
    suave = suavizar(roi).astype(np.float32)
    b, g, r = suave[:, :, 0], suave[:, :, 1], suave[:, :, 2]
    plano = (b + g + r) / 3.0

    if (modo or MODO_CROMA) == "ponderado":
        # peso = brillo^2 sobre lo que no esta quemado. El cuadrado separa la
        # luz del fondo: un halo al doble de brillo que la pared pesa cuatro
        # veces mas, asi que el fondo no arrastra el color aunque ocupe mas.
        peso = np.where(plano < 250, plano, 0.0) ** 2
        total = float(peso.sum())
        if total <= 0:                      # todo quemado: se mide tal cual
            peso, total = np.ones_like(plano), float(plano.size)
        mr = float((r * peso).sum() / total)
        mg = float((g * peso).sum() / total)
        mb = float((b * peso).sum() / total)
        return float(plano.max()), (mr - mg) / (mr + mg + 1.0)

    llano = plano.ravel()
    n = max(12, int(llano.size * 0.001))
    # Primero se descartan los saturados y DESPUES se toman los mas brillantes
    # de lo que queda. Al reves no sirve: con la luz cerca, mas del 3% del
    # cuadro puede estar saturado y un percentil fijo devuelve solo nucleo
    # blanco, sin color.
    idx_ok = np.flatnonzero(llano < 250)
    if idx_ok.size < n:
        idx_ok = np.arange(llano.size)
    n = min(n, idx_ok.size)
    orden = np.argpartition(llano[idx_ok], idx_ok.size - n)[idx_ok.size - n:]
    sel = idx_ok[orden]

    mr = float(r.ravel()[sel].mean())
    mg = float(g.ravel()[sel].mean())
    mb = float(b.ravel()[sel].mean())
    return (mr + mg + mb) / 3.0, (mr - mg) / (mr + mg + 1.0)


# ------------------------------------------- 2.2 de numeros a estados -----
#
# Ninguna decision usa valores absolutos, siempre el RECORRIDO de la serie en
# un rato: el control de exposicion del celular deriva durante la toma (en una
# grabacion real el croma del verde paso de -0,09 a -0,21) y con umbrales fijos
# el preambulo se lee mal y nunca engancha.


def recorrido(v):
    """(p10, p90) de una serie: entre esos dos valores se mueve la luz."""
    return float(np.percentile(v, 10)), float(np.percentile(v, 90))


def hay_cambio(p10, p90):
    """Si el recorrido da para creer que ahi hay una luz que se enciende.

    Vale con escalares y con los vectores de umbrales_moviles.
    """
    return (p90 - p10) >= MARGEN_PARPADEO


def encendida(v, p10, p90, frac=FRAC_ENCENDIDO):
    """Mascara de "la luz esta prendida en este cuadro"."""
    return np.asarray(v) >= p10 + frac * (p90 - p10)


def anclas_de(n, paso=PASO_UMBRALES):
    """Muestras donde se calculan de verdad los umbrales.

    Entre ancla y ancla se interpola: ver PASO_UMBRALES.
    """
    anclas = np.arange(0, n, paso)
    if len(anclas) == 0 or anclas[-1] != n - 1:
        anclas = np.append(anclas, n - 1)
    return anclas


def umbrales_moviles(v, ventana=VENTANA_UMBRALES, bajo=10, alto=90,
                     paso=PASO_UMBRALES):
    """Dos percentiles de una ventana movil CENTRADA, para toda la serie.

    Devuelve dos vectores del largo de v.
    """
    n = len(v)
    anclas = anclas_de(n, paso)
    lo = np.empty(len(anclas), dtype=np.float32)
    hi = np.empty(len(anclas), dtype=np.float32)
    for k, i in enumerate(anclas):
        trozo = v[max(0, i - ventana):min(n, i + ventana)]
        lo[k], hi[k] = np.percentile(trozo, (bajo, alto))
    if n == len(anclas):
        return lo, hi
    todos = np.arange(n)
    return np.interp(todos, anclas, lo), np.interp(todos, anclas, hi)


def clasificar_por_posicion(brillos_a, brillos_b, ventana=VENTANA_UMBRALES):
    """Dos series de brillo -> estado de las luces en cada cuadro.

    estado = (A prendida) + 2*(B prendida). Sirve con luces del mismo color,
    que es lo normal; lo unico que hace falta es verlas como dos puntos.
    """
    a = np.asarray(brillos_a, dtype=np.float32)
    b = np.asarray(brillos_b, dtype=np.float32)
    n = len(a)
    if n == 0 or len(b) != n:
        return []
    estados = np.zeros(n, dtype=int)
    for serie, peso in ((a, LUZ_A), (b, LUZ_B)):
        p10, p90 = umbrales_moviles(serie, ventana)
        estados += peso * (hay_cambio(p10, p90) & encendida(serie, p10, p90))
    return list(estados)


def tres_grupos(valores, vueltas=12):
    """Parte una serie de cromas en TRES grupos y devuelve las dos fronteras.

    Es un k-medias de una dimension con k=3 (verde, las dos, roja), arrancado
    en los percentiles 10/50/90 para que salga siempre igual: no hay azar y no
    hace falta sklearn.

    Sustituye a cortar el recorrido en tercios fijos, y la diferencia es
    grande. Los tercios suponen que "las dos encendidas" cae justo en el medio
    del recorrido, y eso solo pasa si los dos LED se ven IGUAL de brillantes.
    Con uno un 20% mas luminoso que el otro, el punto de "las dos" se corre
    hacia el brillante, se sale de su tercio y la trama no cierra el CRC nunca.
    Los grupos se colocan donde de verdad estan las muestras, asi que aguantan
    el desequilibrio.

    Devuelve (t1, t2) con t1 < t2, o None si no hay tres grupos que valgan.
    """
    v = np.sort(np.asarray(valores, dtype=np.float64))
    if len(v) < 12:
        return None
    centros = np.percentile(v, (10, 50, 90))
    for _ in range(vueltas):
        # frontera = punto medio entre centros vecinos
        cortes = (centros[:-1] + centros[1:]) / 2.0
        grupo = np.searchsorted(cortes, v)
        nuevos = np.array([v[grupo == k].mean() if np.any(grupo == k)
                           else centros[k] for k in range(3)])
        if np.allclose(nuevos, centros, atol=1e-6):
            break
        centros = np.sort(nuevos)
    t1, t2 = (centros[0] + centros[1]) / 2.0, (centros[1] + centros[2]) / 2.0
    if t2 - t1 < 0.01:                  # los tres grupos son el mismo color
        return None
    return float(t1), float(t2)


def clasificar_por_color(lums, cromas, ventana=VENTANA_UMBRALES):
    """Series de (luminancia, croma) -> estado de las luces en cada cuadro.

    La unica forma de leerlas cuando estan tan lejos que se funden en un solo
    punto y ya no hay dos sitios que mirar. A cambio exige que sean de colores
    distintos.

    Dos decisiones distintas, y cada una con su criterio:
      APAGADO / encendida    por LUMINANCIA, con percentiles moviles.
      cual de las tres       por CROMA, con tres grupos (ver tres_grupos).
    """
    lums = np.asarray(lums, dtype=np.float32)
    cromas = np.asarray(cromas, dtype=np.float32)
    n = len(lums)
    if n == 0:
        return []
    p10, p90 = umbrales_moviles(lums, ventana)
    corte_off = p10 + 0.35 * (p90 - p10)
    # aqui el minimo de recorrido es mayor que MARGEN_PARPADEO: para separar
    # DOS colores hace falta mas señal que para ver si una luz se enciende
    apagado = (p90 - p10 < 6) | (lums < corte_off)

    # Las fronteras de croma dependen de QUE muestras estan encendidas en cada
    # ventana, asi que se calculan por anclas igual que las de luminancia. Un
    # ancla sin color utilizable se queda en cero y no aporta.
    anclas = anclas_de(n)
    ct1 = np.zeros(len(anclas), dtype=np.float32)
    ct2 = np.zeros(len(anclas), dtype=np.float32)
    hay = np.zeros(len(anclas), dtype=np.float32)
    for k, i in enumerate(anclas):
        a, b = max(0, i - ventana), min(n, i + ventana)
        prendidos = cromas[a:b][lums[a:b] >= corte_off[i]]
        if len(prendidos) < 10:
            continue
        fronteras = tres_grupos(prendidos)
        if fronteras is None:           # un solo color en la ventana
            continue
        ct1[k], ct2[k] = fronteras
        hay[k] = 1.0
    todos = np.arange(n)
    t1 = np.interp(todos, anclas, ct1)
    t2 = np.interp(todos, anclas, ct2)
    con_color = np.interp(todos, anclas, hay) >= 0.5

    estados = np.full(n, AMBAS, dtype=int)
    estados[con_color & (cromas < t1)] = LUZ_B
    estados[con_color & (cromas > t2)] = LUZ_A
    estados[apagado] = APAGADO
    return list(estados)


# Cambiar cual luz es la A y cual la B. NO es simetrico: el orden de los
# destinos cambia y con el los trits, asi que un cableado invertido produce
# basura con CRC fallido. Se prueban las dos y punto.
INTERCAMBIO = {APAGADO: APAGADO, LUZ_A: LUZ_B, LUZ_B: LUZ_A, AMBAS: AMBAS}


def intercambiar(estados):
    """Cambia la luz A por la B en toda una traza."""
    return [INTERCAMBIO[s] for s in estados]


# ------------------------------------------- 2.3 encontrar las luces ------

def reducir_para_buscar(f, zona=None):
    """El cuadro como lo mira la busqueda: recortado, reducido y en gris.

    Buscar no necesita resolucion (medir si, y por eso mide aparte sobre el
    cuadro entero). Con 'zona' se busca solo dentro de ese recuadro, que
    ademas de acertar mas es mas rapido.

    Devuelve (gris, escala, origen): con esos dos ultimos se devuelve
    cualquier coordenada de aqui a pixeles del cuadro original.
    """
    g, origen = f, (0.0, 0.0)
    if zona:
        x, y, w, h = (int(v) for v in zona)
        x, y = max(0, x), max(0, y)
        recorte = f[y:y + h, x:x + w]
        if recorte.shape[0] > 16 and recorte.shape[1] > 16:
            g, origen = recorte, (float(x), float(y))
    esc = min(1.0, float(ANCHO_BUSQUEDA) / g.shape[1])
    if esc < 1.0:
        g = cv2.resize(g, None, fx=esc, fy=esc)
    gris = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY) if g.ndim == 3 else g.copy()
    return gris, 1.0 / esc, origen


def mapa_luz(bloque, fps, banda=BANDA_PARPADEO):
    """Donde hay algo que PARPADEA deprisa y ademas ALUMBRA.

    El maximo de varianza no sirve al aire libre: gana la gente que pasa, que
    ocupa mucha mas imagen que un LED de 5 px. Lo que distingue a la luz es el
    RITMO (5-12 simbolos/s; una persona caminando va por debajo de 2 Hz) y el
    BRILLO (satura, y el resto de la escena no). Se toma la amplitud del pico
    en la banda util, se castiga la energia lenta -la firma del que camina- y
    se multiplica por el brillo al cuadrado.
    """
    def gris(f):
        # el bloque llega en color (un video) o ya en gris (la camara en vivo,
        # que guarda el buffer de busqueda en gris para que quepa a 640 px)
        g = f.astype(np.float32)
        return cv2.GaussianBlur(g.mean(2) if g.ndim == 3 else g, (3, 3), 0)

    pila = np.stack([gris(f) for f in bloque])
    forma = pila.shape[1:]
    # El maximo temporal, no el percentil 95: da practicamente lo mismo (una
    # luz que se enciende llega a su tope en muchos cuadros) y cuesta 10 ms en
    # vez de 620, porque el percentil tiene que ordenar cada pixel.
    brillo = pila.max(0) / 255.0
    pila = (pila - pila.mean(0, keepdims=True)).reshape(len(bloque), -1)
    llano = brillo.ravel()

    # SOLO SE TRANSFORMA LO QUE ALUMBRA. El resultado se multiplica por
    # brillo^2, asi que lo oscuro acaba en cero de todas formas y transformarlo
    # es tiempo tirado: sobre un tramo real, 1565 ms -> 128 ms con los mismos
    # picos. Ver FRACCION_PIXELES_FFT.
    if 0 < FRACCION_PIXELES_FFT < 1.0:
        corte = float(np.quantile(llano, 1.0 - FRACCION_PIXELES_FFT))
        indices = np.flatnonzero(llano >= corte)
    else:
        indices = np.arange(llano.size)
    if indices.size == 0:
        return np.zeros(forma, np.float32)
    pila = pila[:, indices]

    espectro = np.abs(np.fft.rfft(pila, axis=0))
    frec = np.fft.rfftfreq(len(bloque), d=1.0 / max(1e-6, fps))
    util = (frec >= banda[0]) & (frec <= banda[1])
    if not util.any():                   # bloque tan corto que no hay bandas
        util = frec > 0
    pico = espectro[util].max(0)

    lentas = (frec > 0) & (frec < banda[0])
    if lentas.any():
        pico = pico * np.minimum(1.0, pico / (espectro[lentas].max(0) + 1.0))

    mapa = np.zeros(llano.size, np.float32)
    mapa[indices] = pico * llano[indices] ** 2
    return mapa.reshape(forma)


def picos_de_luz(mapa, cuantos=4, frac=0.45, margen=2, borde=5):
    """Los puntos mas altos del mapa, separados por MANCHA y no por distancia.

    Separarlos por una distancia fija falla justo donde importa: de cerca el
    halo de una sola luz mide 40 px, asi que los dos primeros picos caen dentro
    de la MISMA luz y se acaba midiendo dos veces lo mismo. Borrando la region
    conexa entera de cada pico, el siguiente ya es la otra luz.

    'borde' tapa el marco de la imagen, donde el desenfoque y la transformada
    dejan valores altos que no son ninguna luz.
    """
    m = mapa.copy()
    if borde:
        m[:borde, :] = m[-borde:, :] = 0
        m[:, :borde] = m[:, -borde:] = 0
    salida = []
    for _ in range(cuantos):
        y, x = np.unravel_index(np.argmax(m), m.shape)
        alto = float(m[y, x])
        if alto <= 0:
            break
        salida.append((int(x), int(y), alto))
        mancha = (m >= alto * frac).astype(np.uint8)
        _, etiquetas = cv2.connectedComponents(mancha, 8)
        region = (etiquetas == etiquetas[y, x]).astype(np.uint8)
        if margen:
            ancho = 2 * margen + 1
            region = cv2.dilate(region, np.ones((ancho, ancho), np.uint8))
        m[region > 0] = 0
    return salida


def parpadeo_en(bloque, x, y, lado):
    """Serie de "esta prendido" en un punto del bloque reducido.

    Devuelve (prendida, cambia). Los recuadros son diminutos a proposito: a
    esta escala las dos luces estan a trece pixeles y uno grande mediria las
    dos a la vez.
    """
    v = np.array([brillo_de(recorte_centrado(f, (x, y), lado))
                  for f in bloque], dtype=np.float32)
    p10, p90 = recorrido(v)
    if not hay_cambio(p10, p90):
        return np.zeros(len(v), dtype=bool), False
    return encendida(v, p10, p90), True


def buscar_parejas(bloque, fps, escala, origen, cuantas=2, picos=6,
                   sueltos=2):
    """Las parejas de luces que se ven en un bloque de cuadros reducidos.

    Devuelve [(punto_A, vector_hasta_B, nota, puntaje)] en pixeles del cuadro
    ORIGINAL, de la mas prometedora a la menos, o [] si no se ve nada
    parpadeando. Un vector NULO significa "aqui hay un punto suelto": o es una
    sola luz, o son las dos fundidas, y en los dos casos toca leerlo por color.
    Siempre se proponen los 'sueltos' picos mas fuertes ademas de las parejas.

    No empareja por altura del pico sino exigiendo que los dos puntos LLEVEN
    SEÑALES DISTINTAS. Las luces salen tambien reflejadas -en un vidrio, en el
    piso- y el reflejo parpadea igual de fuerte y al mismo ritmo, asi que por
    altura ganaba "una luz y su propio reflejo", que no dice nada. Un reflejo
    coincide con su luz el 100% del tiempo; las dos luces de verdad difieren
    en un tercio de los cuadros.
    """
    if len(bloque) < 20:
        return []
    hallados = picos_de_luz(mapa_luz(bloque, fps), cuantos=picos)
    if not hallados:
        return []

    # los limites vienen en pixeles del cuadro original y aqui se trabaja sobre
    # el reducido, asi que hay que dividirlos por la escala
    sep_min, sep_max = (v / max(1.0, escala) for v in SEPARACION_LUCES_PX)
    lado = max(2, int(sep_min / 2))
    parpadeos = [parpadeo_en(bloque, x, y, lado) for x, y, _ in hallados]

    parejas = []
    for i, (xi, yi, vi) in enumerate(hallados):
        if not parpadeos[i][1]:
            continue
        for j, (xj, yj, vj) in enumerate(hallados[i + 1:], start=i + 1):
            if not parpadeos[j][1]:
                continue
            if not (sep_min <= math.hypot(xj - xi, yj - yi) <= sep_max):
                continue
            distintos = float(np.mean(parpadeos[i][0] != parpadeos[j][0]))
            if distintos < 0.10:
                continue            # llevan la misma señal: no informan
            parejas.append(((vi + vj) * distintos,
                            np.array([xi, yi], dtype=float),
                            np.array([xj - xi, yj - yi], dtype=float),
                            distintos))
    parejas.sort(key=lambda p: -p[0])

    ox, oy = origen
    salida = []
    for puntaje, p, v, distintos in parejas[:cuantas]:
        p, v = p * escala, v * escala
        nota = ("dos luces a %.0f px (se diferencian en el %.0f%% de los "
                "cuadros)" % (math.hypot(v[0], v[1]), 100 * distintos))
        salida.append((p + (ox, oy), v, nota, puntaje))

    # Y SIEMPRE, ademas, los picos sueltos mas fuertes, con separacion nula
    # (o sea: "aqui puede haber DOS luces fundidas en un punto, leelas por
    # color"). Antes esto solo se hacia cuando no habia salido NINGUNA pareja,
    # y por eso se perdian tomas enteras:
    #
    #   si las dos luces estan tan lejos que se funden, el LED no puede
    #   emparejarse con nadie; pero si en la escena hay otras cosas que
    #   parpadean -hojas, un reflejo, un monitor-, ESAS si se emparejan entre
    #   ellas, la lista no queda vacia, y el punto suelto no se proponia nunca.
    #
    # Medido sobre una toma de prueba: el LED era el pico MAS FUERTE de toda la
    # imagen (588 contra 425, 376 y 330) y no aparecia en ninguna de las tres
    # parejas propuestas. Proponerlo cuesta un candidato mas, que es barato:
    # medir ocho parejas vale casi lo mismo que medir una.
    for (x, y, fuerza), (_, cambia) in zip(hallados[:sueltos], parpadeos):
        if not cambia:
            continue
        p = np.array([x, y], dtype=float) * escala
        salida.append((p + (ox, oy), np.zeros(2),
                       "un punto suelto: puede ser una pareja fundida",
                       fuerza))
    return salida


def misma_pareja(punto_a, sep_a, punto_b, sep_b):
    """Si dos propuestas de la busqueda son la misma pareja de luces.

    Es lo que deja contar cuantas veces ha vuelto a salir cada pareja, y esa
    cuenta es lo unico que separa unas luces de unas hojas moviendose: las dos
    parpadean igual de rapido, pero solo las luces vuelven a salir siempre en
    el mismo sitio.
    """
    return (math.hypot(sep_a[0] - sep_b[0], sep_a[1] - sep_b[1])
            < TOLERANCIA_SEPARACION_PX and
            math.hypot(punto_a[0] - punto_b[0], punto_a[1] - punto_b[1])
            < TOLERANCIA_PUNTO_PX)


# ##########################################################################
#  3. DECODIFICADOR
#     De "el estado de las luces en cada cuadro" a "el bloque de celdas".
#     Aqui tampoco hay pixeles: la entrada es una lista de numeros.
# ##########################################################################

def agrupar_rachas(estados):
    """Agrupa estados repetidos: [1,1,1,2,2] -> [[1,3],[2,2]]."""
    out = []
    for s in estados:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return out


def simbolos_estables(estados, cuadros_por_simbolo, frac=FRAC_GLITCH):
    """Quita glitches de conmutacion y colapsa repeticiones.

    Las dos lamparas no conmutan a la vez, asi que en cada cambio puede
    aparecer un estado intermedio de 1-2 cuadros (de 01 a 10 se llega a ver un
    00 o un 11 fugaz). Se descarta toda racha mas corta que una fraccion del
    simbolo nominal.
    """
    umbral = max(1.0, cuadros_por_simbolo * frac)
    return colapsar([s for s, n in agrupar_rachas(estados) if n >= umbral])


def separar_rafagas(estados, cuadros_por_simbolo):
    """Corta la traza donde las dos luces quedaron apagadas mucho rato.

    Cada copia del bloque llega como una rafaga. Separarlas deja probar cada
    una por aparte, en vez de darle al decodificador un pegote de tres copias
    seguidas.
    """
    silencio = max(3, int(cuadros_por_simbolo * 3))
    trozos, actual, ceros = [], [], 0
    for s in estados:
        if s == APAGADO:
            ceros += 1
            if ceros >= silencio and actual:
                trozos.append(actual)
                actual, ceros = [], 0
                continue
        else:
            ceros = 0
        if s != APAGADO or actual:
            actual.append(s)
    if actual:
        trozos.append(actual)
    return [t for t in trozos if len(t) > 20]


def probar_periodos(estados, cuadros_nominal):
    """Barre periodos candidatos y devuelve el primer analisis con CRC valido.

    Si el periodo nominal no cuadra (la camara entrego menos fps de los
    pedidos, por ejemplo) uno de los factores del BARRIDO lo compensa.
    """
    mejor_parcial = None
    for factor in BARRIDO:
        cps = cuadros_nominal * factor
        if cps < 1.2:
            continue
        sec = simbolos_estables(estados, cps)
        if len(sec) < 20:
            continue
        bits, _ = decodificar_linea(sec)
        if bits is None:
            continue
        info = analizar_trama(bits)
        if info.get("crc_ok"):
            return info, cps
        if info.get("cabecera_ok") and mejor_parcial is None:
            mejor_parcial = (info, cps)
    return mejor_parcial if mejor_parcial else (None, None)


def decodificar_rafagas(traza, cuadros_nominal):
    candidatos = []
    for trozo in separar_rafagas(traza, cuadros_nominal) or [traza]:
        info, _ = probar_periodos(trozo, cuadros_nominal)
        if info:
            candidatos.append(info)
            if info.get("crc_ok"):
                return info, True
    info, _ = probar_periodos(traza, cuadros_nominal)
    if info and info.get("crc_ok"):
        return info, True
    if info:
        candidatos.append(info)
    return (candidatos[0] if candidatos else None), False


def decodificar_traza(traza, cuadros_nominal):
    """Intenta la traza entera y cada rafaga por separado, con las dos
    asignaciones posibles de las luces. Devuelve (info, nota).

    Cual luz es la A y cual la B no se sabe mirando, y NO da igual: el orden
    de los destinos cambia y con el los trits, asi que un cableado
    invertido produce basura con CRC fallido. Por eso se prueban las dos, salvo
    que LUZ_A_ES_LA_MAS_ROJA diga cual es.
    """
    intentos = [("", traza), (" [luces intercambiadas]", intercambiar(traza))]
    if LUZ_A_ES_LA_MAS_ROJA is True:
        intentos = intentos[:1]
    elif LUZ_A_ES_LA_MAS_ROJA is False:
        intentos = intentos[1:]

    parcial = None
    for etiqueta, datos in intentos:
        info, ok = decodificar_rafagas(datos, cuadros_nominal)
        if ok:
            return info, "CRC valido" + etiqueta
        if info is not None and parcial is None:
            parcial = (info, "cabecera ok, payload con errores" + etiqueta)
    if parcial:
        return parcial
    return None, "sin enganche"


def estimar_simbolos_por_s(tiempos, estados, minimo=1.0, maximo=25.0,
                           fps=None):
    """Simbolos/s leidos de la propia señal, sin que nadie los diga.

    El transmisor cambia de estado solo en las fronteras de simbolo, asi que
    todos los cambios caen en t0 + k*T. Se busca la T que los deja mas
    agrupados en fase: se mapea cada cambio a un angulo 2*pi*(t/T mod 1) y se
    mide la longitud del vector medio (concentracion circular, 1 = todos en la
    misma fase). No necesita que los cambios sean consecutivos: los simbolos
    repetidos, que no producen cambio, simplemente no aportan.

    'fps' hace dos cosas, las dos imprescindibles. Descarta el ALIAS DE LA
    CAMARA: con ~1 cuadro por simbolo casi todo cuadro trae un cambio y, como
    los cuadros estan igualmente espaciados, la concentracion en el periodo de
    cuadro sale 1,00 clavada (una toma de 23,80 fps "medía" 23,82 sim/s). Y
    pone el techo en fps/3, por encima del cual no hay simbolo que valga.

    Devuelve (simbolos_por_s, concentracion) o (None, 0.0).
    """
    t = np.asarray(tiempos, dtype=np.float64)
    e = np.asarray(estados)
    if len(t) != len(e) or len(t) < 20:
        return None, 0.0
    cambios = t[1:][e[1:] != e[:-1]]
    if len(cambios) < 8:
        return None, 0.0
    if fps:
        maximo = min(maximo, fps / CUADROS_POR_SIMBOLO_MIN)
    if maximo <= minimo:
        return None, 0.0
    tasas = np.arange(minimo, maximo + 1e-9, 0.02)
    if fps:
        for k in range(1, 5):
            tasas = tasas[np.abs(tasas - fps / k) > max(0.15, 0.02 * fps / k)]
    if len(tasas) == 0:
        return None, 0.0
    periodos = 1.0 / tasas
    fases = 2 * np.pi * (cambios[None, :] / periodos[:, None] % 1.0)
    vector = np.abs(np.exp(1j * fases).mean(axis=1))
    k = int(np.argmax(vector))
    return 1.0 / periodos[k], float(vector[k])


def a_cuadricula(info):
    """El resultado de analizar_trama -> lista de listas de celdas."""
    filas, cols = info["filas"], info["cols"]
    if not (1 <= filas <= MAX_FILAS and 1 <= cols <= MAX_COLS):
        return None
    try:
        celdas, _ = bits_a_celdas(info["payload"], filas * cols)
        return [celdas[i * cols:(i + 1) * cols] for i in range(filas)]
    except ValueError:
        pass
    # payload incompleto: se rescata celda por celda hasta donde alcance
    celdas, bits, i = [], info["payload"], 0
    while len(celdas) < filas * cols:
        try:
            trozo, usados = bits_a_celdas(bits[i:], 1)
        except (ValueError, IndexError):
            break
        celdas.append(trozo[0])
        i += usados
    celdas += ["?"] * (filas * cols - len(celdas))
    return [celdas[f * cols:(f + 1) * cols] for f in range(filas)]


# ##########################################################################
#  4. MEDIR
#     De un archivo o de la camara sale un bloque. La unica parte que abre
#     una captura, y la que junta todo lo anterior:
#
#       4.1  lo que se mide de una pareja de luces
#       4.2  de lo medido al bloque
#       4.3  un archivo de video
#       4.4  abrir la camara
#       4.5  la camara en vivo
#
#     Los dos caminos -archivo y camara- usan el mismo motor: buscar las luces
#     sobre unos pocos tramos reducidos, medir cada pareja candidata en cada
#     cuadro sobre la imagen sin reducir, y descifrar de las series. Se miden
#     VARIAS parejas en la misma pasada, que cuesta casi lo mismo que medir
#     una y evita tener que acertar a la primera.
# ##########################################################################

# ------------------------------ 4.1 lo que se mide de una pareja ----------

@dataclass
class Lectura:
    """Lo medido de una pareja de luces a lo largo del tiempo.

    Son tres maneras de mirar la misma señal, y el descifrador las prueba en
    ese orden: por pixeles quemados, por brillo y por color.
    """

    etiqueta: str
    t: np.ndarray
    quemados_a: np.ndarray
    quemados_b: np.ndarray
    brillo_a: np.ndarray
    brillo_b: np.ndarray
    lum: np.ndarray
    croma: np.ndarray
    separadas: bool
    con_color: bool

    def __len__(self):
        return len(self.t)


class Candidato:
    """Una pareja de luces que se esta midiendo, con lo medido hasta ahora.

    Guarda cuatro series y ninguna imagen: el brillo de cada luz (para leerlas
    por posicion) y la luminancia y el croma del par (para leerlas por color,
    que es lo que sirve cuando estan tan lejos que se funden en un punto).
    """

    def __init__(self, punto, separacion, escala, historia, nacido,
                 con_color=True, umbral_saturado=UMBRAL_SATURADO_BGR):
        self.punto = np.asarray(punto, dtype=float)
        # de que escala vienen los pixeles: BGR llega a 255, el plano Y de un
        # video de consumo se queda en 235. Ver UMBRAL_SATURADO_* .
        self.umbral_saturado = umbral_saturado
        self.separacion = np.asarray(separacion, dtype=float)
        self.historia = historia
        self.nacido = nacido
        self.escala = max(1.0, escala)
        d = math.hypot(self.separacion[0], self.separacion[1])
        # El recuadro de cada luz NO puede llegar hasta la otra: si llega, las
        # dos se miden juntas y el estado sale siempre "las dos prendidas", que
        # es justo lo que pasaba al reducir el cuadro a 320 px.
        self.lado = (int(np.clip(d / 2.5, 4, 30)) if d > 0
                     else int(np.clip(6 * escala, 8, 40)))
        self.t, self.ba, self.bb = [], [], []
        self.sa, self.sb = [], []          # pixeles quemados: ver saturados()
        self.lum, self.croma = [], []
        self.n = 0
        self.mejor = 0.0          # el parpadeo mas vivo que se le ha visto
        self.visto = 1            # en cuantas busquedas ha vuelto a salir
        self.protegida = False    # ya dio una cabecera valida: no se suelta
        # Medir el color es lo caro de cada cuadro (el recuadro que abarca las
        # dos luces, unos 90x50 px, contra dos cuadraditos) y casi nunca sirve,
        # asi que solo se mide donde puede hacer falta.
        self.con_color = con_color

    @property
    def separadas(self):
        """True si se ven como dos puntos; False si estan fundidas en uno."""
        return bool(np.any(self.separacion))

    def etiqueta(self):
        return ("(%d,%d)+(%d,%d)"
                % (self.punto[0], self.punto[1],
                   self.separacion[0], self.separacion[1]))

    def roi(self):
        """El recuadro que abarca las DOS luces, en pixeles originales."""
        q = self.punto + self.separacion
        x0 = int(min(self.punto[0], q[0])) - self.lado
        y0 = int(min(self.punto[1], q[1])) - self.lado
        return (max(0, x0), max(0, y0),
                int(abs(self.separacion[0])) + 2 * self.lado,
                int(abs(self.separacion[1])) + 2 * self.lado)

    def es_la_misma(self, punto, separacion, holgura=1.0):
        """Si una propuesta nueva es la pareja que ya se esta midiendo.

        El margen es el temblor de la busqueda, que trabaja sobre el cuadro
        reducido: un pixel suyo son tres del original. Dentro del margen la
        propuesta se descarta y la pareja no se mueve -mover los recuadros a
        media medicion mete un escalon de brillo en la trama-; fuera, entra
        como pareja nueva y que decida el CRC.

        Con holgura>1 la pregunta es mas floja ("sera la misma aunque salga
        corrida?") y solo sirve para contar avistamientos.
        """
        cerca = max(8.0, 3.0 * self.escala) * holgura
        return (math.hypot(punto[0] - self.punto[0],
                           punto[1] - self.punto[1]) < cerca and
                math.hypot(separacion[0] - self.separacion[0],
                           separacion[1] - self.separacion[1]) < cerca)

    def lectura(self):
        """Copia de lo medido hasta ahora, lista para descifrar.

        Se recortan todas las series al mismo largo porque el bucle de la
        camara sigue midiendo mientras el hilo que descifra las lee.
        """
        crudas = (self.t, self.sa, self.sb, self.ba, self.bb,
                  self.lum, self.croma)
        n = min(len(c) for c in crudas)
        return Lectura(self.etiqueta(),
                       *[np.asarray(c[:n], dtype=np.float64) for c in crudas],
                       separadas=self.separadas, con_color=self.con_color)

    def precargar(self, recientes, escala, origen):
        """Mide hacia atras sobre los cuadros reducidos que aun se guardan.

        Es una medida de peor calidad -el cuadro esta reducido- pero cae en la
        misma escala util: lo que decide el estado son percentiles sobre una
        ventana movil, no valores absolutos, y el nucleo del LED satura igual
        reducido que sin reducir. Lo que importa es no llegar tarde al
        preambulo.
        """
        d = max(2, int(round(self.lado / max(1.0, escala))))
        pa = (self.punto - origen) / escala
        pb = (self.punto + self.separacion - origen) / escala
        x0, y0, w, h = self.roi()
        caja = ((x0 - origen[0]) / escala, (y0 - origen[1]) / escala,
                w / escala, h / escala)
        for t, g in recientes:
            ra = recorte_centrado(g, pa, d)
            rb = recorte_centrado(g, pb, d)
            ventana = recorte_caja(g, caja)
            self.ba.append(brillo_de(ra))
            self.bb.append(brillo_de(rb))
            # Los quemados son una CUENTA DE PIXELES, asi que dependen del
            # tamaño del recuadro: aqui la imagen viene reducida y el recuadro
            # tiene escala^2 veces menos pixeles. Sin corregirlo la serie da un
            # escalon justo donde acaba la precarga y empieza la medida buena,
            # y la ventana movil de umbrales se come ese escalon como si fuera
            # señal.
            self.sa.append(saturados(ra, self.umbral_saturado) * escala ** 2)
            self.sb.append(saturados(rb, self.umbral_saturado) * escala ** 2)
            # los cuadros guardados son en gris: hay luminancia pero no croma
            self.lum.append(float(ventana.mean()) if ventana.size else 0.0)
            self.croma.append(0.0)
            self.t.append(t)

    # --- lo de cada cuadro ----------------------------------------------
    def medir(self, f, t, fps):
        """Los cuatro numeros del cuadro, sobre la imagen SIN REDUCIR.

        Sin reducir es la clave de todo: a 320 px de ancho dos luces separadas
        36 px quedan a 6 y ya no hay dos puntos que separar.
        """
        # se calculan los cuatro numeros ANTES de apuntar ninguno: si algo
        # fallara a medio camino, las cuatro series quedarian con largos
        # distintos y a partir de ahi el brillo de A no seria del mismo cuadro
        # que el de B
        ra = recorte_centrado(f, self.punto, self.lado)
        rb = recorte_centrado(f, self.punto + self.separacion, self.lado)
        a, b = brillo_de(ra), brillo_de(rb)
        sa, sb = (saturados(ra, self.umbral_saturado),
                  saturados(rb, self.umbral_saturado))
        # para el modo por color hacen falta las DOS en el mismo recuadro: el
        # croma no dice cual esta prendida si cada una se mide por separado
        l, c = (lum_y_croma(recorte_caja(f, self.roi())) if self.con_color
                else (0.0, 0.0))
        self.ba.append(a)
        self.bb.append(b)
        self.sa.append(sa)
        self.sb.append(sb)
        self.lum.append(l)
        self.croma.append(c)
        self.t.append(t)
        if len(self.t) > self.historia:
            for serie in (self.t, self.ba, self.bb, self.sa, self.sb,
                          self.lum, self.croma):
                del serie[0]
        self.n += 1
        if self.n % 30 == 0:
            self.actividad(fps)   # de paso deja apuntado el maximo

    # --- que tan prometedora es -----------------------------------------
    def actividad(self, fps):
        """Cambios por segundo que PODRIAN ser simbolos, en el ultimo rato.

        Es lo que separa una pareja de luces de verdad (7 simbolos/s se ven
        como 7-14 cambios/s) de un reflejo o de alguien caminando por detras, y
        decide a cual se mira primero y cual sobra si hay que soltar una.

        Lo de "podrian ser" no es un adorno: contar cambios a secas premia
        al ruido: un reflejo en el marco de una ventana daba 25 y hasta 52
        cambios/s y se quedaba con las plazas mientras la pareja buena, que
        daba 10, no entraba nunca. Pero por encima de fps/3 no hay simbolo que
        valga -hacen falta cuadros a los dos lados de cada transicion, ver la
        nota del encabezado-, asi que lo que cambia mas rapido que eso no es
        una señal y se puntua con cero.
        """
        n = int(min(len(self.t), max(60, 4 * fps)))
        if n < 30:
            return 0.0
        # Cambios del ESTADO CONJUNTO, no de cada luz sumados: con codigo por
        # transicion el conjunto cambia una vez por simbolo, asi que esta
        # cuenta ES la velocidad y el techo fisico se le aplica tal cual.
        estado = np.zeros(n, dtype=np.int16)
        vivo = False
        series = (((self.ba, LUZ_A), (self.bb, LUZ_B)) if self.separadas
                  else ((self.lum, LUZ_A),))
        for serie, peso in series:
            v = np.asarray(serie[-n:])
            p10, p90 = recorrido(v)
            if not hay_cambio(p10, p90):
                continue                # esa luz no cambia en este rato
            vivo = True
            estado += peso * encendida(v, p10, p90)
        if not vivo:
            return 0.0
        cambios = int(np.count_nonzero(estado[1:] != estado[:-1]))
        tasa = cambios / max(1e-6, self.t[-1] - self.t[-n])
        if tasa > fps / CUADROS_POR_SIMBOLO_MIN:
            return 0.0                 # mas rapido que el limite: es ruido
        self.mejor = max(self.mejor, tasa)
        return tasa

    def puntaje(self, fps, ahora):
        """(avistamientos, parpadeo, edad) para ordenar y para desempatar.

        Manda la CONSTANCIA, no la velocidad: al aire libre las hojas de un
        arbol parpadean a 9 o 10 cambios/s, igual que las luces, pero la
        pareja buena vuelve a salir busqueda tras busqueda en el mismo sitio y
        una sombra entre las hojas sale una vez y no vuelve.

        Desempata el parpadeo MAS VIVO que se le ha visto, no el de ahora
        mismo, porque entre dos copias del bloque las luces se quedan quietas.
        Y luego la edad: sin eso, al principio todas valen (1, algo) y cada
        busqueda echaria a la mas vieja, que es la que mas ha probado.
        """
        if self.protegida:
            return (10 ** 6, 0.0, 0.0)
        if ahora - self.nacido < 2.0:
            return (self.visto, 5.0, -self.nacido)
        return (self.visto, max(self.mejor, self.actividad(fps)), -self.nacido)

    def apagado(self, fps):
        """True si lleva PACIENCIA_VIVO_S sin que cambie nada: se perdio."""
        n = int(PACIENCIA_VIVO_S * max(1.0, fps))
        if len(self.t) < n:
            return False
        for serie in (self.ba, self.bb, self.lum):
            if hay_cambio(*recorrido(serie[-n:])):
                return False
        return True


# ----------------------------------- 4.2 de lo medido al bloque -----------
#
# Aqui ya no hay pixeles: entran series de numeros y sale un bloque de celdas.
# Lo comparten el camino de archivo y el de la camara en vivo.


def fraccion_recibida(info):
    """Que fraccion del payload alcanzo a llegar, de 0 a 1.

    Sirve para escoger entre varios intentos que fallaron el CRC. La cabecera
    lleva su propio CRC-8, asi que cuando 'cabecera_ok' es True las dimensiones
    y la longitud son de fiar y esta cuenta significa algo: es literalmente
    cuantas celdas se van a poder pintar y cuantas van a salir con '?'.
    """
    if not info or not info.get("cabecera_ok"):
        return 0.0
    nbits = max(1, info.get("nbits", 0))
    return min(len(info.get("payload", "")), nbits) / float(nbits)


def probar_velocidades(tiempos, estados, fps, simbolos_por_s=None,
                       avisar=None):
    """Prueba velocidades sobre UNA traza de estados y devuelve lo mejor.

    Es el bucle interior que comparten los dos caminos, el de archivo y el de
    la camara en vivo: primero la velocidad que se haya pedido a mano, luego
    la que se mide sobre la propia señal, y luego las tipicas. Se para en el
    primer CRC valido; si ninguno cuadra devuelve el mejor parcial (cabecera
    buena, payload con errores), que todavia sirve para pintar el bloque.

    Devuelve (info, nota, simbolos_por_s_usados, velocidad_medida).
    """
    medida, confianza = estimar_simbolos_por_s(tiempos, estados, fps=fps)
    if avisar:
        avisar(medida)
    velocidades = []
    if simbolos_por_s:
        velocidades.append(float(simbolos_por_s))
    if medida is not None and confianza >= 0.25:
        velocidades.append(medida)
    techo = fps / CUADROS_POR_SIMBOLO_MIN
    velocidades += [v for v in VELOCIDADES_TIPICAS if v <= techo
                    and all(abs(v - u) > 0.2 for u in velocidades)]

    # Si ninguna cuadra el CRC se devuelve la PRIMERA que dio algo, o sea la de
    # la velocidad medida sobre la señal. Aqui no vale quedarse con la que
    # traiga mas payload: entre dos relojes, el que produce mas bits es
    # simplemente el que corta la señal en mas trozos, y esos bits de mas son
    # inventados. Mas vale un interrogante que una letra equivocada.
    parcial = None
    for sps in velocidades:
        info, nota = decodificar_traza(estados, fps / max(0.1, sps))
        if info and info.get("crc_ok"):
            return info, nota, sps, medida
        if info and parcial is None:
            parcial = (info, nota, sps, medida)
    if parcial:
        return parcial
    return None, None, None, medida


# Las tres maneras de sacar el estado de las luces de lo medido, en el orden
# en que se prueban. La primera es la que mas manda de dia y la ultima la unica
# que sirve cuando las dos luces caen en el mismo punto de la imagen.
LECTURAS = (
    ("quemados", lambda l: clasificar_por_posicion(l.quemados_a, l.quemados_b),
     lambda l: l.separadas),
    ("brillo", lambda l: clasificar_por_posicion(l.brillo_a, l.brillo_b),
     lambda l: l.separadas),
    ("color", lambda l: clasificar_por_color(l.lum, l.croma),
     lambda l: l.con_color),
)

MUESTRAS_MINIMAS = 60


def descifrar_medidas(lecturas, fps, simbolos_por_s=None, avisar=None):
    """De las series medidas sale el bloque. Aqui ya no hay pixeles.

    Se prueban TODAS las parejas con una manera de leerlas antes de pasar a la
    siguiente, y no al reves: lo normal es que cuadre en la primera vuelta, y
    asi el caso normal no paga las otras dos.

    Lo usan los dos caminos, el de archivo y el de la camara.
    """
    if not lecturas:
        return None, "ninguna pareja parpadea como una señal: nadie transmite"
    largo = max(len(l) for l in lecturas)
    if largo < MUESTRAS_MINIMAS:
        return None, "juntando cuadros..."

    mejor = None
    for modo, sacar_estados, aplica in LECTURAS:
        for lectura in lecturas:
            if len(lectura) < MUESTRAS_MINIMAS or not aplica(lectura):
                continue
            estados = sacar_estados(lectura)
            if not estados:
                continue
            decir = None
            if avisar:
                decir = lambda m, e=lectura.etiqueta, o=modo: avisar(
                    "por %-8s en %-22s velocidad medida %s"
                    % (o, e, "%.2f sim/s" % m if m else "no medible"))
            info, nota, sps, _ = probar_velocidades(
                lectura.t, estados, fps, simbolos_por_s, avisar=decir)
            if info is None:
                continue
            texto = "%s  (por %s en %s, %.2f sim/s)" % (
                nota, modo, lectura.etiqueta, sps)
            if info.get("crc_ok"):
                if fps / sps < CUADROS_POR_SIMBOLO_MIN:
                    texto += "  [ojo: solo %.1f cuadros/simbolo]" % (fps / sps)
                return info, texto
            # Entre PAREJAS distintas si vale quedarse con la que mas trajo:
            # ahi no se esta cambiando el reloj, se esta midiendo otra cosa.
            if (mejor is None or
                    fraccion_recibida(info) > fraccion_recibida(mejor[0])):
                mejor = (info, texto)
    if mejor:
        return mejor
    return None, "nada cuadra todavia: %d cuadros a %.0f fps" % (largo, fps)


# ---------------------------------------- 4.3 un archivo de video ---------
#
# Tres pasos -buscar, medir, descifrar- y ni una imagen guardada de uno al
# siguiente. La pasada de medida es UNA y mide todas las parejas candidatas a
# la vez: un recuadro de 30x30 px cuesta microsegundos, asi que ocho parejas
# valen casi lo mismo que una.


#
# Tres pasos y ni una imagen guardada de uno al siguiente. La pasada de medida
# es UNA y mide todas las parejas candidatas a la vez, sobre el cuadro sin
# reducir: medir un recuadro de 30x30 px cuesta microsegundos, asi que ocho
# parejas cuestan casi lo mismo que una.


@contextmanager
def stderr_callado():
    """Tapa la salida de error del sistema mientras dure el bloque.

    Es por una linea concreta: la primera vez que se lee un video sin convertir
    a color, OpenCV escribe un aviso desde C++ que no pasa por su propio
    registro, asi que setLogLevel no lo calla.
    """
    copia = nulo = None
    try:
        sys.stderr.flush()
        copia = os.dup(2)
        nulo = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nulo, 2)
    except OSError:
        copia = None
    try:
        yield
    finally:
        if copia is not None:
            os.dup2(copia, 2)
            os.close(copia)
            os.close(nulo)


def abrir_video(ruta, solo_luz=True):
    """Abre un archivo de video. Con solo_luz pide la LUMINANCIA cruda.

    Decodificar el video es lo mas caro del receptor y la mitad de ese tiempo
    se va convirtiendo cada cuadro de YUV a BGR: 13,9 ms por cuadro de 1080p
    leyendo normal y 6,4 ms pidiendole a FFMPEG que no convierta. Esa
    conversion casi no se usa, porque el brillo y los pixeles quemados salen
    del plano Y; solo el modo por color necesita los tres canales y para eso se
    relee (ver procesar_video).

    Devuelve (cap, en_luz), porque no todos los contenedores lo permiten y hay
    que poder volver al camino normal.
    """
    cap = cv2.VideoCapture(str(ruta), cv2.CAP_FFMPEG)
    if not cap.isOpened() or not solo_luz:
        return (cap if cap.isOpened() else cv2.VideoCapture(str(ruta))), False
    if not cap.set(cv2.CAP_PROP_CONVERT_RGB, 0):
        return cap, False
    alto = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    with stderr_callado():
        ok, f = cap.read()
    # Sin convertir, algunos formatos entregan el buffer YUV entero (una vez y
    # media de alto) en vez del plano Y suelto. Si no llega una imagen de un
    # solo canal y del alto que toca, no se arriesga nada y se lee normal.
    if not ok or f is None or f.ndim != 2 or abs(f.shape[0] - alto) > 2:
        cap.release()
        return cv2.VideoCapture(str(ruta)), False
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return cap, True


def tramos_de_video(cap, tramos, largo, zona=None):
    """Va sacando tramos repartidos por el video, recortados y reducidos.

    Salta de tramo en tramo en vez de leerlo entero: para saber DONDE estan las
    luces no hacen falta todos los cuadros, y saltar cuesta una decima parte.
    Devuelve (cuadro_inicial, bloque, escala, origen).
    """
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        return
    paso = max(largo, (total - largo) // max(1, tramos - 1))
    i = 0
    for i0 in range(0, max(1, total - largo), paso):
        # Se avanza con grab(), que descomprime el cuadro pero no lo convierte
        # ni lo entrega. Salta a lo que hay entre tramo y tramo por la mitad de
        # precio, y sin usar cap.set(), que en un mp4 tiene que retroceder al
        # fotograma clave anterior y decodificar otra vez desde ahi.
        while i < i0:
            if not cap.grab():
                return
            i += 1
        bloque, escala, origen = [], 1.0, (0.0, 0.0)
        for _ in range(largo):
            ok, f = cap.read()
            i += 1
            if not ok:
                break
            g, escala, origen = reducir_para_buscar(f, zona)
            bloque.append(g)
        if len(bloque) >= 20:
            yield i0, bloque, escala, origen


def buscar_luces_en_video(ruta, zona=None, tramos=TRAMOS_BUSQUEDA,
                          maximo=MAX_PAREJAS_ARCHIVO, avisar=None):
    """Las parejas de luces que aparecen a lo largo del video.

    Se catan varios tramos y de cada uno salen las parejas que mejor pintan.
    Las de todos los tramos se juntan en GRUPOS: dos propuestas son la misma
    pareja si llevan la misma separacion, aunque esten en sitios distintos.
    Cada grupo guarda entonces donde estaba la pareja en cada tramo, que es lo
    que permite seguirla si la camara se movio despacio, sin ningun seguidor.

    'zona' limita la busqueda a un recuadro del cuadro original: es lo que se
    escoge a mano, y ademas de acertar mas hace la busqueda mas rapida, porque
    se trabaja sobre un recorte pequeño.

    Devuelve [(punto, separacion, anclas)] en pixeles del cuadro original.
    """
    cap, _ = abrir_video(ruta)          # para buscar basta la luminancia
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    grupos = []
    for i0, bloque, escala, origen in tramos_de_video(
            cap, tramos, CUADROS_BUSQUEDA, zona):
        for punto, separacion, nota, puntaje in buscar_parejas(
                bloque, fps, escala, origen, cuantas=3):
            centro = i0 + len(bloque) / 2.0
            for g in grupos:
                if misma_pareja(punto, separacion,
                                g["anclas"][-1][1], g["sep"]):
                    g["anclas"].append((centro, punto))
                    g["seps"].append(separacion)
                    g["veces"] += 1
                    g["puntaje"] += puntaje
                    break
            else:
                grupos.append({"sep": separacion, "seps": [separacion],
                               "veces": 1, "puntaje": puntaje,
                               "anclas": [(centro, punto)], "nota": nota})
    cap.release()

    # Ordena por en cuantos TRAMOS aparecio, y a igualdad por lo fuerte que se
    # vio. Aparecer una y otra vez es lo que separa una pareja de luces de una
    # sombra entre las hojas: la sombra sale en un tramo y no vuelve, aunque en
    # ese tramo se vea fortisima.
    grupos.sort(key=lambda g: (-g["veces"], -g["puntaje"]))
    salida = []
    for g in grupos[:maximo]:
        anclas = g["anclas"]
        # la separacion es fija en el montaje, asi que la mediana de todos los
        # tramos vale mucho mas que lo que diga uno suelto
        separacion = np.median(np.array(g["seps"]), axis=0)
        punto = np.median(np.array([p for _, p in anclas]), axis=0)
        salida.append((punto, separacion, anclas))
        if avisar:
            avisar("pareja en (%4d,%4d) + (%4d,%4d), en %d de los tramos"
                   % (punto[0], punto[1], separacion[0], separacion[1],
                      g["veces"]))
    return salida


def trayectoria_de(anclas, total):
    """Donde esta la pareja en cada cuadro, interpolando entre tramos.

    Si entre tramo y tramo apenas se movio, se deja QUIETA en la mediana: el
    temblor de la rejilla de busqueda son dos o tres pixeles (un pixel de la
    imagen reducida son tres del original) y hacerle caso metia un escalon de
    brillo en la serie cada pocos segundos. Solo se interpola cuando la camara
    se movio de verdad.
    """
    puntos = np.array([p for _, p in anclas], dtype=float)
    quieta = np.median(puntos, axis=0)
    if len(anclas) < 2 or np.ptp(puntos, axis=0).max() < DERIVA_MINIMA_PX:
        return None, quieta
    xs = np.array([i for i, _ in anclas], dtype=float)
    orden = np.argsort(xs)
    t = np.arange(total, dtype=float)
    camino = np.stack([np.interp(t, xs[orden], puntos[orden, 0]),
                       np.interp(t, xs[orden], puntos[orden, 1])], axis=1)
    return camino, quieta


def medir_en_video(ruta, parejas, avisar=None, con_color=False):
    """Mide TODAS las parejas en una sola pasada, sobre el cuadro sin reducir.

    Con con_color=False -lo normal- se lee solo la luminancia, que es la mitad
    de cara y basta para leer las luces por brillo y por pixeles quemados. El
    color solo se pide cuando de verdad hace falta.

    Devuelve (candidatos, fps). No guarda ni un cuadro: de cada uno salen unos
    numeros por pareja y la imagen se tira.
    """
    cap, en_luz = abrir_video(ruta, solo_luz=not con_color)
    if not cap.isOpened():
        return [], 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # cuanto se redujo el cuadro para buscar: de ahi sale el lado del recuadro
    # cuando las luces vienen fundidas y no hay separacion que mande
    escala = max(1.0, (cap.get(cv2.CAP_PROP_FRAME_WIDTH) or ANCHO_BUSQUEDA)
                 / float(ANCHO_BUSQUEDA))

    candidatos, caminos = [], []
    separadas = 0
    for punto, separacion, anclas in parejas:
        camino, quieta = trayectoria_de(anclas, max(total, 1))
        # color para las fundidas en un punto, que es donde es la UNICA
        # manera, y para las dos primeras separadas, como red de seguridad
        fundidas = not np.any(separacion)
        mide_color = con_color and (fundidas or separadas < 3)
        separadas += 0 if fundidas else 1
        candidatos.append(Candidato(
            quieta, separacion, escala, 10 ** 9, 0.0, con_color=mide_color,
            # el camino rapido entrega el plano Y, que se queda en 235
            umbral_saturado=(UMBRAL_SATURADO_LUZ if en_luz
                             else UMBRAL_SATURADO_BGR)))
        caminos.append(camino)

    tiempos, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        tiempos.append(t)
        for c, camino in zip(candidatos, caminos):
            if camino is not None:
                c.punto = camino[min(i, len(camino) - 1)]
            c.medir(f, t, fps)
        i += 1
        if avisar and total and i % 120 == 0:
            avisar(i / float(total))
    cap.release()
    if len(tiempos) > 1 and tiempos[-1] > tiempos[0]:
        fps = (len(tiempos) - 1) / (tiempos[-1] - tiempos[0])
    return candidatos, fps


def seleccionar_zona_video(ruta):
    """Muestra un cuadro del video y deja marcar DONDE ESTAN LAS LUCES.

    Devuelve el recuadro en pixeles del cuadro original, o None para que las
    busque solo. Enter o Space confirma; C o Esc deja la busqueda automatica.

    Ojo con lo que significa esto ahora, porque antes significaba otra cosa y
    por eso marcar el recuadro NUNCA funcionaba: el recuadro NO dice donde
    medir, dice DONDE BUSCAR. Antes se tomaba como el sitio exacto que habia
    que medir, y ademas eso apagaba el modo por posicion y dejaba solo el modo
    por color, que es el que NO sirve para dos luces del mismo color. Marcar la
    caja daba justo el peor de los dos modos.
    """
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        print("No se pudo abrir el video para escoger la zona.")
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total > 1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
    ok, cuadro = cap.read()
    cap.release()
    if not ok or cuadro is None:
        print("No se pudo leer un cuadro del video.")
        return None

    esc = min(1.0, 900.0 / cuadro.shape[1])
    vista = cv2.resize(cuadro, None, fx=esc, fy=esc)
    cv2.putText(vista, "Encierra las dos luces y pulsa Enter;  "
                       "C = buscarlas solo",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 255, 255), 1, cv2.LINE_AA)
    cv2.namedWindow("donde estan las luces", cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI("donde estan las luces", vista,
                               showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("donde estan las luces")
    if w <= 4 or h <= 4:
        return None
    # un poco de margen: la caja se mueve y las luces tienen halo
    margen = int(0.15 * max(w, h))
    def original(v):
        return int(round(v / esc))

    return (original(x - margen), original(y - margen),
            original(w + 2 * margen), original(h + 2 * margen))


def procesar_video(ruta, simbolos_por_s=None, verboso=True, zona=None):
    """Descifra un archivo entero. Devuelve (grid, nota, roi, escala).

    Buscar, medir, descifrar. Es todo: no se reproduce nada, no se descifra dos
    veces y no se carga la pelicula en memoria.
    """
    aviso = (lambda m: print("   " + m)) if verboso else None
    avance = ((lambda p: print("   %3.0f%%" % (p * 100), end="\r"))
              if verboso else None)

    if verboso:
        print("Buscando las luces%s..."
              % (" dentro del recuadro" if zona else " en todo el cuadro"))
    parejas = buscar_luces_en_video(ruta, zona, avisar=aviso)
    if not parejas:
        return (None, "no se ve ninguna pareja de luces que parpadee entre 2 "
                "y 25 Hz. Si estan muy lejos se funden en un punto y hay que "
                "acercarse o hacer zoom; si hay muchas cosas moviendose, "
                "marcar a mano donde esta la caja ayuda.", None, 1.0)

    if verboso:
        print("Midiendo las %d parejas de una pasada..." % len(parejas))
    candidatos, fps = medir_en_video(ruta, parejas, avisar=avance)
    if not candidatos or not candidatos[0].t:
        return None, "no se pudo leer el video", None, 1.0

    if verboso:
        print("   %d cuadros, %.2f fps efectivos"
              % (len(candidatos[0].t), fps))
        print("Descifrando...")
    info, nota = descifrar_medidas([c.lectura() for c in candidatos],
                                   fps, simbolos_por_s, avisar=aviso)

    # Segunda pasada en color, solo si la primera no cerro ningun CRC: cuesta
    # otra lectura entera del archivo. Aporta el modo por color, que la
    # luminancia no puede mirar, y de paso vuelve a medir brillo y quemados
    # sobre los tres canales en vez del plano Y, que no da lo mismo: el umbral
    # de quemado cae en sitios distintos y alguna toma cuadra solo asi.
    if info is None or not info.get("crc_ok"):
        if verboso:
            print("Sin CRC por luminancia: releyendo en color...")
        en_color, fps2 = medir_en_video(ruta, parejas, avisar=avance,
                                        con_color=True)
        if en_color and en_color[0].t:
            info2, nota2 = descifrar_medidas(
                [c.lectura() for c in en_color], fps2, simbolos_por_s,
                avisar=aviso)
            mejora = (info is None or info2.get("crc_ok") or
                      fraccion_recibida(info2) > fraccion_recibida(info))
            if info2 is not None and mejora:
                info, nota, candidatos = info2, nota2, en_color

    roi = None
    if info is not None:
        for c in candidatos:
            if c.etiqueta() in nota:
                roi = c.roi()
                break
    grid = a_cuadricula(info) if info and info.get("cabecera_ok") else None
    if info is None:
        nota += ("\n              El video tiene %.1f fps, o sea un techo de "
                 "~%.0f simbolos/s: por encima de eso hay que grabar a 60."
                 "\n              Y si la camara iba EN LA MANO, este no es "
                 "el receptor que toca, porque mide en recuadros quietos. "
                 "Para esas tomas esta rx_camara_con_seguimiento.py, al lado "
                 "de este archivo, que sigue las luces cuadro a cuadro (y "
                 "tarda mucho mas)." % (fps, fps / CUADROS_POR_SIMBOLO_MIN))
    return grid, nota, roi, 1.0


# ------------------------------------------- 4.4 abrir la camara ----------
#
# Windows, macOS y Linux no abren las camaras con el mismo backend, y pedir el
# que no toca no da un error claro: da una camara que "no responde" o que
# entrega negro. Aqui se prueban en el orden que corresponde a cada sistema.

def backends_de_camara():
    """Los backends que hay que probar en ESTE sistema, en orden.

    Windows  DSHOW es el unico que deja fijar la exposicion, pero las camaras
             "modernas" (el celular por Enlace movil, por ejemplo) solo abren
             por MSMF: con DSHOW a secas salen en la lista y luego no abren.
    macOS    AVFOUNDATION es el unico que existe; con el hay que dar permiso
             de camara a la aplicacion (Ajustes > Privacidad > Camara).
    Linux    V4L2.

    CAP_ANY va siempre de ultimo, que es "que decida OpenCV".
    """
    preferidos = {"win32": ("CAP_DSHOW", "CAP_MSMF"),
                  "darwin": ("CAP_AVFOUNDATION",),
                  }.get(sys.platform, ("CAP_V4L2",))
    orden = [getattr(cv2, n) for n in preferidos if hasattr(cv2, n)]
    return orden + [cv2.CAP_ANY]


def fijar_exposicion(cap, exposicion):
    """Baja la exposicion, si el backend deja.

    En Windows el valor va en pasos logaritmicos (-7 es oscuro); en macOS y
    Linux la escala es otra y muchas camaras UVC ni lo admiten. Como no todas
    responden igual, se intenta y no se da por hecho: si no cambia nada, la
    imagen sigue viendose y no se rompe nada.
    """
    if exposicion is None:
        return False
    try:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)   # 0.25 = manual en Windows
        if sys.platform.startswith("linux"):
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # 1 = manual en V4L2
        return bool(cap.set(cv2.CAP_PROP_EXPOSURE, exposicion))
    except cv2.error:
        return False


def abrir_camara(cual, fps_pedidos=FPS_CAMARA, exposicion=EXPOSICION_CAMARA):
    """Abre una camara por indice (0, 1, ...) o por URL, y la deja lista.

    Una URL sirve para usar el celular o una camara de red como camara del PC:
    ver la nota de COMO CONECTAR OTRA CAMARA en el encabezado. Con URL se usa
    FFMPEG, que es el backend que entiende http y rtsp; con indice, el que
    corresponda al sistema (ver backends_de_camara).
    """
    if isinstance(cual, str) and not str(cual).isdigit():
        cap = cv2.VideoCapture(cual, cv2.CAP_FFMPEG)          # celular o IP
    else:
        orden = backends_de_camara()
        cap = None
        for backend in orden:
            prueba = cv2.VideoCapture(int(cual), backend)
            if prueba.isOpened() and prueba.read()[0]:
                cap = prueba
                break
            prueba.release()
        if cap is None:                    # ninguno abrio: se devuelve cerrada
            return cv2.VideoCapture(int(cual), orden[0])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, fps_pedidos)
    # Solo si se pide: en un cuarto normal una exposicion de -7 deja la imagen
    # practicamente negra, y eso parece una camara rota cuando en realidad
    # esta funcionando. Ver EXPOSICION_CAMARA en PARAMETROS.
    fijar_exposicion(cap, exposicion)
    return cap


def nombres_camaras(hasta=8):
    """Los NOMBRES de las camaras del PC, los mismos que muestra Zoom o Meet.

    OpenCV solo las abre por NUMERO; el nombre no lo sabe. En Windows lo tiene
    DirectShow y se lee con pygrabber (pip install pygrabber). En macOS y Linux
    no hay equivalente sencillo, asi que devuelve [] y se escoge por numero:
    no es un fallo, es que ahi no hay nombres que dar.
    """
    if sys.platform != "win32":
        return []
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())[:hasta]
    except Exception:
        return []


def camaras_disponibles(hasta=6):
    """Las camaras que responden: [(indice, nombre, ancho, alto, brillo)].

    Abrir cada camara tarda un segundo largo, asi que esto es para --camaras y
    para cuando no hay nombres. Para solo escoger, nombres_camaras() basta y es
    instantaneo.
    """
    nombres = nombres_camaras(hasta)
    encontradas = []
    for i in range(hasta):
        cap = None
        for backend in backends_de_camara():
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                break
            cap.release()
        if cap is not None and cap.isOpened():
            ok, f = cap.read()
            for _ in range(4):            # las primeras suelen venir en negro
                ok2, f2 = cap.read()
                if ok2:
                    ok, f = ok2, f2
            if ok:
                nombre = nombres[i] if i < len(nombres) else "camara %d" % i
                encontradas.append(
                    (i, nombre, f.shape[1], f.shape[0], float(f.mean())))
        cap.release()
    return encontradas


def resolver_camara(valor):
    """Traduce lo que venga en --camara a algo que abrir_camara entienda.

    Un numero se deja igual, una URL tambien, y un texto suelto se busca entre
    los nombres de las camaras: --camara "iriun" o --camara "enlace" evita
    tener que mirar primero que numero le toco hoy.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto.isdigit() or "://" in texto:
        return texto
    for i, nombre in enumerate(nombres_camaras()):
        if texto.lower() in nombre.lower():
            return i
    return texto


# ---------------------------------------------- 4.5 la camara en vivo -----
#
# Un archivo se puede releer entero; en vivo cada cuadro pasa una vez. Por eso
# el rastreador no guarda imagenes: busca las luces sobre cuadros reducidos y
# mide sobre el original, dejando cuatro numeros por cuadro. Un minuto de
# escucha son unos miles de floats, no un giga de pixeles, y descifrar toda la
# historia cuesta menos de un segundo.


class RastreadorVivo:
    """Busca las luces y las mide, cuadro a cuadro, sin guardar imagenes.

    Sigue hasta MAX_CANDIDATOS_VIVO parejas a la vez y no se casa con ninguna:
    mientras no salga el bloque se vuelve a buscar cada BUSQUEDA_CADA_S
    segundos, las parejas nuevas se suman a las que ya se estaban midiendo, y
    las que llevan rato sin parpadear se sueltan. Asi un mal comienzo -alguien
    cruzando por delante justo cuando arranca la transmision- ya no cuesta la
    toma entera.
    """

    def __init__(self, historia=HISTORIA_VIVO_CUADROS):
        self.historia = historia
        self.reiniciar()

    def reiniciar(self, zona=None):
        """Deja el rastreador como recien arrancado.

        'zona' limita la busqueda a un recuadro del cuadro original: es lo que
        se escoge con la tecla m cuando hay otras cosas parpadeando alrededor.
        """
        self.zona = zona
        self.origen = (0.0, 0.0)
        self.escala = 1.0
        # anillo de cuadros reducidos: los mas nuevos sirven para buscar y
        # todos para precargar una pareja recien encontrada
        self.buscando = []
        self.candidatos = []
        # Cuantas veces ha visto la busqueda cada pareja, se este midiendo o
        # no. Va aparte de los candidatos porque si el contador viviera dentro,
        # al soltar uno se perderia justo lo que hace falta para reconocerlo la
        # proxima vez.
        self.vistas = []
        self.cada = 0
        self.reloj = 0.0
        self.nota = "buscando las luces..."

    # --- lo que le pregunta el bucle de la camara -----------------------
    @property
    def enganchado(self):
        return bool(self.candidatos)

    def listo_para_buscar(self):
        return len(self.buscando) >= CUADROS_BUSQUEDA

    def medidos(self):
        return max((len(c.t) for c in self.candidatos), default=0)

    def rois(self):
        """Los recuadros que se estan midiendo, el mas prometedor primero."""
        return [c.roi() for c in self.candidatos]

    # --- las dos tareas caras, para lanzarlas en otro hilo ---------------
    def tarea_de_busqueda(self, fps):
        """Cierra sobre una COPIA del bloque: el hilo no toca nada vivo."""
        bloque = [g for _, g in self.buscando[-CUADROS_BUSQUEDA:]]
        escala, origen = self.escala, self.origen
        # el anillo NO se vacia: los cuadros que acaba de usar la busqueda son
        # justo los que hacen falta para precargar la pareja que encuentre. El
        # ritmo de las busquedas lo pone BUSQUEDA_CADA_S, no el anillo.
        return lambda: buscar_parejas(bloque, fps, escala, origen)

    def tarea_de_descifrado(self, fps, simbolos_por_s):
        """Lo que se le manda al hilo que descifra, ya copiado y ordenado.

        Quedan fuera las parejas a las que nunca se les vio un parpadeo que
        pudiera ser de simbolos: si no ha cambiado a un ritmo posible, no hay
        trama que sacar. Es lo que evita quemar el procesador mientras no
        transmite nadie. Las recien nacidas pasan igual, que aun no han tenido
        ocasion de enseñar nada.
        """
        ahora = max((c.t[-1] for c in self.candidatos if c.t), default=0.0)
        vivas = [c for c in self.candidatos
                 if c.mejor > 0 or ahora - c.nacido < 4.0]
        lecturas = [c.lectura() for c in
                    sorted(vivas, key=lambda c: c.puntaje(fps, ahora),
                           reverse=True)]
        return lambda: descifrar_medidas(lecturas, fps, simbolos_por_s)

    def sembrar(self, hallazgos, fps, ahora):
        """Mete las parejas que encontro una busqueda entre las que se miden.

        Cada pareja nueva nace con los ultimos segundos YA medidos sobre los
        cuadros reducidos que todavia se guardan: ver CUADROS_PRECARGA_VIVO.
        """
        recien = []
        for punto, separacion, nota, _ in hallazgos:
            veces = self._apuntar_vista(punto, separacion)
            for c in self.candidatos:
                if c.es_la_misma(punto, separacion, holgura=3.0):
                    c.visto = veces
            if any(c.es_la_misma(punto, separacion) for c in self.candidatos):
                continue        # ya se esta midiendo; NO se le toca el sitio
            nueva = Candidato(punto, separacion, self.escala,
                               self.historia, ahora)
            nueva.visto = veces
            nueva.precargar(list(self.buscando), self.escala, self.origen)
            self.candidatos.append(nueva)
            recien.append(nueva)
            if len(self.candidatos) > MAX_CANDIDATOS_VIVO:
                self._soltar_la_peor(recien, fps, ahora)
        if recien:
            self.nota = self._resumen(fps, ahora)

    def _soltar_la_peor(self, recien, fps, ahora):
        """Deja sitio, pero NUNCA a costa de las que acaban de entrar.

        A una recien nacida se le supone un puntaje modesto, asi que sin esta
        salvedad seria siempre la mas floja de la lista y cada busqueda echaria
        a la pareja que acaba de proponer. Se sueltan solo las que ya tuvieron
        su oportunidad; si todas son recientes no se suelta ninguna y la lista
        crece un poco, que es mas barato que perder la buena.
        """
        viejas = [c for c in self.candidatos
                  if c not in recien and ahora - c.nacido >= 2.0]
        if viejas:
            self.candidatos.remove(min(viejas,
                                       key=lambda c: c.puntaje(fps, ahora)))

    def proteger(self, nota):
        """Deja intocable la pareja que firma 'nota', ya no se suelta.

        Unica realimentacion entre descifrar y buscar, y hace falta: al aire
        libre las hojas de un arbol parpadean igual de rapido y le ganaban el
        puesto. Una cabecera con su CRC-8 bueno son 24 bits cuadrando, asi que
        no hay nada que la busqueda pueda proponer que valga mas.
        """
        for c in self.candidatos:
            if c.etiqueta() in nota:
                c.protegida = True
                return True
        return False

    def _apuntar_vista(self, punto, separacion):
        """Suma uno al contador de esta pareja y devuelve cuantas van."""
        for v in self.vistas:
            if misma_pareja(punto, separacion, v["punto"], v["sep"]):
                v["veces"] += 1
                v["punto"] = punto
                return v["veces"]
        self.vistas.append({"punto": punto, "sep": separacion, "veces": 1})
        if len(self.vistas) > 60:
            self.vistas.sort(key=lambda v: -v["veces"])
            del self.vistas[40:]
        return 1

    def _resumen(self, fps, ahora):
        partes = []
        for c in sorted(self.candidatos, key=lambda c: c.puntaje(fps, ahora),
                        reverse=True):
            d = math.hypot(c.separacion[0], c.separacion[1])
            partes.append("%s a %.0f px (vista %d veces, %.0f cambios/s)"
                          % ("dos luces" if c.separadas else "una luz",
                             d, c.visto, c.actividad(fps)))
        return "midiendo %d: %s" % (len(partes), " | ".join(partes))

    # --- el cuadro a cuadro ---------------------------------------------
    def alimentar(self, f, t, fps, buscar_mas=True):
        """Un cuadro nuevo: se mide sobre el y, si hace falta, se guarda para
        buscar. Las dos cosas son baratas; lo caro va en otro hilo."""
        self.reloj = t
        for c in self.candidatos:
            # un cuadro raro de la camara (medio recibido, de otro tamaño) no
            # puede tumbar una escucha que lleva un minuto acumulando
            try:
                c.medir(f, t, fps)
            except cv2.error:
                pass
        # mirar si alguna se apago cuesta tres percentiles sobre medio millar
        # de muestras: barato una vez por segundo, caro sesenta veces
        self.cada += 1
        if self.cada % 30 == 0:
            for c in list(self.candidatos):
                if c.apagado(fps) and not c.protegida:
                    self.candidatos.remove(c)
                    self.nota = "una pareja dejo de parpadear: soltada"
        if not buscar_mas:
            self.buscando = []
            return
        # el anillo va en gris: se pierde el croma de los segundos
        # precargados, que solo hace falta con las luces fundidas en un punto
        gris, self.escala, self.origen = reducir_para_buscar(f, self.zona)
        self.buscando.append((t, gris))
        if len(self.buscando) > CUADROS_BUSQUEDA + CUADROS_PRECARGA_VIVO:
            self.buscando.pop(0)


class TareaEnHilo(threading.Thread):
    """Corre una tarea aparte para que la ventana nunca se congele.

    ESTE HILO ES EL ARREGLO de que la tecla 'q' no respondiera en vivo: buscar
    las luces y descifrar tardan lo suyo, y hacerlo en el bucle que dibuja
    dejaba la ventana bloqueada mas de la mitad del tiempo, asi que waitKey
    casi nunca veia la tecla. Aqui el bucle solo lanza la tarea y sigue
    dibujando; cuando termina, deja el resultado en .salida.
    """

    def __init__(self, tipo, tarea):
        super().__init__(daemon=True)
        self.tipo, self.tarea = tipo, tarea
        self.salida, self.fallo = None, None

    def run(self):
        try:
            self.salida = self.tarea()
        except Exception as e:                 # el hilo no puede tumbar la app
            self.salida, self.fallo = None, "error al %s: %s" % (self.tipo, e)


# Cuadros seguidos sin imagen antes de dar la camara por perdida.
CUADROS_PERDIDOS_MAX = 30

# Cuadros sobre los que se promedian los fps reales.
VENTANA_FPS = 150


class EscuchaEnVivo:
    """El estado de una escucha: lo medido, lo descifrado y lo que corre
    en otro hilo.

    Esta separado del bucle que lee la camara porque son dos cosas distintas:
    el bucle se ocupa de la captura (abrirla, leerla, la exposicion) y esta
    clase de la señal. Ademas asi se puede seguir el hilo de lo que pasa sin
    leer un bucle de ciento cincuenta lineas.

    Lo caro -buscar las luces y descifrar- va SIEMPRE fuera del bucle, en dos
    hilos separados. Dos y no uno: tardan parecido, y compartiendo hilo la
    busqueda se quedaba esperando al descifrado, lo que retrasaba entre uno y
    tres segundos el momento en que entra la pareja buena. Como la rafaga dura
    lo que dura, la escucha enganchaba unas veces si y otras no.
    """

    def __init__(self, simbolos_por_s=None, cada=REINTENTO_VIVO_S,
                 fps_inicial=FPS_CAMARA):
        self.rastreador = RastreadorVivo()
        self.simbolos_por_s = simbolos_por_s
        self.cada = cada
        self.fps = fps_inicial
        self.grid = None
        self.nota = "esperando transmision..."
        self.congelado = False
        self.zona = None
        self.hilo_busca = None
        self.hilo_descifra = None
        self.proxima_busqueda = 0.0
        self.proximo_intento = 0.0
        self._relojes = []

    # --- lo que se hace con cada cuadro ---------------------------------
    def procesar(self, cuadro, t):
        """Mide el cuadro, recoge lo de los hilos y lanza lo siguiente."""
        self._actualizar_fps(t)
        self.rastreador.alimentar(cuadro, t, self.fps,
                                  buscar_mas=not self.congelado)
        self._recoger_busqueda()
        self._recoger_descifrado()
        self._lanzar_tareas(t)

    def _actualizar_fps(self, t):
        """Los fps DE VERDAD, no los que se le pidieron a la camara: de esto
        salen los cuadros por simbolo, que es lo que decide si hay señal."""
        self._relojes.append(t)
        if len(self._relojes) > VENTANA_FPS:
            self._relojes.pop(0)
        if len(self._relojes) > 30 and self._relojes[-1] > self._relojes[0]:
            self.fps = ((len(self._relojes) - 1) /
                        (self._relojes[-1] - self._relojes[0]))

    def _recoger_busqueda(self):
        hilo, self.hilo_busca = self.hilo_busca, None
        if hilo is None or hilo.is_alive():
            self.hilo_busca = hilo
            return
        if hilo.fallo:
            self.nota = hilo.fallo
        elif hilo.salida:
            self.rastreador.sembrar(hilo.salida, self.fps,
                                    self.rastreador.reloj)
        elif not self.rastreador.enganchado:
            self.rastreador.nota = ("no se ve nada parpadeando: acercate o "
                                    "zoom (m limita la busqueda)")

    def _recoger_descifrado(self):
        hilo, self.hilo_descifra = self.hilo_descifra, None
        if hilo is None or hilo.is_alive():
            self.hilo_descifra = hilo
            return
        if hilo.fallo:
            self.nota = hilo.fallo
            return
        if hilo.salida is None:
            return
        info, self.nota = hilo.salida
        if not (info and info.get("cabecera_ok")):
            return
        self.rastreador.proteger(self.nota)
        nuevo = a_cuadricula(info)
        if nuevo:
            self.grid = nuevo
        if info.get("crc_ok"):
            self.congelado = True          # llego entero: no se toca mas

    def _lanzar_tareas(self, t):
        if self.congelado:
            return
        if (self.hilo_busca is None and t >= self.proxima_busqueda
                and self.rastreador.listo_para_buscar()):
            self.proxima_busqueda = t + BUSQUEDA_CADA_S
            self.hilo_busca = TareaEnHilo(
                "buscar", self.rastreador.tarea_de_busqueda(self.fps))
            self.hilo_busca.start()
        if (self.hilo_descifra is None and t >= self.proximo_intento
                and self.rastreador.enganchado
                and self.rastreador.medidos() > MUESTRAS_MINIMAS):
            self.proximo_intento = t + self.cada
            self.hilo_descifra = TareaEnHilo(
                "descifrar", self.rastreador.tarea_de_descifrado(
                    self.fps, self.simbolos_por_s))
            self.hilo_descifra.start()

    # --- lo que ve y lo que responde quien dibuja ------------------------
    def estado(self, cuadro, t, exposicion):
        return {
            "grid": self.grid, "nota": self.nota, "cuadro": cuadro,
            "rois": self.rastreador.rois(), "zona": self.zona,
            "estado": self.rastreador.nota,
            "enganchado": self.rastreador.enganchado,
            "congelado": self.congelado,
            "descifrando": self.hilo_descifra is not None,
            "buscando": self.hilo_busca is not None,
            "segundos": t, "cuadros": self.rastreador.medidos(),
            "fps": self.fps, "exposicion": exposicion,
        }

    def atender(self, respuesta):
        """Aplica lo que pidio quien dibuja, menos la exposicion (esa es de la
        captura y la maneja el bucle)."""
        if isinstance(respuesta, dict) and "zona" in respuesta:
            # el recuadro a mano dice DONDE BUSCAR, no donde medir: donde medir
            # lo decide el rastreador y lo hace mejor que un rectangulo a pulso
            self.zona = respuesta["zona"]
            self._empezar_de_cero("buscando solo dentro del recuadro"
                                  if self.zona
                                  else "buscando en todo el cuadro")
        elif respuesta == "reiniciar":
            self._empezar_de_cero("escucha reiniciada")

    def _empezar_de_cero(self, nota):
        self.rastreador.reiniciar(self.zona)
        self.grid, self.congelado, self.nota = None, False, nota
        self.hilo_busca = self.hilo_descifra = None

    # --- el remate --------------------------------------------------------
    def ultimo_intento(self):
        """Descifra una vez mas con TODO lo medido, ya sin prisa.

        Los intentos van cada REINTENTO_VIVO_S segundos, asi que al ultimo le
        faltaba siempre el remate de la trama; y una trama de estas dura medio
        minuto, o sea que perder los dos ultimos segundos es perderla entera.
        Escuchando de verdad da igual porque el transmisor repite, pero cuando
        la fuente se acaba de golpe -un video simulado, la camara desenchufada,
        la tecla q- este intento es el que salva la toma.
        """
        if self.congelado or not self.rastreador.enganchado:
            return
        try:
            info, nota = self.rastreador.tarea_de_descifrado(
                self.fps, self.simbolos_por_s)()
        except Exception as e:
            self.nota = "error en el ultimo intento: %s" % e
            return
        if info and info.get("cabecera_ok"):
            nuevo = a_cuadricula(info)
            if nuevo:
                self.grid, self.nota = nuevo, nota


def escuchar_camara(cual=CAMARA, simbolos_por_s=None, fps_pedidos=FPS_CAMARA,
                    exposicion=EXPOSICION_CAMARA, al_actualizar=None,
                    cada=REINTENTO_VIVO_S, cap=None, reloj=None):
    """La camara en vivo, que es el unico caso donde no existe "el final".

    Este bucle solo se ocupa de la captura: leer un cuadro, pasarselo a la
    escucha y atender lo que pida quien dibuja. Todo lo caro corre en otros
    hilos, asi que las teclas responden al instante por larga que sea la
    escucha. En cuanto un CRC cuadra el resultado se congela.

    'al_actualizar(estado)' se llama en CADA cuadro con un diccionario y debe
    devolver True para seguir, False para parar, "reiniciar" para tirar la
    historia, o un dict con la exposicion o la zona de busqueda nuevas.

    'cap' y 'reloj' existen para poder probar todo esto con un video grabado en
    vez de una camara: ver simular_vivo().
    """
    if cap is None:
        cap = abrir_camara(cual, fps_pedidos, exposicion)
    if not cap.isOpened():
        return None, "no se pudo abrir la camara %s" % cual

    escucha = EscuchaEnVivo(simbolos_por_s, cada, fps_pedidos)
    exposicion_actual = exposicion
    t_ini, sin_imagen = time.time(), 0
    try:
        while True:
            ok, cuadro = cap.read()
            if not ok:
                sin_imagen += 1
                if sin_imagen > CUADROS_PERDIDOS_MAX:
                    escucha.nota = "se acabo la imagen de la camara"
                    break
                continue
            sin_imagen = 0

            t = reloj() if reloj else time.time() - t_ini
            escucha.procesar(cuadro, t)
            if al_actualizar is None:
                continue

            respuesta = al_actualizar(
                escucha.estado(cuadro, t, exposicion_actual))
            if respuesta is False:
                break
            if isinstance(respuesta, dict) and "exposicion" in respuesta:
                exposicion_actual = respuesta["exposicion"]
                fijar_exposicion(cap, exposicion_actual)
            escucha.atender(respuesta)
    finally:
        cap.release()

    escucha.ultimo_intento()
    return escucha.grid, escucha.nota


class CamaraDesdeVideo:
    """Un archivo de video haciendose pasar por una camara.

    Es lo unico que permite probar la escucha en vivo sin tener a alguien al
    otro lado encendiendo luces: entrega los cuadros de uno en uno y con el
    reloj DEL VIDEO, asi que el rastreador ve exactamente lo que veria en vivo
    (no puede volver atras ni saber cuanto falta, y los fps son los de la
    toma).
    """

    def __init__(self, ruta, tiempo_real=False):
        self.cap = cv2.VideoCapture(str(ruta))
        self.tiempo_real = tiempo_real
        self.t = 0.0
        self.t0 = time.time()

    def isOpened(self):
        return self.cap.isOpened()

    def read(self):
        ok, f = self.cap.read()
        if ok:
            self.t = self.cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if self.tiempo_real:
                espera = self.t - (time.time() - self.t0)
                if espera > 0:
                    time.sleep(espera)
        return ok, f

    def release(self):
        self.cap.release()

    def set(self, *a):
        return self.cap.set(*a)

    def get(self, *a):
        return self.cap.get(*a)


def simular_vivo(ruta, simbolos_por_s=None, al_actualizar=None,
                 tiempo_real=False, cada=REINTENTO_VIVO_S):
    """Pasa un video grabado por el camino de la CAMARA EN VIVO.

    Sirve para dos cosas: comprobar que la escucha funciona antes de tener el
    montaje delante, y saber si un fallo en vivo es de la camara o de aqui.
    Con tiempo_real=True los cuadros salen a la velocidad de la toma, como
    saldrian de una camara; sin el va tan rapido como lea el archivo, que
    es lo comodo para probar.
    """
    fuente = CamaraDesdeVideo(ruta, tiempo_real)
    if not fuente.isOpened():
        return None, "no se pudo abrir %s" % ruta
    return escuchar_camara(simbolos_por_s=simbolos_por_s,
                           al_actualizar=al_actualizar, cada=cada,
                           cap=fuente, reloj=lambda: fuente.t)


# ##########################################################################
#  5. INTERFAZ
#     Lo unico que abre ventanas. Se puede borrar entera y las secciones
#     1 a 4 siguen funcionando desde otro programa.
# ##########################################################################

EXT_VIDEO = (".mp4", ".avi", ".mov", ".mkv", ".m4v")

# Paleta de las dos ventanas, en un solo sitio: cambiar un color aqui las
# cambia las dos. tkinter se importa dentro de cada funcion a proposito, para
# que el resto del programa siga sirviendo en un equipo que no lo tenga.
COLOR = {"fondo": "#1e1e2e", "hueco": "#181825", "texto": "#cdd6f4",
         "titulo": "#89b4fa", "suave": "#a6adc8", "ok": "#a6e3a1",
         "cancelar": "#f38ba8", "camara": "#f9e2af", "probar": "#f5c2e7"}


def _rotulo(padre, texto, color="titulo", tam=10, negrita=True):
    """Una etiqueta de las ventanas. Hay que empaquetarla al gusto."""
    import tkinter as tk
    fuente = ("Segoe UI", tam, "bold") if negrita else ("Segoe UI", tam)
    return tk.Label(padre, text=texto, bg=COLOR["fondo"], fg=COLOR[color],
                    font=fuente)


def _listado(padre, fuente=9, **extra):
    """El Listbox oscuro que usan las dos ventanas."""
    import tkinter as tk
    return tk.Listbox(padre, bg=COLOR["hueco"], fg=COLOR["texto"],
                      selectbackground=COLOR["titulo"],
                      selectforeground=COLOR["hueco"],
                      font=("Consolas", fuente), activestyle="none",
                      borderwidth=0, highlightthickness=0, **extra)


def _botonera(padre, botones):
    """Una fila de botones a partir de [(texto, funcion, color)]."""
    import tkinter as tk
    marco = tk.Frame(padre, bg=COLOR["fondo"])
    marco.pack(fill="x", padx=12, pady=12)
    for texto, orden, color in botones:
        tk.Button(marco, text=texto, command=orden, bg=COLOR[color],
                  fg=COLOR["hueco"], font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=12,
                  pady=6).pack(side="left", padx=(0, 8))
    return marco


def _al_frente(win):
    """La sube una vez y le quita el "siempre encima" enseguida.

    Al darle al play la ventana nace detras del editor; dejarla fija delante
    estorbaria luego a las ventanas de OpenCV.
    """
    win.lift()
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))


# Donde se guardan las ultimas carpetas usadas. En el perfil del usuario y no
# junto al archivo, para que funcione aunque el programa este en una carpeta de
# solo lectura o dentro del repositorio.
MEMORIA_CARPETAS = Path.home() / ".rx_camara_carpetas"


def _recordar_carpeta(ruta):
    """Apunta la carpeta de un video escogido a mano, para la proxima vez."""
    try:
        carpeta = str(Path(ruta).resolve().parent)
        previas = [l for l in _leer_carpetas_recordadas() if l != carpeta]
        MEMORIA_CARPETAS.write_text(
            "\n".join([carpeta] + previas[:4]), encoding="utf-8")
    except OSError:
        pass                       # recordar es una comodidad, no un requisito


def _leer_carpetas_recordadas():
    try:
        return [l.strip() for l in
                MEMORIA_CARPETAS.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except OSError:
        return []


def carpetas_de_videos():
    """Donde buscar videos. NO hay ninguna ruta fija en el codigo.

    Se mira, por este orden:
      1. la carpeta de este archivo y un nivel de sus subcarpetas
      2. la carpeta desde la que se ejecuta (y sus subcarpetas)
      3. las ultimas carpetas de las que se escogio un video a mano

    Asi quien descargue el repositorio deja sus videos al lado del archivo (o
    en una subcarpeta) y los ve igual, sin tocar nada. Y a quien los tenga en
    otro sitio le basta con escogerlos una vez con 'Buscar otro archivo'.
    """
    bases, vistas = [], set()
    candidatas = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    candidatas += [Path(p) for p in _leer_carpetas_recordadas()]
    for base in candidatas:
        try:
            base = base.resolve()
        except OSError:
            continue
        if base in vistas or not base.is_dir():
            continue
        vistas.add(base)
        bases.append(base)
        try:
            bases += sorted(d for d in base.iterdir() if d.is_dir()
                            and not d.name.startswith((".", "__")))
        except OSError:
            pass
    return bases


def buscar_videos():
    """Los videos de esas carpetas, del mas reciente al mas viejo."""
    vistos, salida = set(), []
    for carpeta in carpetas_de_videos():
        try:
            hijos = list(carpeta.iterdir())
        except OSError:
            continue
        for f in hijos:
            if f.suffix.lower() in EXT_VIDEO and f.resolve() not in vistos:
                vistos.add(f.resolve())
                salida.append(f)
    salida.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return salida


def _preguntar_cual_camara(padre=None):
    """Ventana para escoger CUAL camara, como la lista de Zoom o Meet.

    Devuelve el indice (0, 1, ...), o la URL escrita, o None si se cancela.
    La del celular aparece aqui con su nombre siempre que Windows la vea como
    una camara mas: Enlace movil, DroidCam, Iriun, EpocCam. Si en cambio se
    usa una aplicacion tipo IP Webcam, que publica la camara en la red, va por
    la casilla de la URL.
    """
    import tkinter as tk

    nombres = nombres_camaras()
    if nombres:
        opciones = list(enumerate(nombres))
    else:
        # sin pygrabber no hay nombres: se abren para ver cuales responden
        opciones = [(i, "camara %d   %dx%d%s"
                     % (i, w, h, "   (imagen NEGRA)" if brillo < 6 else ""))
                    for i, _n, w, h, brillo in camaras_disponibles()]
        if not opciones:
            opciones = [(i, "camara %d" % i) for i in range(3)]

    elegida = {"cual": None}
    win = tk.Toplevel(padre) if padre is not None else tk.Tk()
    win.title("Que camara uso?")
    win.configure(bg=COLOR["fondo"])
    win.geometry("560x360")

    _rotulo(win, "Camaras del PC (doble clic para usarla)").pack(
        anchor="w", padx=12, pady=(12, 4))

    lista = _listado(win, fuente=10)
    lista.pack(fill="both", expand=True, padx=12)
    for i, nombre in opciones:
        lista.insert("end", "  %d)  %s" % (i, nombre))
    lista.selection_set(0)

    _rotulo(win, "...o la direccion de una camara por red "
                 "(IP Webcam, camara IP):",
            color="suave", tam=9, negrita=False).pack(
        anchor="w", padx=12, pady=(10, 2))
    url = tk.Entry(win, bg=COLOR["hueco"], fg=COLOR["texto"],
                   insertbackground=COLOR["texto"], font=("Consolas", 9),
                   relief="flat")
    url.pack(fill="x", padx=12)

    def usar(_=None):
        texto = url.get().strip()
        if texto:
            elegida["cual"] = texto
        else:
            sel = lista.curselection()
            if not sel:
                return
            elegida["cual"] = opciones[sel[0]][0]
        win.destroy()

    lista.bind("<Double-Button-1>", usar)
    lista.bind("<Return>", usar)
    url.bind("<Return>", usar)

    _botonera(win, (("Usar esta camara", usar, "ok"),
                    ("Cancelar", win.destroy, "cancelar")))

    win.bind("<Escape>", lambda _: win.destroy())
    lista.focus_set()
    _al_frente(win)
    if padre is not None:
        win.transient(padre)
        win.grab_set()
        padre.wait_window(win)
    else:
        win.mainloop()
    return elegida["cual"]


def elegir_fuente():
    """Ventana para escoger que analizar.

    Devuelve (ruta_video, camara, simular): 'simular' a True significa pasar
    ese video por el camino de la CAMARA EN VIVO en vez de leerlo como archivo.

    Existe para poder darle al boton de play y probar una toma sin escribir un
    comando. Si no hay tkinter cae a un menu por consola.
    """
    videos = buscar_videos()
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return _elegir_por_consola(videos)

    elegido = {"video": None, "camara": None, "simular": False}
    raiz = tk.Tk()
    raiz.title("Receptor por camara - que quieres analizar?")
    raiz.configure(bg=COLOR["fondo"])
    raiz.geometry("780x430")

    _rotulo(raiz, "Videos encontrados junto a este archivo "
                  "(doble clic para descifrar)").pack(
        anchor="w", padx=12, pady=(12, 4))

    marco = tk.Frame(raiz, bg=COLOR["fondo"])
    marco.pack(fill="both", expand=True, padx=12)
    barra = tk.Scrollbar(marco)
    barra.pack(side="right", fill="y")
    lista = _listado(marco, yscrollcommand=barra.set)
    lista.pack(side="left", fill="both", expand=True)
    barra.config(command=lista.yview)

    if videos:
        for v in videos:
            lista.insert("end", "  %-28s  %s" % (v.name, v.parent))
        lista.selection_set(0)
    else:
        lista.insert("end", "  (no hay videos en esta carpeta ni en sus "
                            "subcarpetas: usa 'Buscar otro archivo')")

    def analizar(_=None):
        sel = lista.curselection()
        if sel and videos:
            elegido["video"] = str(videos[sel[0]])
            raiz.destroy()

    def otro():
        r = filedialog.askopenfilename(
            title="Escoge un video",
            filetypes=[("Videos", "*.mp4 *.avi *.mov *.mkv *.m4v"),
                       ("Todos", "*.*")])
        if r:
            elegido["video"] = r
            _recordar_carpeta(r)
            raiz.destroy()

    def camara():
        cual = _preguntar_cual_camara(raiz)
        if cual is not None:
            elegido["camara"] = cual
            raiz.destroy()

    def como_en_vivo():
        """El video seleccionado, pero pasado por el camino de la camara.

        Es la unica manera de probar la escucha en vivo sin tener el montaje
        delante: el receptor ve los cuadros de uno en uno, con el reloj del
        video, sin poder volver atras. Si funciona aqui, funciona en vivo.
        """
        sel = lista.curselection()
        if sel and videos:
            elegido["video"] = str(videos[sel[0]])
            elegido["simular"] = True
            raiz.destroy()

    lista.bind("<Double-Button-1>", analizar)
    lista.bind("<Return>", analizar)

    _botonera(raiz, (
        ("Descifrar el seleccionado", analizar, "ok"),
        ("Buscar otro archivo...", otro, "titulo"),
        ("Camara en vivo", camara, "camara"),
        ("Probarlo como si fuera en vivo", como_en_vivo, "probar")))

    raiz.bind("<Escape>", lambda _: raiz.destroy())
    lista.focus_set()
    _al_frente(raiz)
    raiz.mainloop()
    return elegido["video"], elegido["camara"], elegido["simular"]


def _elegir_camara_por_consola():
    """Lo mismo que la ventana, pero escribiendo. Devuelve indice o URL."""
    nombres = nombres_camaras()
    if nombres:
        print("\nCamaras del PC:")
        for i, nombre in enumerate(nombres):
            print("  %2d) %s" % (i, nombre))
    else:
        print("\nBuscando camaras (instala pygrabber para ver los nombres)...")
        for i, nombre, w, h, brillo in camaras_disponibles():
            aviso = "   <- imagen NEGRA" if brillo < 6 else ""
            print("  %2d) %s   %dx%d%s" % (i, nombre, w, h, aviso))
    r = input("Cual uso? (numero, o una URL http/rtsp) [0]: ").strip() or "0"
    return int(r) if r.isdigit() else r


def _elegir_por_consola(videos):
    if not videos:
        return None, _elegir_camara_por_consola(), False
    print("\nVideos encontrados:")
    for i, v in enumerate(videos, 1):
        print("  %2d) %s   (%s)" % (i, v.name, v.parent))
    print("   c) camara en vivo")
    print("   (poner una v delante del numero lo pasa por el camino de la")
    print("    camara en vivo: v3 = el 3 como si fuera en vivo)")
    r = input("Cual descifro? [1]: ").strip().lower() or "1"
    if r == "c":
        return None, _elegir_camara_por_consola(), False
    simular = r.startswith("v")
    try:
        return str(videos[int(r.lstrip("v")) - 1]), None, simular
    except (ValueError, IndexError):
        return str(videos[0]), None, False


# ------------------------------------------------------------- dibujo -----
def pintar_bloque(grid, ancho=620, alto=520, titulo=""):
    """El bloque recibido, tal como se debe copiar en la hoja."""
    img = np.full((alto, ancho, 3), 24, np.uint8)
    if not grid:
        cv2.putText(img, "no se pudo descifrar", (20, alto // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1,
                    cv2.LINE_AA)
        cv2.putText(img, titulo[:70], (14, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (120, 160, 220), 1, cv2.LINE_AA)
        return img
    filas, cols = len(grid), len(grid[0])
    lado = max(14, min((ancho - 40) // cols, (alto - 80) // filas))
    x0 = (ancho - lado * cols) // 2
    y0 = 52
    for i in range(filas):
        for j in range(cols):
            v = grid[i][j]
            x, y = x0 + j * lado, y0 + i * lado
            if v == NEGRO:
                color = (20, 20, 20)
            elif v == "?":
                color = (40, 40, 190)          # celda que no llego
            else:
                color = (250, 250, 250)
            cv2.rectangle(img, (x, y), (x + lado, y + lado), color, -1)
            cv2.rectangle(img, (x, y), (x + lado, y + lado), (90, 90, 90), 1)
            if v not in (NEGRO, BLANCO):
                # las fuentes de OpenCV son ASCII puro: la Ñ se pinta como N
                # con la virgulilla encima, o saldria "??" en pantalla
                letra = "N" if v == "Ñ" else v
                esc = lado / 34.0
                (tw, th), _ = cv2.getTextSize(
                    letra, cv2.FONT_HERSHEY_SIMPLEX, esc, 2)
                cv2.putText(img, letra,
                            (x + (lado - tw) // 2, y + (lado + th) // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, esc, (0, 0, 0), 2,
                            cv2.LINE_AA)
                if v == "Ñ":
                    cv2.putText(img, "~",
                                (x + (lado - tw) // 2, y + th // 2 + 2),
                                cv2.FONT_HERSHEY_SIMPLEX, esc * 0.8,
                                (0, 0, 0), 2)
    cv2.putText(img, titulo[:70], (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58,
                (140, 230, 160) if "valido" in titulo else (140, 190, 240),
                1, cv2.LINE_AA)
    return img


def imprimir_bloque(grid, nota):
    """El bloque en la consola, para copiarlo a la hoja sin abrir ventanas."""
    print("\n" + "=" * 52)
    print("  " + nota)
    if grid:
        print("  bloque %dx%d:" % (len(grid), len(grid[0])))
        print()
        for fila in grid:
            print("      " + "  ".join(fila))
        if "CRC valido" not in nota:
            print()
            print("  OJO: el CRC no cuadro. Las dimensiones son de fiar (la")
            print("  cabecera trae su propia suma de control) pero las celdas")
            print("  pueden estar mal, no solo las que salen con '?'.")
    else:
        print("  no se pudo descifrar el bloque")
    print("=" * 52 + "\n")


def mostrar_resultado(grid, nota, guardar=None):
    """Deja el bloque en pantalla hasta que se cierre. Nada mas.

    No se reproduce el video: el resultado ya esta calculado y lo unico que
    falta es verlo.
    """
    titulo = (nota if not grid else
              "%dx%d  -  %s" % (len(grid), len(grid[0]), nota))
    img = pintar_bloque(grid, titulo=titulo)
    if guardar:
        cv2.imwrite(guardar, pintar_bloque(grid, 900, 760, titulo))
        print("imagen guardada en %s" % guardar)
    cv2.imshow("bloque recibido  ('s' guarda, 'q' cierra)", img)
    while True:
        k = cv2.waitKey(50) & 0xFF
        if k in (ord("q"), 27):
            break
        if k == ord("s") and grid:
            nombre = "bloque_recibido_%s.png" % time.strftime("%H%M%S")
            cv2.imwrite(nombre, pintar_bloque(grid, 900, 760, titulo))
            print("guardado:", nombre)
        # si cierran la ventana con la X
        if cv2.getWindowProperty("bloque recibido  ('s' guarda, 'q' cierra)",
                                 cv2.WND_PROP_VISIBLE) < 1:
            break
    cv2.destroyAllWindows()


VENTANA_CAMARA = ("camara   q salir | r reiniciar | + - exposicion | "
                  "m buscar solo en un recuadro | a en todo el cuadro")


AVISO_IMAGEN_NEGRA = (
    "- tiene tapa de privacidad puesta?",
    "- la esta usando otra aplicacion (Teams, Zoom, Meet)?",
    "- exposicion muy baja: subela con la tecla +",
    "- prueba otra camara: --camara 1",
)


def _rotular(vista, texto, fila, escala=0.5, color=(160, 220, 160)):
    cv2.putText(vista, texto, (12, 26 + fila * 22), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, 1, cv2.LINE_AA)


def _pintar_camara(e):
    """El cuadro de la camara con los recuadros y el estado encima."""
    cuadro = e["cuadro"]
    vista = cuadro.copy()

    # Los recuadros van en pixeles del cuadro TAL CUAL lo entrega la camara:
    # desde que se mide sin reducir no hay ninguna escala que deshacer.
    if e["zona"]:
        x, y, w, h = e["zona"]
        cv2.rectangle(vista, (x, y), (x + w, y + h), (0, 255, 255), 2)
    # Se pintan TODAS las parejas que se miden, no solo la mejor: de un
    # vistazo se ve por que no engancha (un recuadro sobre la persona que
    # pasa canta enseguida). La primera es la que mas pinta de transmisor.
    for i, (x, y, w, h) in enumerate(e["rois"]):
        m = max(6, w // 3)
        color = ((0, 255, 0) if e["congelado"] else
                 (255, 180, 0) if i == 0 else (140, 140, 140))
        cv2.rectangle(vista, (x - m, y - m), (x + w + m, y + h + m), color,
                      2 if i == 0 else 1)

    # Una camara tapada, ocupada por otra aplicacion o con la exposicion muy
    # baja se ve igual que una que no funciona, asi que hay que decirlo.
    brillo = float(cuadro.mean())
    if brillo < 6:
        _rotular(vista, "LA CAMARA ENTREGA IMAGEN NEGRA (brillo medio %.1f "
                        "de 255)" % brillo, 0, 0.55, (60, 60, 255))
        for i, texto in enumerate(AVISO_IMAGEN_NEGRA, start=1):
            _rotular(vista, texto, i, 0.45, (120, 200, 255))
    else:
        _rotular(vista, e["estado"], 0, 0.55,
                 (120, 255, 180) if e["enganchado"] else (120, 200, 255))
        if e["zona"]:
            _rotular(vista, "buscando solo dentro del recuadro "
                            "(a = en todo el cuadro)", 1, 0.45, (0, 255, 255))

    cv2.putText(vista, "%ds  %d medidos  %.0f fps%s"
                % (e["segundos"], e["cuadros"], e["fps"],
                   "  descifrando..." if e["descifrando"] else ""),
                (12, vista.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (160, 220, 160), 1, cv2.LINE_AA)
    return vista


def _pedir_zona(cuadro):
    """Deja marcar donde buscar. Devuelve el recuadro en pixeles originales.

    Se marca sobre una copia reducida para que el cuadro quepa en pantalla.
    """
    esc = min(1.0, 640.0 / cuadro.shape[1])
    cv2.namedWindow("donde buscar las luces", cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI("donde buscar las luces",
                               cv2.resize(cuadro, None, fx=esc, fy=esc),
                               showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("donde buscar las luces")
    if w <= 4 or h <= 4:
        return None
    return tuple(int(round(v / esc)) for v in (x, y, w, h))


def _atender_teclado(e, tecla):
    """Traduce una tecla a lo que espera escuchar_camara."""
    if tecla in (ord("q"), 27):
        return False
    if tecla == ord("r"):
        return "reiniciar"
    if tecla == ord("m"):
        zona = _pedir_zona(e["cuadro"])
        return {"zona": zona} if zona else True
    if tecla == ord("a"):
        return {"zona": None}
    if tecla in (ord("+"), ord("=")):
        return {"exposicion": (e["exposicion"] or -7) + 1}
    if tecla == ord("-"):
        return {"exposicion": (e["exposicion"] or -7) - 1}
    # cerrar la ventana con la X tambien para
    if cv2.getWindowProperty(VENTANA_CAMARA, cv2.WND_PROP_VISIBLE) < 1:
        return False
    return True


def dibujar_vista(e):
    """Pinta la escucha y devuelve lo que haya pedido el teclado.

    Se llama en cada cuadro, asi que las teclas responden al momento: buscar y
    descifrar van en otro hilo.
    """
    vista = _pintar_camara(e)
    esc = min(1.0, 640.0 / vista.shape[1])
    cv2.imshow(VENTANA_CAMARA, cv2.resize(vista, None, fx=esc, fy=esc))
    titulo = ("BLOQUE COMPLETO - " if e["congelado"] else "") + e["nota"]
    cv2.imshow("bloque recibido", pintar_bloque(e["grid"], titulo=titulo))
    return _atender_teclado(e, cv2.waitKey(1) & 0xFF)


# ##########################################################################
#  6. ARRANQUE
# ##########################################################################

def autoprueba():
    """Comprueba las secciones 1 y 3 sin camara ni video.

    Se arma una trama, se codifica a estados de las luces, se le añaden
    repeticiones como las que produciria una camara, y se decodifica.
    """
    grid = [["H", "O", "L", "A"], [NEGRO] * 4,
            ["M", "U", "N", "D"], ["O", BLANCO, BLANCO, BLANCO]]
    payload = celdas_a_bits(grid)
    bits = construir_trama(TIPO_BLOQUE, 4, 4, payload)
    info = analizar_trama(bits)
    assert info["crc_ok"] and info["filas"] == 4 and info["cols"] == 4
    assert a_cuadricula(info) == grid

    simbolos = codificar_linea(bits)
    assert len(simbolos) == simbolos_necesarios(len(bits))
    # como lo veria una camara a 5 cuadros por simbolo
    vistos = [s for s in simbolos for _ in range(5)]
    limpios = simbolos_estables(vistos, 5.0)
    info2 = analizar_trama(decodificar_linea(limpios)[0])
    assert info2["crc_ok"] and a_cuadricula(info2) == grid

    # un bit corrompido tiene que caer en el CRC-16, pero la cabecera debe
    # seguir legible para poder pintar lo que si llego
    malo = list(bits)
    k = BITS_CABECERA + 20
    malo[k] = "1" if malo[k] == "0" else "0"
    roto = analizar_trama("".join(malo))
    assert not roto["crc_ok"] and roto["cabecera_ok"]

    print("autoprueba OK")
    print("  trama de %d bits -> %d simbolos" % (len(bits), len(simbolos)))
    print("  empieza asi: %s ..."
          % " ".join(NOMBRES_ESTADO[s] for s in simbolos[:16]))
    print("               (12 alternancias de preambulo, y AB -- es el SFD)")
    print("  a 12,5 simbolos/s son %.1f s por copia" % (len(simbolos) / 12.5))
    return 0


def _argumentos():
    ap = argparse.ArgumentParser(
        description="Receptor por camara de dos luces. Sin argumentos "
                    "pregunta que video descifrar.")
    ap.add_argument("--video",
                    help="descifra este archivo y muestra el bloque")
    ap.add_argument("--simular-vivo", dest="simular_vivo",
                    help="pasa un video grabado por el camino de la CAMARA EN "
                         "VIVO, para probar la escucha sin montaje delante")
    ap.add_argument("--tiempo-real", dest="tiempo_real", action="store_true",
                    help="con --simular-vivo, entrega los cuadros a la "
                         "velocidad de la toma y no lo mas rapido posible")
    ap.add_argument("--camara", default=None,
                    help="escucha en vivo: un numero (0 es la primera), "
                         "parte del nombre de la camara, o una URL de "
                         "celular/camara IP")
    ap.add_argument("--exposicion", type=int, default=EXPOSICION_CAMARA,
                    help="exposicion de la camara (-7 es baja); sin esto la "
                         "decide la camara")
    ap.add_argument("--camaras", action="store_true",
                    help="lista las camaras que responden y termina")
    ap.add_argument("--simbolos", default=SIMBOLOS_POR_SEGUNDO or "auto",
                    help="simbolos/s del transmisor, o 'auto' para medirlos "
                         "sobre la señal")
    ap.add_argument("--guardar", help="guarda el bloque recibido en este .png")
    ap.add_argument("--autoprueba", action="store_true",
                    help="comprueba la codificacion sin camara ni video")
    return ap.parse_args()


def listar_camaras():
    """Imprime que camaras responden, con su nombre si se puede."""
    print("Buscando camaras...")
    halladas = camaras_disponibles()
    if not halladas:
        print("  ninguna responde.")
        return 1
    for i, nombre, w, h, brillo in halladas:
        aviso = "   <- entrega imagen NEGRA" if brillo < 6 else ""
        print("  --camara %d   %-34s %dx%d   brillo medio %.1f%s"
              % (i, nombre[:34], w, h, brillo, aviso))
    if not nombres_camaras():
        print("\n(instala pygrabber para ver el NOMBRE de cada camara:"
              "  pip install pygrabber)")
    print("\nTambien vale el nombre en vez del numero, o una URL:")
    print('  --camara "iriun"      --camara http://192.168.1.5:8080/video')
    return 0


def descifrar_archivo(ruta, simbolos, guardar=None):
    """Un video grabado, de principio a fin."""
    print("Video: %s" % Path(ruta).name)
    print("Encierra las dos luces con el mouse y pulsa Enter, o C para que "
          "las busque solo.")
    zona = seleccionar_zona_video(ruta)
    t0 = time.time()
    grid, nota, _, _ = procesar_video(ruta, simbolos, zona=zona)
    print("   (%.0f s)" % (time.time() - t0))
    imprimir_bloque(grid, nota)
    mostrar_resultado(grid, nota, guardar)
    return 0


def descifrar_simulando(ruta, simbolos, tiempo_real=False, guardar=None):
    """El mismo video, pero por el camino de la camara en vivo."""
    print("Simulando la camara en vivo con %s" % Path(ruta).name)
    print("  q salir | r reiniciar | m limitar la busqueda | a quitar")
    grid, nota = simular_vivo(ruta, simbolos, al_actualizar=dibujar_vista,
                              tiempo_real=tiempo_real)
    cv2.destroyAllWindows()
    imprimir_bloque(grid, nota)
    mostrar_resultado(grid, nota, guardar)
    return 0


def descifrar_en_vivo(cual, simbolos, exposicion=None, guardar=None):
    """La camara, hasta que se cierre la ventana o cuadre un CRC."""
    cual = resolver_camara(cual)
    nombres = nombres_camaras()
    etiqueta = cual
    if str(cual).isdigit() and int(cual) < len(nombres):
        etiqueta = "%s (%s)" % (cual, nombres[int(cual)])
    print("Escuchando la camara %s." % etiqueta)
    print("  q salir | r reiniciar | + - exposicion | "
          "m limitar la busqueda a un recuadro | a quitarlo")
    grid, nota = escuchar_camara(cual, simbolos, exposicion=exposicion,
                                 al_actualizar=dibujar_vista)
    cv2.destroyAllWindows()
    imprimir_bloque(grid, nota)
    if grid and guardar:
        cv2.imwrite(guardar, pintar_bloque(grid, 900, 760, nota))
        print("imagen guardada en %s" % guardar)
    return 0


def main():
    args = _argumentos()
    if args.autoprueba:
        return autoprueba()
    if args.camaras:
        return listar_camaras()

    simbolos = (None if str(args.simbolos).strip().lower() == "auto"
                else float(args.simbolos))

    # Sin argumentos -el caso de darle al play- se pregunta que analizar, en
    # vez de asumir la camara: probar una toma grabada es lo que mas se hace.
    if args.video is None and args.camara is None and not args.simular_vivo:
        args.video, args.camara, simular = elegir_fuente()
        if args.video is None and args.camara is None:
            print("No se escogio nada.")
            return 0
        if simular:
            args.simular_vivo, args.video = args.video, None

    if args.simular_vivo:
        return descifrar_simulando(args.simular_vivo, simbolos,
                                   args.tiempo_real, args.guardar)
    if args.video:
        return descifrar_archivo(args.video, simbolos, args.guardar)
    return descifrar_en_vivo(args.camara, simbolos, args.exposicion,
                             args.guardar)


if __name__ == "__main__":
    sys.exit(main())
