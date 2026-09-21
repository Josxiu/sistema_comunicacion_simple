# -*- coding: utf-8 -*-
"""Cuanto acierta el lector sobre las hojas generadas."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # camara/
from leer_hoja import leer_hoja, Plantillas

carpeta = Path(sys.argv[1] if len(sys.argv) > 1 else "hojas")
verdad = json.loads((carpeta / "verdad.json").read_text())
P = Plantillas()

tot_c = tot_ok = hojas_ok = 0
fallos = {}
for caso in verdad:
    esperado = caso["grid"]
    grid, nota, conf = leer_hoja(carpeta / caso["archivo"], P)
    n = len(esperado) * len(esperado[0])
    if grid is None:
        print("%-20s  NO LEE   (%s)" % (caso["archivo"], nota)); tot_c += n; continue
    tam_ok = (len(grid) == len(esperado) and len(grid[0]) == len(esperado[0]))
    if not tam_ok:
        print("%-20s  TAMAÑO MAL: leyo %s, era %dx%d"
              % (caso["archivo"], nota, len(esperado), len(esperado[0])))
        tot_c += n; continue
    ok = sum(a == b for fe, fl in zip(esperado, grid) for a, b in zip(fe, fl))
    tot_c += n; tot_ok += ok
    hojas_ok += (ok == n)
    for fe, fl in zip(esperado, grid):
        for a, b in zip(fe, fl):
            if a != b:
                fallos[(a, b)] = fallos.get((a, b), 0) + 1
    print("%-20s  %s  %3d/%-3d celdas  (%s)"
          % (caso["archivo"], "OK   " if ok == n else "FALLA",
             ok, n, caso["fuente"]))

print("\nceldas  %d/%d = %.1f%%" % (tot_ok, tot_c, 100.0*tot_ok/max(1,tot_c)))
print("hojas   %d/%d perfectas" % (hojas_ok, len(verdad)))
if fallos:
    print("\nconfusiones (esperado -> leido):")
    for (a, b), k in sorted(fallos.items(), key=lambda x: -x[1])[:15]:
        print("   %s -> %s   x%d" % (a, b, k))
