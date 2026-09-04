# -*- coding: utf-8 -*-
"""RECEPTOR POR CAMARA -- lee las dos luces en un video (o en vivo) y
reconstruye el bloque de celdas.

    Se abre en VS Code y se le da al boton de play. No lleva argumentos:
    sale una ventana con los videos que encuentre al lado y se escoge uno.

Este archivo FUNCIONA SOLO: no importa nada del proyecto, solo numpy y
opencv-python. La codificacion esta incluida en la seccion 1, para que baste
con descargar este archivo y tener el receptor completo.

    python -m pip install numpy opencv-python

LO QUE HAY QUE TOCAR esta todo junto en el bloque PARAMETROS, unas lineas mas
abajo: como estan puestas las luces, cada cuantos cuadros hace falta, la
camara, la exposicion. No hace falta bajar al codigo para ajustar nada de eso.


COMO ESTA ORGANIZADO
--------------------
El archivo va de lo abstracto a lo concreto, y cada seccion solo usa las
anteriores. Se puede leer de arriba a abajo o saltar a la que interese.

    0. PARAMETROS         todo lo ajustable, junto y comentado.
    1. EL CODIGO          bits <-> celdas. No sabe que existen las camaras.
    2. PDI                imagen -> estado de las luces.
    3. DECODIFICADOR      estados en el tiempo -> bloque de celdas.
    4. PROCESAR           un video entero, o la camara en vivo.
    5. INTERFAZ           escoger la fuente y pintar el resultado.
    6. ARRANQUE           main().

Las secciones 1 y 3 son puro calculo y se pueden probar sin camara: ejecutar
con --autoprueba lo comprueba en un segundo. La 2 es la unica que toca
pixeles. La 5 es la unica que abre ventanas.


LAS DOS LUCES: COLOR O POSICION
-------------------------------
Hay dos maneras de saber cual de las dos luces esta prendida, y cual sirve
depende de como se vean en la imagen, no de que LED se compre:

  POR COLOR      cuando las dos luces caen en el MISMO punto de la imagen (a
                 300 m dos luces separadas 20 cm caen en unos 2 pixeles: se
                 funden). Entonces no se pueden separar por donde estan, y hay
                 que separarlas por el color. EXIGE colores distintos.

  POR POSICION   cuando en la imagen se ven como dos puntos separados. Se mide
                 cada uno por su lado y basta con que enciendan y apaguen.
                 SIRVE CON DOS LUCES DEL MISMO COLOR, blancas incluidas.

Comprobado con videos de prueba generados a proposito:

    luces          se funden en la imagen    se ven separadas
    dos colores    color: SI                 color: NO   posicion: SI
    mismo color    NO se puede               posicion: SI

O sea que dos luces blancas SI sirven, siempre que en la imagen queden
separadas. Si van a quedar fundidas, tienen que ser de colores distintos.
MODO_LUCES = "auto" prueba las dos maneras y se queda con la que funcione.


COMO CONECTAR OTRA CAMARA
-------------------------
Para ver que camaras responden y con que numero:

    python rx_camara.py --camaras

Si sale "entrega imagen NEGRA" el problema no es este programa: casi siempre
es la tapa de privacidad del portatil, otra aplicacion que ya tiene la camara
cogida (Teams, Zoom, Meet), o la exposicion demasiado baja (tecla + en vivo).

  CELULAR. Es la opcion mas practica, porque graba a 60 fps y tiene mejor
  optica que cualquier webcam. Se instala una aplicacion que publique la
  camara en la red local (IP Webcam en Android, por ejemplo), y se le pasa la
  direccion que muestre:

      python rx_camara.py --camara http://192.168.1.5:8080/video

  Con las que se instalan como camara virtual del PC (DroidCam, Iriun,
  EpocCam) no hace falta URL: aparecen como una camara mas y salen en
  --camaras con su numero.

  CAMARA PROFESIONAL O REFLEX. Por HDMI hace falta una capturadora USB; con
  ella la camara aparece como una camara mas del PC. Muchas marcas tambien
  tienen un programa (Webcam Utility, EOS Webcam Utility) que hace lo mismo
  por USB. En los dos casos se usa el numero que diga --camaras.

  CAMARA IP / DE SEGURIDAD. Se le pasa su URL rtsp:

      python rx_camara.py --camara "rtsp://usuario:clave@192.168.1.9:554/stream1"

Sea cual sea, lo que hay que mirar es que entregue 60 cuadros por segundo de
verdad: es lo unico que decide la velocidad maxima (ver el apartado siguiente).


CUANTOS CUADROS POR SEGUNDO HACEN FALTA
---------------------------------------
El codigo de linea es por transicion: cada frontera de simbolo se ve como un
cambio de las luces, y para ver un cambio hacen falta cuadros a los dos lados.
Por debajo de ~3 cuadros por simbolo no hay decodificador que valga. Medido
sobre grabaciones reales:

    54,1 fps -> 4,3 cuadros/simbolo -> CRC valido
    27,1 fps -> 2,2 cuadros/simbolo -> nada (y es EL MISMO video, decimado)
    23,8 fps -> 1,9 cuadros/simbolo -> nada

O sea: la velocidad maxima es fps/3. A 30 fps, 10 simbolos/s; a 60 fps, 20.
No tiene nada que ver con que haya luz ambiente o no: manda la tasa de cuadros.

Redes de Computadores I - UdeA 2026-2 - Proyecto 01
"""

