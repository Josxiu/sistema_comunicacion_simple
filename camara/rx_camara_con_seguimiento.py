# -*- coding: utf-8 -*-
"""Receptor por camara que SIGUE las luces cuadro a cuadro.

Redes de Computadores I, UdeA 2026-2, Proyecto 01. Lee las dos luces de un
video o de la camara en vivo y reconstruye el bloque de celdas. Al seguir las
luces aguanta grabar con el celular en la mano, a costa de tardar varios
minutos por video; para tomas con la camara apoyada, rx_camara.py es mas
rapido.

Sin argumentos sale una ventana con los videos que haya al lado. Funciona
solo, sin nada del proyecto, solo numpy y opencv-python.

    python -m pip install numpy opencv-python

Todo lo ajustable esta en la seccion 0. Secciones (de lo abstracto a lo
concreto, cada una usa solo las anteriores):

    0. PARAMETROS      lo ajustable, todo junto.
    1. EL CODIGO       bits <-> celdas.
    2. PDI             imagen -> estado de las luces.
    3. DECODIFICADOR   estados en el tiempo -> bloque de celdas.
    4. PROCESAR        un video entero, o la camara en vivo.
    5. INTERFAZ        elegir la fuente y pintar el resultado.
    6. ARRANQUE

Las 1 y 3 son puro calculo (--autoprueba las prueba), la 2 es la unica que
toca pixeles y la 5 la unica que abre ventanas.

Cosas a tener en cuenta:

- Cual luz esta prendida se decide por color (si las dos se funden en un punto,
  hacen falta colores distintos) o por posicion (si se ven separadas, sirve
  cualquier color, blancas incluidas). MODO_LUCES = "auto" prueba las dos.
- Con el celular en la mano las luces se van del cuadro; por eso primero se
  BUSCAN (por ritmo, 5-12 Hz, y por brillo) y luego se SIGUEN. Sintoma tipico
  de recuadro fijo mal puesto: el preambulo se lee bien y en cuanto empiezan
  los datos salen tramos larguisimos con el mismo estado. Al grabar ayuda
  acercarse y apoyar el celular.
- La velocidad maxima es fps/3: 10 simbolos/s a 30 fps, 20 a 60. Manda la tasa
  de cuadros, no la luz ambiente; grabar a 60 fps.
- La camara en vivo es otro problema, no un archivo mas rapido: cada cuadro
  pasa una sola vez. Se siguen varias parejas a la vez y se guardan solo cuatro
  numeros por cuadro. Los reflejos en vidrios y pantallas parpadean igual que
  las luces, asi que una pareja solo cuenta si sus dos puntos se diferencian.
- --simular-vivo "toma.mp4" pasa un video por el camino de la camara, para
  saber si un fallo es de la camara o del receptor.
- Camara en vivo: sale la lista de camaras del PC (nombres via pygrabber; sin
  el, numeros). Un celular a 60 fps por IP Webcam es lo mejor
  (--camara http://IP:8080/video); tambien DroidCam/Iriun/EpocCam o el Enlace
  movil de Windows. Imagen negra = tapa de privacidad, otra app con la camara,
  o exposicion baja (tecla + en vivo).
"""

import argparse
import gc
import math
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np


# ##########################################################################
#  0. PARAMETROS
# ##########################################################################

# --- COMO ESTAN PUESTAS LAS LUCES ---------------------------------------
# "auto"      prueba por color y, si no engancha, por posicion (recomendado)
# "color"     las dos luces se funden en un punto -> colores distintos
# "posicion"  se ven como dos puntos separados -> sirve cualquier color
MODO_LUCES = "auto"

# Cual luz es la "A": None prueba las dos y se queda con la del CRC valido.
# True = la mas roja, False = la otra. Fijarlo solo ahorra trabajo. El receptor
# no necesita los colores exactos: mide croma = (R-G)/(R+G) y compara una luz
# con la otra; da igual naranja/azul mientras una sea mas roja.
LUZ_A_ES_LA_MAS_ROJA = None

# Distancia minima (px de la imagen de trabajo) para que el localizador de
# recuadro QUIETO de dos luces por separadas. El seguimiento tiene su propio
# minimo, mucho mas corto (llega a leer dos puntos a 9 px).
SEPARACION_MINIMA_PX = 12

# --- VELOCIDAD ---------------------------------------------------------
# Simbolos/s del transmisor; None = medirlo sobre la señal.
SIMBOLOS_POR_SEGUNDO = None

# Las que se prueban si la medida no cuadra.
VELOCIDADES_TIPICAS = (5, 4, 6, 3, 8, 2, 10, 1, 12.5, 15, 20)

# Menos cuadros por simbolo que esto y la grabacion no sirve (medido).
CUADROS_POR_SIMBOLO_MIN = 3.0

# --- CAMARA EN VIVO --------------------------------------------------
# Cual camara: numero (0 = la primera), URL http/rtsp, o parte del nombre
# ("iriun"). Se cambia con --camara o desde la lista.
CAMARA = 0

# fps que se le piden. Pedir 60 es lo importante.
FPS_CAMARA = 60.0

# Exposicion en vivo. None = la camara decide (empezar asi). -7 la baja para
# que las luces conserven el color, pero deja la imagen casi negra en un cuarto
# normal. En vivo se ajusta con + y -.
EXPOSICION_CAMARA = None

# Cada cuantos segundos se reintenta descifrar mientras escucha (en otro hilo,
# la ventana sigue respondiendo).
REINTENTO_VIVO_S = 2.0

# Cuadros de historia en vivo (a 60 fps, 3600 = 1 min). Son las medidas de cada
# cuadro, cuatro numeros, no imagenes.
HISTORIA_VIVO_CUADROS = 3600

# Ancho al que se reduce el cuadro SOLO para buscar en vivo (medir va sin
# reducir, y eso arreglo la escucha: a 320 px las dos luces del cuarto quedan a
# 6 px y el recuadro medía las dos, con el estado siempre en "las dos
# prendidas"). Buscar tampoco puede bajar de 640: el localizador borra la
# mancha conexa de cada pico antes del siguiente, y por debajo de 640 los halos
# son una sola mancha, asi que al borrar la primera luz se lleva la segunda. El
# buffer va en gris, subir a 640 no cuesta memoria.
ANCHO_BUSQUEDA_VIVO = 640

# Cuadros que se juntan antes de localizar en vivo: 90 son 1,5 s a 60 fps.
CUADROS_BUSQUEDA_VIVO = 90

# Cuadros reducidos que se guardan para precargar una pareja nueva con lo ya
# ocurrido. Una pareja solo se encuentra cuando YA parpadea, o sea con la
# rafaga empezada, y entre juntar el bloque y buscar nace 2-3 s tarde, justo
# encima del preambulo. Con 240 (4 s a 60 fps) nace con esos segundos ya
# medidos. En gris para que quepa.
CUADROS_PRECARGA_VIVO = 240

# Una vez fijados, los recuadros de una pareja no se mueven. Moverlos empeora:
# un servo de brillo se va solo hacia el halo de la luz encendida (derivas
# medidas de 10 a 22 px) y saltar a la siguiente busqueda deja un escalon en
# mitad de una trama que dura medio minuto. Si las luces se mueven de verdad,
# la busqueda las encuentra en el sitio nuevo y entran como una pareja nueva;
# decide el CRC.

# Segundos sin ver parpadeo antes de soltar una pareja. Mas que el hueco entre
# dos copias del bloque, o se tiraria una rafaga recien recibida.
PACIENCIA_VIVO_S = 8.0

# Parejas que se siguen a la vez. Medir una no cuesta casi nada, y seguir
# varias salva la escucha de un mal comienzo: mientras alguien pasa por delante
# el mapa de parpadeo lo señala a el y no a los LED.
MAX_CANDIDATOS_VIVO = 5

# Cada cuantos segundos se vuelve a buscar mientras no salga el bloque (en otro
# hilo, no frena la imagen).
BUSQUEDA_CADA_S = 3.0

# --- SEGUIR LAS LUCES ------------------------------------------------
# Con el celular en la mano las luces no se quedan quietas; el receptor primero
# las BUSCA y luego las SIGUE cuadro a cuadro. Con la camara apoyada se puede
# apagar.
SEGUIR_LUCES = True

# Cada cuantos cuadros se vuelve a fijar donde estan las luces. Los dos no
# valen para lo mismo: 45 para luz pequeña y lejana (hace falta acumular
# parpadeos), 20 para camara temblorosa de cerca.
BLOQUES_SEGUIMIENTO = (45, 20)

# Lado (px) del recuadro que se mide sobre cada luz ya seguida.
LADOS_SEGUIMIENTO = (8, 12)

# Tramos del video de donde se sacan puntos de partida. Cada tramo da dos (el
# pico puede ser cualquiera de las dos luces) y cada punto cuesta una pasada.
SEMILLAS_SEGUIMIENTO = 2

# Banda de parpadeo (Hz). Distingue la luz (5-12 Hz) de la gente que pasa (por
# debajo de 2 Hz).
BANDA_PARPADEO = (2.0, 25.0)

# Separacion (min, max) entre las dos luces, en px de la imagen de trabajo,
# para darlas por buenas al buscarlas.
SEPARACION_SEGUIMIENTO = (4.0, 80.0)

# --- PROCESO DE IMAGEN ---------------------------------------------
# Ancho al que se reduce cada cuadro para medir. 320 va de sobra y hace que un
# video de 25 s se procese en medio minuto.
ANCHO_TRABAJO = 320

# Ancho del segundo intento, solo si el primero no engancha. Con las luces a
# 40 m quedan a 9 px y a 320 se funden; cuesta otra pasada entera, asi que se
# deja para cuando el intento barato ya fallo. None lo desactiva.
ANCHO_SEGUNDO_INTENTO = 640

# Cada cuantas muestras se recalculan los umbrales moviles; en medio se
# interpolan. Son percentiles de +-260 muestras, casi no se mueven, y asi va
# veinte veces mas rapido: en vivo se descifra la historia entera cada dos
# segundos y por varias parejas.
PASO_UMBRALES = 20

# Rachas mas cortas que esta fraccion del simbolo se tiran: glitch de que las
# dos lamparas no cambian a la vez.
FRAC_GLITCH = 0.45

# Factores del periodo de simbolo que se prueban si el nominal no cuadra.
BARRIDO = [0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1]

# Recuadros candidatos que se prueban como maximo antes de rendirse.
MAX_CANDIDATOS_ROI = 18


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


def _destinos(estado):
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
        estado = _destinos(estado)[t % 3]
        simbolos.append(estado)
    return simbolos


def simbolos_a_trits(simbolos, estado_inicial=APAGADO):
    """Inverso. Un estado repetido no puede ser un simbolo valido, asi que se
    trata como el mismo simbolo visto dos veces y se ignora."""
    trits, estado = [], estado_inicial
    for s in simbolos:
        if s == estado:
            continue
        trits.append(_destinos(estado).index(s))
        estado = s
    return trits


def codificar_linea(bits):
    """Cadena de bits -> lista completa de estados, con preambulo y SFD."""
    simbolos = list(PREAMBULO) + list(SFD)
    simbolos += trits_a_simbolos(bits_a_trits(bits), estado_inicial=simbolos[-1])
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
#     Lo unico de todo el archivo que toca pixeles: de una imagen sale un par
#     de numeros (luminancia, croma) y de una serie de esos sale el estado de
#     las luces en cada cuadro.
# ##########################################################################

def _suavizar(img, k=5):
    """GaussianBlur que nunca revienta.

    Con recuadros diminutos, o cuando OpenCV se queda sin memoria, GaussianBlur
    lanza una excepcion de C++ sin mensaje ninguno. Leyendo un archivo eso es
    una molestia; en vivo tumbaba una escucha que llevaba un minuto acumulando,
    por un solo cuadro raro. Si falla se sigue con la imagen sin suavizar: mide
    un poco peor y no se pierde la toma.
    """
    if img.size == 0:
        return img
    try:
        return cv2.GaussianBlur(img, (k, k), 0)
    except cv2.error:
        return img


