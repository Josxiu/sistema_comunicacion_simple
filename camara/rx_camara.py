# -*- coding: utf-8 -*-
"""RECEPTOR POR CAMARA -- lee las dos luces en un video (o en vivo) y
reconstruye el bloque de celdas.

    Se abre en VS Code y se le da al boton de play. No lleva argumentos:
    sale una ventana con los videos que encuentre al lado y se escoge uno.

Este archivo FUNCIONA SOLO: no importa nada del proyecto, solo numpy y
opencv-python. La codificacion esta incluida en la seccion 1, para que baste
con descargar este archivo y tener el receptor completo.

    pip install numpy opencv-python


COMO ESTA ORGANIZADO
--------------------
El archivo va de lo abstracto a lo concreto, y cada seccion solo usa las
anteriores. Se puede leer de arriba a abajo o saltar a la que interese.

    1. EL CODIGO          bits <-> celdas. No sabe que existen las camaras.
    2. PDI                imagen -> (luminancia, croma) -> estado de las luces.
    3. DECODIFICADOR      estados en el tiempo -> bloque de celdas.
    4. PROCESAR           un video entero, o la camara en vivo.
    5. INTERFAZ           escoger la fuente y pintar el resultado.
    6. ARRANQUE           main().

Las secciones 1 y 3 son puro calculo y se pueden probar sin camara (al final
del archivo, ejecutar con --autoprueba lo comprueba). La 2 es la unica que
toca pixeles. La 5 es la unica que abre ventanas.


DIFERENCIA CON rx_camara_v2.py
------------------------------
La v2 procesa el video y despues lo reproduce descifrandolo otra vez en vivo,
lo que borra el resultado bueno y obliga a esperar a que el video termine.
Sirve para ver el proceso; para mirar el mensaje estorba. Aqui el video se
procesa entero y se muestra el resultado, y ya. En vivo, que es el unico caso
donde no existe "el final", el resultado se CONGELA en cuanto un CRC cuadra y
no se vuelve a pisar con una lectura peor.


COMO SEPARA LAS DOS LUCES
-------------------------
NO por posicion. A 300 m dos luces separadas 20 cm caen en unos 2 pixeles de
una camara de celular: se funden y se sobreexponen. Se separan POR COLOR:

    luminancia = (R+G+B)/3           distingue apagado de encendido
    croma      = (R-G)/(R+G)         roja (+) / verde (-) / las dos (~0)

Restar G y no max(G,B) es deliberado: el LED rojo se ve MAGENTA en la camara
(satura tambien el azul), asi que restarle el azul anularia la señal.


CUANTOS CUADROS HACEN FALTA
---------------------------
El codigo de linea es por transicion: cada frontera de simbolo se ve como un
cambio de las luces, y para ver un cambio hacen falta cuadros a los dos lados.
Por debajo de ~3 cuadros por simbolo no hay decodificador que valga. Medido
sobre las tomas del 25/08/2026:

    54,1 fps -> 4,3 cuadros/simbolo -> CRC valido
    27,1 fps -> 2,2 cuadros/simbolo -> nada (y es EL MISMO video, decimado)
    23,8 fps -> 1,9 cuadros/simbolo -> nada

O sea: la velocidad maxima es fps/3. A 30 fps, 10 simbolos/s; a 60 fps, 20.

Redes de Computadores I - UdeA 2026-2 - Proyecto 01
"""

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np


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
    """CRC-8/ATM (polinomio 0x07) sobre una cadena de bits. Protege la cabecera."""
    crc = 0
    for i in range(0, len(bits), 8):
        byte = int((bits[i:i + 8] + "0" * 8)[:8], 2)
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE (0x1021, init 0xFFFF). Protege la trama entera."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
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
    relleno = bits + "0" * ((-len(bits)) % BITS_POR_GRUPO)
    trits = []
    for i in range(0, len(relleno), BITS_POR_GRUPO):
        v = int(relleno[i:i + BITS_POR_GRUPO], 2)
        trits.append(v // 3)
        trits.append(v % 3)
    return trits


def trits_a_bits(trits, nbits=None):
    bits = []
    for i in range(0, len(trits) - 1, TRITS_POR_GRUPO):
        v = trits[i] * 3 + trits[i + 1]
        if v > 7:
            v = 7                     # grupo corrompido; el CRC lo detectara
        bits.append(format(v, "03b"))
    salida = "".join(bits)
    return salida[:nbits] if nbits is not None else salida


def trits_a_simbolos(trits, estado_inicial=APAGADO):
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
    return "".join(celda_a_bits(c) for fila in grid for c in fila)


def construir_trama(tipo, filas, cols, payload_bits=""):
    if filas > MAX_FILAS or cols > MAX_COLS:
        raise ValueError("dimensiones fuera de rango (max %dx%d)" % (MAX_FILAS, MAX_COLS))
    if len(payload_bits) > MAX_NBITS:
        raise ValueError("payload de %d bits, maximo %d" % (len(payload_bits), MAX_NBITS))
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
    return (int(cab[0:4], 2), int(cab[4:9], 2), int(cab[9:14], 2), int(cab[14:24], 2))


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
    """Recuadro conexo alrededor de (y,x) con varianza >= frac veces la de ahi."""
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


def candidatos_roi(frames, maximo=18):
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

FRAC_GLITCH = 0.45          # rachas mas cortas que esto x el simbolo se descartan
BARRIDO = [0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1]

# Por debajo de esto la grabacion no sirve. Ver la nota del encabezado.
CUADROS_POR_SIMBOLO_MIN = 3.0


def rachas(estados):
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
    asignaciones posibles de color. Devuelve (info, nota)."""
    parcial = None
    for etiqueta, datos in (("", traza),
                            (" [luces intercambiadas]", intercambiar(traza))):
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

ANCHO_TRABAJO = 320       # se reduce a esto para medir; de sobra y mucho mas rapido
VELOCIDADES_TIPICAS = (5, 4, 6, 3, 8, 2, 10, 1, 12.5, 15, 20)


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
    """Carga el video reducido. Devuelve (cuadros, tiempos, fps, ancho_original)."""
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


def decodificar_cuadros(cuadros, tiempos, fps, simbolos_por_s=None, avisar=None):
    """El nucleo: prueba recuadros y velocidades hasta que un CRC cuadre.

    'simbolos_por_s' None significa "mideme la velocidad". Si se da un numero
    se prueba antes que la medida, por si el usuario sabe algo que la señal no
    dice. Devuelve (info, nota, roi).
    """
    mejor = None
    for roi in candidatos_roi(cuadros[:700]):
        x, y, w, h = roi
        lums, cromas = [], []
        for f in cuadros:
            l, c = medir(f[y:y + h, x:x + w])
            lums.append(l)
            cromas.append(c)
        estados = clasificar_serie(lums, cromas)

        medida, confianza = estimar_simbolos_por_s(tiempos, estados, fps=fps)
        velocidades = []
        if simbolos_por_s:
            velocidades.append(float(simbolos_por_s))
        if medida is not None and confianza >= 0.25:
            velocidades.append(medida)
        velocidades += [v for v in VELOCIDADES_TIPICAS
                        if all(abs(v - u) > 0.2 for u in velocidades)]
        if avisar:
            avisar("recuadro (%d,%d,%d,%d): velocidad medida %s"
                   % (x, y, w, h,
                      "%.2f sim/s" % medida if medida else "no medible"))

        for sps in velocidades:
            info, nota = decodificar_traza(estados, fps / max(0.1, sps))
            if info and info.get("crc_ok"):
                aviso = ""
                if fps / sps < CUADROS_POR_SIMBOLO_MIN:
                    aviso = "  [ojo: solo %.1f cuadros/simbolo]" % (fps / sps)
                return info, "%s  (%.2f sim/s)%s" % (nota, sps, aviso), roi
            if info and mejor is None:
                mejor = (info, "%s  (%.2f sim/s)" % (nota, sps), roi)
    if mejor:
        return mejor

    # Sin enganche: casi siempre es que la camara no da abasto, y merece la
    # pena decirlo en vez de dejar a alguien probando recuadros a mano. El
    # aviso se apoya en los fps, que es un dato duro, y NO en la velocidad
    # medida: cuando la señal no da, la medida es basura y su confianza no lo
    # delata (en el video bueno la ROI ganadora tenia 0,42 y en el mismo video
    # decimado, donde no hay nada que leer, salian 0,37 y 0,39).
    return None, ("sin enganche  (el video tiene %.1f fps, o sea un techo de "
                  "~%.0f simbolos/s; por encima de eso hay que grabar a 60)"
                  % (fps, fps / CUADROS_POR_SIMBOLO_MIN)), None


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


def escuchar_camara(indice, simbolos_por_s=None, fps_pedidos=60.0,
                    al_actualizar=None, cada=1.5):
    """La camara en vivo, que es el unico caso donde no existe "el final".

    Se acumulan cuadros y cada 'cada' segundos se reintenta sobre TODA la
    historia (no cuadro a cuadro: la ventana movil de umbrales tiene que quedar
    centrada para absorber la deriva de exposicion). En cuanto un CRC cuadra el
    resultado se CONGELA y no se vuelve a pisar con una lectura peor, que es
    justo lo que hacia perder el bloque bueno en la version anterior.

    'al_actualizar(grid, nota, cuadro, roi, congelado)' se llama en cada vuelta
    y debe devolver True para seguir o False para parar.
    """
    cap = cv2.VideoCapture(indice, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FPS, fps_pedidos)
    # exposicion baja: es lo que evita que las luces se saturen y pierdan color
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -7)
    if not cap.isOpened():
        return None, "no se pudo abrir la camara"

    cuadros, tiempos = [], []
    grid, nota, roi, congelado = None, "esperando transmision...", None, False
    t_ini = time.time()
    proximo = t_ini + 4.0
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            ahora = time.time()
            esc = min(1.0, float(ANCHO_TRABAJO) / f.shape[1])
            cuadros.append(cv2.resize(f, None, fx=esc, fy=esc))
            tiempos.append(ahora - t_ini)
            # se guarda un minuto de historia: mas no aporta y cuesta memoria
            if len(cuadros) > 3600:
                cuadros.pop(0)
                tiempos.pop(0)

            if not congelado and ahora >= proximo and len(cuadros) > 90:
                proximo = ahora + cada
                fps = _fps_efectivo(cap, len(cuadros),
                                    tiempos[-1] - tiempos[0])
                info, nota, roi = decodificar_cuadros(
                    cuadros, np.asarray(tiempos), fps, simbolos_por_s)
                if info and info.get("cabecera_ok"):
                    nuevo = a_cuadricula(info)
                    if nuevo:
                        grid = nuevo
                    if info.get("crc_ok"):
                        congelado = True      # llego entero: no se toca mas

            if al_actualizar and not al_actualizar(grid, nota, f, roi, congelado):
                break
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


def _vista_camara(grid, nota, cuadro, roi, congelado):
    """Lo que se pinta mientras la camara escucha. Devuelve False para parar."""
    vista = cuadro.copy()
    if roi:
        x, y, w, h = roi
        esc = cuadro.shape[1] / float(ANCHO_TRABAJO)
        cv2.rectangle(vista, (int(x * esc), int(y * esc)),
                      (int((x + w) * esc), int((y + h) * esc)),
                      (0, 255, 255), 2)
    escv = min(1.0, 640.0 / vista.shape[1])
    cv2.imshow("camara  ('q' termina)", cv2.resize(vista, None, fx=escv, fy=escv))
    titulo = ("BLOQUE COMPLETO - " if congelado else "") + nota
    cv2.imshow("bloque recibido", pintar_bloque(grid, titulo=titulo))
    return (cv2.waitKey(1) & 0xFF) != ord("q")


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
    print("  a 12,5 simbolos/s son %.1f s por copia" % (len(simbolos) / 12.5))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Receptor por camara de dos luces. Sin argumentos "
                    "pregunta que video descifrar.")
    ap.add_argument("--video", help="descifra este archivo y muestra el bloque")
    ap.add_argument("--camara", type=int, default=None,
                    help="escucha esta camara en vivo (0 es la primera)")
    ap.add_argument("--simbolos", default="auto",
                    help="simbolos/s del transmisor, o 'auto' para medirlos "
                         "sobre la señal (por defecto)")
    ap.add_argument("--guardar", help="guarda el bloque recibido en este .png")
    ap.add_argument("--autoprueba", action="store_true",
                    help="comprueba la codificacion sin camara ni video")
    args = ap.parse_args()

    if args.autoprueba:
        return autoprueba()

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

    print("Escuchando la camara %d. 'q' para terminar." % args.camara)
    grid, nota = escuchar_camara(args.camara, simbolos,
                                 al_actualizar=_vista_camara)
    cv2.destroyAllWindows()
    imprimir_bloque(grid, nota)
    if grid and args.guardar:
        cv2.imwrite(args.guardar, pintar_bloque(grid, 900, 760, nota))
        print("imagen guardada en %s" % args.guardar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