import argparse
import math
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np


# ##########################################################################
#  0. PARAMETROS
#     Todo lo ajustable del receptor, junto. Nada de esto hay que buscarlo
#     dentro del codigo: se cambia aqui y ya.
# ##########################################################################

# --- COMO ESTAN PUESTAS LAS LUCES ----------------------------------------
# "auto"      prueba por color y, si no engancha, por posicion (recomendado)
# "color"     las dos luces se funden en el mismo punto -> colores distintos
# "posicion"  se ven como dos puntos separados -> sirve cualquier color
MODO_LUCES = "auto"

# Cual de las dos luces es la "A" del codigo.
#   None   prueba las dos y se queda con la que de CRC valido (recomendado)
#   True   la luz A es la que tira mas al ROJO
#   False  la luz A es la otra
#
# Ponerlo a True o False no cambia el resultado, solo ahorra la mitad del
# trabajo cuando ya se sabe como quedo el cableado. Y OJO: el receptor NO
# necesita saber los colores exactos. Mide croma = (R-G)/(R+G) y compara las
# dos luces entre si, asi que si se cambian los LED por naranja y azul sigue
# funcionando mientras uno sea mas rojo que el otro. Lo que NO puede es
# distinguir dos luces del mismo color: para eso esta MODO_LUCES = "posicion".
LUZ_A_ES_LA_MAS_ROJA = None

# Distancia minima, en pixeles de la imagen de trabajo (320 px de ancho), para
# considerar que dos luces estan separadas y no fundidas. Con 320 px de ancho,
# 12 px son casi 4 grados del campo de vision.
SEPARACION_MINIMA_PX = 12

# --- VELOCIDAD -----------------------------------------------------------
# Simbolos por segundo del transmisor. None = medirlo sobre la propia señal
# (es lo normal: se mide bien y evita tener que acordarse).
SIMBOLOS_POR_SEGUNDO = None

# Velocidades que se prueban si la medida no cuadra, en orden.
VELOCIDADES_TIPICAS = (5, 4, 6, 3, 8, 2, 10, 1, 12.5, 15, 20)

# Cuadros por simbolo por debajo de los cuales la grabacion no sirve. Ver la
# nota del encabezado: no es un umbral inventado, esta medido.
CUADROS_POR_SIMBOLO_MIN = 3.0

# --- CAMARA EN VIVO ------------------------------------------------------
# Cual camara usar. Puede ser:
#   un numero  ->  0 es la primera del PC, 1 la segunda...
#   una URL    ->  "http://192.168.1.5:8080/video"   (celular con IP Webcam)
#                  "rtsp://usuario:clave@192.168.1.9:554/stream1"
# Con --camara se cambia sin tocar el archivo.
CAMARA = 0

# fps que se le piden a la camara. Pedir 60 es lo importante: ver el encabezado.
FPS_CAMARA = 60.0

