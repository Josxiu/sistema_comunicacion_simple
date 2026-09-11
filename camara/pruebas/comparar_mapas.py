# -*- coding: utf-8 -*-
"""Compara las dos formas de medir el parpadeo, sobre los mismos videos.

    python comparar_mapas.py [carpeta con videos]

Para cada video mide, con "fft" y con "iir":

    donde salen los picos      si los dos coinciden, el mapa sirve igual
    cuanto tarda el mapa       por tramo de 90 cuadros
    si descifra                que es lo unico que decide de verdad

Sin esto no hay forma de saber si un cambio en el mapa mejora o solo mueve el
problema de sitio.
"""

import sys
import time
from pathlib import Path

import cv2

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))
import rx_camara as R                                        # noqa: E402


def un_tramo(ruta, salto=0.35, largo=90):
    """Un bloque de cuadros de la mitad del video, ya reducido y en gris."""
    cap, _ = R.abrir_video(ruta)
    if not cap.isOpened():
        return [], 30.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * salto))
    bloque = []
    for _ in range(largo):
        ok, f = cap.read()
        if not ok:
            break
        g, _, _ = R.reducir_para_buscar(f)
        bloque.append(g)
    cap.release()
    return bloque, fps


def comparar(ruta):
    bloque, fps = un_tramo(ruta)
    if len(bloque) < 20:
        print("%-28s (no se pudo leer)" % Path(ruta).name)
        return
    fila = {"video": Path(ruta).name}
    for metodo in ("fft", "iir"):
        t0 = time.perf_counter()
        mapa = R.mapa_de_parpadeo(bloque, fps, metodo=metodo)
        ms = (time.perf_counter() - t0) * 1000
        picos = [(x, y) for x, y, _ in R.picos_de_luz(mapa)[:2]]
        fila[metodo] = (ms, picos)

    (ms_f, pf), (ms_i, pi) = fila["fft"], fila["iir"]
    cerca = (pf and pi and
             max(abs(pf[0][0] - pi[0][0]), abs(pf[0][1] - pi[0][1])) <= 6)
    print("%-28s fft %6.0f ms %-20s | iir %6.0f ms %-20s | %s"
          % (fila["video"], ms_f, str(pf[:1]), ms_i, str(pi[:1]),
             "mismo pico" if cerca else "PICOS DISTINTOS"))


def descifrar_con(ruta, metodo, esperado=None):
    antes = R.METODO_MAPA
    R.METODO_MAPA = metodo
    try:
        t0 = time.time()
        grid, nota, _, _ = R.procesar_video(str(ruta), verboso=False)
        dt = time.time() - t0
    finally:
        R.METODO_MAPA = antes
    ok = "CRC valido" in str(nota)
    if esperado is not None and grid is not None:
        ok = ok and grid == esperado
    return ok, dt, str(nota).split("\n")[0][:40]


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else CARPETA
    videos = sorted(f for f in base.rglob("*") if f.suffix.lower() in R.EXT_VIDEO)
    if not videos:
        print("No hay videos en %s" % base)
        return 1

    print("MAPA DE PARPADEO, un tramo de 90 cuadros\n")
    for v in videos:
        comparar(str(v))

    print("\nDESCIFRADO COMPLETO\n")
    print("%-28s %-18s %-18s" % ("video", "fft", "iir"))
    print("-" * 68)
    iguales = 0
    for v in videos:
        okf, tf, _ = descifrar_con(v, "fft")
        oki, ti, _ = descifrar_con(v, "iir")
        iguales += (okf == oki)
        print("%-28s %-4s %6.0f s      %-4s %6.0f s      %s"
              % (v.name, "CRC" if okf else "no", tf,
                 "CRC" if oki else "no", ti,
                 "" if okf == oki else "<- NO COINCIDEN"))
    print("-" * 68)
    print("coinciden en %d de %d" % (iguales, len(videos)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
