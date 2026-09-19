# -*- coding: utf-8 -*-
"""Hojas de prueba: la cuadricula impresa, fotografiada con un celular.

    python hacer_hojas.py              las tres tandas
    python hacer_hojas.py crucigrama   solo el estilo del profesor

Genera la hoja con PIL (fuentes de verdad) y luego le mete lo que le pasa a
una foto: perspectiva, luz despareja, sombra, desenfoque y ruido.

PIL SOLO SE USA AQUI. El lector no la necesita.
"""
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ALFABETO = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
NEGRO, BLANCO = "#", "_"

# Las fuentes de las hojas NO son las de las plantillas del lector: si fueran
# las mismas la prueba estaria amañada.
FUENTES_HOJA = [
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def cuadricula_al_azar(filas, cols, rng):
    """Una matriz como la que entregaria el profesor."""
    g = []
    for f in range(filas):
        fila = []
        for c in range(cols):
            r = rng.random()
            fila.append(NEGRO if r < 0.15 else
                        BLANCO if r < 0.30 else
                        rng.choice(ALFABETO))
        g.append(fila)
    return g


def dibujar_hoja(grid, fuente, lado=110, margen=90, grosor=3):
    """La hoja tal cual saldria de la impresora."""
    filas, cols = len(grid), len(grid[0])
    W, H = cols * lado + 2 * margen, filas * lado + 2 * margen
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    tipo = ImageFont.truetype(fuente, int(lado * 0.60))

    for f in range(filas):
        for c in range(cols):
            x0, y0 = margen + c * lado, margen + f * lado
            x1, y1 = x0 + lado, y0 + lado
            v = grid[f][c]
            if v == NEGRO:
                d.rectangle([x0 + grosor, y0 + grosor,
                             x1 - grosor, y1 - grosor], fill=30)
            elif v != BLANCO:
                caja = d.textbbox((0, 0), v, font=tipo)
                d.text((x0 + (lado - (caja[2] - caja[0])) / 2 - caja[0],
                        y0 + (lado - (caja[3] - caja[1])) / 2 - caja[1]),
                       v, font=tipo, fill=20)
            d.rectangle([x0, y0, x1, y1], outline=0, width=grosor)
    return np.array(img)


def fotografiar(hoja, rng, perspectiva=0.05, giro=3.0, desenfoque=3,
                ruido=6.0, sombra=0.35):
    """Lo que le pasa a la hoja entre la impresora y el sensor."""
    H, W = hoja.shape
    lienzo = np.full((int(H * 1.35), int(W * 1.35)), 235, np.uint8)
    oy, ox = (lienzo.shape[0] - H) // 2, (lienzo.shape[1] - W) // 2
    lienzo[oy:oy + H, ox:ox + W] = hoja

    h, w = lienzo.shape
    d = lambda: rng.uniform(-perspectiva, perspectiva)
    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    destino = np.float32([[w * d(), h * d()], [w * (1 + d()), h * d()],
                          [w * (1 + d()), h * (1 + d())],
                          [w * d(), h * (1 + d())]])
    M = cv2.getPerspectiveTransform(origen, destino)
    img = cv2.warpPerspective(lienzo, M, (w, h),
                              borderValue=235, flags=cv2.INTER_LINEAR)
    M2 = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-giro, giro), 1.0)
    img = cv2.warpAffine(img, M2, (w, h), borderValue=235)

    # luz despareja: un gradiente suave mas una sombra de lado
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rampa = 1.0 - sombra * (xx / w) * rng.uniform(0.5, 1.0)
    rampa *= 1.0 - 0.18 * ((yy / h - 0.5) ** 2) * 4
    img = np.clip(img.astype(np.float32) * rampa, 0, 255)

    if desenfoque > 1:
        k = desenfoque | 1
        img = cv2.GaussianBlur(img, (k, k), 0)
    img = np.clip(img + rng.gauss(0, 1) * 0 +
                  np.random.normal(0, ruido, img.shape), 0, 255).astype(np.uint8)
    return img


PALABRAS = ["AQUI", "HAY", "UNA", "CARTA", "LUZ", "SEÑAL", "REDES", "MENSAJE",
            "CLAVE", "NOCHE", "FARO", "ONDA", "PULSO", "TRAMA", "BIT"]