# Exposicion de la camara en vivo.
#   None  ->  no se toca (la camara decide). Empezar SIEMPRE por aqui.
#   -7    ->  exposicion baja, para que las luces no se sobreexpongan y
#             conserven el color. Util de noche y con las luces cerca, pero
#             deja la imagen casi negra en un cuarto normal.
# En vivo se sube y baja con las teclas + y - sin reiniciar nada.
EXPOSICION_CAMARA = None

# Cada cuantos segundos se reintenta descifrar mientras la camara escucha.
# El intento corre aparte, asi que la ventana sigue respondiendo mientras.
REINTENTO_VIVO_S = 2.0

# Cuantos cuadros de historia se guardan en vivo (a 60 fps, 3600 = 1 minuto).
HISTORIA_VIVO_CUADROS = 3600

# --- PROCESO DE IMAGEN ---------------------------------------------------
# A que ancho se reduce cada cuadro para medir. 320 va de sobra y es lo que
# hace que un video de 25 s se procese en medio minuto y no en diez.
ANCHO_TRABAJO = 320

# Rachas mas cortas que esto por simbolo se tiran por ser glitches de
# conmutacion: las dos lamparas no cambian exactamente a la vez.
FRAC_GLITCH = 0.45

# Factores del periodo de simbolo que se prueban cuando el nominal no cuadra.
BARRIDO = [0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1]

# Cuantos recuadros candidatos se prueban como maximo antes de rendirse.
MAX_CANDIDATOS_ROI = 18


# ##########################################################################
#  1. EL CODIGO
#     Como se convierte una cuadricula de celdas en estados de las dos luces
#     y al reves. Aqui no hay camaras ni ventanas: solo bits.
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
    suave = cv2.GaussianBlur(roi, (5, 5), 0).astype(np.float32)
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
    estados = np.zeros(n, dtype=int)
    for i in range(n):
        a, b = max(0, i - ventana), min(n, i + ventana)
        vl = lums[a:b]
        p10, p90 = np.percentile(vl, 10), np.percentile(vl, 90)
        corte_off = p10 + 0.35 * (p90 - p10)
        if p90 - p10 < 6 or lums[i] < corte_off:
            estados[i] = APAGADO
            continue
        encendidos = cromas[a:b][vl >= corte_off]
        if len(encendidos) < 10:
            estados[i] = AMBAS
            continue
        lo, hi = np.percentile(encendidos, 12), np.percentile(encendidos, 88)
        if hi - lo < 0.02:              # un solo color en la ventana
            estados[i] = AMBAS
            continue
        t1, t2 = lo + 0.34 * (hi - lo), lo + 0.68 * (hi - lo)
        estados[i] = (LUZ_B if cromas[i] < t1 else
                      LUZ_A if cromas[i] > t2 else AMBAS)
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
    suave = cv2.GaussianBlur(roi, (5, 5), 0).astype(np.float32)
    plano = suave.mean(2).ravel()
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
    for i in range(n):
        lo, hi = max(0, i - ventana), min(n, i + ventana)
        prendidas = 0
        for serie, peso in ((a, 1), (b, 2)):
            v = serie[lo:hi]
            p10, p90 = np.percentile(v, 10), np.percentile(v, 90)
            if p90 - p10 < 4:
                continue                # esa luz no cambia en esta ventana
            if serie[i] >= p10 + 0.45 * (p90 - p10):
                prendidas += peso
        estados[i] = prendidas
    return list(estados)


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


def leer_video(ruta, avisar=None):
    """Carga el video reducido.

    Devuelve (cuadros, tiempos, fps, ancho_original).
    """
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
        esc = min(1.0, float(ANCHO_TRABAJO) / f.shape[1])
        cuadros.append(cv2.resize(f, None, fx=esc, fy=esc))
        if avisar and total and len(cuadros) % 120 == 0:
            avisar(len(cuadros) / total)
    tiempos = np.asarray(tiempos, dtype=np.float64)
    dur = float(tiempos[-1] - tiempos[0]) if len(tiempos) > 1 else 0.0
    fps = _fps_efectivo(cap, len(cuadros), dur)
    cap.release()
    return cuadros, tiempos, fps, original


