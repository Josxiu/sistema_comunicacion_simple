# -*- coding: utf-8 -*-
"""Receptor para tomas A PULSO: sigue las luces mientras la camara se mueve.

    python rx_camara_con_seguimiento.py --video "toma.mp4"

Es el hermano de rx_camara.py, para cuando la camara NO estaba quieta. Aquel
mide en recuadros fijos, que es lo correcto con el telefono apoyado y bastante
mas rapido; en cuanto la camara se mueve se queda atras. El sintoma es
inconfundible y costo encontrarlo: el preambulo se lee perfecto y en cuanto
empiezan los datos aparecen tramos de 10, 16 y 21 simbolos con el mismo estado,
que con codigo por transicion son imposibles. No es la señal, es el recuadro.

Todo lo que no sea seguir las luces se importa de rx_camara: la codificacion,
la medida, la clasificacion, el decodificador, la ventana y la camara en vivo.
Asi no hay dos copias que se separen con el tiempo, y cualquier arreglo de alli
llega aqui solo. Este archivo se queda con tres cosas:

    semillas_de_luces   de donde partir
    seguir_luces        el camino, tramo a tramo
    afinar_camino       el retoque cuadro a cuadro

POR QUE NO SE ESTABILIZA LA IMAGEN Y YA
---------------------------------------
Se probo, porque es lo que parece obvio: estimar el desplazamiento global con
cv2.phaseCorrelate y restarlo. No sirve aqui. El temblor real es deriva MUY
lenta (17 px a lo largo de 39 s, o sea 0,03 Hz), asi que cada cuadro aporta una
fraccion de pixel y hay que acumular miles de estimaciones. Medido sobre
sintetico_temblor.mp4, la deriva acumulada del estimador era de ~11 px al final
del video, mas que la separacion entre las dos luces. Anclarse a las luces
mismas, que es lo que hace este archivo, no acumula error: cada ancla se mide
contra el mapa de parpadeo, en absoluto.

Redes de Computadores I - UdeA 2026-2 - Proyecto 01
"""

import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rx_camara as base                                     # noqa: E402

# Lo que se usa tal cual de rx_camara, para poder nombrarlo sin prefijo.
from rx_camara import (                                      # noqa: E402,F401
    APAGADO, LUZ_A, LUZ_B, AMBAS, NEGRO, BLANCO,
    mapa_luz, picos_de_luz, brillo_de, recorte_centrado,
    a_cuadricula, descifrar_medidas, Lectura,
    imprimir_bloque, mostrar_resultado, hay_pantalla, EXT_VIDEO,
)


# ##########################################################################
#  0. PARAMETROS
#     Los del receptor normal estan en rx_camara.py y valen tambien aqui.
#     Estos son solo los del seguimiento.
# ##########################################################################

# Ancho al que se reduce el video para SEGUIR. Seguir no necesita resolucion
# -se busca un maximo del mapa de parpadeo, no se mide- y aqui hay que tener
# todos los cuadros en memoria a la vez, asi que conviene que sea pequeño.
# Medir se hace despues, en otra pasada y sobre el cuadro sin reducir.
ANCHO_SEGUIMIENTO = 640

# Cada cuantos cuadros se vuelve a fijar donde estan las luces. Los dos no
# valen para lo mismo: 45 para luz pequeña y lejana (hace falta acumular
# parpadeos), 20 para camara temblorosa de cerca.
BLOQUES_SEGUIMIENTO = (45, 20)

# Tramos de los que se sacan puntos de partida. Cada tramo da dos (el pico
# puede ser cualquiera de las dos luces) y cada punto cuesta una pasada.
SEMILLAS_SEGUIMIENTO = 2

# Separacion (min, max) entre las dos luces, en px de la imagen de seguimiento,
# para darlas por buenas al buscarlas.
SEPARACION_SEGUIMIENTO = (4.0, 80.0)

# Cuanto se mueve el recuadro de medida entre anclas antes de creerselo. Por
# debajo es temblor del propio buscador y conviene dejarlo quieto.
DERIVA_MINIMA_PX = 3.0

