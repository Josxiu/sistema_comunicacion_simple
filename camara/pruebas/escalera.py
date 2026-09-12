# -*- coding: utf-8 -*-
"""Degrada un video que SI descifra y mide hasta donde aguanta el receptor.

    python escalera.py "toma_buena.mp4"

Baja los cuadros por segundo y le mete ruido, en escalones, y prueba cada
escalon con la decision dura y con la blanda (DECISION_BLANDA). Sirve para dos
cosas: saber cuanto margen tiene una grabacion que funciona, y comprobar si un
cambio en el decodificador gana algo de verdad o solo lo parece.

Los videos degradados se escriben en escalera/ al lado de este archivo.
"""
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

CARPETA = Path(__file__).resolve().parent
sys.path.insert(0, str(CARPETA.parent))
import rx_camara as R                                         # noqa: E402

FUENTE = sys.argv[1] if len(sys.argv) > 1 else "toma.mp4"

def decimar(salida, cada):
    """Se queda con 1 de cada 'cada' cuadros: baja los fps efectivos."""
    if os.path.exists(salida): return
    cap = cv2.VideoCapture(FUENTE)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    esc = cv2.VideoWriter(salida, cv2.VideoWriter_fourcc(*"mp4v"), fps/cada, (w,h))
    i=0
    while True:
        ok,f = cap.read()
        if not ok: break
        if i % cada == 0: esc.write(f)
        i+=1
    cap.release(); esc.release()

def con_ruido(salida, sigma):
    if os.path.exists(salida): return
    rng = np.random.default_rng(3)
    cap = cv2.VideoCapture(FUENTE)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    esc = cv2.VideoWriter(salida, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w,h))
    while True:
        ok,f = cap.read()
        if not ok: break
        esc.write(np.clip(f.astype(np.float32)+rng.normal(0,sigma,f.shape),0,255).astype(np.uint8))
    cap.release(); esc.release()

def probar(v, blanda):
    R.DECISION_BLANDA = blanda
    t0=time.time()
    try:
        grid, nota, _, _ = R.procesar_video(v, verboso=False)
    except Exception as e:
        return False, time.time()-t0, str(e)[:20]
    ok = bool(grid) and "CRC valido" in str(nota)
    return ok, time.time()-t0, ""

def main():
    casos = []
    for cada in (1,2,3,4):
        v = "escalera/dec%d.mp4" % cada
        decimar(v, cada); casos.append(("%.1f fps (%.1f cuadros/simbolo)" % (59.94/cada, 8.56/cada), v))
    for s in (6,10,14,18):
        v = "escalera/ruido%d.mp4" % s
        con_ruido(v, s); casos.append(("ruido sigma %d" % s, v))

    print("%-34s %-16s %-16s" % ("caso","dura","blanda"))
    print("-"*70)
    gd=gb=0
    for nombre, v in casos:
        od, td, _ = probar(v, False)
        ob, tb, _ = probar(v, True)
        gd += od; gb += ob
        print("%-34s %-4s %5.0f s     %-4s %5.0f s   %s"
              % (nombre, "CRC" if od else "no", td, "CRC" if ob else "no", tb,
                 "  <- la blanda rescata" if ob and not od else ""))
    print("-"*70)
    print("dura %d/%d   blanda %d/%d" % (gd,len(casos),gb,len(casos)))

if __name__ == "__main__":
    if not os.path.exists(FUENTE):
        print("No encuentro %s.\nUso: python escalera.py \"toma_buena.mp4\"" % FUENTE)
        sys.exit(1)
    os.makedirs("escalera", exist_ok=True)
    main()