def medir(roi):
    """(luminancia, croma) de un recuadro BGR.

    croma = (R-G)/(R+G): positivo = luz roja, negativo = verde, ~0 = las dos
    (o ninguna, que se distingue por la luminancia). Dividir por (R+G) lo hace
    independiente de la exposicion.

    Se mide sobre los pixeles MAS BRILLANTES QUE NO ESTEN SATURADOS. Las dos
    exclusiones importan:

      * Promediar el cuadro entero solo funciona si la luz florece hasta
        llenarlo. Con la luz lejos y pequeña su aporte se diluye y desaparece.
      * Quedarse con el pico es peor: de cerca el nucleo satura en R=G=B=255 y
        ahi el color ya no existe. El color vive en el HALO, justo por debajo
        de la saturacion.
    """
    if roi.size == 0:
        return 0.0, 0.0
    suave = _suavizar(roi).astype(np.float32)
    b, g, r = suave[:, :, 0], suave[:, :, 1], suave[:, :, 2]
    plano = ((b + g + r) / 3.0).ravel()
    n = max(12, int(plano.size * 0.001))          # los N mas brillantes

    # Primero se descartan los saturados y DESPUES se toman los mas brillantes
    # de lo que queda. Al reves no sirve: con la luz cerca, mas del 3% del
    # cuadro puede estar saturado y un percentil fijo devuelve solo nucleo
    # blanco, sin color.
    idx_ok = np.flatnonzero(plano < 250)
    if idx_ok.size < n:
        idx_ok = np.arange(plano.size)
    n = min(n, idx_ok.size)
    orden = np.argpartition(plano[idx_ok], idx_ok.size - n)[idx_ok.size - n:]
    sel = idx_ok[orden]

    mr = float(r.ravel()[sel].mean())
    mg = float(g.ravel()[sel].mean())
    mb = float(b.ravel()[sel].mean())
    return (mr + mg + mb) / 3.0, (mr - mg) / (mr + mg + 1.0)


def _umbrales_moviles(v, ventana, bajo=10, alto=90, paso=PASO_UMBRALES):
    """Dos percentiles de una ventana movil CENTRADA, para toda la serie.

    Se calculan cada 'paso' muestras y se interpolan en medio: ver
    PASO_UMBRALES. Devuelve dos vectores del largo de v.
    """
    n = len(v)
    anclas = np.arange(0, n, paso)
    if len(anclas) == 0 or anclas[-1] != n - 1:
        anclas = np.append(anclas, n - 1)
    lo = np.empty(len(anclas), dtype=np.float32)
    hi = np.empty(len(anclas), dtype=np.float32)
    for k, i in enumerate(anclas):
        trozo = v[max(0, i - ventana):min(n, i + ventana)]
        lo[k], hi[k] = np.percentile(trozo, (bajo, alto))
    if n == len(anclas):
        return lo, hi
    todos = np.arange(n)
    return np.interp(todos, anclas, lo), np.interp(todos, anclas, hi)


def clasificar_serie(lums, cromas, ventana=260):
    """Series de (luminancia, croma) -> estado de las luces en cada cuadro.

    Los umbrales se recalculan sobre una ventana movil centrada. Es obligatorio
    porque el control de exposicion del celular deriva durante la toma: en una
    grabacion real el croma del verde paso de -0,09 (exposicion alta, al
    principio) a -0,21 (ya estabilizada). Con umbrales fijos el preambulo se
    lee mal y nunca engancha.
    """
    lums = np.asarray(lums, dtype=np.float32)
    cromas = np.asarray(cromas, dtype=np.float32)
    n = len(lums)
    if n == 0:
        return []
    p10, p90 = _umbrales_moviles(lums, ventana)
    corte_off = p10 + 0.35 * (p90 - p10)
    apagado = (p90 - p10 < 6) | (lums < corte_off)

    # los umbrales de croma dependen de QUE muestras estan encendidas en cada
    # ventana, asi que van por anclas igual que los de luminancia
    anclas = np.arange(0, n, PASO_UMBRALES)
    if anclas[-1] != n - 1:
        anclas = np.append(anclas, n - 1)
    ct1 = np.empty(len(anclas), dtype=np.float32)
    ct2 = np.empty(len(anclas), dtype=np.float32)
    hay = np.zeros(len(anclas), dtype=np.float32)
    for k, i in enumerate(anclas):
        a, b = max(0, i - ventana), min(n, i + ventana)
        encendidos = cromas[a:b][lums[a:b] >= corte_off[i]]
        if len(encendidos) < 10:
            ct1[k] = ct2[k] = 0.0
            continue
        lo, hi = np.percentile(encendidos, (12, 88))
        if hi - lo < 0.02:              # un solo color en la ventana
            ct1[k] = ct2[k] = 0.0
            continue
        ct1[k] = lo + 0.34 * (hi - lo)
        ct2[k] = lo + 0.68 * (hi - lo)
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


# Intercambiar cual luz es 'A' y cual es 'B'. NO es simetrico: el orden de los
# destinos cambia y con el los trits, asi que un cableado invertido produce
# basura con CRC fallido. Se prueban las dos y punto.
_INTERCAMBIO = {APAGADO: APAGADO, LUZ_A: LUZ_B, LUZ_B: LUZ_A, AMBAS: AMBAS}


def intercambiar(estados):
    """Cambia la luz A por la B en toda una traza."""
    return [_INTERCAMBIO[s] for s in estados]


# ------------------------------------------------ donde estan las luces ---
FRACCIONES_ROI = (0.75, 0.65, 0.55, 0.45)


def auto_roi(frames, frac=0.55):
    """Recuadro donde la luminancia PARPADEA, alrededor del maximo de varianza.

    'frac' decide que tan amplio queda: alto = pegado al nucleo, bajo = incluye
    el halo. El tamaño importa mas de lo que parece: uno amplio mete pared y
    cobijas alumbradas por el destello y diluye el color; uno pegado al nucleo
    saturado pierde el color del todo.
    """
    if not frames:
        return None
    pila = np.stack([f.astype(np.float32).mean(2) for f in frames])
    var = cv2.GaussianBlur(pila.std(0), (9, 9), 0)
    pico = float(var.max())
    if pico < 3.0:                       # nada parpadea: no hay luces a la vista
        return None
    mascara = (var >= pico * frac).astype(np.uint8)
    _, etiquetas, stats, _ = cv2.connectedComponentsWithStats(mascara, 8)
    y, x = np.unravel_index(np.argmax(var), var.shape)
    st = stats[etiquetas[y, x]]
    return int(st[0]), int(st[1]), int(st[2]), int(st[3])


def _region_en(var, y, x, frac, forma):
    """Recuadro conexo en (y,x) con varianza >= frac veces la de ahi."""
    alto, ancho = forma
    mascara = (var >= var[y, x] * frac).astype(np.uint8)
    _, etiquetas, stats, _ = cv2.connectedComponentsWithStats(mascara, 8)
    st = stats[etiquetas[y, x]]
    x0, y0, w, h = int(st[0]), int(st[1]), int(st[2]), int(st[3])
    if w < 6 or h < 6 or w > ancho * 0.92 or h > alto * 0.92:
        return None
    return x0, y0, w, h


def _muy_parecidos(a, b, umbral=0.80):
    """Interseccion sobre union de dos recuadros."""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return union > 0 and inter / float(union) >= umbral


