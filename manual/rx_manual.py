# -*- coding: utf-8 -*-
"""RECEPTOR: la persona mira las luces y pulsa teclas; el programa descifra.

No hay que hacer cuentas ni mirar la tabla. Cada vez que las luces cambian se
pulsa la tecla de lo que se ve:

    1 = solo ROJA    2 = solo VERDE    3 = LAS DOS    0 = NINGUNA

Y la regla del mini parpadeo: si la luz se corta un instante y vuelve IGUAL,
es el mismo simbolo dos veces, o sea que se pulsa la MISMA tecla otra vez. Un
apagon de un tiempo entero si es el separador, y ahi va el 0.

El programa va armando el bloque y marca cada fila como ok, con error o que
falta: eso es exactamente lo que hay que pedir que repitan. Si se pierde un
simbolo, la siguiente oscuridad vuelve a sincronizar y solo se dana una celda.

Equivocarse no arruina lo anterior. Las teclas sueltas o al azar se descartan
solas, y basta con que la fila llegue otra vez entera y bien para que quede
bien: una fila que ya paso su suma de control NO se pisa con una peor. Ademas
RETROCESO deshace el ultimo simbolo y SUPR lo borra todo.

La caja de pegar sirve para practicar sin luces: se pega lo que copia
tx_manual.py. La codificacion esta en codigo_manual.py.
"""

import time
import tkinter as tk

import codigo_manual as M

# --- colores -------------------------------------------------------------
FONDO = "#1e1e1e"
NEGRO = "#111111"
BLANCO = "#ffffff"
FALTA = "#8e2b22"          # celda que aún no llega
DUDA = "#c0392b"           # celda que llegó rota
BORDE = "#666666"
VERDE = "#5fe07a"
AMBAR = "#ffd54f"
AZUL = "#9fd0ff"

# (estado, tecla, rótulo, color del botón)
BOTONES = [
    (M.LUZ_A, "1", "solo ROJA", "#ff3b30"),
    (M.LUZ_B, "2", "solo VERDE", "#34c759"),
    (M.AMBAS, "3", "LAS DOS", "#ffd54f"),
    (M.SEP,   "0", "NINGUNA", "#555555"),
]