def _series_de_estados(cuadros, modo):
    """Genera (etiqueta, estados, roi) por cada manera de leer las luces.

    Es un generador y no una lista a proposito: cada elemento cuesta una pasada
    entera por el video, asi que se calculan de uno en uno y se para en cuanto
    uno de CRC valido.
    """
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
        for roi in candidatos_roi(cuadros[:700]):
            x, y, w, h = roi
            lums, cromas = [], []
            for f in cuadros:
                l, c = medir(f[y:y + h, x:x + w])
                lums.append(l)
                cromas.append(c)
            yield ("color", clasificar_serie(lums, cromas), roi)


def decodificar_cuadros(cuadros, tiempos, fps, simbolos_por_s=None, avisar=None,
                        modo=None):
    """El nucleo: prueba maneras de leer las luces y velocidades hasta que un
    CRC cuadre.

    'simbolos_por_s' None significa "mideme la velocidad". Si se da un numero
    se prueba antes que la medida, por si el usuario sabe algo que la señal no
    dice. 'modo' es MODO_LUCES si no se dice otra cosa. Devuelve (info, nota, roi).
    """
    mejor = None
    for etiqueta, estados, roi in _series_de_estados(
            cuadros, modo or MODO_LUCES):
        medida, confianza = estimar_simbolos_por_s(tiempos, estados, fps=fps)
        velocidades = []
        if simbolos_por_s:
            velocidades.append(float(simbolos_por_s))
        if medida is not None and confianza >= 0.25:
            velocidades.append(medida)
        velocidades += [v for v in VELOCIDADES_TIPICAS
                        if all(abs(v - u) > 0.2 for u in velocidades)]
        if avisar:
            avisar("por %-18s recuadro (%d,%d,%d,%d): velocidad medida %s"
                   % (etiqueta, roi[0], roi[1], roi[2], roi[3],
                      "%.2f sim/s" % medida if medida else "no medible"))

        for sps in velocidades:
            info, nota = decodificar_traza(estados, fps / max(0.1, sps))
            if info and info.get("crc_ok"):
                aviso = ""
                if fps / sps < CUADROS_POR_SIMBOLO_MIN:
                    aviso = "  [ojo: solo %.1f cuadros/simbolo]" % (fps / sps)
                return (info, "%s  (por %s, %.2f sim/s)%s"
                        % (nota, etiqueta, sps, aviso), roi)
            if info and mejor is None:
                mejor = (info, "%s  (por %s, %.2f sim/s)"
                         % (nota, etiqueta, sps), roi)
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
    return None, motivo, None


def procesar_video(ruta, simbolos_por_s=None, verboso=True):
    """Procesa un video ENTERO y devuelve (grid, nota, roi, escala).

    Es todo lo que hace falta para un archivo: no se reproduce nada, no se
    descifra dos veces. El resultado se devuelve listo para pintar.
    """
    if verboso:
        print("Leyendo el video...")
    cuadros, tiempos, fps, original = leer_video(
        ruta, avisar=(lambda p: print("   %3.0f%%" % (p * 100), end="\r"))
        if verboso else None)
    if not cuadros:
        return None, "no se pudo leer el video", None, 1.0
    escala = float(original) / cuadros[0].shape[1]
    if verboso:
        print("   %d cuadros, %.1f s -> %.2f fps efectivos"
              % (len(cuadros), tiempos[-1] - tiempos[0], fps))
        print("Buscando las luces y descifrando...")
    info, nota, roi = decodificar_cuadros(
        cuadros, tiempos, fps, simbolos_por_s,
        avisar=(lambda m: print("   " + m)) if verboso else None)
    grid = a_cuadricula(info) if info and info.get("cabecera_ok") else None
    if roi is not None:
        roi = tuple(int(round(v * escala)) for v in roi)
    return grid, nota, roi, escala


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
        cap = cv2.VideoCapture(int(cual), cv2.CAP_DSHOW)      # camara del PC
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


def camaras_disponibles(hasta=6):
    """Que camaras responden. Devuelve [(indice, ancho, alto, brillo_medio)]."""
    encontradas = []
    for i in range(hasta):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, f = cap.read()
            for _ in range(4):            # las primeras suelen venir en negro
                ok2, f2 = cap.read()
                if ok2:
                    ok, f = ok2, f2
            if ok:
                encontradas.append((i, f.shape[1], f.shape[0], float(f.mean())))
        cap.release()
    return encontradas


