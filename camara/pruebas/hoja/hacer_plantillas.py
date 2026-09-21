# -*- coding: utf-8 -*-
"""Genera plantillas.npz: cada letra en varias fuentes, ya normalizada.

Se corre UNA VEZ y el resultado se guarda al lado del lector. Necesita PIL,
pero el lector no: el lector solo abre el .npz.

Las fuentes de aqui NO son las de las hojas de prueba.
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# El lector vive en camara/, dos carpetas mas arriba, y plantillas.npz va a su
# lado: lo carga el, no este script.
CAMARA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.abspath(CAMARA))
from leer_hoja import ALFABETO, normalizar, LADO_PLANTILLA

FUENTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
] + ["/mnt/skills/examples/canvas-design/canvas-fonts/" + f for f in (
    "IBMPlexSerif-Regular.ttf", "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Bold.ttf", "JetBrainsMono-Regular.ttf",
    "InstrumentSans-Regular.ttf", "InstrumentSans-Bold.ttf",
    "Lora-Regular.ttf", "CrimsonPro-Regular.ttf",
    "LibreBaskerville-Regular.ttf", "BricolageGrotesque-Regular.ttf",
    "GeistMono-Regular.ttf", "DMMono-Regular.ttf",
)]

def render(letra, ruta, px=120):
    img = Image.new("L", (px * 2, px * 2), 255)
    d = ImageDraw.Draw(img)
    t = ImageFont.truetype(ruta, px)
    caja = d.textbbox((0, 0), letra, font=t)
    d.text((px - (caja[2] - caja[0]) / 2 - caja[0],
            px - (caja[3] - caja[1]) / 2 - caja[1]), letra, font=t, fill=0)
    return 255 - np.array(img)          # tinta en blanco

def tiene_glifo(ruta, letra, px=120):
    """Si la fuente no trae la letra dibuja un cuadrito, y ese cuadrito se
    guardaria como si fuera la letra. La Ñ es la que falta a menudo."""
    falta = render("\ue000", ruta, px)          # seguro que no existe
    return float(np.abs(render(letra, ruta, px) - falta).mean()) > 1.0


def main():
    pilas, etiquetas = [], []
    saltadas = 0
    for i, letra in enumerate(ALFABETO):
        for ruta in FUENTES:
            try:
                if not tiene_glifo(ruta, letra):
                    saltadas += 1
                    continue
                v = normalizar(render(letra, ruta))
            except Exception:
                saltadas += 1
                continue
            if v is not None:
                pilas.append(v); etiquetas.append(i)
    np.savez_compressed(os.path.join(os.path.abspath(CAMARA), "plantillas.npz"),
                        pilas=np.array(pilas, dtype=np.float32),
                        etiquetas=np.array(etiquetas, dtype=np.int16),
                        alfabeto=np.array(list(ALFABETO)))
    print("%d plantillas de %d letras en %d fuentes, %dx%d  (%d saltadas: "
          "la fuente no traia la letra)"
          % (len(pilas), len(ALFABETO), len(FUENTES),
             LADO_PLANTILLA, LADO_PLANTILLA, saltadas))

if __name__ == "__main__":
    main()