def crucigrama(filas, cols, rng):
    """Un tablero mayormente NEGRO con palabras cruzadas, como el del enunciado.

    La proporcion importa y no es un detalle de adorno. La primera tanda ponia
    70% de letras, y la hoja del profesor es al reves: medio tablero en negro y
    en bloques grandes. Ahi es donde el borde entre dos celdas sencillamente no
    existe en el papel, que es el caso que de verdad cuesta.
    """
    g = [[NEGRO] * cols for _ in range(filas)]
    for _ in range(max(3, (filas * cols) // 8)):
        p = rng.choice(PALABRAS)
        if rng.random() < 0.5 and cols >= len(p):
            f, c = rng.randrange(filas), rng.randrange(cols - len(p) + 1)
            for k, ch in enumerate(p):
                g[f][c + k] = ch
        elif filas >= len(p):
            f, c = rng.randrange(filas - len(p) + 1), rng.randrange(cols)
            for k, ch in enumerate(p):
                g[f + k][c] = ch
    for _ in range((filas * cols) // 10):
        g[rng.randrange(filas)][rng.randrange(cols)] = BLANCO
    return g


# (carpeta, como se llena, casos)
# El caso es (filas, cols, perspectiva, giro, desenfoque, ruido, sombra, escala)
NORMAL = [(2, 3), (4, 4), (5, 8), (9, 8), (10, 8), (3, 3), (6, 6), (8, 11)]

DURAS = [(4, 4, 0.10, 10, 5, 10, 0.55, 1.0),
         (4, 4, 0.06,  7, 3,  8, 0.40, 0.45),   # de lejos
         (5, 5, 0.12, 14, 7, 12, 0.60, 1.0),    # muy torcida
         (6, 6, 0.04,  3, 9,  8, 0.30, 1.0),    # muy desenfocada
         (8, 8, 0.08,  8, 5, 14, 0.50, 1.0),
         (10, 8, 0.05,  4, 3,  6, 0.65, 1.0)]   # sombra fuerte

# Los tamaños que nombra el enunciado; el tope son 80 celdas.
TAMAÑOS = [(4, 20), (8, 10), (9, 8), (6, 6), (20, 4), (5, 16)]


def tanda(carpeta, casos, relleno, rng, semilla):
    salida = Path(carpeta)
    salida.mkdir(parents=True, exist_ok=True)
    np.random.seed(semilla)
    fichas = []
    for i, caso in enumerate(casos):
        filas, cols = caso[0], caso[1]
        extra = caso[2:] if len(caso) > 2 else ()
        pers, giro, des, rui, som, escf = (
            extra if extra else (0.05, 3.0, 3, 6, 0.35, 1.0))
        grid = relleno(filas, cols, rng)
        fuente = FUENTES_HOJA[i % len(FUENTES_HOJA)]
        foto = fotografiar(dibujar_hoja(grid, fuente), rng, perspectiva=pers,
                           giro=giro, desenfoque=des, ruido=rui, sombra=som)
        if escf != 1.0:
            foto = cv2.resize(foto, None, fx=escf, fy=escf,
                              interpolation=cv2.INTER_AREA)
        nombre = "%dx%d_%d.png" % (filas, cols, i)
        cv2.imwrite(str(salida / nombre), foto)
        fichas.append({"archivo": nombre, "grid": grid,
                       "fuente": Path(fuente).name})
        print("  %-14s %2dx%-3d %-26s %dx%d px" % (nombre, filas, cols,
              Path(fuente).name, foto.shape[1], foto.shape[0]))
    (salida / "verdad.json").write_text(
        json.dumps(fichas, ensure_ascii=False, indent=1))


def main():
    cual = sys.argv[1] if len(sys.argv) > 1 else "todo"
    rng = random.Random(7)
    if cual in ("todo", "normal"):
        print("hojas/ -- mayoria de letras, foto tranquila")
        tanda("hojas", NORMAL, cuadricula_al_azar, rng, 7)
    if cual in ("todo", "duras"):
        print("hojas_duras/ -- giro, sombra y desenfoque fuertes")
        tanda("hojas_duras", DURAS, cuadricula_al_azar, rng, 23)
    if cual in ("todo", "crucigrama"):
        print("hojas_profe/ -- estilo del enunciado, mayoria de negros")
        tanda("hojas_profe", [(7, 7), (8, 8), (9, 9), (6, 9), (10, 8),
                              (5, 5), (11, 10)], crucigrama, rng, 11)
        print("hojas_tam/ -- los tamaños que nombra el enunciado")
        tanda("hojas_tam", TAMAÑOS, crucigrama, rng, 5)


if __name__ == "__main__":
    main()
