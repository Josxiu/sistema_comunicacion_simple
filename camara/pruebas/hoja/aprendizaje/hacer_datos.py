# -*- coding: utf-8 -*-
"""Fabrica letras de mentira, ESTROPEADAS a proposito, para entrenar con ellas.

    python hacer_datos.py [cuantas_por_letra_y_fuente]   ->  datos.npz

Entrenar con las letras limpias de una fuente no sirve de nada: eso es
exactamente lo que ya hacen las plantillas. Lo que el lector no sabe manejar es
la letra ESTROPEADA, y estropeada de una forma muy concreta que se vio mirando
las fotos que fallan: con la celda pequeña y algo desenfocada, el trazo fino se
queda por encima del corte del umbral y DESAPARECE, y lo que queda es otra
letra perfectamente nitida -la E sin sus barras es una I, la T sin la suya
tambien-. Por eso el margen contra las plantillas no lo nota.

Asi que la degradacion no es ruido por ruido: es la cadena de la foto, en orden.

    1. girar un poco       el papel nunca esta perfectamente derecho
    2. engordar o afinar   segun la impresora y el papel
    3. encoger            a un tamaño de celda de verdad (24 a 70 px). Aqui es
                          donde se pierde el detalle: la hoja de 4x20 deja 29 px
    4. desenfocar         la camara del telefono, el pulso
    5. aclarar el trazo   lo que decide si el trazo pasa o no pasa el corte
    6. ruido              grano del sensor y del papel
    7. umbralizar         y aqui es donde el trazo fino se pierde del todo

Al final se normaliza con la MISMA normalizar() del lector, asi que los vectores
salen comparables con los de las celdas de verdad y con las plantillas.

Las fuentes son las del sistema y NO son las de las hojas impresas, igual que
en hacer_plantillas.py: si fueran las mismas, esto mediria otra cosa.
"""
import os
import sys

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
# camara/ esta tres carpetas mas arriba: aprendizaje -> hoja -> pruebas -> camara
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, "..", "..", "..")))
import leer_hoja as LH

FUENTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
]


def fuentes_que_hay():
    return [f for f in FUENTES if os.path.exists(f)]


def render(letra, ruta, px=120):
    """La letra limpia, tinta en blanco, como en hacer_plantillas.py."""
    img = Image.new("L", (px * 2, px * 2), 255)
    d = ImageDraw.Draw(img)
    t = ImageFont.truetype(ruta, px)
    caja = d.textbbox((0, 0), letra, font=t)
    d.text((px - (caja[2] - caja[0]) / 2 - caja[0],
            px - (caja[3] - caja[1]) / 2 - caja[1]), letra, font=t, fill=0)
    return 255 - np.array(img)


def tiene_glifo(ruta, letra, px=120):
    """La Ñ es la que suele faltar, y sin esto se guardaria el cuadrito."""
    falta = render("", ruta, px)
    return float(np.abs(render(letra, ruta, px) - falta).mean()) > 1.0


def estropear(limpia, rng):
    """La cadena de la foto, en orden. Devuelve una mascara binaria."""
    img = limpia.astype(np.float32)

    # 1. girar un poco
    ang = rng.uniform(-3.0, 3.0)
    H, W = img.shape
    M = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), ang, 1.0)
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)

    # 2. engordar o afinar el trazo
    g = rng.integers(-1, 3)
    if g > 0:
        img = cv2.dilate(img, np.ones((2 * int(g) + 1,) * 2, np.uint8))
    elif g < 0:
        img = cv2.erode(img, np.ones((3, 3), np.uint8))

    # 3. encoger a un tamaño de celda de verdad (aqui se pierde el detalle)
    lado = int(rng.integers(24, 71))
    img = cv2.resize(img, (lado, lado), interpolation=cv2.INTER_AREA)

    # 4. desenfocar
    s = float(rng.uniform(0.3, 1.6))
    k = max(3, int(s * 4) | 1)
    img = cv2.GaussianBlur(img, (k, k), s)

    # 5. aclarar el trazo: cuanta tinta llega de verdad
    img *= float(rng.uniform(0.45, 1.05))

    # 6. ruido
    img += rng.normal(0.0, float(rng.uniform(2.0, 14.0)), img.shape)

    # 7. umbralizar, que es donde el trazo fino se pierde
    return ((img > 128.0).astype(np.uint8) * 255)


def main(por_combinacion=12, semilla=0):
    rng = np.random.default_rng(semilla)
    fuentes = fuentes_que_hay()
    if not fuentes:
        print("No hay ninguna de las fuentes esperadas en este equipo.")
        return
    V, L = [], []
    saltadas = 0
    for i, letra in enumerate(LH.ALFABETO):
        for ruta in fuentes:
            try:
                if not tiene_glifo(ruta, letra):
                    saltadas += 1
                    continue
                limpia = render(letra, ruta)
            except Exception:
                saltadas += 1
                continue
            for _ in range(por_combinacion):
                v = LH.normalizar(estropear(limpia, rng).astype(np.float32))
                if v is not None:
                    V.append(v); L.append(i)
    V = np.array(V, np.float32); L = np.array(L, np.int16)
    np.savez_compressed(os.path.join(AQUI, "datos.npz"),
                        vectores=V, etiquetas=L,
                        alfabeto=np.array(list(LH.ALFABETO)))
    print("%d ejemplos: %d letras x %d fuentes x %d copias estropeadas"
          % (len(V), len(LH.ALFABETO), len(fuentes), por_combinacion))
    print("(%d saltadas: la fuente no traia la letra)" % saltadas)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