class RxManual(object):

    def __init__(self, root):
        self.root = root
        root.title("Rx MANUAL asistido · dos luces · Redes I")
        root.configure(bg=FONDO)

        self.simbolos = []          # todo lo que se ha marcado, en orden
        self.filas = self.cols = None
        self.recibidas = {}         # índice de fila -> {'celdas': [...], 'ok': bool}
        self.parcial = None         # (índice, celdas) de la fila que está llegando
        self.t0 = None

        self._construir()
        self._refrescar()

    # ------------------------------------------------------------ montaje --
    def _construir(self):
        tk.Label(self.root, bg=FONDO, fg=AMBAR, font=("Segoe UI", 12, "bold"),
                 text="Pulsa la tecla del estado que ves CADA VEZ QUE LAS LUCES "
                      "CAMBIAN").pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(self.root, bg=FONDO, fg="#aaaaaa", font=("Segoe UI", 10),
                 text="Si la luz parpadea un instante y vuelve IGUAL, pulsa la "
                      "misma tecla otra vez.  Si se apaga un tiempo entero, "
                      "eso es el separador: pulsa 0."
                 ).pack(anchor="w", padx=10, pady=(0, 4))

        fila = tk.Frame(self.root, bg=FONDO)
        fila.pack(fill="x", padx=10, pady=4)
        for estado, tecla, nombre, color in BOTONES:
            tk.Button(fila, text="%s\n%s" % (tecla, nombre), bg=color,
                      fg="#dddddd" if estado == M.SEP else "#000000",
                      font=("Segoe UI", 13, "bold"), width=12, height=2,
                      command=lambda e=estado: self.marcar(e)).pack(side="left", padx=5)
        tk.Button(fila, text="DESHACER\n(retroceso)", width=12, height=2,
                  command=self.deshacer).pack(side="left", padx=16)
        tk.Button(fila, text="LIMPIAR\n(supr)", width=10, height=2,
                  command=self.limpiar).pack(side="left")

        # --- caja para pegar una secuencia y practicar sin luces ---
        # Es un Text y no un Entry porque lo que copia tx_manual.py son VARIAS
        # líneas (una por unidad); un Entry se las comería todas juntas.
        pegar = tk.Frame(self.root, bg=FONDO)
        pegar.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(pegar, text="pegar\nsecuencia:", bg=FONDO, fg=AZUL,
                 justify="left").pack(side="left")
        self.ent = tk.Text(pegar, height=3, font=("Consolas", 10), bg="#2b2b2b",
                           fg="#ffffff", insertbackground="white", wrap="word")
        self.ent.pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(pegar, text="cargar", width=10,
                  command=self.cargar).pack(side="left")
        tk.Button(pegar, text="reproducir", width=10,
                  command=self.reproducir).pack(side="left", padx=4)

        self.lbl_est = tk.Label(self.root, text="", bg=FONDO, fg=AZUL,
                                font=("Consolas", 11), anchor="w")
        self.lbl_est.pack(fill="x", padx=10, pady=(8, 2))
        self.lbl_ult = tk.Label(self.root, text="", bg=FONDO, fg="#888888",
                                font=("Consolas", 12), anchor="w")
        self.lbl_ult.pack(fill="x", padx=10)

        self.tira = tk.Frame(self.root, bg=FONDO)      # estado de cada fila
        self.tira.pack(fill="x", padx=10, pady=6)
        self.cajas = []

        self.canvas = tk.Canvas(self.root, bg=FONDO, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=6)

        self.lbl_res = tk.Label(self.root, text="", bg=FONDO, fg="#cccccc",
                                font=("Segoe UI", 11))
        self.lbl_res.pack(pady=(0, 8))

        # --- teclado (sin estorbar cuando se escribe en la caja de pegar) ---
        def atajo(accion):
            def _f(ev):
                if ev.widget is not self.ent:
                    accion()
            return _f
        for estado, tecla, _, _ in BOTONES:
            self.root.bind(tecla, atajo(lambda e=estado: self.marcar(e)))
        self.root.bind("<space>", atajo(lambda: self.marcar(M.SEP)))
        self.root.bind("<BackSpace>", atajo(self.deshacer))
        self.root.bind("<Delete>", atajo(self.limpiar))
        self.root.bind("<Configure>", lambda e: self.dibujar())

    # ------------------------------------------------------------ captura --
    def marcar(self, estado):
        if self.t0 is None:
            self.t0 = time.time()
        self.simbolos.append(estado)
        self._refrescar()

    def deshacer(self):
        if self.simbolos:
            self.simbolos.pop()
            self._refrescar()

    def limpiar(self):
        self.simbolos = []
        self.filas = self.cols = None
        self.recibidas = {}
        self.parcial = None
        self.t0 = None
        self._refrescar()

    def _vaciar_caja(self):
        texto = self.ent.get("1.0", "end")
        self.ent.delete("1.0", "end")
        return M.de_texto(texto)

    def cargar(self):
        """Añade de golpe lo que haya en la caja. Se puede ir pegando unidad
        por unidad: primero la cabecera, después cada fila."""
        simbolos = self._vaciar_caja()
        if not simbolos:
            return
        if self.t0 is None:
            self.t0 = time.time()
        self.simbolos.extend(simbolos)
        self._refrescar()

    def reproducir(self, ms=140):
        """Igual, pero de a un símbolo, para ver cómo se va armando la fila."""
        for k, s in enumerate(self._vaciar_caja()):
            self.root.after(k * ms, self.marcar, s)

    # -------------------------------------------------------- decodificar --
    def _refrescar(self):
        """Vuelve a leer TODO lo capturado desde el principio.

        Se rehace entero en vez de ir acumulando porque así 'deshacer' funciona
        solo, y porque son unos pocos cientos de símbolos: no cuesta nada.
        """
        self.recibidas = {}
        self.parcial = None
        self.filas = self.cols = None

        for unidad in M.segmentar(self.simbolos):
            info = M.analizar(unidad)
            if info["tipo"] == "cabecera":
                self.filas, self.cols = info["filas"], info["cols"]
            elif info["tipo"] == "fila":
                if info["completa"]:
                    self._guardar_fila(info)
                    self.parcial = None
                else:
                    self.parcial = (info["indice"], info["celdas"])

        self._texto_estado()
        self._tira_filas()
        self.dibujar()

    def _guardar_fila(self, info):
        """Guarda una fila, pero UNA BUENA NO SE PISA CON UNA MALA.

        La misma fila puede llegar varias veces: porque se pidió repetir, o
        porque unas teclas sueltas se juntaron y parecieron una fila. Sin esta
        regla, una fila que ya estaba bien se perdía en cuanto llegaba encima
        cualquier basura con ese mismo índice.
        """
        nueva = {"celdas": info["celdas"], "ok": bool(info["control_ok"])}
        vieja = self.recibidas.get(info["indice"])
        if vieja is not None and vieja["ok"] and not nueva["ok"]:
            return                       # ya la teníamos bien: se queda
        self.recibidas[info["indice"]] = nueva

    # -------------------------------------------------------------- estado --
    def _texto_estado(self):
        partes = ["símbolos: %d" % len(self.simbolos)]
        if self.filas:
            faltan = [i for i in range(self.filas) if i not in self.recibidas]
            malas = sorted(i for i, d in self.recibidas.items() if not d["ok"])
            partes.append("bloque %dx%d" % (self.filas, self.cols))
            partes.append("filas %d/%d" % (len(self.recibidas), self.filas))
            if faltan:
                partes.append("faltan: " + ", ".join(str(i) for i in faltan))
            if malas:
                partes.append("con error: " + ", ".join(str(i) for i in malas))
        else:
            partes.append("esperando la cabecera...")
        if self.t0:
            partes.append("%.0f s" % (time.time() - self.t0))
        self.lbl_est.config(text="   |   ".join(partes))

        texto = "últimos:  " + M.a_texto(self.simbolos[-16:])
        if self.parcial:
            texto += "     (recibiendo la fila %d: %d celdas)" % (
                self.parcial[0], len(self.parcial[1]))
        self.lbl_ult.config(text=texto)

        if self.filas and len(self.recibidas) == self.filas:
            if all(d["ok"] for d in self.recibidas.values()):
                self.lbl_res.config(text="BLOQUE COMPLETO Y VERIFICADO", fg=VERDE)
            else:
                self.lbl_res.config(fg=AMBAR,
                                    text="Bloque completo, pero hay filas con "
                                         "error: pide que repitan esas filas")
        else:
            self.lbl_res.config(text="")

    def _tira_filas(self):
        for w in self.cajas:
            w.destroy()
        self.cajas = []
        if not self.filas:
            return
        tk.Label(self.tira, text="Filas:", bg=FONDO, fg="white").pack(
            side="left", padx=(0, 6))
        for i in range(self.filas):
            d = self.recibidas.get(i)
            if d is None:
                texto, bg, fg = "%d\nfalta" % i, FALTA, "#ffffff"
            elif d["ok"]:
                texto, bg, fg = "%d\nok" % i, VERDE, "#000000"
            else:
                texto, bg, fg = "%d\nerror" % i, AMBAR, "#000000"
            caja = tk.Label(self.tira, text=texto, bg=bg, fg=fg, width=6,
                            font=("Consolas", 9, "bold"), relief="raised", bd=1)
            caja.pack(side="left", padx=2)
            self.cajas.append(caja)

    # -------------------------------------------------------------- dibujo --
    def dibujar(self):
        c = self.canvas
        if not c.winfo_exists():      # la ventana ya se cerro
            return
        c.delete("all")
        W = max(c.winfo_width(), 400)
        H = max(c.winfo_height(), 240)

        if not self.filas:
            c.create_text(W / 2, H / 2, fill="#666666", font=("Segoe UI", 13),
                          text="el bloque aparecerá cuando llegue la cabecera")
            return

        s = max(16, min((W - 40) // self.cols, (H - 30) // self.filas, 70))
        x0, y0 = (W - s * self.cols) // 2, 8
        for i in range(self.filas):
            d = self.recibidas.get(i)
            fila = d["celdas"] if d else None
            # la fila que está llegando ahora mismo se pinta a medias
            if fila is None and self.parcial and self.parcial[0] == i:
                fila = list(self.parcial[1]) + ["?"] * (self.cols - len(self.parcial[1]))
            for j in range(self.cols):
                v = fila[j] if fila and j < len(fila) else None
                x, y = x0 + j * s, y0 + i * s
                if v is None:
                    relleno = FALTA
                elif v == "?":
                    relleno = DUDA
                elif v == M.NEGRO:
                    relleno = NEGRO
                else:
                    relleno = BLANCO
                c.create_rectangle(x, y, x + s, y + s, fill=relleno, outline=BORDE)
                if v and v not in (M.NEGRO, M.BLANCO, "?"):
                    c.create_text(x + s / 2, y + s / 2, text=v, fill="#000000",
                                  font=("Segoe UI", int(s * 0.55), "bold"))
            if d and not d["ok"]:           # fila entera marcada como dudosa
                c.create_rectangle(x0, y0 + i * s, x0 + s * self.cols,
                                   y0 + (i + 1) * s, outline=AMBAR, width=3)


def main():
    root = tk.Tk()
    root.geometry("1000x760")
    RxManual(root)
    root.mainloop()


if __name__ == "__main__":
    main()
