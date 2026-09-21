# -*- coding: utf-8 -*-
"""Saca de las fotos del banco el trocito de cada celda CON LETRA, ya
normalizado, para poder probar clasificadores sin volver a hacer el PDI.

    python sacar_celdas.py        ->  celdas.npz

Lo que guarda es EXACTAMENTE el vector que el lector le pasa al comparador de
plantillas: se hace enganchando leer_celda por dentro, no copiando su codigo,
para que no puedan separarse. Asi lo que se mida aqui es lo que pasaria de
verdad si se cambiara el comparador y nada mas.

De cada celda se guarda ademas de que HOJA viene. Hace falta: las 27 fotos son
de 8 hojas, y la misma hoja sale en varias. Si se entrena o se elige modelo
mirando celdas de una hoja y luego se prueba en otra foto de ESA MISMA hoja, el
resultado esta inflado, porque son las mismas letras impresas, con la misma
tinta y el mismo grano de papel. Todo lo que se mide aqui se separa por hoja.
"""
import os
import sys

import numpy as np
import cv2

AQUI = os.path.dirname(os.path.abspath(__file__))
BANCO = os.path.abspath(os.path.join(AQUI, ".."))
sys.path.insert(0, BANCO)                                  # probar_fotos
sys.path.insert(0, os.path.abspath(os.path.join(BANCO, "..", "..")))   # camara/, donde vive leer_hoja

import leer_hoja as LH
import probar_fotos as PF


def sacar(verbose=True):
    """Devuelve (vectores, letras, hojas, fotos) de las celdas con letra."""
    P = LH.Plantillas()
    original = LH.leer_celda
    visto = {}
    descartadas = []

    def espia(binaria, x0, x1, y0, y1, plantillas, alta=None, k=None):
        salida = original(binaria, x0, x1, y0, y1, plantillas, alta, k)
        # Solo la PRIMERA vez que se mira cada celda: la segunda es la relectura
        # con el umbral permisivo de la comprobacion de estabilidad, que no es
        # lo que el comparador ve de verdad.
        clave = (int(x0), int(y0))
        if clave in visto:
            return salida
        # Y solo si el lector la mando DE VERDAD al comparador de letras. Si
        # por la fraccion de tinta ya decidio que era recuadro negro o casilla
        # vacia, el comparador no la ve nunca, asi que meterla aqui seria
        # medir al clasificador por un fallo que no es suyo: la primera version
        # de esto colaba 19 celdas completamente negras entre las "imposibles".
        # Esas son un problema de umbral, y se cuentan aparte.
        if salida[0] in (LH.NEGRO, LH.BLANCO):
            descartadas.append(1)
            return salida
        m = LH.MARGEN_CELDA
        dx, dy = (x1 - x0) * m, (y1 - y0) * m
        b = binaria[int(y0 + dy):int(y1 - dy), int(x0 + dx):int(x1 - dx)]
        if alta is not None:
            kx, ky = k
            ba = alta[int((y0 + dy) * ky):int((y1 - dy) * ky),
                      int((x0 + dx) * kx):int((x1 - dx) * kx)]
            if ba.size >= b.size:
                b = ba
        if b.size >= 16:
            v = LH.normalizar(b.astype(np.float32))
            if v is not None:
                visto[clave] = v
        return salida

    # leer_hoja_girando prueba hasta OCHO maneras de mirar la foto, y cada una
    # llama a leer_celda con sus propias coordenadas. Si se guardara la primera
    # que pasa por cada coordenada, lo que quedaria seria una mezcla de vueltas
    # distintas: salian letras del REVES (una A boca abajo, una U puesta como
    # ∩) apuntadas como si el clasificador las hubiera fallado. Se vacia el
    # cuaderno al EMPEZAR cada pasada, asi que al final solo queda la ultima,
    # que es la que produjo la matriz que se devuelve.
    original_hoja = LH.leer_hoja

    def espia_hoja(*a, **k):
        visto.clear()
        return original_hoja(*a, **k)

    V, L, H, F = [], [], [], []
    total_desc = [0]
    for nombre, clave in PF.CASOS:
        verdad = PF.H[clave]
        im = cv2.imread(os.path.join(PF.FOTOS, nombre))
        visto.clear()
        del descartadas[:]
        LH.leer_celda = espia
        LH.leer_hoja = espia_hoja
        try:
            grid, nota, conf, dbg = LH.leer_hoja_girando(im, P, devolver_debug=True)
        finally:
            LH.leer_celda = original
            LH.leer_hoja = original_hoja
        derecha, cajas = dbg if dbg else (None, None)
        if grid is None or (len(grid), len(grid[0])) != (len(verdad), len(verdad[0])):
            if verbose:
                print("   %-36s se salta (la forma no cuadra)" % nombre)
            continue
        n = 0
        for (f, c), (x0, y0, x1, y1) in cajas.items():
            if f >= len(verdad) or c >= len(verdad[0]):
                continue
            letra = verdad[f][c]
            if letra in (LH.NEGRO, LH.BLANCO):
                continue                      # solo interesan las LETRAS
            v = visto.get((int(x0), int(y0)))
            if v is None:
                continue                      # el lector no la vio como letra
            V.append(v); L.append(letra); H.append(clave); F.append(nombre)
            n += 1
        if verbose:
            print("   %-36s %3d letras  (%s)" % (nombre, n, clave))
        total_desc[0] += len(descartadas)
    if verbose:
        print()
        print("   (%d celdas se quedaron fuera: el lector las dio por negras o"
              " vacias\n    por la fraccion de tinta, sin llegar al comparador"
              " de letras)" % total_desc[0])
    return (np.array(V, np.float32), np.array(L), np.array(H), np.array(F))


if __name__ == "__main__":
    V, L, H, F = sacar()
    np.savez_compressed(os.path.join(AQUI, "celdas.npz"),
                        vectores=V, letras=L, hojas=H, fotos=F)
    print()
    print("%d celdas con letra, de %d hojas y %d fotos"
          % (len(V), len(set(H.tolist())), len(set(F.tolist()))))
    for h in sorted(set(H.tolist())):
        print("   %-9s %3d" % (h, int((H == h).sum())))
