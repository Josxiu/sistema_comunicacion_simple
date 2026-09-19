# -*- coding: utf-8 -*-
"""Arma un PDF con matrices para IMPRIMIR y probar el lector en papel.

    python hacer_pdf.py                 -> matrices_para_imprimir.pdf

Al imprimirlo hay que decirle "tamaño real" o "100%", NO "ajustar a la
pagina": el tamaño de celda en milimetros es justo lo que se esta midiendo.

Las matrices NO llenan la hoja a proposito -el profesor tampoco lo hara- y van
en varios tamaños de celda para encontrar a partir de que tamaño el telefono
deja de leerlas. La ultima lleva un borde grueso alrededor, que es un caso que
se sabe que falla y conviene tener medido.

La respuesta correcta de cada una va en la ULTIMA pagina, no al lado, para no
meterle texto extra a la foto.
"""
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hacer_hojas import crucigrama, NEGRO, BLANCO                # noqa: E402

PPP = 300                                   # puntos por pulgada al imprimir
HOJA_MM = (216.0, 279.0)                    # carta; en A4 tambien cabe
MARGEN_MM = 16.0
FUENTE = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FUENTE_PIE = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def mm(v):
    return int(round(v * PPP / 25.4))


# (etiqueta, filas, columnas, mm de celda, marco decorativo)
MATRICES = [
    ("A", 7, 7, 18.0, False),
    ("B", 7, 7, 12.0, False),
    ("C", 9, 8, 15.0, False),
    ("D", 6, 6, 8.0, False),
    ("E", 4, 20, 9.0, False),
    ("F", 8, 10, 12.0, True),
]
PAGINAS = [["A", "B"], ["C", "D"], ["E", "F"]]


def dibujar(grid, lado_mm, marco=False):
    """Una matriz sola, del tamaño exacto que tendra en el papel."""
    filas, cols = len(grid), len(grid[0])
    lado = mm(lado_mm)
    raya = max(2, mm(0.45))
    orla = mm(4.0) if marco else 0
    W, H = cols * lado + 2 * orla, filas * lado + 2 * orla
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    if marco:
        d.rectangle([0, 0, W - 1, H - 1], fill=40)
        d.rectangle([orla, orla, W - orla - 1, H - orla - 1], fill=255)
    tipo = ImageFont.truetype(FUENTE, int(lado * 0.62))
    for f in range(filas):
        for c in range(cols):
            x0, y0 = orla + c * lado, orla + f * lado
            x1, y1 = x0 + lado, y0 + lado
            v = grid[f][c]
            if v == NEGRO:
                d.rectangle([x0, y0, x1, y1], fill=0)
            elif v != BLANCO:
                caja = d.textbbox((0, 0), v, font=tipo)
                d.text((x0 + (lado - (caja[2] - caja[0])) / 2 - caja[0],
                        y0 + (lado - (caja[3] - caja[1])) / 2 - caja[1]),
                       v, font=tipo, fill=0)
            d.rectangle([x0, y0, x1, y1], outline=0, width=raya)
    return img


def pagina_vacia():
    return Image.new("L", (mm(HOJA_MM[0]), mm(HOJA_MM[1])), 255)


def main():
    rng = random.Random(2026)
    hechas = {}
    for etq, filas, cols, lado_mm, marco in MATRICES:
        grid = crucigrama(filas, cols, rng)
        hechas[etq] = (grid, dibujar(grid, lado_mm, marco), filas, cols, lado_mm)

    paginas = []
    for cuales in PAGINAS:
        hoja = pagina_vacia()
        d = ImageDraw.Draw(hoja)
        pie = ImageFont.truetype(FUENTE_PIE, mm(3.5))
        y = mm(MARGEN_MM)
        libre = mm(HOJA_MM[1]) - 2 * mm(MARGEN_MM)
        alto_total = sum(hechas[e][1].height for e in cuales)
        hueco = max(mm(10.0), (libre - alto_total - len(cuales) * mm(8)) //
                    max(1, len(cuales)))
        for etq in cuales:
            grid, img, filas, cols, lado_mm = hechas[etq]
            x = (hoja.width - img.width) // 2
            hoja.paste(img, (x, y))
            y += img.height + mm(3.5)
            texto = "%s   %d x %d   celda %.0f mm" % (etq, filas, cols, lado_mm)
            d.text((x, y), texto, font=pie, fill=110)
            y += mm(5) + hueco
        paginas.append(hoja)

    # ultima pagina: las respuestas
    clave = pagina_vacia()
    d = ImageDraw.Draw(clave)
    titulo = ImageFont.truetype(FUENTE_PIE, mm(5))
    mono = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", mm(3.2))
    y = mm(MARGEN_MM)
    d.text((mm(MARGEN_MM), y), "Respuestas  (# negro, _ blanco)",
           font=titulo, fill=0)
    y += mm(10)
    for etq, _, _, _, _ in MATRICES:
        grid = hechas[etq][0]
        d.text((mm(MARGEN_MM), y), "%s  %d x %d" % (etq, len(grid), len(grid[0])),
               font=titulo, fill=0)
        y += mm(6)
        for fila in grid:
            d.text((mm(MARGEN_MM + 4), y), " ".join(fila), font=mono, fill=60)
            y += mm(4.2)
        y += mm(5)
    paginas.append(clave)

    salida = Path(__file__).with_name("matrices_para_imprimir.pdf")
    paginas[0].convert("RGB").save(
        salida, save_all=True, resolution=PPP,
        append_images=[p.convert("RGB") for p in paginas[1:]])
    print("%s  (%d paginas)" % (salida.name, len(paginas)))
    for etq, filas, cols, lado_mm, marco in MATRICES:
        g = hechas[etq][0]
        negras = sum(v == NEGRO for f in g for v in f)
        print("  %s  %2dx%-2d  celda %4.0f mm  ->  %3.0f x %3.0f mm   %2d%% negras%s"
              % (etq, filas, cols, lado_mm, cols * lado_mm, filas * lado_mm,
                 100 * negras // (filas * cols), "   con marco" if marco else ""))


if __name__ == "__main__":
    main()