BANDA_PARPADEO = base.BANDA_PARPADEO


# ##########################################################################
#  1. SEGUIR LAS LUCES
#     Lo unico que este archivo hace por su cuenta.
# ##########################################################################

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
        v = vecindad.astype(np.float32)
        gris = cv2.GaussianBlur(v.mean(2) if v.ndim == 3 else v, (3, 3), 0)
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


# ##########################################################################
#  2. DEL CAMINO AL BLOQUE
#     Se sigue sobre cuadros reducidos y se MIDE sobre el video sin reducir,
#     en otra pasada. Medir es lo que necesita resolucion: a 320 px dos luces
#     separadas 10 px quedan a 3 y ya no hay dos puntos que separar.
# ##########################################################################

def cargar_para_seguir(ruta, ancho=ANCHO_SEGUIMIENTO):
    """Los cuadros en gris y reducidos, que es lo unico que pide el seguidor.

    En gris y no en color a proposito: el seguimiento mira el mapa de parpadeo,
    que es de luminancia, y guardar los tres canales multiplica por tres la
    memoria sin aportar nada.

    Devuelve (cuadros, fps, escala) con la escala para volver a pixeles del
    cuadro original.
    """
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return [], 30.0, 1.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cuadros, escala = [], 1.0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        esc = min(1.0, float(ancho) / f.shape[1])
        if esc < 1.0:
            f = cv2.resize(f, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
        escala = 1.0 / esc
        cuadros.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
    cap.release()
    return cuadros, fps, escala


def caminos_candidatos(cuadros, fps, escala):
    """Los caminos que puede seguir la pareja, del mas prometedor al menos.

    Se prueban varios puntos de partida y varios tamaños de tramo porque no hay
    forma de saber de antemano cual acierta: con la luz lejos hace falta un
    tramo largo para acumular parpadeos, y con la camara temblorosa uno corto
    para no emborronar. Quien llame prueba en orden hasta que cuadre el CRC.

    Devuelve [(nombre, punto_inicial, separacion, anclas)] en pixeles del
    cuadro ORIGINAL, listo para que rx_camara.medir_en_video los mida.
    """
    semillas, separacion = semillas_de_luces(cuadros, fps)
    if not semillas or separacion is None:
        return []
    salida, vistos = [], set()
    for bloque in BLOQUES_SEGUIMIENTO:
        for i0, punto in semillas:
            clave = (bloque, round(float(punto[0]), 1), round(float(punto[1]), 1))
            if clave in vistos:
                continue
            vistos.add(clave)
            camino = afinar_camino(
                cuadros,
                seguir_luces(cuadros, i0, punto, separacion, fps, bloque=bloque),
                separacion)
            # anclas cada medio segundo: mas que suficiente para un temblor de
            # mano, y rx_camara interpola entre ellas
            paso = max(1, int(fps // 2))
            anclas = [(k, camino[k] * escala)
                      for k in range(0, len(camino), paso)]
            salida.append(("bloque %d" % bloque, camino[0] * escala,
                           separacion * escala, anclas))
    return salida


def lecturas_siguiendo(ruta, caminos, con_color=False, avisar=None):
    """Mide todas las parejas seguidas de una pasada, sin reducir el cuadro."""
    parejas = [(punto, sep, anclas) for _, punto, sep, anclas in caminos]
    antes = base.DERIVA_MINIMA_PX
    try:
        # aqui SI queremos que el recuadro siga al camino: la camara se movio
        base.DERIVA_MINIMA_PX = DERIVA_MINIMA_PX
        candidatos, fps = base.medir_en_video(ruta, parejas, avisar=avisar,
                                              con_color=con_color)
    finally:
        base.DERIVA_MINIMA_PX = antes
    lecturas = []
    for (nombre, _, _, _), c in zip(caminos, candidatos):
        lectura = c.lectura()
        lecturas.append(Lectura(**dict(lectura.__dict__,
                                       etiqueta="seguidas %s" % nombre)))
    return lecturas, fps, candidatos


def procesar_video(ruta, simbolos_por_s=None, verboso=True, zona=None):
    """Descifra un archivo siguiendo las luces. Devuelve (grid, nota, roi, 1.0).

    Misma firma que rx_camara.procesar_video, asi que los dos se pueden usar
    indistintamente desde fuera (lo hace hacer_video_caja.py, por ejemplo).

    Si el seguimiento no saca nada se cae al receptor normal, que es el que
    acierta cuando la camara estaba quieta y las luces fundidas en un punto.
    """
    aviso = (lambda m: print("   " + m)) if verboso else None
    if verboso:
        print("Cargando el video para seguir las luces...")
    cuadros, fps, escala = cargar_para_seguir(ruta)
    if not cuadros:
        return None, "no se pudo leer el video", None, 1.0

    if verboso:
        print("   %d cuadros a %.0f px de ancho (escala %.1f)"
              % (len(cuadros), cuadros[0].shape[1], escala))
        print("Buscando por donde van las luces...")
    caminos = caminos_candidatos(cuadros, fps, escala)
    recorrido = 0.0
    if caminos:
        puntos = np.array([p for _, p in caminos[0][3]])
        recorrido = float(np.ptp(puntos, axis=0).max())
        if verboso:
            print("   %d caminos candidatos; el primero recorre %.0f px"
                  % (len(caminos), recorrido))
    del cuadros                       # ya no hacen falta: medir relee el video

    info = None
    if caminos:
        if verboso:
            print("Midiendo sobre el cuadro sin reducir...")
        lecturas, fps2, candidatos = lecturas_siguiendo(ruta, caminos)
        info, nota = descifrar_medidas(lecturas, fps2, simbolos_por_s, aviso)
        if info is None or not info.get("crc_ok"):
            if verboso:
                print("Sin CRC por luminancia: releyendo en color...")
            lecturas, fps2, candidatos = lecturas_siguiendo(ruta, caminos,
                                                            con_color=True)
            info2, nota2 = descifrar_medidas(lecturas, fps2, simbolos_por_s,
                                             aviso)
            if info2 is not None and (info is None or info2.get("crc_ok")):
                info, nota = info2, nota2

    if info is not None and info.get("crc_ok"):
        roi = None
        for (nombre, _, _, _), c in zip(caminos, candidatos):
            if nombre in nota:
                roi = c.roi()
                break
        return a_cuadricula(info), nota, roi, 1.0

    if verboso:
        print("El seguimiento no cuadro; probando con recuadros quietos...")
    grid, nota_quieta, roi, esc = base.procesar_video(
        ruta, simbolos_por_s, verboso=verboso, zona=zona)
    if grid:
        return grid, nota_quieta, roi, esc
    if info is not None:
        return a_cuadricula(info), nota, None, 1.0
    return None, nota_quieta, None, 1.0


# ##########################################################################
#  3. ARRANQUE
#     Los mismos argumentos que rx_camara, y la camara en vivo es la suya:
#     en vivo no hay nada que seguir porque la busqueda se repite cada pocos
#     segundos y las parejas nuevas entran solas.
# ##########################################################################

def main():
    args = base._argumentos()
    if args.autoprueba or args.autoprueba_pdi:
        return base.main()
    if args.camaras:
        return base.listar_camaras()

    simbolos = (None if str(args.simbolos).strip().lower() == "auto"
                else float(args.simbolos))
    if args.camara is not None or args.simular_vivo:
        return base.main()            # en vivo lo lleva el receptor normal

    ruta = args.video
    if ruta is None:
        ruta, camara, simular = base.elegir_fuente()
        if ruta is None:
            print("No se escogio nada.")
            return 0

    print("Video: %s  (siguiendo las luces)" % Path(ruta).name)
    t0 = time.time()
    grid, nota, _, _ = procesar_video(ruta, simbolos,
                                      zona=base.leer_zona(args.zona))
    print("   (%.0f s)" % (time.time() - t0))
    imprimir_bloque(grid, nota)
    mostrar_resultado(grid, nota, args.guardar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