def localizar_dos_luces(frames):
    """Los DOS puntos que parpadean, para leerlas por posicion.

    Sirve cuando las luces se ven separadas en la imagen, y entonces da igual
    de que color sean: cada una se mide por su lado y basta con distinguir
    prendida de apagada. Es la unica manera de usar dos luces del MISMO color.

    Se busca el maximo de varianza temporal, se tapa su entorno, y se busca el
    siguiente. Si el segundo queda pegado al primero es que en realidad son una
    sola luz vista de cerca (o las dos fundidas), y entonces esto no aplica:
    se devuelve None y el que llame probara por color.
    """
    if not frames:
        return None
    pila = np.stack([f.astype(np.float32).mean(2) for f in frames])
    var = cv2.GaussianBlur(pila.std(0), (5, 5), 0)
    if float(var.max()) < 3.0:
        return None

    restante = var.copy()
    picos = []
    for _ in range(2):
        y, x = np.unravel_index(np.argmax(restante), var.shape)
        if restante[y, x] < var.max() * 0.25:
            break                       # el segundo punto ya es ruido
        picos.append((int(x), int(y)))
        restante[max(0, y - SEPARACION_MINIMA_PX):y + SEPARACION_MINIMA_PX,
                 max(0, x - SEPARACION_MINIMA_PX):x + SEPARACION_MINIMA_PX] = 0
    if len(picos) < 2:
        return None
    (xa, ya), (xb, yb) = picos
    if math.hypot(xa - xb, ya - yb) < SEPARACION_MINIMA_PX:
        return None                     # estan fundidas: esto no es lo suyo

    # un recuadro por luz, del tamaño de la mancha que parpadea alrededor
    lado = max(4, SEPARACION_MINIMA_PX // 2)
    alto, ancho = var.shape
    cajas = []
    for (x, y) in picos:
        x0, y0 = max(0, x - lado), max(0, y - lado)
        cajas.append((x0, y0, min(ancho - x0, 2 * lado),
                      min(alto - y0, 2 * lado)))
    return tuple(cajas)


def brillo_de(roi):
    """Luminancia media de los pixeles mas brillantes del recuadro.

    Version reducida de medir() para el modo por posicion: aqui no hace falta
    el color, solo si esa luz esta prendida.
    """
    if roi.size == 0:
        return 0.0
    suave = _suavizar(roi).astype(np.float32)
    plano = (suave.mean(2) if suave.ndim == 3 else suave).ravel()
    n = max(6, int(plano.size * 0.05))
    return float(np.sort(plano)[-n:].mean())


def clasificar_por_posicion(brillos_a, brillos_b, ventana=260):
    """Dos series de brillo -> estado de las luces.

    estado = (A prendida) + 2*(B prendida). El umbral de cada luz se saca de su
    propia ventana movil, igual que en el modo por color y por el mismo motivo:
    la exposicion de la camara deriva durante la toma.
    """
    a = np.asarray(brillos_a, dtype=np.float32)
    b = np.asarray(brillos_b, dtype=np.float32)
    n = len(a)
    if n == 0 or len(b) != n:
        return []
    estados = np.zeros(n, dtype=int)
    for serie, peso in ((a, 1), (b, 2)):
        p10, p90 = _umbrales_moviles(serie, ventana)
        cambia = (p90 - p10) >= 4       # si no, esa luz no cambia en la ventana
        prendida = cambia & (serie >= p10 + 0.45 * (p90 - p10))
        estados += peso * prendida
    return list(estados)


# -------------------------------------------- seguir las luces que se mueven -
#
# Todo lo de arriba supone que las luces se quedan quietas en la imagen. Con el
# celular en la mano no se quedan: en videoconzoom la camara recorrio 100 px en
# x y 116 en y sobre una imagen de 320, o sea un tercio del cuadro. El sintoma
# es inconfundible y costo encontrarlo: el preambulo se lee PERFECTO (12
# alternancias de 12 cuadros clavadas) y en cuanto empiezan los datos aparecen
# tramos de 10, 16 y 21 simbolos con el mismo estado, que con codigo por
# transicion son imposibles. No es la señal: es el recuadro, que se quedo atras.
#
# Lo que sigue busca las luces, las sigue, y devuelve el brillo de cada una.


def mapa_luz(bloque, fps, banda=BANDA_PARPADEO):
    """Donde hay algo que PARPADEA deprisa y ademas ALUMBRA.

    Buscar el maximo de varianza no sirve al aire libre: gana siempre la gente
    que pasa por delante, que ocupa mucha mas imagen que un LED de 5 px. Las
    dos cosas que distinguen a la luz son:

      * el RITMO. La luz cambia a 5-12 simbolos/s; una persona caminando se
        mueve por debajo de 2 Hz. Se mide con la transformada de Fourier de
        cada pixel en el bloque y se castiga lo que ademas tenga mucha energia
        lenta, que es la firma del que camina.
      * el BRILLO. El LED satura y el resto de la escena no, asi que multiplicar
        por el brillo al cuadrado lo separa del fondo.

    Con las dos juntas la luz sale de primera en todos los tramos de los tres
    videos de la universidad; con la varianza sola, en ninguno.
    """
    # el bloque puede venir en color (un video) o en gris (la camara en vivo,
    # que guarda el buffer de busqueda en gris para que quepa a 640 px)
    pila = np.stack([cv2.GaussianBlur(
        f.astype(np.float32).mean(2) if f.ndim == 3 else f.astype(np.float32),
        (3, 3), 0) for f in bloque])
    brillo = np.percentile(pila, 95, axis=0) / 255.0
    pila = pila - pila.mean(0, keepdims=True)
    espectro = np.abs(np.fft.rfft(pila, axis=0))
    frec = np.fft.rfftfreq(len(bloque), d=1.0 / max(1e-6, fps))
    util = (frec >= banda[0]) & (frec <= banda[1])
    if not util.any():                   # bloque tan corto que no hay bandas
        util = frec > 0
    pico = espectro[util].max(0)
    lentas = (frec > 0) & (frec < banda[0])
    if lentas.any():
        pico = pico * np.minimum(1.0, pico / (espectro[lentas].max(0) + 1.0))
    return pico * brillo ** 2


def picos_de_luz(mapa, cuantos=4, frac=0.45, margen=2, borde=5):
    """Los puntos mas altos del mapa, separados por MANCHA y no por distancia.

    Separarlos por una distancia fija falla justo donde importa: de cerca el
    halo de una sola luz mide 40 px, asi que los dos primeros picos caen dentro
    de la MISMA luz y el receptor acaba midiendo dos veces lo mismo (se ve al
    dibujarlo: los dos circulos encima del mismo LED). Borrando la region
    conexa entera de cada pico, el siguiente ya es la otra luz.

    'borde' tapa el marco de la imagen: el desenfoque y la transformada dejan
    ahi valores altos que no son ninguna luz, y un punto de partida en la
    esquina es una pasada entera por el video tirada a la basura.
    """
    m = mapa.copy()
    if borde:
        m[:borde, :] = 0; m[-borde:, :] = 0
        m[:, :borde] = 0; m[:, -borde:] = 0
    salida = []
    for _ in range(cuantos):
        y, x = np.unravel_index(np.argmax(m), m.shape)
        alto = float(m[y, x])
        if alto <= 0:
            break
        salida.append((int(x), int(y), alto))
        _, etiquetas = cv2.connectedComponents((m >= alto * frac).astype(np.uint8), 8)
        region = (etiquetas == etiquetas[y, x]).astype(np.uint8)
        if margen:
            region = cv2.dilate(region, np.ones((2 * margen + 1,) * 2, np.uint8))
        m[region > 0] = 0
    return salida


def _orientar(v):
    """Deja el vector siempre apuntando al mismo lado, para poder promediarlos."""
    return v if (v[0] > 0 or (v[0] == 0 and v[1] > 0)) else -v


def semillas_de_luces(cuadros, fps, bloque=45, catas=10,
                      cuantas=SEMILLAS_SEGUIMIENTO):
    """Puntos de partida para el seguimiento y la separacion entre las luces.

    Se catan varios tramos del video. De cada uno sale el pico mas alto del
    mapa de luz y el vector al segundo. La SEPARACION se saca como la mediana
    de todos esos vectores, porque es fija en el montaje y una mediana sobre
    diez tramos es mucho mejor que lo que diga un tramo suelto. El punto de
    partida sale de los tramos con el pico mas alto.

    Devuelve ([(cuadro_inicial, punto)], separacion) o ([], None).
    """
    n = len(cuadros)
    paso = max(bloque, (n - bloque) // max(1, catas - 1))
    catados = []
    for i0 in range(0, max(1, n - bloque), paso):
        picos = picos_de_luz(mapa_luz(cuadros[i0:i0 + bloque], fps))
        if picos:
            catados.append((i0, picos))
    sep_min, sep_max = SEPARACION_SEGUIMIENTO
    separaciones = []
    for _, picos in catados:
        for j in range(1, len(picos)):
            v = np.array([picos[j][0] - picos[0][0],
                          picos[j][1] - picos[0][1]], dtype=float)
            if sep_min <= math.hypot(v[0], v[1]) <= sep_max:
                separaciones.append(_orientar(v))
                break
    if not separaciones:
        return [], None
    separacion = np.median(np.array(separaciones), axis=0)
    catados.sort(key=lambda t: -t[1][0][2])
    salida = []
    for i0, picos in catados[:cuantas]:
        p = np.array([picos[0][0], picos[0][1]], dtype=float)
        # cual de las dos luces es el pico no se sabe: se prueban las dos
        salida.append((i0, p))
        salida.append((i0, p - separacion))
    return salida, separacion


def seguir_luces(cuadros, i_semilla, punto, separacion, fps, bloque=45, radio=14):
    """Camino que siguen las luces por la imagen, tramo a tramo.

    En cada tramo se busca el desplazamiento que deja las DOS luces sobre lo
    mas alto del mapa de luz. Moverlas juntas y no cada una por su lado es lo
    que hace que aguante: la separacion entre ellas no cambia, asi que pedir
    que las dos encajen a la vez descarta los falsos positivos que engancharian
    a una sola.

    Se recorre hacia adelante y hacia atras desde el tramo semilla, y entre
    anclas se interpola.
    """
    alto, ancho = cuadros[0].shape[:2]
    anclas = {}

    def anclar(i0, p):
        trozo = cuadros[i0:i0 + bloque]
        if len(trozo) < 12:
            return p
        cx, cy = p[0] + separacion[0] / 2, p[1] + separacion[1] / 2
        m = int(radio + max(abs(separacion[0]), abs(separacion[1])) / 2 + 6)
        x0 = int(max(0, cx - m)); x1 = int(min(ancho, cx + m + 1))
        y0 = int(max(0, cy - m)); y1 = int(min(alto, cy + m + 1))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return p
        mapa = mapa_luz([f[y0:y1, x0:x1] for f in trozo], fps)
        mejor, salto = -1.0, (0, 0)
        for dy in range(-radio, radio + 1):
            for dx in range(-radio, radio + 1):
                ax = int(round(p[0] + dx - x0)); ay = int(round(p[1] + dy - y0))
                bx = int(round(p[0] + separacion[0] + dx - x0))
                by = int(round(p[1] + separacion[1] + dy - y0))
                if not (0 <= ax < mapa.shape[1] and 0 <= ay < mapa.shape[0] and
                        0 <= bx < mapa.shape[1] and 0 <= by < mapa.shape[0]):
                    continue
                suma = mapa[ay, ax] + mapa[by, bx]
                if suma > mejor:
                    mejor, salto = suma, (dx, dy)
        return p + salto

    p = np.array(punto, dtype=float)
    anclas[i_semilla] = p.copy()
    for i0 in range(i_semilla + bloque, len(cuadros), bloque):
        p = anclar(i0, p)
        anclas[i0] = p.copy()
    p = anclas[i_semilla].copy()
    for i0 in range(i_semilla - bloque, -bloque, -bloque):
        j = max(0, i0)
        p = anclar(j, p)
        anclas[j] = p.copy()

    claves = sorted(anclas)
    xs = np.array([k + bloque / 2.0 for k in claves], dtype=float)
    px = np.array([anclas[k][0] for k in claves], dtype=float)
    py = np.array([anclas[k][1] for k in claves], dtype=float)
    t = np.arange(len(cuadros), dtype=float)
    return np.stack([np.interp(t, xs, px), np.interp(t, xs, py)], axis=1)


def afinar_camino(cuadros, camino, separacion, radio=5, margen=18):
    """Ajusta el camino cuadro a cuadro pegandose al pico de brillo.

    Las anclas van cada 20-45 cuadros y entre ellas se interpola en linea
    recta; el pulso de la mano no va en linea recta. Este retoque corrige esos
    pocos pixeles sin dejar que la posicion se escape, porque solo mira a
    +-5 px de donde dice el camino y solo se mueve si ahi hay algo claramente
    mas brillante que el fondo (si no, las luces estan apagadas y no hay nada
    a lo que pegarse). Sin este paso videoconzoom no descifra.
    """
    alto, ancho = cuadros[0].shape[:2]
    salida = camino.copy()
    for i, f in enumerate(cuadros):
        base = camino[i]
        cx = int(np.clip(base[0], 0, ancho - 1)); cy = int(np.clip(base[1], 0, alto - 1))
        vecindad = f[max(0, cy - 30):cy + 30, max(0, cx - 30):cx + 30]
        if vecindad.size == 0:
            continue
        gris = cv2.GaussianBlur(vecindad.astype(np.float32).mean(2), (3, 3), 0)
        ox, oy = max(0, cx - 30), max(0, cy - 30)
        fondo = float(np.median(gris))
        mejor, salto = -1e9, None
        for q in (base, base + separacion):
            x0 = int(np.clip(q[0] - radio - ox, 0, gris.shape[1] - 1))
            x1 = int(np.clip(q[0] + radio + 1 - ox, 1, gris.shape[1]))
            y0 = int(np.clip(q[1] - radio - oy, 0, gris.shape[0] - 1))
            y1 = int(np.clip(q[1] + radio + 1 - oy, 1, gris.shape[0]))
            v = gris[y0:y1, x0:x1]
            if v.size == 0:
                continue
            iy, ix = np.unravel_index(np.argmax(v), v.shape)
            if v[iy, ix] > mejor:
                mejor = float(v[iy, ix])
                salto = np.array([x0 + ix + ox, y0 + iy + oy], dtype=float) - q
        if salto is not None and mejor > fondo + margen:
            salida[i] = base + salto
    return salida


def brillos_seguidos(cuadros, camino, separacion, lado):
    """Brillo de cada luz a lo largo del camino."""
    alto, ancho = cuadros[0].shape[:2]
    d = max(3, lado // 2)
    a, b = [], []
    for f, p in zip(cuadros, camino):
        for q, donde in ((p, a), (p + separacion, b)):
            x = int(np.clip(round(q[0]), d, ancho - d - 1))
            y = int(np.clip(round(q[1]), d, alto - d - 1))
            donde.append(brillo_de(np.ascontiguousarray(f[y - d:y + d, x - d:x + d])))
    return np.asarray(a), np.asarray(b)


def candidatos_roi(frames, maximo=MAX_CANDIDATOS_ROI):
    """Varios recuadros donde pueden estar las luces, del mas al menos probable.

    Quedarse solo con el maximo de varianza falla en cuanto hay otra cosa que
    cambie mas que las luces. En las tomas del 25/08 ganaba SIEMPRE la pantalla
    del computador del fondo: el nucleo del LED estaba sobreexpuesto, clavado
    en 255, asi que su varianza era baja, mientras que una ventana que aparece
    y desaparece en el monitor va de negro a blanco.

    Se puntua cada pixel de tres maneras y se toman los picos de cada una:

        var          lo que cambia           (sirve de dia)
        var * brillo lo que cambia Y alumbra (el LED gana casi siempre)
        brillo       lo que mas alumbra      (por si el LED satura tanto que
                                              su varianza es minima)

    De cada pico salen tres tamaños. Quien llame a esto los prueba en orden
    hasta que uno de CRC valido: validar es barato y adivinar no funciona.
    """
    if not frames:
        return []
    pila = np.stack([f.astype(np.float32).mean(2) for f in frames])
    var = cv2.GaussianBlur(pila.std(0), (9, 9), 0)
    if float(var.max()) < 3.0:
        return []
    brillo = cv2.GaussianBlur(
        np.percentile(pila, 95, axis=0).astype(np.float32), (9, 9), 0)

    forma = var.shape
    # Los de siempre van PRIMERO y con sus mismas fracciones: en las tomas
    # donde la luz esta lejos son los que aciertan, y perderlos por añadir
    # candidatos nuevos seria cambiar un fallo por otro.
    salida = [r for r in (auto_roi(frames, f) for f in FRACCIONES_ROI)
              if r is not None and r[2] >= 6 and r[3] >= 6]
    for mapa in (var * brillo, var, brillo):
        restante = mapa.copy()
        for _ in range(4):
            y, x = np.unravel_index(np.argmax(restante), forma)
            if restante[y, x] <= 0:
                break
            for frac in (0.75, 0.55, 0.40):
                r = _region_en(var, y, x, frac, forma)
                if r is not None:
                    salida.append(r)
            radio = max(forma) // 12
            restante[max(0, y - radio):y + radio,
                     max(0, x - radio):x + radio] = 0

    unicos = []
    for r in salida:
        if not any(_muy_parecidos(r, u) for u in unicos):
            unicos.append(r)
        if len(unicos) >= maximo:
            break
    return unicos


# ##########################################################################
#  3. DECODIFICADOR
#     De "el estado de las luces en cada cuadro" a "el bloque de celdas".
#     Aqui tampoco hay pixeles: la entrada es una lista de numeros.
# ##########################################################################

def rachas(estados):
    """Agrupa estados repetidos: [1,1,1,2,2] -> [[1,3],[2,2]]."""
    out = []
    for s in estados:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return out


def estables(estados, cuadros_por_simbolo, frac=FRAC_GLITCH):
    """Quita glitches de conmutacion y colapsa repeticiones.

    Las dos lamparas no conmutan a la vez, asi que en cada cambio puede
    aparecer un estado intermedio de 1-2 cuadros (de 01 a 10 se llega a ver un
    00 o un 11 fugaz). Se descarta toda racha mas corta que una fraccion del
    simbolo nominal.
    """
    umbral = max(1.0, cuadros_por_simbolo * frac)
    return colapsar([s for s, n in rachas(estados) if n >= umbral])


def separar_rafagas(estados, cuadros_por_simbolo):
    """Corta la traza donde las dos luces quedaron apagadas mucho rato.

    Cada copia del bloque llega como una rafaga; separarlas permite intentar
    cada una por aparte en vez de darle al decodificador un pegote de tres
    copias seguidas.
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


def intentar(estados, cuadros_nominal):
    """Barre periodos candidatos y devuelve el primer analisis con CRC valido.

    Si el periodo nominal no cuadra (la camara entrego menos fps de los
    pedidos, por ejemplo) uno de los factores del BARRIDO lo compensa.
    """
    mejor_parcial = None
    for factor in BARRIDO:
        cps = cuadros_nominal * factor
        if cps < 1.2:
            continue
        sec = estables(estados, cps)
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


def _decodificar_una(traza, cuadros_nominal):
    candidatos = []
    for trozo in separar_rafagas(traza, cuadros_nominal) or [traza]:
        info, _ = intentar(trozo, cuadros_nominal)
        if info:
            candidatos.append(info)
            if info.get("crc_ok"):
                return info, True
    info, _ = intentar(traza, cuadros_nominal)
    if info and info.get("crc_ok"):
        return info, True
    if info:
        candidatos.append(info)
    return (candidatos[0] if candidatos else None), False


def decodificar_traza(traza, cuadros_nominal):
    """Intenta la traza entera y cada rafaga por separado, con las dos
    asignaciones posibles de las luces. Devuelve (info, nota).

    Cual luz es la A y cual la B no se puede saber mirando, y NO es indiferente:
    el orden de los destinos cambia y con el los trits, asi que un cableado
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
        info, ok = _decodificar_una(datos, cuadros_nominal)
        if ok:
            return info, "CRC valido" + etiqueta
        if info is not None and parcial is None:
            parcial = (info, "cabecera ok, payload con errores" + etiqueta)
    if parcial:
        return parcial
    return None, "sin enganche"


def estimar_simbolos_por_s(tiempos, estados, minimo=1.0, maximo=25.0, fps=None):
    """Simbolos/s leidos de la propia señal, sin que nadie los diga.

    El transmisor cambia de estado solo en las fronteras de simbolo, asi que
    todos los cambios caen en t0 + k*T. Se busca la T que los deja mas
    agrupados en fase: se mapea cada cambio a un angulo 2*pi*(t/T mod 1) y se
    mide la longitud del vector medio (concentracion circular, 1 = todos en la
    misma fase). No necesita que los cambios sean consecutivos: los simbolos
    repetidos, que no producen cambio, simplemente no aportan.

    'fps' activa el rechazo del ALIAS DE LA CAMARA, y hace falta siempre que se
    sepa: cuando hay ~1 cuadro por simbolo casi todo cuadro trae un cambio, y
    como los cuadros estan igualmente espaciados la concentracion en el periodo
    de cuadro sale 1,00 clavada. Sin este rechazo una toma de 23,80 fps "medía"
    23,82 simbolos/s con confianza perfecta: no es la señal, es el reloj de la
    camara mirandose al espejo.

    Devuelve (simbolos_por_s, concentracion) o (None, 0.0).
    """
    t = np.asarray(tiempos, dtype=np.float64)
    e = np.asarray(estados)
    if len(t) != len(e) or len(t) < 20:
        return None, 0.0
    cambios = t[1:][e[1:] != e[:-1]]
    if len(cambios) < 8:
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
#  4. PROCESAR
#     Junta las tres secciones anteriores: de un archivo de video o de la
#     camara sale un bloque. Es la unica parte que abre una captura.
# ##########################################################################

def _fps_efectivo(cap, n_cuadros, duracion):
    """fps reales a partir de los sellos de tiempo, no del nominal.

    Los videos de celular suelen ser de tasa variable: el contenedor declara
    23,80 / 26,96 / 54,14 y ninguno lo cumple cuadro a cuadro. Como los
    cuadros/simbolo salen de aqui, usar el nominal descoloca el filtro de
    glitches.
    """
    if duracion > 0.5 and n_cuadros > 1:
        return (n_cuadros - 1) / duracion
    return cap.get(cv2.CAP_PROP_FPS) or 30.0


def leer_video(ruta, avisar=None, ancho=None):
    """Carga el video reducido a 'ancho' (ANCHO_TRABAJO si no se dice otro).

    Devuelve (cuadros, tiempos, fps, ancho_original).
    """
    ancho = ancho or ANCHO_TRABAJO
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return None, None, None, None
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    cuadros, tiempos, original = [], [], None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if original is None:
            original = f.shape[1]
        tiempos.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        esc = min(1.0, float(ancho) / f.shape[1])
        cuadros.append(cv2.resize(f, None, fx=esc, fy=esc) if esc < 1.0 else f)
        if avisar and total and len(cuadros) % 120 == 0:
            avisar(len(cuadros) / total)
    tiempos = np.asarray(tiempos, dtype=np.float64)
    dur = float(tiempos[-1] - tiempos[0]) if len(tiempos) > 1 else 0.0
    fps = _fps_efectivo(cap, len(cuadros), dur)
    cap.release()
    return cuadros, tiempos, fps, original


def _series_de_estados(cuadros, modo, fps, roi_manual=None, seguir=True):
    """Genera (etiqueta, estados, roi) por cada manera de leer las luces.

    Es un generador y no una lista a proposito: cada elemento cuesta una pasada
    entera por el video, asi que se calculan de uno en uno y se para en cuanto
    uno de CRC valido.

    El ORDEN importa: primero las luces seguidas, que es lo unico que funciona
    si la camara se movio, y despues el recuadro quieto de siempre, que es lo
    que funciona cuando las dos luces se funden en un punto. Ninguna de las dos
    sobra: en los videos de la universidad solo engancha la primera, y en los
    de referencia (luces fundidas, camara en tripie) solo la segunda.
    """
    if (seguir and SEGUIR_LUCES and modo in ("auto", "posicion")
            and roi_manual is None):
        semillas, separacion = semillas_de_luces(cuadros, fps)
        caminos = {}
        # el lado del recuadro va en el bucle de FUERA para que la primera
        # vuelta pruebe todos los puntos de partida con el recuadro chico, que
        # es el que acierta casi siempre. Los caminos se guardan, asi que la
        # segunda vuelta ya no cuesta seguimiento, solo medir.
        for lado in LADOS_SEGUIMIENTO:
            for i0, punto in semillas:
                for bloque in BLOQUES_SEGUIMIENTO:
                    clave = (i0, float(punto[0]), float(punto[1]), bloque)
                    if clave not in caminos:
                        caminos[clave] = afinar_camino(
                            cuadros,
                            seguir_luces(cuadros, i0, punto, separacion, fps,
                                         bloque=bloque),
                            separacion)
                    camino = caminos[clave]
                    # un recuadro que abarca las dos luces, solo para dibujarlo
                    p = camino[len(camino) // 2]
                    x = int(min(p[0], p[0] + separacion[0])) - 8
                    y = int(min(p[1], p[1] + separacion[1])) - 8
                    roi = (max(0, x), max(0, y),
                           int(abs(separacion[0])) + 16,
                           int(abs(separacion[1])) + 16)
                    a, b = brillos_seguidos(cuadros, camino, separacion, lado)
                    yield ("luces seguidas (bloque %d, lado %d)" % (bloque, lado),
                           clasificar_por_posicion(a, b), roi)

    if modo in ("auto", "posicion"):
        cajas = localizar_dos_luces(cuadros[:700])
        if cajas is not None:
            (xa, ya, wa, ha), (xb, yb, wb, hb) = cajas
            ba = [brillo_de(f[ya:ya + ha, xa:xa + wa]) for f in cuadros]
            bb = [brillo_de(f[yb:yb + hb, xb:xb + wb]) for f in cuadros]
            # cual luz es la A y cual la B no se puede saber mirando: se
            # prueban las dos asignaciones, igual que con los colores
            yield ("posicion", clasificar_por_posicion(ba, bb), cajas[0])
            yield ("posicion invertida",
                   clasificar_por_posicion(bb, ba), cajas[1])
        elif modo == "posicion":
            return          # se pidio por posicion y no hay dos puntos

    if modo in ("auto", "color"):
        candidatos = ([roi_manual] if roi_manual is not None
                      else candidatos_roi(cuadros[:700]))
        for roi in candidatos:
            x, y, w, h = roi
            lums, cromas = [], []
            for f in cuadros:
                l, c = medir(f[y:y + h, x:x + w])
                lums.append(l)
                cromas.append(c)
            yield ("color", clasificar_serie(lums, cromas), roi)


def _probar_velocidades(tiempos, estados, fps, simbolos_por_s=None, avisar=None):
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
    velocidades += [v for v in VELOCIDADES_TIPICAS
                    if all(abs(v - u) > 0.2 for u in velocidades)]

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


def decodificar_cuadros(cuadros, tiempos, fps, simbolos_por_s=None, avisar=None,
                        modo=None, roi_manual=None, seguir=True):
    """El nucleo: prueba maneras de leer las luces y velocidades hasta que un
    CRC cuadre.

    'simbolos_por_s' None significa "mideme la velocidad". Si se da un numero
    se prueba antes que la medida, por si el usuario sabe algo que la señal no
    dice. 'modo' es MODO_LUCES si no se dice otra cosa. 'seguir' a False deja
    fuera el seguimiento de las luces, que es lo que hace la escucha en vivo
    porque ahi no cabe en el tiempo entre reintentos. Devuelve (info, nota, roi).
    """
    mejor = None
    for etiqueta, estados, roi in _series_de_estados(
            cuadros, modo or MODO_LUCES, fps, roi_manual=roi_manual,
            seguir=seguir):
        decir = None
        if avisar:
            decir = lambda m, e=etiqueta, r=roi: avisar(
                "por %-18s recuadro (%d,%d,%d,%d): velocidad medida %s"
                % (e, r[0], r[1], r[2], r[3],
                   "%.2f sim/s" % m if m else "no medible"))
        info, nota, sps, _ = _probar_velocidades(
            tiempos, estados, fps, simbolos_por_s, avisar=decir)
        if info is None:
            continue
        texto = "%s  (por %s, %.2f sim/s)" % (nota, etiqueta, sps)
        if info.get("crc_ok"):
            if fps / sps < CUADROS_POR_SIMBOLO_MIN:
                texto += "  [ojo: solo %.1f cuadros/simbolo]" % (fps / sps)
            return info, texto, roi
        if mejor is None:
            mejor = (info, texto, roi)
    if mejor:
        return mejor

    # Sin enganche. Merece la pena decir POR QUE, en vez de dejar a alguien
    # probando recuadros a mano. Las dos causas de lejos mas frecuentes son la
    # tasa de cuadros y que las luces no se puedan separar.
    #
    # El aviso se apoya en los fps, que es un dato duro, y NO en la velocidad
    # medida: cuando la señal no da, la medida es basura y su confianza no lo
    # delata (en el video bueno la ROI ganadora tenia 0,42 y en el mismo video
    # decimado, donde no hay nada que leer, salian 0,37 y 0,39).
    motivo = ("sin enganche  (el video tiene %.1f fps, o sea un techo de "
              "~%.0f simbolos/s; por encima de eso hay que grabar a 60)"
              % (fps, fps / CUADROS_POR_SIMBOLO_MIN))
    if (modo or MODO_LUCES) in ("auto", "posicion") and \
            localizar_dos_luces(cuadros[:700]) is None:
        motivo += ("\n              Ademas, solo se ve UN punto que parpadea: "
                   "las dos luces estan fundidas en la imagen, asi que hay que "
                   "separarlas por color. Si son del mismo color, no hay manera: "
                   "hay que separarlas mas o ponerles colores distintos.")
    if seguir and SEGUIR_LUCES and semillas_de_luces(cuadros, fps)[1] is None:
        motivo += ("\n              Tampoco se encontro un par de luces que "
                   "parpadeen a la vez: o quedaron demasiado lejos para verlas, "
                   "o no salen en cuadro todo el rato. Acercarse o hacer zoom es "
                   "lo que mas cambia.")
    return None, motivo, None


def seleccionar_roi_video(ruta):
    """Muestra un cuadro del video y devuelve un ROI en coordenadas de trabajo.

    Enter/Space confirma la seleccion. C o Esc cancela y deja que el receptor
    busque el ROI automaticamente.
    """
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        print("No se pudo abrir el video para seleccionar el ROI.")
        return None

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total > 1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
    ok, cuadro = cap.read()
    cap.release()
    if not ok or cuadro is None:
        print("No se pudo leer un cuadro del video para seleccionar el ROI.")
        return None

    esc = min(1.0, 900.0 / cuadro.shape[1])
    vista = cv2.resize(cuadro, None, fx=esc, fy=esc)
    cv2.putText(vista, "Arrastra sobre las luces y pulsa Enter; C = automatico",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (0, 255, 255), 1, cv2.LINE_AA)
    cv2.namedWindow("seleccionar ROI del video", cv2.WINDOW_NORMAL)
    x, y, w, h = cv2.selectROI(
        "seleccionar ROI del video", vista,
        showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("seleccionar ROI del video")
    if w <= 4 or h <= 4:
        return None

    esc_trabajo = min(1.0, float(ANCHO_TRABAJO) / cuadro.shape[1])
    return tuple(int(round(v / esc * esc_trabajo)) for v in (x, y, w, h))


def procesar_video(ruta, simbolos_por_s=None, verboso=True, roi_manual=None):
    """Procesa un video ENTERO y devuelve (grid, nota, roi, escala).

    Es todo lo que hace falta para un archivo: no se reproduce nada, no se
    descifra dos veces. El resultado se devuelve listo para pintar.
    """
    avance = (lambda p: print("   %3.0f%%" % (p * 100), end="\r")) if verboso else None
    aviso = (lambda m: print("   " + m)) if verboso else None
    anchos = [ANCHO_TRABAJO]
    # el recuadro a mano viene en pixeles de la imagen de trabajo, asi que si
    # se cambia el ancho deja de valer: con roi_manual no hay segundo intento
    if (ANCHO_SEGUNDO_INTENTO and ANCHO_SEGUNDO_INTENTO > ANCHO_TRABAJO
            and roi_manual is None):
        anchos.append(ANCHO_SEGUNDO_INTENTO)

    ultimo = (None, "no se pudo leer el video", None, 1.0)
    for intento, ancho in enumerate(anchos):
        if verboso:
            print("Leyendo el video%s..."
                  % ("" if intento == 0 else " otra vez, sin reducirlo tanto"))
        cuadros, tiempos, fps, original = leer_video(ruta, avisar=avance, ancho=ancho)
        if not cuadros:
            return ultimo
        if intento and original <= anchos[intento - 1]:
            return ultimo          # ya se vio a resolucion completa, no hay mas
        escala = float(original) / cuadros[0].shape[1]
        if verboso:
            print("   %d cuadros de %d px de ancho, %.1f s -> %.2f fps efectivos"
                  % (len(cuadros), cuadros[0].shape[1],
                     tiempos[-1] - tiempos[0], fps))
            print("Buscando las luces y descifrando...")
        info, nota, roi = decodificar_cuadros(
            cuadros, tiempos, fps, simbolos_por_s, avisar=aviso,
            roi_manual=roi_manual)
        grid = a_cuadricula(info) if info and info.get("cabecera_ok") else None
        if roi is not None:
            roi = tuple(int(round(v * escala)) for v in roi)
        if info and info.get("crc_ok"):
            return grid, nota, roi, escala
        if grid is not None or ultimo[0] is None:
            ultimo = (grid, nota, roi, escala)   # guardar lo mejor que salio

        # Soltar la memoria ANTES de releer, y de verdad. Un video largo a
        # resolucion completa son varios GB, asi que las dos lecturas a la vez
        # no caben: el sintoma es que OpenCV revienta con un error raro dentro
        # de una funcion diminuta. Poner 'cuadros = None' no basta, porque el
        # generador de candidatos se quedo suspendido a medias y sigue
        # agarrando la lista hasta que pasa el recolector.
        del cuadros, tiempos
        gc.collect()
    return ultimo


def abrir_camara(cual, fps_pedidos=FPS_CAMARA, exposicion=EXPOSICION_CAMARA):
    """Abre una camara por indice (0, 1, ...) o por URL, y la deja lista.

    Una URL sirve para usar el celular o una camara de red como camara del PC:
    ver la nota de COMO CONECTAR OTRA CAMARA en el encabezado. Con URL se usa
    FFMPEG, que es el backend que entiende http y rtsp; con indice, el de
    Windows (DSHOW), que es el unico que deja fijar la exposicion.
    """
    if isinstance(cual, str) and not str(cual).isdigit():
        cap = cv2.VideoCapture(cual, cv2.CAP_FFMPEG)          # celular o IP
    else:
        # Se prueban los tres backends en orden. DSHOW es el unico que deja
        # fijar la exposicion, pero las camaras "modernas" de Windows (la del
        # celular por Enlace movil, por ejemplo) solo abren por MSMF: si se
        # usara DSHOW a secas, esas camaras salen en la lista y luego no abren.
        cap = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            prueba = cv2.VideoCapture(int(cual), backend)
            if prueba.isOpened() and prueba.read()[0]:
                cap = prueba
                break
            prueba.release()
        if cap is None:                    # ninguno abrio: se devuelve cerrada
            return cv2.VideoCapture(int(cual), cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, fps_pedidos)
    if exposicion is not None:
        # Solo si se pide: en un cuarto normal una exposicion de -7 deja la
        # imagen practicamente negra, y eso parece una camara rota cuando en
        # realidad esta funcionando. Ver EXPOSICION_CAMARA en PARAMETROS.
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
        cap.set(cv2.CAP_PROP_EXPOSURE, exposicion)
    return cap


def nombres_camaras(hasta=8):
    """Los NOMBRES de las camaras del PC, los mismos que muestra Zoom o Meet.

    OpenCV no sabe los nombres: solo abre camaras por numero, y por eso este
    programa usaba siempre la 0 (la del portatil). Los nombres los tiene
    DirectShow, que es de donde los sacan Zoom, Meet o Teams, y en Windows se
    leen con pygrabber:

        pip install pygrabber

    Sin pygrabber esto devuelve [] y el programa cae a mostrar las camaras por
    numero, que sigue funcionando pero obliga a adivinar cual es cual.
    """
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())[:hasta]
    except Exception:
        return []


def camaras_disponibles(hasta=6):
    """Que camaras responden de verdad. [(indice, nombre, ancho, alto, brillo)].

    Abrir cada camara tarda un segundo largo, asi que esto es para --camaras y
    para cuando no hay nombres. Para solo escoger, nombres_camaras() basta y es
    instantaneo.
    """
    nombres = nombres_camaras(hasta)
    encontradas = []
    for i in range(hasta):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
        if cap.isOpened():
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


# ------------------------------------------------- la camara en vivo ------
#
# Un archivo se puede releer entero tantas veces como haga falta, y por eso el
# camino de arriba prueba recuadro tras recuadro hasta que uno engancha. En
# vivo no hay nada que releer: cada cuadro pasa una vez y se va.
#
# Antes esto se resolvia guardando la pelicula entera para poder rebuscar sobre
# ella, y salia caro dos veces:
#
#   MEMORIA  un minuto a 60 fps son 3600 imagenes; para que cupieran se
#            reducian a 320 px de ancho. AHI MURIO LA CAMARA EN VIVO: las dos
#            luces del cuarto quedan a 36 px una de otra sobre 1920, o sea 6 px
#            sobre 320, y a 6 px el recuadro de una mide tambien la otra. El
#            estado salia siempre "las dos prendidas" y no aparecia mensaje
#            ninguno, ni bueno ni malo. El MISMO video, leido como archivo, si
#            descifra, porque el archivo se relee a 640 px cuando el primer
#            intento falla; en vivo no hay segunda lectura que valga.
#   TIEMPO   cada reintento volvia a buscar el recuadro sobre TODA la historia,
#            asi que cuanto mas rato escuchando, mas tardaba cada intento.
#
# El rastreador le da la vuelta y parte el trabajo en dos:
#
#   BUSCAR   cuesta, pero se hace UNA vez y sobre cuadros reducidos, que para
#            buscar sobra: el mapa de parpadeo encuentra el par igual de bien a
#            480 px que a 1920 (comprobado: los dos picos salen en el mismo
#            sitio a 320, 480 y 640).
#   MEDIR    es lo de cada cuadro, y se hace sobre la imagen ORIGINAL, que es
#            lo unico que permite separar dos luces a 36 px.
#
# De cada cuadro quedan cuatro numeros, asi que descifrar un minuto de historia
# cuesta menos de un segundo y no hay que guardar ni una imagen.


def _parpadeo_en(bloque, x, y, lado):
    """Serie de "esta prendido" en un punto del bloque reducido.

    Devuelve (prendida, cambia): un vector de booleanos y si de verdad hay
    algo que cambie ahi. Los recuadros son diminutos a proposito, porque a esta
    escala las dos luces estan a trece pixeles y uno grande mediria las dos.
    """
    serie = []
    for f in bloque:
        alto, ancho = f.shape[:2]
        d = int(np.clip(lado, 1, max(1, min(alto, ancho) // 2 - 1)))
        cx = int(np.clip(x, d, ancho - d - 1))
        cy = int(np.clip(y, d, alto - d - 1))
        serie.append(brillo_de(np.ascontiguousarray(
            f[cy - d:cy + d, cx - d:cx + d])))
    v = np.asarray(serie, dtype=np.float32)
    p10, p90 = np.percentile(v, 10), np.percentile(v, 90)
    if p90 - p10 < 4:
        return np.zeros(len(v), dtype=bool), False
    return v >= p10 + 0.45 * (p90 - p10), True


def _buscar_par_de_luces(bloque, fps, escala, origen, cuantas=2, picos=6):
    """Las parejas de luces que se ven en un bloque de cuadros reducidos.

    Devuelve [(punto_A, vector_hasta_B, nota)] en pixeles del cuadro ORIGINAL,
    de la mas prometedora a la menos, o [] si no se ve nada parpadeando. Si
    solo aparece un punto util el vector sale nulo: las luces estan fundidas y
    habra que leerlas por color.

    Lo que decide NO es la altura de los picos, y esto es lo que costo:
    en un cuarto las dos luces salen tambien reflejadas -en el vidrio de un
    cuadro, en una pantalla apagada, en el piso-, y esos reflejos parpadean
    exactamente igual de fuerte y exactamente al mismo ritmo. Emparejando por
    altura, la pareja que ganaba era casi siempre "una luz y su propio
    reflejo", que llevan LA MISMA señal y por lo tanto no dicen nada: el estado
    conjunto sale siempre "las dos prendidas" o "las dos apagadas".

    Asi que cada pareja se comprueba sobre el propio bloque: se mira cuando
    esta prendido cada punto y se exige que NO coincidan siempre. Un punto y su
    reflejo coinciden el 100% del tiempo; las dos luces de verdad se
    diferencian en un tercio de los cuadros, porque para eso llevan simbolos
    distintos.
    """
    if len(bloque) < 20:
        return []
    hallados = picos_de_luz(mapa_luz(bloque, fps), cuantos=picos)
    if not hallados:
        return []

    # los limites de separacion estan dados en pixeles de ANCHO_TRABAJO
    k = float(bloque[0].shape[1]) / ANCHO_TRABAJO
    sep_min, sep_max = (v * k for v in SEPARACION_SEGUIMIENTO)

    lado = max(2, int(sep_min / 2))
    parpadeos = [_parpadeo_en(bloque, x, y, lado) for x, y, _ in hallados]

    parejas = []
    for i, (xi, yi, vi) in enumerate(hallados):
        if not parpadeos[i][1]:
            continue
        for j, (xj, yj, vj) in enumerate(hallados):
            if j <= i or not parpadeos[j][1]:
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
    for _, p, v, distintos in parejas[:cuantas]:
        p, v = p * escala, v * escala
        salida.append((p + (ox, oy), v,
                       "dos luces a %.0f px (se diferencian en el %.0f%% de "
                       "los cuadros)" % (math.hypot(v[0], v[1]), 100 * distintos)))
    if not salida:
        # un solo punto util: o hay una sola luz a la vista, o las dos estan
        # tan lejos que se fundieron. En los dos casos toca leerlas por color.
        for (x, y, _), (_, cambia) in zip(hallados, parpadeos):
            if cambia:
                p = np.array([x, y], dtype=float) * escala
                salida.append((p + (ox, oy), np.zeros(2),
                               "una sola luz a la vista"))
                break
    return salida


class _Candidato:
    """Una pareja de luces que se esta midiendo, con lo medido hasta ahora.

    Guarda cuatro series y ninguna imagen: el brillo de cada luz (para leerlas
    por posicion) y la luminancia y el croma del par (para leerlas por color,
    que es lo que sirve cuando estan tan lejos que se funden en un punto).
    """

    def __init__(self, punto, separacion, escala, historia, nacido):
        self.punto = np.asarray(punto, dtype=float)
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
        self.t, self.ba, self.bb, self.lum, self.croma = [], [], [], [], []
        self.n = 0
        self.mejor = 0.0          # el parpadeo mas vivo que se le ha visto

    @property
    def separadas(self):
        """True si se ven como dos puntos; False si estan fundidas en uno."""
        return bool(np.any(self.separacion))

    def etiqueta(self):
        return ("(%d,%d)+(%d,%d)"
                % (self.punto[0], self.punto[1],
                   self.separacion[0], self.separacion[1]))

    def roi(self):
        """Recuadro que abarca las dos luces, en pixeles del cuadro original."""
        q = self.punto + self.separacion
        x0 = int(min(self.punto[0], q[0])) - self.lado
        y0 = int(min(self.punto[1], q[1])) - self.lado
        return (max(0, x0), max(0, y0),
                int(abs(self.separacion[0])) + 2 * self.lado,
                int(abs(self.separacion[1])) + 2 * self.lado)

    def es_la_misma(self, punto, separacion):
        """Si una propuesta nueva es la pareja que ya se esta midiendo.

        El margen es el temblor de la busqueda y nada mas: la busqueda trabaja
        sobre el cuadro reducido, asi que un pixel suyo son tres del original y
        dos busquedas seguidas sobre una camara QUIETA ya dan puntos que se
        diferencian en dos o tres pixeles.

        Dentro del margen la propuesta se descarta y la pareja se queda EXACTA-
        MENTE donde estaba. Fuera del margen entra como una pareja nueva, con
        sus segundos de precarga, y la vieja sigue midiendo por su cuenta. Es a
        proposito: mover los recuadros de una serie a medio medir le mete un
        escalon de brillo en mitad de la trama, y una trama de estas dura medio
        minuto. Se probo mover -medio camino, con tope de 6 px- y una toma que
        daba CRC valido se quedaba en "cabecera ok, payload con errores". Sale
        mas barato tener dos parejas casi iguales y que decida el CRC.
        """
        cerca = max(6.0, 1.6 * self.escala)
        return (math.hypot(punto[0] - self.punto[0],
                           punto[1] - self.punto[1]) < cerca and
                math.hypot(separacion[0] - self.separacion[0],
                           separacion[1] - self.separacion[1]) < cerca)

    def series(self):
        """(tiempos, brillo_A, brillo_B, luminancia, croma), ya copiadas.

        Se recortan todas al mismo largo porque el bucle de la camara sigue
        midiendo mientras el hilo que descifra las lee.
        """
        crudas = (self.t, self.ba, self.bb, self.lum, self.croma)
        n = min(len(c) for c in crudas)
        return tuple(np.asarray(c[:n], dtype=np.float64) for c in crudas)

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
            a = brillo_de(self._recorte(g, pa, d))
            b = brillo_de(self._recorte(g, pb, d))
            ventana = self._ventana(g, caja)
            self.ba.append(a)
            self.bb.append(b)
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
        a = brillo_de(self._recorte(f, self.punto, self.lado))
        b = brillo_de(self._recorte(f, self.punto + self.separacion, self.lado))
        # para el modo por color hacen falta las DOS en el mismo recuadro: el
        # croma no dice cual esta prendida si cada una se mide por separado
        l, c = medir(self._ventana(f, self.roi()))
        self.ba.append(a)
        self.bb.append(b)
        self.lum.append(l)
        self.croma.append(c)
        self.t.append(t)
        if len(self.t) > self.historia:
            for serie in (self.t, self.ba, self.bb, self.lum, self.croma):
                del serie[0]
        self.n += 1
        if self.n % 30 == 0:
            self.actividad(fps)   # de paso deja apuntado el maximo

    @staticmethod
    def _recorte(f, centro, lado):
        """El recuadro de una luz, siempre dentro de la imagen."""
        alto, ancho = f.shape[:2]
        d = int(np.clip(lado, 1, max(1, min(alto, ancho) // 2 - 1)))
        x = int(np.clip(round(centro[0]), d, ancho - d - 1))
        y = int(np.clip(round(centro[1]), d, alto - d - 1))
        return np.ascontiguousarray(f[y - d:y + d, x - d:x + d])

    @staticmethod
    def _ventana(f, caja):
        """Un recuadro cualquiera, recortado a lo que hay de imagen."""
        alto, ancho = f.shape[:2]
        x0, y0, w, h = caja
        x0 = int(np.clip(x0, 0, max(0, ancho - 6)))
        y0 = int(np.clip(y0, 0, max(0, alto - 6)))
        x1 = int(np.clip(x0 + w, x0 + 6, ancho))
        y1 = int(np.clip(y0 + h, y0 + 6, alto))
        return np.ascontiguousarray(f[y0:y1, x0:x1])

    # --- que tan prometedora es -----------------------------------------
    def actividad(self, fps):
        """Cambios por segundo que PODRIAN ser simbolos, en el ultimo rato.

        Es lo que separa una pareja de luces de verdad (7 simbolos/s se ven
        como 7-14 cambios/s) de un reflejo o de alguien caminando por detras, y
        decide a cual se mira primero y cual sobra si hay que soltar una.

        Lo de "podrian ser" no es un adorno. Contar cambios a secas premia justo
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
        cambios = 0
        for serie in ((self.ba, self.bb) if self.separadas else (self.lum,)):
            v = np.asarray(serie[-n:])
            p10, p90 = np.percentile(v, 10), np.percentile(v, 90)
            if p90 - p10 < 4:
                continue
            prendida = v >= p10 + 0.45 * (p90 - p10)
            cambios += int(np.count_nonzero(prendida[1:] != prendida[:-1]))
        tasa = cambios / max(1e-6, self.t[-1] - self.t[-n])
        if tasa > fps / CUADROS_POR_SIMBOLO_MIN:
            return 0.0                  # mas rapido que el limite fisico: ruido
        self.mejor = max(self.mejor, tasa)
        return tasa

    def puntaje(self, fps, ahora):
        """Lo que vale esta pareja, para saber cual soltar si sobran.

        Se mira el parpadeo MAS VIVO que se le ha visto nunca, no el de ahora
        mismo, y esto no es un detalle: entre dos copias del bloque las luces
        se quedan quietas, asi que mirando solo el ultimo rato se soltaba justo
        la pareja buena en el hueco entre rafagas. En estas tomas entraba a los
        8 s, se caia a los 12 y la rafaga que traia el bloque empezaba a los 11.

        A la recien nacida se le supone buena un par de segundos: con medio
        segundo medido todavia no tiene actividad que enseñar, y sin el margen
        cada busqueda soltaria la pareja que acaba de proponer.
        """
        if ahora - self.nacido < 2.0:
            return 5.0
        return max(self.mejor, self.actividad(fps))

    def apagado(self, fps):
        """True si lleva PACIENCIA_VIVO_S sin que cambie nada: se perdio."""
        n = int(PACIENCIA_VIVO_S * max(1.0, fps))
        if len(self.t) < n:
            return False
        for serie in (self.ba, self.bb, self.lum):
            v = np.asarray(serie[-n:])
            if np.percentile(v, 90) - np.percentile(v, 10) >= 4:
                return False
        return True


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
        self.cada = 0
        self.reloj = 0.0
        self.nota = "buscando las luces..."

    # --- lo que le pregunta el bucle de la camara -----------------------
    @property
    def enganchado(self):
        return bool(self.candidatos)

    def listo_para_buscar(self):
        return len(self.buscando) >= CUADROS_BUSQUEDA_VIVO

    def medidos(self):
        return max((len(c.t) for c in self.candidatos), default=0)

    def rois(self):
        """Los recuadros que se estan midiendo, el mas prometedor primero."""
        return [c.roi() for c in self.candidatos]

    # --- las dos tareas caras, para lanzarlas en otro hilo ---------------
    def tarea_de_busqueda(self, fps):
        """Cierra sobre una COPIA del bloque: el hilo no toca nada vivo."""
        bloque = [g for _, g in self.buscando[-CUADROS_BUSQUEDA_VIVO:]]
        escala, origen = self.escala, self.origen
        # el anillo NO se vacia: los cuadros que acaba de usar la busqueda son
        # justo los que hacen falta para precargar la pareja que encuentre. El
        # ritmo de las busquedas lo pone BUSQUEDA_CADA_S, no el anillo.
        return lambda: _buscar_par_de_luces(bloque, fps, escala, origen)

    def tarea_de_descifrado(self, fps, simbolos_por_s):
        """Lo que se le manda al hilo que descifra, ya copiado y ordenado.

        Se dejan fuera las parejas a las que NUNCA se les ha visto un parpadeo
        que pudiera ser de simbolos. No es un atajo dudoso: si esa pareja no ha
        cambiado a un ritmo posible, no hay trama ahi que sacar. Y es lo que
        hace que la escucha no queme el procesador mientras no transmite nadie,
        que es la mayor parte del tiempo. A las recien nacidas se les da margen,
        que todavia no han tenido ocasion de enseñar nada.
        """
        ahora = max((c.t[-1] for c in self.candidatos if c.t), default=0.0)
        vivas = [c for c in self.candidatos
                 if c.mejor > 0 or ahora - c.nacido < 4.0]
        orden = sorted(vivas, key=lambda c: -c.puntaje(fps, ahora))
        lotes = [(c.etiqueta(), c.series(), c.separadas) for c in orden]
        return lambda: descifrar_en_vivo(lotes, fps, simbolos_por_s)

    def sembrar(self, hallazgos, fps, ahora):
        """Mete las parejas que encontro una busqueda entre las que se miden.

        Cada pareja nueva nace con los ultimos segundos YA medidos sobre los
        cuadros reducidos que todavia se guardan: ver CUADROS_PRECARGA_VIVO.
        """
        recien = []
        for punto, separacion, nota in hallazgos:
            if any(c.es_la_misma(punto, separacion) for c in self.candidatos):
                continue        # ya se esta midiendo; NO se le toca el sitio
            nueva = _Candidato(punto, separacion, self.escala,
                               self.historia, ahora)
            nueva.precargar(list(self.buscando), self.escala, self.origen)
            self.candidatos.append(nueva)
            recien.append(nueva)
            if len(self.candidatos) > MAX_CANDIDATOS_VIVO:
                self._soltar_la_peor(recien, fps, ahora)
        if recien:
            self.nota = self._resumen(fps, ahora)

    def _soltar_la_peor(self, recien, fps, ahora):
        """Deja sitio, pero NUNCA a costa de las que acaban de entrar.

        Aqui estaba el fallo que dejaba la escucha ciega. A una pareja recien
        nacida se le supone un puntaje modesto -todavia no ha tenido tiempo de
        parpadear-, asi que era siempre la mas floja de la lista: cada busqueda
        proponia dos parejas, la segunda echaba a la primera, y la pareja BUENA,
        que la busqueda encontraba una y otra vez desde el segundo 10 y ademas
        proponia LA PRIMERA, no llego a medirse nunca. Solo sobrevivian las
        parejas viejas, que eran las del comienzo de la toma, o sea la persona
        que cruzaba por delante.

        Se sueltan solo las que ya tuvieron su oportunidad; si todas son
        recientes no se suelta ninguna y la lista crece un poco de mas, que es
        mucho mas barato que perder la buena.
        """
        viejas = [c for c in self.candidatos
                  if c not in recien and ahora - c.nacido >= 2.0]
        if viejas:
            self.candidatos.remove(min(viejas,
                                       key=lambda c: c.puntaje(fps, ahora)))

    def _resumen(self, fps, ahora):
        partes = []
        for c in sorted(self.candidatos, key=lambda c: -c.puntaje(fps, ahora)):
            d = math.hypot(c.separacion[0], c.separacion[1])
            partes.append("%s a %.0f px (%.0f cambios/s)"
                          % ("dos luces" if c.separadas else "una luz",
                             d, c.actividad(fps)))
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
                if c.apagado(fps):
                    self.candidatos.remove(c)
                    self.nota = "una pareja dejo de parpadear: soltada"
        if not buscar_mas:
            self.buscando = []
            return
        self.buscando.append((t, self._reducir(f)))
        if len(self.buscando) > CUADROS_BUSQUEDA_VIVO + CUADROS_PRECARGA_VIVO:
            self.buscando.pop(0)

    def _reducir(self, f):
        """El cuadro como se usa para BUSCAR y para PRECARGAR: recortado a la
        zona, reducido y en gris.

        En gris porque las dos cosas que se hacen con el -el mapa de parpadeo y
        el brillo de cada luz- solo miran la luminancia. Lo unico que se pierde
        es el croma de los segundos precargados, que solo hace falta cuando las
        luces se ven FUNDIDAS en un punto; en ese caso la precarga entra con
        croma cero y el modo por color arranca de verdad unos segundos despues.
        """
        g, self.origen = f, (0.0, 0.0)
        if self.zona:
            x, y, w, h = self.zona
            x, y = max(0, int(x)), max(0, int(y))
            recorte = f[y:y + int(h), x:x + int(w)]
            if recorte.shape[0] > 16 and recorte.shape[1] > 16:
                g, self.origen = recorte, (float(x), float(y))
        esc = min(1.0, float(ANCHO_BUSQUEDA_VIVO) / g.shape[1])
        self.escala = 1.0 / esc
        if esc < 1.0:
            g = cv2.resize(g, None, fx=esc, fy=esc)
        return cv2.cvtColor(g, cv2.COLOR_BGR2GRAY) if g.ndim == 3 else g.copy()


def descifrar_en_vivo(lotes, fps, simbolos_por_s=None):
    """Descifra lo medido en vivo, sin imagenes de por medio.

    Entran las series de cada pareja que se esta siguiendo y sale el bloque.
    Primero se prueban TODAS por posicion y solo despues por color: en vivo la
    pareja buena casi siempre son dos puntos separados, y dejar el color para
    la segunda vuelta hace que el caso normal salga en la mitad de tiempo.
    """
    if not lotes:
        return None, "ninguna pareja parpadea como una señal: nadie transmite"
    if max(len(l[1][0]) for l in lotes) < 60:
        return None, "juntando cuadros..."

    mejor = None
    for modo in ("posicion", "color"):
        for etiqueta, (t, ba, bb, lum, croma), separadas in lotes:
            if len(t) < 60:
                continue
            if modo == "posicion":
                if not separadas:
                    continue
                estados = clasificar_por_posicion(ba, bb)
            else:
                estados = clasificar_serie(lum, croma)
            if not estados:
                continue
            info, nota, sps, _ = _probar_velocidades(
                t, estados, fps, simbolos_por_s)
            if info is None:
                continue
            texto = "%s  (por %s en %s, %.2f sim/s)" % (nota, modo, etiqueta, sps)
            if info.get("crc_ok"):
                if fps / sps < CUADROS_POR_SIMBOLO_MIN:
                    texto += "  [ojo: solo %.1f cuadros/simbolo]" % (fps / sps)
                return info, texto
            if mejor is None:
                mejor = (info, texto)
    if mejor:
        return mejor
    return None, ("escuchando: %d cuadros a %.0f fps, todavia sin trama"
                  % (max(len(l[1][0]) for l in lotes), fps))


class _EnSegundoPlano(threading.Thread):
    """Corre una tarea aparte para que la ventana nunca se congele.

    ESTE HILO ES EL ARREGLO de que la tecla 'q' no respondiera en vivo: buscar
    las luces y descifrar tardan lo suyo, y hacerlo en el mismo bucle que dibuja
    dejaba la ventana bloqueada mas de la mitad del tiempo, asi que cv2.waitKey
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


def escuchar_camara(cual=CAMARA, simbolos_por_s=None, fps_pedidos=FPS_CAMARA,
                    exposicion=EXPOSICION_CAMARA, al_actualizar=None,
                    cada=REINTENTO_VIVO_S, cap=None, reloj=None):
    """La camara en vivo, que es el unico caso donde no existe "el final".

    El bucle no hace nada caro: lee un cuadro, se lo da al rastreador (que mide
    las parejas que sigue y guarda una copia reducida para buscar) y dibuja. Lo
    caro -buscar las luces y descifrar- va SIEMPRE en otro hilo, uno cada vez,
    asi que las teclas responden al instante por larga que sea la escucha.

    Mientras no cuadre un CRC se sigue buscando cada BUSQUEDA_CADA_S segundos,
    para no quedarse pegado a una pareja mala. En cuanto uno cuadra el resultado
    se CONGELA y no se vuelve a pisar con una lectura peor.

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

    rastreador = RastreadorVivo()
    grid, nota, congelado = None, "esperando transmision...", False
    zona = None
    # DOS hilos y no uno: buscar y descifrar tardan parecido, y con un solo
    # hilo la busqueda se quedaba esperando a que terminara el descifrado. Eso
    # retrasaba el momento en que entra la pareja buena entre uno y tres
    # segundos, al azar segun lo que estuviera corriendo, y como la rafaga dura
    # lo que dura, la escucha enganchaba unas veces si y otras no sin que
    # cambiara nada. Cada tarea con su hilo y el azar se acaba.
    hilo_busca = hilo_descifra = None
    t_ini = time.time()
    proxima_busqueda, proximo_intento = 0.0, 0.0
    fps, relojes = fps_pedidos, []
    exposicion_actual = exposicion
    sin_imagen = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                sin_imagen += 1
                if sin_imagen > 30:
                    nota = "se acabo la imagen de la camara"
                    break
                continue
            sin_imagen = 0
            t = reloj() if reloj else time.time() - t_ini

            # los fps DE VERDAD, medidos sobre los ultimos cuadros y no los que
            # se pidieron: de esto salen los cuadros por simbolo
            relojes.append(t)
            if len(relojes) > 150:
                relojes.pop(0)
            if len(relojes) > 30 and relojes[-1] > relojes[0]:
                fps = (len(relojes) - 1) / (relojes[-1] - relojes[0])

            rastreador.alimentar(f, t, fps, buscar_mas=not congelado)

            # recoger lo que dejo cada hilo
            if hilo_busca is not None and not hilo_busca.is_alive():
                if hilo_busca.fallo:
                    nota = hilo_busca.fallo
                elif hilo_busca.salida:
                    rastreador.sembrar(hilo_busca.salida, fps, t)
                elif not rastreador.enganchado:
                    rastreador.nota = ("no se ve nada parpadeando: acercate o "
                                       "haz zoom (m limita la busqueda)")
                hilo_busca = None
            if hilo_descifra is not None and not hilo_descifra.is_alive():
                if hilo_descifra.fallo:
                    nota = hilo_descifra.fallo
                elif hilo_descifra.salida is not None:
                    info, nota = hilo_descifra.salida
                    if info and info.get("cabecera_ok"):
                        nuevo = a_cuadricula(info)
                        if nuevo:
                            grid = nuevo
                        if info.get("crc_ok"):
                            congelado = True   # llego entero: no se toca mas
                hilo_descifra = None

            if not congelado:
                if (hilo_busca is None and t >= proxima_busqueda
                        and rastreador.listo_para_buscar()):
                    proxima_busqueda = t + BUSQUEDA_CADA_S
                    hilo_busca = _EnSegundoPlano(
                        "buscar", rastreador.tarea_de_busqueda(fps))
                    hilo_busca.start()
                if (hilo_descifra is None and t >= proximo_intento
                        and rastreador.enganchado
                        and rastreador.medidos() > 60):
                    proximo_intento = t + cada
                    hilo_descifra = _EnSegundoPlano(
                        "descifrar",
                        rastreador.tarea_de_descifrado(fps, simbolos_por_s))
                    hilo_descifra.start()

            if al_actualizar is None:
                continue
            respuesta = al_actualizar({
                "grid": grid, "nota": nota, "cuadro": f,
                "rois": rastreador.rois(), "zona": zona,
                "estado": rastreador.nota, "enganchado": rastreador.enganchado,
                "congelado": congelado,
                "descifrando": hilo_descifra is not None,
                "buscando": hilo_busca is not None,
                "segundos": t, "cuadros": rastreador.medidos(),
                "fps": fps, "exposicion": exposicion_actual,
            })
            if respuesta is False:
                break
            if isinstance(respuesta, dict) and "exposicion" in respuesta:
                exposicion_actual = respuesta["exposicion"]
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                cap.set(cv2.CAP_PROP_EXPOSURE, exposicion_actual)
            if isinstance(respuesta, dict) and "zona" in respuesta:
                # el recuadro a mano ya no dice DONDE MEDIR sino DONDE BUSCAR:
                # donde medir lo decide el rastreador, y lo hace mejor que un
                # rectangulo dibujado a pulso
                zona = respuesta["zona"]
                rastreador.reiniciar(zona)
                grid, congelado = None, False
                hilo_busca = hilo_descifra = None
                nota = ("buscando solo dentro del recuadro" if zona
                        else "buscando en todo el cuadro")
            if respuesta == "reiniciar":
                rastreador.reiniciar(zona)
                grid, congelado = None, False
                hilo_busca = hilo_descifra = None
                nota = "escucha reiniciada"
    finally:
        cap.release()

    # UN ULTIMO INTENTO con todo lo medido, ya sin prisa. Los intentos van cada
    # REINTENTO_VIVO_S segundos, asi que el ultimo se lanzo unos segundos antes
    # del final y le faltaba justo el remate de la trama; y una trama de estas
    # dura medio minuto, o sea que perder los ultimos dos segundos es perder la
    # trama entera. Escuchando de verdad da igual, porque el transmisor repite
    # el bloque; cuando la fuente se acaba de golpe -un video simulado, la
    # camara desenchufada, la tecla q- este intento es el que la salva.
    if not congelado and rastreador.enganchado:
        try:
            info, ultima = rastreador.tarea_de_descifrado(fps, simbolos_por_s)()
        except Exception as e:
            return grid, "error en el ultimo intento: %s" % e
        if info and info.get("cabecera_ok"):
            nuevo = a_cuadricula(info)
            if nuevo:
                grid, nota = nuevo, ultima
    return grid, nota


class _CamaraDeVideo:
    """Un archivo de video haciendose pasar por una camara.

    Es lo unico que permite probar la escucha en vivo sin tener a alguien al
    otro lado encendiendo luces: entrega los cuadros de uno en uno y con el
    reloj DEL VIDEO, asi que el rastreador ve exactamente lo que veria en vivo
    (no puede volver atras, no sabe cuanto falta, y los fps son los de la toma).
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
    montaje delante, y saber si un fallo en vivo es de la camara o del receptor.
    Con tiempo_real=True los cuadros salen a la velocidad de la toma, como
    saldrian de una camara; sin el va tan rapido como pueda leer el archivo, que
    es lo comodo para probar.
    """
    fuente = _CamaraDeVideo(ruta, tiempo_real)
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


# Donde se guardan las ultimas carpetas usadas. En el perfil del usuario y no
# junto al archivo, para que funcione aunque el programa este en una carpeta de
# solo lectura o dentro del repositorio.
_MEMORIA_CARPETAS = Path.home() / ".rx_camara_carpetas"


def _recordar_carpeta(ruta):
    """Apunta la carpeta de un video escogido a mano, para verla la proxima vez."""
    try:
        carpeta = str(Path(ruta).resolve().parent)
        previas = [l for l in _leer_carpetas_recordadas() if l != carpeta]
        _MEMORIA_CARPETAS.write_text(
            "\n".join([carpeta] + previas[:4]), encoding="utf-8")
    except OSError:
        pass                       # recordar es una comodidad, no un requisito


def _leer_carpetas_recordadas():
    try:
        return [l.strip() for l in
                _MEMORIA_CARPETAS.read_text(encoding="utf-8").splitlines()
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
    win.configure(bg="#1e1e2e")
    win.geometry("560x360")

    tk.Label(win, text="Camaras del PC (doble clic para usarla)",
             bg="#1e1e2e", fg="#89b4fa",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))

    lista = tk.Listbox(win, bg="#181825", fg="#cdd6f4",
                       selectbackground="#89b4fa", selectforeground="#181825",
                       font=("Consolas", 10), activestyle="none",
                       borderwidth=0, highlightthickness=0)
    lista.pack(fill="both", expand=True, padx=12)
    for i, nombre in opciones:
        lista.insert("end", "  %d)  %s" % (i, nombre))
    lista.selection_set(0)

    tk.Label(win, text="...o la direccion de una camara por red "
                       "(IP Webcam, camara IP):",
             bg="#1e1e2e", fg="#a6adc8",
             font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(10, 2))
    url = tk.Entry(win, bg="#181825", fg="#cdd6f4", insertbackground="#cdd6f4",
                   font=("Consolas", 9), relief="flat")
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

    botones = tk.Frame(win, bg="#1e1e2e")
    botones.pack(fill="x", padx=12, pady=12)
    for texto, orden, color in (("Usar esta camara", usar, "#a6e3a1"),
                                ("Cancelar", win.destroy, "#f38ba8")):
        tk.Button(botones, text=texto, command=orden, bg=color, fg="#181825",
                  font=("Segoe UI", 9, "bold"), relief="flat",
                  padx=12, pady=6).pack(side="left", padx=(0, 8))

    win.bind("<Escape>", lambda _: win.destroy())
    lista.focus_set()
    win.lift()
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))
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
    raiz.configure(bg="#1e1e2e")
    raiz.geometry("780x430")

    tk.Label(raiz, text="Videos encontrados junto a este archivo "
                        "(doble clic para descifrar)",
             bg="#1e1e2e", fg="#89b4fa",
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))

    marco = tk.Frame(raiz, bg="#1e1e2e")
    marco.pack(fill="both", expand=True, padx=12)
    barra = tk.Scrollbar(marco)
    barra.pack(side="right", fill="y")
    lista = tk.Listbox(marco, bg="#181825", fg="#cdd6f4",
                       selectbackground="#89b4fa", selectforeground="#181825",
                       font=("Consolas", 9), yscrollcommand=barra.set,
                       activestyle="none", borderwidth=0, highlightthickness=0)
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

    botones = tk.Frame(raiz, bg="#1e1e2e")
    botones.pack(fill="x", padx=12, pady=12)
    for texto, orden, color in (("Descifrar el seleccionado", analizar, "#a6e3a1"),
                                ("Buscar otro archivo...", otro, "#89b4fa"),
                                ("Camara en vivo", camara, "#f9e2af"),
                                ("Probarlo como si fuera en vivo",
                                 como_en_vivo, "#f5c2e7")):
        tk.Button(botones, text=texto, command=orden, bg=color, fg="#181825",
                  font=("Segoe UI", 9, "bold"), relief="flat",
                  padx=12, pady=6).pack(side="left", padx=(0, 8))

    raiz.bind("<Escape>", lambda _: raiz.destroy())
    lista.focus_set()
    # al darle al play la ventana nace detras del editor; se sube al frente una
    # sola vez y se le quita el 'siempre encima' enseguida, para que despues no
    # estorbe a las ventanas de OpenCV
    raiz.lift()
    raiz.attributes("-topmost", True)
    raiz.after(300, lambda: raiz.attributes("-topmost", False))
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
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 1, cv2.LINE_AA)
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
                (tw, th), _ = cv2.getTextSize(letra, cv2.FONT_HERSHEY_SIMPLEX, esc, 2)
                cv2.putText(img, letra, (x + (lado - tw) // 2, y + (lado + th) // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, esc, (0, 0, 0), 2, cv2.LINE_AA)
                if v == "Ñ":
                    cv2.putText(img, "~", (x + (lado - tw) // 2, y + th // 2 + 2),
                                cv2.FONT_HERSHEY_SIMPLEX, esc * 0.8, (0, 0, 0), 2)
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
    else:
        print("  no se pudo descifrar el bloque")
    print("=" * 52 + "\n")


def mostrar_resultado(grid, nota, guardar=None):
    """Deja el bloque en pantalla hasta que se cierre. Nada mas.

    No se reproduce el video: el resultado ya esta calculado y lo unico que
    falta es verlo.
    """
    titulo = nota if not grid else "%dx%d  -  %s" % (len(grid), len(grid[0]), nota)
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


def _vista_camara(e):
    """Lo que se pinta mientras la camara escucha.

    Devuelve False para parar, "reiniciar" para tirar la historia, o un dict con
    la exposicion o la zona de busqueda nuevas. Se llama en cada cuadro, asi que
    las teclas responden al momento: buscar y descifrar van en otro hilo.
    """
    cuadro = e["cuadro"]
    vista = cuadro.copy()

    # El recuadro va en pixeles del cuadro TAL CUAL lo entrega la camara: desde
    # que se mide sin reducir, no hay ninguna escala que deshacer.
    if e["zona"]:
        x, y, w, h = e["zona"]
        cv2.rectangle(vista, (x, y), (x + w, y + h), (0, 255, 255), 2)
    # Se pintan TODAS las parejas que se estan midiendo, no solo una: viendo
    # cuales son se entiende de un vistazo por que no engancha (el recuadro
    # sobre la persona que pasa se ve enseguida). La primera es la que mas
    # parpadea, o sea la que mas se parece a un transmisor.
    for i, (x, y, w, h) in enumerate(e["rois"]):
        m = max(6, w // 3)
        color = ((0, 255, 0) if e["congelado"] else
                 (255, 180, 0) if i == 0 else (140, 140, 140))
        cv2.rectangle(vista, (x - m, y - m), (x + w + m, y + h + m), color,
                      2 if i == 0 else 1)

    # Aviso de imagen negra: sin esto una camara tapada, ocupada por otra app o
    # con la exposicion muy baja se ve igual que una que no funciona, y uno se
    # queda mirando un rectangulo negro sin saber que pasa.
    brillo = float(cuadro.mean())
    if brillo < 6:
        for i, texto in enumerate([
                "LA CAMARA ENTREGA IMAGEN NEGRA (brillo medio %.1f de 255)" % brillo,
                "- tiene tapa de privacidad puesta?",
                "- la esta usando otra aplicacion (Teams, Zoom, Meet)?",
                "- exposicion muy baja: subela con la tecla +",
                "- prueba otra camara: --camara 1"]):
            cv2.putText(vista, texto, (12, 26 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55 if i == 0 else 0.45,
                        (60, 60, 255) if i == 0 else (120, 200, 255), 1,
                        cv2.LINE_AA)
    else:
        # Que esta haciendo el receptor AHORA. Antes no se decia, y una escucha
        # que no encuentra las luces se ve igual que una que si: se pierde el
        # rato mirando la imagen sin saber si el problema es la camara, la
        # distancia o el transmisor.
        cv2.putText(vista, e["estado"], (12, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (120, 255, 180) if e["enganchado"] else (120, 200, 255),
                    1, cv2.LINE_AA)
        if e["zona"]:
            cv2.putText(vista, "buscando solo dentro del recuadro "
                               "(a = en todo el cuadro)",
                        (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (0, 255, 255), 1, cv2.LINE_AA)

    estado = "%ds  %d medidos  %.0f fps%s" % (
        e["segundos"], e["cuadros"], e["fps"],
        "  descifrando..." if e["descifrando"] else "")
    cv2.putText(vista, estado, (12, vista.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 220, 160), 1, cv2.LINE_AA)

    escv = min(1.0, 640.0 / vista.shape[1])
    cv2.imshow(VENTANA_CAMARA, cv2.resize(vista, None, fx=escv, fy=escv))
    titulo = ("BLOQUE COMPLETO - " if e["congelado"] else "") + e["nota"]
    cv2.imshow("bloque recibido", pintar_bloque(e["grid"], titulo=titulo))

    k = cv2.waitKey(1) & 0xFF
    if k in (ord("q"), 27):
        return False
    if k == ord("r"):
        return "reiniciar"
    if k == ord("m"):
        # Se selecciona sobre una copia reducida para que el cuadro quepa en
        # pantalla; despues se convierte a pixeles del cuadro original.
        esc_sel = min(1.0, 640.0 / cuadro.shape[1])
        seleccion = cv2.resize(cuadro, None, fx=esc_sel, fy=esc_sel)
        cv2.namedWindow("donde buscar las luces", cv2.WINDOW_NORMAL)
        x, y, w, h = cv2.selectROI("donde buscar las luces", seleccion,
                                   showCrosshair=True, fromCenter=False)
        cv2.destroyWindow("donde buscar las luces")
        if w > 4 and h > 4:
            return {"zona": tuple(int(round(v / esc_sel))
                                  for v in (x, y, w, h))}
    if k == ord("a"):
        return {"zona": None}
    if k in (ord("+"), ord("=")):
        return {"exposicion": (e["exposicion"] or -7) + 1}
    if k == ord("-"):
        return {"exposicion": (e["exposicion"] or -7) - 1}
    # si cierran la ventana con la X, tambien hay que parar
    if cv2.getWindowProperty(VENTANA_CAMARA, cv2.WND_PROP_VISIBLE) < 1:
        return False
    return True


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
    info2 = analizar_trama(decodificar_linea(estables(vistos, 5.0))[0])
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


def main():
    ap = argparse.ArgumentParser(
        description="Receptor por camara de dos luces. Sin argumentos "
                    "pregunta que video descifrar.")
    ap.add_argument("--video", help="descifra este archivo y muestra el bloque")
    ap.add_argument("--simular-vivo", dest="simular_vivo",
                    help="pasa un video grabado por el camino de la CAMARA EN "
                         "VIVO, para probar la escucha sin montaje delante")
    ap.add_argument("--tiempo-real", dest="tiempo_real", action="store_true",
                    help="con --simular-vivo, entrega los cuadros a la "
                         "velocidad de la toma en vez de lo mas rapido posible")
    ap.add_argument("--camara", default=None,
                    help="escucha en vivo: un numero (0 es la primera del PC), "
                         "parte del nombre de la camara, o una URL de "
                         "celular/camara IP")
    ap.add_argument("--exposicion", type=int, default=EXPOSICION_CAMARA,
                    help="exposicion de la camara (-7 es baja); sin esto la "
                         "decide la camara")
    ap.add_argument("--camaras", action="store_true",
                    help="lista las camaras que responden y termina")
    ap.add_argument("--simbolos", default=SIMBOLOS_POR_SEGUNDO or "auto",
                    help="simbolos/s del transmisor, o 'auto' para medirlos "
                         "sobre la señal. Por defecto, lo que diga "
                         "SIMBOLOS_POR_SEGUNDO en PARAMETROS")
    ap.add_argument("--guardar", help="guarda el bloque recibido en este .png")
    ap.add_argument("--autoprueba", action="store_true",
                    help="comprueba la codificacion sin camara ni video")
    args = ap.parse_args()

    if args.autoprueba:
        return autoprueba()

    if args.camaras:
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
            print()
            print("(instala pygrabber para ver el NOMBRE de cada camara:")
            print("  pip install pygrabber                                 )")
        print()
        print("Tambien se puede escribir el nombre en vez del numero:")
        print('  --camara "iriun"      --camara "enlace movil"')
        print("Para una camara por red se usa la URL:")
        print("  --camara http://192.168.1.5:8080/video")
        return 0

    simbolos = (None if str(args.simbolos).strip().lower() == "auto"
                else float(args.simbolos))

    # Sin argumentos (el caso de darle al play) se pregunta que analizar en vez
    # de asumir la camara: probar una toma grabada es lo que mas se hace.
    if args.video is None and args.camara is None:
        args.video, args.camara, simular = elegir_fuente()
        if args.video is None and args.camara is None:
            print("No se escogio nada.")
            return 0
        if simular:
            args.simular_vivo, args.video = args.video, None

    if args.simular_vivo:
        print("Simulando la camara en vivo con %s"
              % Path(args.simular_vivo).name)
        print("  q salir | r reiniciar | m limitar la busqueda | a quitar")
        grid, nota = simular_vivo(args.simular_vivo, simbolos,
                                  al_actualizar=_vista_camara,
                                  tiempo_real=args.tiempo_real)
        cv2.destroyAllWindows()
        imprimir_bloque(grid, nota)
        mostrar_resultado(grid, nota, args.guardar)
        return 0

    if args.video:
        print("Video: %s" % Path(args.video).name)
        print("Selecciona el area del ROI. Pulsa Enter para confirmar o C para usar el automatico.")
        roi_manual = seleccionar_roi_video(args.video)
        t0 = time.time()
        grid, nota, _, _ = procesar_video(
            args.video, simbolos, roi_manual=roi_manual)
        print("   (%.0f s)" % (time.time() - t0))
        imprimir_bloque(grid, nota)
        mostrar_resultado(grid, nota, args.guardar)
        return 0

    args.camara = resolver_camara(args.camara)
    nombres = nombres_camaras()
    etiqueta = args.camara
    if isinstance(args.camara, int) or str(args.camara).isdigit():
        i = int(args.camara)
        if i < len(nombres):
            etiqueta = "%d (%s)" % (i, nombres[i])
    print("Escuchando la camara %s." % etiqueta)
    print("  q salir | r reiniciar | + - exposicion | "
          "m limitar la busqueda a un recuadro | a quitarlo")
    grid, nota = escuchar_camara(args.camara, simbolos,
                                 exposicion=args.exposicion,
                                 al_actualizar=_vista_camara)
    cv2.destroyAllWindows()
    imprimir_bloque(grid, nota)
    if grid and args.guardar:
        cv2.imwrite(args.guardar, pintar_bloque(grid, 900, 760, nota))
        print("imagen guardada en %s" % args.guardar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
