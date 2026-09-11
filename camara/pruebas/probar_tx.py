# -*- coding: utf-8 -*-
"""Prueba el transmisor sin Arduino y sin mirar la pantalla.

    python probar_tx.py

Ejercita los fallos que aparecieron usandolo: que PARAR no paraba, que la
cuadricula se ponia a parpadear sola al editar, que el aviso pisaba la
transmision, y que la pantalla iba al doble de velocidad que la placa. Todos
salian de temporizadores de Tk que se quedaban vivos y de mandarle a la placa
las copias de golpe.

La placa se sustituye por una falsa que apunta lo que le mandan, asi que esto
corre en cualquier sitio. Hace falta una pantalla; en un servidor, con
    xvfb-run -a python probar_tx.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tkinter as tk                                          # noqa: E402
import tx_camara as T                                         # noqa: E402


class ArduinoFalso:
    """Se hace pasar por la placa y apunta lo que le mandan."""
    MAX_SIMBOLOS = 512

    def __init__(self):
        self.ordenes = []          # ("emitir"|"cortar"|"velocidad"|"fijar", t)

    def _ap(self, que):
        self.ordenes.append((que, time.time()))

    def velocidad(self, v): self._ap("velocidad")
    def periodo_us(self, us): self._ap("periodo")
    def emitir(self, simbolos): self._ap("emitir")
    def cortar(self): self._ap("cortar")
    def fijar(self, e): self._ap("fijar")
    def apagar(self): self._ap("apagar")
    def cerrar(self): pass

    def cuenta(self, que):
        return sum(1 for q, _ in self.ordenes if q == que)


def esperar(root, segundos):
    """Deja correr el bucle de Tk sin bloquear."""
    fin = time.time() + segundos
    while time.time() < fin:
        root.update()
        time.sleep(0.005)


def jobs_vivos(app):
    return [n for n in ("_job_tic", "_job_aviso")
            if getattr(app, n, None) is not None]


def main():
    fallos = []

    def comprobar(nombre, condicion, detalle=""):
        print("  %-58s %s" % (nombre, "BIEN" if condicion else "FALLA"))
        if not condicion:
            fallos.append("%s %s" % (nombre, detalle))

    root = tk.Tk()
    app = T.TxCamara(root)
    app.arduino = ArduinoFalso()
    app.velocidad = 10.0
    app.copias = 3
    app.nueva_cuadricula(4, 4)
    for f in range(4):
        for c in range(4):
            app.grid[f][c] = "A"
    app._regenerar()
    n_simbolos = len(app.simbolos)
    print("trama de %d simbolos a %.0f sim/s, %d copias  (%.1f s por copia)"
          % (n_simbolos, app.velocidad, app.copias, n_simbolos / app.velocidad))

    # --- 1. PARAR para de verdad -----------------------------------------
    print("\n1. parar() detiene la emision y avisa a la placa")
    app.cambiar_modo()                      # a TRANSMITIR
    app.emitir()
    esperar(root, 0.6)
    i_antes = app.i
    app.parar_y_avisar()
    esperar(root, 0.6)
    comprobar("corriendo queda en False", app.corriendo is False)
    comprobar("no quedan temporizadores vivos", jobs_vivos(app) == [],
              str(jobs_vivos(app)))
    comprobar("el indice ya no avanza", app.i == i_antes,
              "%d -> %d" % (i_antes, app.i))
    comprobar("se le mando cortar a la placa", app.arduino.cuenta("cortar") >= 1)

    # --- 2. una copia a la vez -------------------------------------------
    print("\n2. a la placa se le manda UNA copia a la vez")
    comprobar("solo una copia enviada al arrancar",
              app.arduino.cuenta("emitir") == 1,
              "%d" % app.arduino.cuenta("emitir"))

    # --- 3. arrancar y parar varias veces no acumula cadenas -------------
    print("\n3. arrancar/parar repetido no deja cadenas en paralelo")
    for _ in range(4):
        app.emitir()
        esperar(root, 0.25)
        app.parar()
        esperar(root, 0.1)
    app.emitir()
    esperar(root, 0.5)
    i1 = app.i
    esperar(root, 1.0)
    avanzo = app.i - i1
    esperado = app.velocidad * 1.0
    comprobar("la pantalla avanza al ritmo pedido (no al doble)",
              abs(avanzo - esperado) <= 3,
              "avanzo %d, esperado ~%.0f" % (avanzo, esperado))
    app.parar()
    esperar(root, 0.3)

    # --- 4. editar mientras transmite para la transmision ----------------
    print("\n4. editar mientras transmite no la reinicia: la para")
    app.emitir()
    esperar(root, 0.4)
    app._regenerar()                        # lo que hace al escribir una celda
    esperar(root, 0.5)
    i_tras = app.i
    esperar(root, 0.5)
    comprobar("queda parado despues de editar", app.corriendo is False)
    comprobar("no vuelve a parpadear solo", app.i == i_tras,
              "%d -> %d" % (i_tras, app.i))
    comprobar("sin temporizadores vivos", jobs_vivos(app) == [])

    # --- 5. el aviso no se solapa ni pisa la transmision -----------------
    print("\n5. el aviso no deja parpadeo colgado")
    app.avisar()
    esperar(root, 0.2)
    app.avisar()                            # dos veces seguidas, a proposito
    esperar(root, 0.2)
    app.emitir()                            # y a transmitir enseguida
    esperar(root, 0.5)
    comprobar("al transmitir no queda aviso pendiente",
              getattr(app, "_job_aviso", None) is None)
    comprobar("la luz fija no pisa la transmision", app.luz_fija is None)
    app.parar()
    esperar(root, 0.3)

    # --- 6. pantalla y placa van juntas ----------------------------------
    print("\n6. la pantalla sigue al reloj, no acumula retraso")
    app.arduino.ordenes.clear()
    app.emitir()
    t0 = time.time()
    esperar(root, 2.0)
    transcurrido = time.time() - t0
    esperado = transcurrido * app.velocidad
    visto = app.copia_actual * n_simbolos + app.i
    comprobar("el simbolo mostrado cuadra con el reloj",
              abs(visto - esperado) <= 4,
              "visto %d, reloj dice %.0f" % (visto, esperado))
    app.parar()
    esperar(root, 0.3)

    # --- 7. las copias se van mandando segun avanza ----------------------
    print("\n7. las copias se mandan segun avanza, no todas de golpe")
    app.arduino.ordenes.clear()
    app.copias = 3
    app.emitir()
    esperar(root, n_simbolos / app.velocidad * 1.2)
    enviadas = app.arduino.cuenta("emitir")
    comprobar("a la segunda copia van 2 enviadas, no 3",
              enviadas == 2, "%d" % enviadas)
    app.parar()

    root.destroy()
    print("\n" + "=" * 64)
    if fallos:
        print("FALLAN %d:" % len(fallos))
        for f in fallos:
            print("   -", f)
        return 1
    print("todo bien")
    return 0


if __name__ == "__main__":
    sys.exit(main())