class _Descifrador(threading.Thread):
    """Descifra en segundo plano, para que la ventana nunca se congele.

    ESTE HILO ES EL ARREGLO de que la tecla 'q' no respondiera en vivo: cada
    intento tarda un par de segundos (recorre toda la historia probando varios
    recuadros), y hacerlo en el mismo bucle que dibuja dejaba la ventana
    bloqueada mas de la mitad del tiempo, asi que cv2.waitKey casi nunca veia
    la tecla. Aqui el bucle solo copia la historia, se la pasa al hilo y sigue
    dibujando; cuando el hilo termina, deja el resultado en .salida.
    """

    def __init__(self, cuadros, tiempos, fps, simbolos_por_s):
        super().__init__(daemon=True)
        self.cuadros, self.tiempos = cuadros, tiempos
        self.fps, self.simbolos_por_s = fps, simbolos_por_s
        self.salida = None

    def run(self):
        try:
            self.salida = decodificar_cuadros(
                self.cuadros, self.tiempos, self.fps, self.simbolos_por_s)
        except Exception as e:                 # el hilo no puede tumbar la app
            self.salida = (None, "error al descifrar: %s" % e, None)


def escuchar_camara(cual=CAMARA, simbolos_por_s=None, fps_pedidos=FPS_CAMARA,
                    exposicion=EXPOSICION_CAMARA, al_actualizar=None,
                    cada=REINTENTO_VIVO_S):
    """La camara en vivo, que es el unico caso donde no existe "el final".

    Se acumulan cuadros y cada 'cada' segundos se lanza un intento sobre TODA
    la historia (no cuadro a cuadro: la ventana movil de umbrales tiene que
    quedar centrada para absorber la deriva de exposicion). En cuanto un CRC
    cuadra el resultado se CONGELA y no se vuelve a pisar con una lectura peor.

    'al_actualizar(estado)' se llama en CADA cuadro con un diccionario y debe
    devolver True para seguir o False para parar. Como el descifrado va en otro
    hilo, esto se llama a ritmo de camara y las teclas responden siempre.
    """
    cap = abrir_camara(cual, fps_pedidos, exposicion)
    if not cap.isOpened():
        return None, "no se pudo abrir la camara %s" % cual

    cuadros, tiempos = [], []
    grid, nota, roi, congelado = None, "esperando transmision...", None, False
    hilo = None
    t_ini = time.time()
    proximo = t_ini + 4.0
    exposicion_actual = exposicion
    sin_imagen = 0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                sin_imagen += 1
                if sin_imagen > 30:
                    nota = "la camara dejo de entregar imagen"
                    break
                continue
            sin_imagen = 0
            ahora = time.time()
            esc = min(1.0, float(ANCHO_TRABAJO) / f.shape[1])
            cuadros.append(cv2.resize(f, None, fx=esc, fy=esc))
            tiempos.append(ahora - t_ini)
            if len(cuadros) > HISTORIA_VIVO_CUADROS:
                cuadros.pop(0)
                tiempos.pop(0)

            # recoger el resultado del intento anterior, si ya termino
            if hilo is not None and not hilo.is_alive():
                info, nota, roi = hilo.salida or (None, nota, roi)
                hilo = None
                if info and info.get("cabecera_ok"):
                    nuevo = a_cuadricula(info)
                    if nuevo:
                        grid = nuevo
                    if info.get("crc_ok"):
                        congelado = True      # llego entero: no se toca mas

            # lanzar el siguiente
            if (not congelado and hilo is None and ahora >= proximo
                    and len(cuadros) > 90):
                proximo = ahora + cada
                fps = (len(cuadros) - 1) / max(0.5, tiempos[-1] - tiempos[0])
                hilo = _Descifrador(list(cuadros), np.asarray(tiempos), fps,
                                    simbolos_por_s)
                hilo.start()

            if al_actualizar is None:
                continue
            respuesta = al_actualizar({
                "grid": grid, "nota": nota, "cuadro": f, "roi": roi,
                "congelado": congelado, "descifrando": hilo is not None,
                "segundos": ahora - t_ini, "cuadros": len(cuadros),
                "exposicion": exposicion_actual,
            })
            if respuesta is False:
                break
            if isinstance(respuesta, dict) and "exposicion" in respuesta:
                exposicion_actual = respuesta["exposicion"]
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                cap.set(cv2.CAP_PROP_EXPOSURE, exposicion_actual)
            if respuesta == "reiniciar":
                cuadros, tiempos = [], []
                grid, congelado, roi = None, False, None
                nota = "escucha reiniciada"
                t_ini = time.time()
    finally:
        cap.release()
    return grid, nota


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


