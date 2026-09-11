# -*- coding: utf-8 -*-
"""Videos de prueba de la caja, hechos con piezas de las tomas reales.

    python hacer_video_caja.py            genera los casos y los descifra
    python hacer_video_caja.py quieto     solo los que lleven eso en el nombre

Las piezas estan en sprites/ y salieron de recortar un video real:

    fondo_caja.png        un cuadro del balcon con las luces apagadas
    sprite_rojo.png       el halo de la luz roja, restado de un cuadro encendido
    sprite_amarillo.png   lo mismo de la amarilla

Las luces se SUMAN al fondo, que es lo que hace la luz de verdad: sale el mismo
nucleo quemado y el mismo halo de color, y "las dos prendidas" se distingue de
"solo una" porque dos focos que alumbran el mismo sitio suman.

Encima se le mete temblor de camara, calibrado con lo medido en las tomas
reales (recorrido total a lo largo del video, en pixeles del original):

    0 px   tripode
    8 px   mano apoyada en la baranda
    15 px  como videoprueba1 / videoprueba3
    55 px  como videoconzoom, un tercio del cuadro

Para lo que sirve de verdad: para separar "el receptor falla" de "la grabacion
no daba". Si un video sintetico con el mismo temblor y la misma velocidad SI
descifra, el problema esta en la toma; si tampoco, esta en el codigo.

Los videos se escriben al lado de este archivo y no se suben al repositorio
(ver .gitignore): cada uno pesa entre 25 y 65 MB.
"""

import sys
import time
from pathlib import Path

import cv2
import numpy as np

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))
import rx_camara as codec                                    # noqa: E402


# --- lo ajustable ---------------------------------------------------------

MENSAJE = [list("HOLA"),
           ["_", "_", "_", "#"],
           ["#", "#", "_", "#"],
           list("DIEG")]

# (nombre, simbolos/s, temblor en px, separacion de las luces en px)
CASOS = [
    ("sintetico_quieto.mp4",       5.0,  0, 10),
    ("sintetico_temblor.mp4",      5.0, 15, 10),
    ("sintetico_muy_movido.mp4",   5.0, 55, 10),
    ("sintetico_rapido.mp4",      10.0, 15, 10),
    ("sintetico_juntas.mp4",       5.0, 15,  6),
]

FPS = 60.0
SEGUNDOS_ANTES = 2.0          # oscuridad delante, como en las tomas reales
SEGUNDOS_DESPUES = 1.5
COPIAS = 2
RUIDO = 2.0                   # ruido del sensor, en niveles

# Donde estaban las luces de verdad en el cuadro del que salio el fondo.
LUZ_ROJA = (245, 345)
LUZ_AMARILLA = (254, 345)

SPRITES = CARPETA / "sprites"


# --- generar --------------------------------------------------------------

def cargar_piezas():
    faltan = [p.name for p in (SPRITES / "fondo_caja.png",
                               SPRITES / "sprite_rojo.png",
                               SPRITES / "sprite_amarillo.png")
              if not p.exists()]
    if faltan:
        raise FileNotFoundError("Faltan %s en %s" % (", ".join(faltan), SPRITES))
    return (cv2.imread(str(SPRITES / "fondo_caja.png")),
            cv2.imread(str(SPRITES / "sprite_rojo.png")),
            cv2.imread(str(SPRITES / "sprite_amarillo.png")))


def sumar_luz(imagen, centro, sprite):
    """Pega el halo sumando, no sobreescribiendo."""
    radio = sprite.shape[0] // 2
    x, y = int(round(centro[0])), int(round(centro[1]))
    alto, ancho = imagen.shape[:2]
    x1, y1 = max(0, x - radio), max(0, y - radio)
    x2, y2 = min(ancho, x + radio + 1), min(alto, y + radio + 1)
    if x2 <= x1 or y2 <= y1:
        return
    sx1, sy1 = x1 - (x - radio), y1 - (y - radio)
    imagen[y1:y2, x1:x2] = cv2.add(
        imagen[y1:y2, x1:x2],
        sprite[sy1:sy1 + (y2 - y1), sx1:sx1 + (x2 - x1)])


