# -*- coding: utf-8 -*-
"""Entrena la red chica con todas las letras estropeadas y la guarda.

    python hacer_datos.py 40     (antes: fabrica datos.npz)
    python entrenar.py           ->  modelo.npz

modelo.npz son cuatro matrices y pesa medio mega. Se carga con numpy y ya:
no hace falta instalar nada, ni tener internet, que es la condicion del equipo
de la prueba.

NO esta enchufado al lector. Para probarlo habria que cambiar Plantillas.letra
en leer_hoja.py por esto, y antes de hacer eso conviene leer el README: el
lector de hoy ya no deja pasar ningun error sin marcar, asi que lo que esto
mejora es el margen, no el resultado final.
"""
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, "..", "..", "..")))
sys.path.insert(0, AQUI)
import leer_hoja as LH
import modelos as M


def main(semilla=0):
    d = np.load(os.path.join(AQUI, "datos.npz"), allow_pickle=False)
    V, y = d["vectores"], d["etiquetas"].astype(np.int64)
    print("entrenando con %d letras estropeadas..." % len(V))
    m = M.RedChica(V, y, semilla=semilla)
    ruta = os.path.join(AQUI, "modelo.npz")
    np.savez_compressed(ruta, W1=m.W1, b1=m.b1, W2=m.W2, b2=m.b2,
                        alfabeto=np.array(list(LH.ALFABETO)))
    pred, _ = m.predecir(V)
    print("guardado en %s  (%.1f MB)"
          % (os.path.basename(ruta), os.path.getsize(ruta) / 1048576.0))
    print("acierto sobre lo que ha visto: %.1f%%  (no significa nada, "
          "el numero que vale esta en probar_modelos.py)"
          % (100.0 * (pred == y).mean()))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