def elegir_fuente():
    """Ventana para escoger que analizar. Devuelve (ruta_video, indice_camara).

    Existe para poder darle al boton de play y probar una toma sin escribir un
    comando. Si no hay tkinter cae a un menu por consola.
    """
    videos = buscar_videos()
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return _elegir_por_consola(videos)

    elegido = {"video": None, "camara": None}
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
        elegido["camara"] = 0
        raiz.destroy()

    lista.bind("<Double-Button-1>", analizar)
    lista.bind("<Return>", analizar)

    botones = tk.Frame(raiz, bg="#1e1e2e")
    botones.pack(fill="x", padx=12, pady=12)
    for texto, orden, color in (("Descifrar el seleccionado", analizar, "#a6e3a1"),
                                ("Buscar otro archivo...", otro, "#89b4fa"),
                                ("Camara en vivo", camara, "#f9e2af")):
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
    return elegido["video"], elegido["camara"]


def _elegir_por_consola(videos):
    if not videos:
        return None, 0
    print("\nVideos encontrados:")
    for i, v in enumerate(videos, 1):
        print("  %2d) %s   (%s)" % (i, v.name, v.parent))
    print("   c) camara en vivo")
    r = input("Cual descifro? [1]: ").strip().lower() or "1"
    if r == "c":
        return None, 0
    try:
        return str(videos[int(r) - 1]), None
    except (ValueError, IndexError):
        return str(videos[0]), None


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


VENTANA_CAMARA = "camara   q salir | r reiniciar | + - exposicion"


def _vista_camara(e):
    """Lo que se pinta mientras la camara escucha.

    Devuelve False para parar, "reiniciar" para tirar la historia, o un dict
    con la exposicion nueva. Se llama en cada cuadro, asi que las teclas
    responden al momento: el descifrado va en otro hilo.
    """
    cuadro = e["cuadro"]
    vista = cuadro.copy()
    if e["roi"]:
        x, y, w, h = e["roi"]
        esc = cuadro.shape[1] / float(ANCHO_TRABAJO)
        cv2.rectangle(vista, (int(x * esc), int(y * esc)),
                      (int((x + w) * esc), int((y + h) * esc)),
                      (0, 255, 255), 2)

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

    estado = "%ds  %d cuadros%s" % (e["segundos"], e["cuadros"],
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
    ap.add_argument("--camara", default=None,
                    help="escucha en vivo: un numero (0 es la primera del PC) "
                         "o una URL de celular/camara IP")
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
        for i, w, h, brillo in halladas:
            aviso = "   <- entrega imagen NEGRA" if brillo < 6 else ""
            print("  --camara %d   %dx%d   brillo medio %.1f%s"
                  % (i, w, h, brillo, aviso))
        print()
        print("Para el celular o una camara IP se usa la URL:")
        print("  --camara http://192.168.1.5:8080/video")
        return 0

    simbolos = (None if str(args.simbolos).strip().lower() == "auto"
                else float(args.simbolos))

    # Sin argumentos (el caso de darle al play) se pregunta que analizar en vez
    # de asumir la camara: probar una toma grabada es lo que mas se hace.
    if args.video is None and args.camara is None:
        args.video, args.camara = elegir_fuente()
        if args.video is None and args.camara is None:
            print("No se escogio nada.")
            return 0

    if args.video:
        print("Video: %s" % Path(args.video).name)
        t0 = time.time()
        grid, nota, _, _ = procesar_video(args.video, simbolos)
        print("   (%.0f s)" % (time.time() - t0))
        imprimir_bloque(grid, nota)
        mostrar_resultado(grid, nota, args.guardar)
        return 0

    print("Escuchando la camara %s.  q salir | r reiniciar | + - exposicion"
          % args.camara)
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