def camino_de_temblor(n, amplitud, semilla=0):
    """Un vaiven suave, como el pulso de una mano.

    No es ruido blanco. Lo medido en las tomas reales son 17 px de recorrido a
    lo largo de 39 segundos, o sea 0,03 Hz: eso es deriva, no vaiven. Un primer
    intento repartia la energia hasta ~2,4 Hz y el video sintetico dejaba de
    descifrar aunque el real con el mismo recorrido si descifraba, porque a esa
    frecuencia TODOS los bordes de la escena caen dentro de la banda de
    parpadeo y el buscador de luces se iba a la baranda.
    """
    if amplitud <= 0:
        return np.zeros((n, 2))
    rng = np.random.default_rng(semilla)
    relleno = 600
    bruto = rng.normal(0, 1.0, (n + 2 * relleno, 2))

    def suavizar(x, ventana):
        nucleo = np.ones(int(ventana)) / int(ventana)
        return np.stack([np.convolve(x[:, k], nucleo, mode="same")
                         for k in range(2)], axis=1)

    def escalar(x, tope):
        pico = np.abs(x).max()
        return x * (tope / pico) if pico > 0 else x

    lento = suavizar(bruto, max(120, n // 4))[relleno:relleno + n]
    lento = escalar(lento - lento.mean(axis=0), amplitud)
    pulso = suavizar(bruto, 6)[relleno:relleno + n]
    return lento + escalar(pulso, min(1.5, amplitud * 0.1))


def hacer_video(salida, sps, temblor, separacion, mensaje=None):
    mensaje = mensaje or MENSAJE
    fondo, sprite_rojo, sprite_amarillo = cargar_piezas()
    bits = codec.construir_trama(codec.TIPO_BLOQUE, len(mensaje),
                                 len(mensaje[0]), codec.celdas_a_bits(mensaje))
    simbolos = codec.codificar_linea(bits) * COPIAS

    alto, ancho = fondo.shape[:2]
    n = int((len(simbolos) / sps + SEGUNDOS_ANTES + SEGUNDOS_DESPUES) * FPS)
    camino = camino_de_temblor(n, temblor)

    # La camara se simula MIRANDO UNA VENTANA que se mueve por el fondo, no
    # desplazando la imagen. Desplazarla dejaba bordes replicados que parpadean
    # con el temblor, y el receptor se iba derecho a esas esquinas.
    margen = int(np.ceil(np.abs(camino).max())) + 6 if temblor > 0 else 0
    ancho_s, alto_s = ancho - 2 * margen, alto - 2 * margen

    medio = ((LUZ_ROJA[0] + LUZ_AMARILLA[0]) / 2.0,
             (LUZ_ROJA[1] + LUZ_AMARILLA[1]) / 2.0)
    izquierda = (medio[0] - separacion / 2.0, medio[1])
    derecha = (medio[0] + separacion / 2.0, medio[1])

    escritor = cv2.VideoWriter(str(salida), cv2.VideoWriter_fourcc(*"mp4v"),
                               FPS, (ancho_s, alto_s))
    if not escritor.isOpened():
        raise RuntimeError("No se pudo abrir %s para escribir" % salida)

    for k in range(n):
        idx = int((k / FPS - SEGUNDOS_ANTES) * sps)
        estado = simbolos[idx] if 0 <= idx < len(simbolos) else codec.APAGADO

        imagen = fondo.copy()
        if estado in (codec.LUZ_A, codec.AMBAS):
            sumar_luz(imagen, izquierda, sprite_rojo)
        if estado in (codec.LUZ_B, codec.AMBAS):
            sumar_luz(imagen, derecha, sprite_amarillo)

        # Se mueve y se recorta AL DOBLE de tamaño y luego se reduce, que es lo
        # que hace el sensor: cada pixel promedia lo que le cae encima. Con
        # saltos de pixel entero el video sintetico no descifraba ni con 15 px
        # de temblor, que en la vida real si descifra.
        dx, dy = camino[k]
        grande = cv2.resize(imagen, (ancho * 2, alto * 2),
                            interpolation=cv2.INTER_CUBIC)
        grande = cv2.warpAffine(
            grande, np.float32([[1, 0, -dx * 2], [0, 1, -dy * 2]]),
            (ancho * 2, alto * 2), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE)
        cuadro = cv2.resize(
            grande[margen * 2:(margen + alto_s) * 2,
                   margen * 2:(margen + ancho_s) * 2],
            (ancho_s, alto_s), interpolation=cv2.INTER_AREA)
        if RUIDO > 0:
            cuadro = np.clip(cuadro.astype(np.float32) +
                             np.random.normal(0, RUIDO, cuadro.shape),
                             0, 255).astype(np.uint8)
        escritor.write(cuadro)
    escritor.release()
    return len(simbolos), n


def comprobar(ruta, mensaje=None, receptor=codec):
    mensaje = mensaje or MENSAJE
    grid, nota, _, _ = receptor.procesar_video(str(ruta), verboso=False)
    if not grid:
        return False, nota
    igual = (len(grid) == len(mensaje) and
             all(list(a) == list(b) for a, b in zip(grid, mensaje)))
    return igual, nota


def main():
    filtro = sys.argv[1] if len(sys.argv) > 1 else None
    print("mensaje: %s" % " / ".join("".join(f) for f in MENSAJE))
    for nombre, sps, temblor, separacion in CASOS:
        if filtro and filtro not in nombre:
            continue
        ruta = CARPETA / nombre
        if not ruta.exists():
            t0 = time.time()
            cuantos, cuadros = hacer_video(ruta, sps, temblor, separacion)
            print("\n%-26s %d simbolos, %d cuadros  [%.0f s]"
                  % (nombre, cuantos, cuadros, time.time() - t0))
        else:
            print("\n%-26s (ya estaba)" % nombre)
        t0 = time.time()
        bien, nota = comprobar(ruta)
        print("   temblor %2d px, luces a %2d px  ->  %-10s %s  [%.0f s]"
              % (temblor, separacion, "IGUAL" if bien else "NO cuadra",
                 str(nota).split("\n")[0][:56], time.time() - t0))


if __name__ == "__main__":
    main()
