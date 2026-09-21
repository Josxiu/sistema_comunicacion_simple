# -*- coding: utf-8 -*-
"""Compara los clasificadores contra las plantillas, EN LAS MISMAS CELDAS.

    python sacar_celdas.py      (una vez: saca las celdas de las 27 fotos)
    python hacer_datos.py 40    (una vez: fabrica las letras estropeadas)
    python probar_modelos.py

Se mide solo el CLASIFICADOR DE LETRA. Todo el PDI -marco, homografia, contar
celdas- se queda como esta: las celdas que entran aqui son las que el lector ya
encontro, y la pregunta es solo si algo acierta mas que las plantillas al decir
QUE letra es.

DOS COSAS QUE HACEN QUE EL NUMERO SIGNIFIQUE ALGO:

1. Se separa por HOJA, no por foto. Las 27 fotos son de 8 hojas y la misma hoja
   sale hasta en 4 fotos; son las mismas letras impresas, con la misma tinta y
   el mismo grano. Elegir modelo mirando una foto y medirlo en otra de la misma
   hoja es hacerse trampas. Se deja una hoja fuera, se escoge con las otras
   siete, y se mide en la que se dejo fuera. Ocho veces, una por hoja.

2. Se comparan A IGUALDAD DE CELDAS MARCADAS. Cada modelo tiene su confianza y
   en su propia escala, asi que un umbral fijo no compara nada. Lo que se hace
   es marcar en todos las MISMAS N celdas -las de menor confianza, con N el que
   marcan hoy las plantillas- y contar cuantos errores se cuelan sin marcar.
   Eso es lo que de verdad importa: los errores que NO se ven.
"""
import os
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
# camara/ esta tres carpetas mas arriba: aprendizaje -> hoja -> pruebas -> camara
sys.path.insert(0, os.path.abspath(os.path.join(AQUI, "..", "..", "..")))
import leer_hoja as LH
import modelos as M


def cargar():
    c = np.load(os.path.join(AQUI, "celdas.npz"), allow_pickle=False)
    d = np.load(os.path.join(AQUI, "datos.npz"), allow_pickle=False)
    alfabeto = LH.ALFABETO
    y = np.array([alfabeto.index(l) for l in c["letras"].tolist()], np.int16)
    return (c["vectores"], y, c["hojas"], d["vectores"], d["etiquetas"])


class Plantillas(object):
    """El lector de hoy, envuelto para que se le pueda preguntar igual."""
    nombre = "plantillas (hoy)"

    def __init__(self):
        p = LH.Plantillas()
        self.m = M.VecinoMasCercano(p.pilas, p.etiquetas.astype(np.int64))
        self.m.clases = len(LH.ALFABETO)

    def predecir(self, X):
        return self.m.predecir(X)


def construye(Vtr, ytr):
    """Los modelos a comparar, todos entrenados con lo mismo."""
    return [
        Plantillas(),
        M.VecinoMasCercano(Vtr, ytr, k=1),
        M.VecinoMasCercano(Vtr, ytr, k=5),
        M.Centroide(Vtr, ytr),
        M.Softmax(Vtr, ytr),
        M.RedChica(Vtr, ytr),
    ]


def cuela(acierta, conf, n_marcar):
    """Errores que se cuelan si se marcan las n_marcar celdas menos seguras."""
    if n_marcar <= 0:
        return int((~acierta).sum())
    orden = np.argsort(conf)            # de menos a mas seguro
    marcada = np.zeros(len(conf), bool)
    marcada[orden[:n_marcar]] = True
    return int((~acierta & ~marcada).sum())


def main():
    X, y, hojas, Vtr, ytr = cargar()
    print("celdas con letra: %d, de %d hojas" % (len(X), len(set(hojas.tolist()))))
    print("entrenamiento: %d letras estropeadas (sinteticas, ninguna hoja real)"
          % len(Vtr))
    print()

    modelos = construye(Vtr, ytr)
    nombres = [m.nombre for m in modelos]

    # --- 1. todas las celdas de golpe (optimista: sirve para orientarse) ----
    print("TODAS LAS CELDAS (sin separar; solo para orientarse)")
    print("   %-18s  aciertos      errores que se cuelan marcando lo mismo" % "modelo")
    base_conf = None
    n_marcar = None
    for m in modelos:
        pred, conf = m.predecir(X)
        ac = (pred == y)
        if base_conf is None:
            base_conf = conf
            n_marcar = int((conf < LH.DUDA).sum())
        print("   %-18s  %4d/%4d (%5.1f%%)   %3d   (marcando %d)"
              % (m.nombre, ac.sum(), len(y), 100.0 * ac.mean(),
                 cuela(ac, conf, n_marcar), n_marcar))
    print()

    # --- 2. dejando una hoja fuera, que es el numero honesto ---------------
    print("DEJANDO UNA HOJA FUERA (el numero que vale)")
    print("   %-18s %s" % ("modelo", "  ".join("%8s" % h[:8]
                                               for h in sorted(set(hojas.tolist())))))
    tot = {n: [0, 0, 0] for n in nombres}     # aciertos, celdas, colados
    filas = {n: [] for n in nombres}
    for h in sorted(set(hojas.tolist())):
        fuera = (hojas == h)
        # el numero de celdas a marcar se fija con las OTRAS hojas
        pb, cb = modelos[0].predecir(X[fuera])
        n_marcar = int((cb < LH.DUDA).sum())
        for m in modelos:
            pred, conf = m.predecir(X[fuera])
            ac = (pred == y[fuera])
            c = cuela(ac, conf, n_marcar)
            tot[m.nombre][0] += int(ac.sum())
            tot[m.nombre][1] += int(fuera.sum())
            tot[m.nombre][2] += c
            filas[m.nombre].append(100.0 * ac.mean())
    for n in nombres:
        print("   %-18s %s" % (n, "  ".join("%7.1f%%" % v for v in filas[n])))
    print()
    print("   %-18s  aciertos      se cuelan" % "TOTAL")
    for n in nombres:
        a, t, c = tot[n]
        print("   %-18s  %4d/%4d (%5.1f%%)   %3d" % (n, a, t, 100.0 * a / t, c))


if __name__ == "__main__":
    main()
