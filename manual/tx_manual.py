# -*- coding: utf-8 -*-
"""TRANSMISOR: se digita la cuadricula y la ventana dice que luces prender.

Dos modos, se cambian con F5:
  EDITAR       se escribe la cuadricula.  . espacio # = negro   - _ = blanco
               letras A..Z N   flechas   ENTER = fila siguiente   Ctrl+Z
  TRANSMITIR   se elige una unidad a la derecha y ESPACIO la reproduce (y la
               para); las dos bolas grandes van diciendo, simbolo a simbolo,
               que prender

En cualquiera de los dos modos, 1 2 3 0 prenden y apagan las luces A MANO, sin
transmitir nada: sirve para apuntarlas y para comprobar el cableado. Son las
MISMAS teclas que usa el receptor para apuntar lo que ve. El * manda el AVISO,
un parpadeo rapido de las dos que quiere decir "preparate, voy a transmitir".

El ARDUINO ES OPCIONAL, y opcional quiere decir que el programa hace lo mismo
sin el: la diferencia es quien mueve el interruptor. Sin Arduino lo mueve una
persona mirando la pantalla; con Arduino lo mueve la placa, con la
temporizacion exacta (util sobre todo para el mini parpadeo, que a mano sale
como un toque rapido y no siempre igual de corto).

El teclado siempre es de la cuadricula: las filas y columnas se cambian con
botones + y -, no escribiendo, asi que ninguna casilla de texto se lo puede
robar. Si aun asi se va (el deslizador si toma foco), ESC lo devuelve.

La codificacion no esta aqui, esta en codigo_manual.py.
"""

import time
import tkinter as tk
from tkinter import ttk, messagebox

import codigo_manual as M

# --- colores -------------------------------------------------------------
FONDO = "#1e1e1e"
PANEL = "#151515"
NEGRO = "#111111"
BLANCO = "#ffffff"
BORDE = "#444444"
CURSOR = "#2f7de1"
VERDE = "#5fe07a"
AMBAR = "#ffd54f"
ROJO = "#ff6b6b"
AZUL = "#9fd0ff"

MAX_CELDAS = 80          # el máximo que pide el enunciado

# Las cuatro teclas del control manual de las luces son LAS MISMAS que usa el
# receptor para apuntar lo que ve. Así los dos lados hablan igual: el del
# transmisor pulsa 2 y prende la verde, el del receptor ve verde y pulsa 2.
#   (estado, tecla, rótulo, color)
LUCES = [
    (M.LUZ_A, "1", "solo ROJA", "#ff3b30"),
    (M.LUZ_B, "2", "solo VERDE", "#34c759"),
    (M.AMBAS, "3", "LAS DOS", "#ffd54f"),
    (M.SEP,   "0", "NINGUNA", "#555555"),
]
TECLA_AVISO = "asterisk"        # la tecla *


# =========================================================================
#  ARDUINO
#
#  Nada de esto hace falta para transmitir: es solo para no tener que mover el
#  interruptor a mano. Si no hay pyserial o no hay placa, el resto del programa
#  funciona igual. Firmware en relaylink/relaylink.ino.
# =========================================================================
def puertos_disponibles():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


def _empaquetar(ranuras):
    """Estados -> hexadecimal, 2 bits por ranura y 4 ranuras por byte."""
    datos = bytearray((len(ranuras) + 3) // 4)
    for i, s in enumerate(ranuras):
        datos[i >> 2] |= (s & 3) << (6 - 2 * (i & 3))
    return datos.hex().upper()


class Arduino(object):
    """Enlace mínimo con relaylink.ino. Escribe y sigue: no se queda esperando,
    para que la ventana no se congele mientras las luces conmutan.

    Ojo: el firmware guarda como mucho MAX_RANURAS ranuras por orden. Con
    SUBRANURAS = 4 eso son 128 símbolos, más que cualquier fila real.
    """

    MAX_RANURAS = 512

    def __init__(self, puerto):
        import serial                       # pyserial: pip install pyserial
        self.ser = serial.Serial(puerto, 115200, timeout=0.1)
        time.sleep(2.0)                     # el Arduino se reinicia al abrir
        self.ser.reset_input_buffer()

    def velocidad(self, segundos_por_simbolo):
        """El Arduino trabaja en ranuras, no en símbolos: se le pone el período
        dividido entre SUBRANURAS para que el mini parpadeo le quepa."""
        self.ser.write(b"S:%d\n" % int(segundos_por_simbolo * 1e6 / M.SUBRANURAS))

    def periodo_us(self, us):
        """Período de ranura directo, en microsegundos. Lo usa el aviso,
        que va mucho más rápido que un símbolo."""
        self.ser.write(b"S:%d\n" % int(us))

    def emitir(self, ranuras):
        ranuras = ranuras[:self.MAX_RANURAS]
        self.ser.write(b"X:%d:%s\n" % (len(ranuras),
                                       _empaquetar(ranuras).encode()))

    def cortar(self):
        """Aborta la emisión que la placa esté haciendo ahora mismo.

        Hace falta porque emitir() le manda al Arduino la unidad ENTERA de
        un golpe y la placa se queda ocupada varios segundos emitiéndola:
        sin esto, darle a PARAR solo detenía la animación de la pantalla y
        las luces seguían solas hasta el final. El firmware mira si llega
        una 'Z' entre símbolo y símbolo, así que el corte tarda como mucho
        una ranura.
        """
        self.ser.write(b"Z\n")

    def fijar(self, estado):
        """Deja las luces en uno de los 4 estados, sin transmitir nada."""
        self.ser.write(b"B:%d\n" % (estado & 3))

    def apagar(self):
        self.fijar(M.SEP)

    def leer(self):
        """Las líneas que haya mandado el Arduino, si hay alguna."""
        salida = []
        try:
            while self.ser.in_waiting:
                linea = self.ser.readline().decode("ascii", "ignore").strip()
                if linea:
                    salida.append(linea)
        except Exception:
            pass
        return salida

    def cerrar(self):
        try:
            self.apagar()
            self.ser.close()
        except Exception:
            pass


# =========================================================================
#  LA VENTANA
# =========================================================================
class TxManual(object):

    def __init__(self, root):
        self.root = root
        root.title("Tx MANUAL · dos luces · Redes I")
        root.configure(bg=FONDO)

        self.filas, self.cols = 4, 4
        self.grid = []
        self.cur = [0, 0]
        self.geom = None
        self.t0 = None                  # cronómetro: arranca con la 1ª tecla
        self.historial = []             # para deshacer (Ctrl+Z)

        self.modo = "editar"
        self.unidades = []              # [(nombre, [símbolos]), ...]
        self.enviadas = set()
        self.k = 0                      # unidad seleccionada
        self.i = 0                      # símbolo dentro de la unidad
        self.fase = 0                   # 1 = pintando el mini parpadeo
        self.corriendo = False
        self.luz_fija = None            # lo que se ve ahora, o None
        self.luz_pedida = None          # lo último que se pidió a mano
        self._job_parpadeo = None       # parpadeo manual pendiente
        self.periodo = M.T_SIMBOLO_S
        self.arduino = None
        self._job = None

        self._construir()
        self.nueva_cuadricula(self.filas, self.cols)
        self.lbl_est.config(text="Las luces las prende una persona siguiendo esta "
                                 "pantalla. Conectar un Arduino solo automatiza "
                                 "eso; sin él funciona igual.", fg="#888888")
        self._bucle()

    # ------------------------------------------------------------ montaje --
    def _contador(self, padre, texto, que):
        """Rótulo + botones - y +. No hay casilla de texto a propósito: así
        nunca se queda el teclado atrapado fuera de la cuadrícula."""
        tk.Label(padre, text=texto, bg=FONDO, fg="white").pack(side="left")
        tk.Button(padre, text="−", width=2, font=("Segoe UI", 11, "bold"),
                  command=lambda: self.cambiar_tamano(que, -1)
                  ).pack(side="left", padx=(4, 0))
        lbl = tk.Label(padre, text="0", bg="#2b2b2b", fg="white", width=3,
                       font=("Consolas", 12, "bold"), relief="sunken", bd=1)
        lbl.pack(side="left", padx=2)
        tk.Button(padre, text="+", width=2, font=("Segoe UI", 11, "bold"),
                  command=lambda: self.cambiar_tamano(que, +1)).pack(side="left")
        return lbl

    def _construir(self):
        # ---- barra 1: tamaño de la cuadrícula ----
        top = tk.Frame(self.root, bg=FONDO)
        top.pack(fill="x", padx=8, pady=(6, 0))

        self.lbl_filas = self._contador(top, "Filas:", "filas")
        tk.Frame(top, bg=FONDO, width=18).pack(side="left")
        self.lbl_cols = self._contador(top, "Columnas:", "cols")

        tk.Button(top, text="Limpiar", command=self.limpiar).pack(side="left", padx=14)
        tk.Button(top, text="Deshacer (Ctrl+Z)",
                  command=self.deshacer).pack(side="left")

        self.lbl_celdas = tk.Label(top, text="", bg=FONDO, fg="#888888",
                                   font=("Segoe UI", 9))
        self.lbl_celdas.pack(side="left", padx=12)

        self.lbl_t = tk.Label(top, text="00.0 s", bg=FONDO, fg=VERDE,
                              font=("Consolas", 18, "bold"))
        self.lbl_t.pack(side="right", padx=8)

        # ---- barra 2: velocidad y Arduino ----
        top2 = tk.Frame(self.root, bg=FONDO)
        top2.pack(fill="x", padx=8, pady=(2, 4))

        tk.Label(top2, text="seg/símbolo:", bg=FONDO, fg="white").pack(side="left")
        self.esc_t = tk.Scale(top2, from_=0.3, to=3.0, resolution=0.1,
                              orient="horizontal", length=180, bg=FONDO,
                              fg="white", troughcolor="#333333",
                              highlightthickness=0, sliderrelief="flat",
                              command=self._on_periodo)
        self.esc_t.set(self.periodo)
        self.esc_t.pack(side="left", padx=4)

        tk.Label(top2, text="   Luces:", bg=FONDO, fg="white").pack(side="left")
        tk.Label(top2, text="a mano  ·  o con Arduino en", bg=FONDO,
                 fg="#888888").pack(side="left", padx=(2, 4))
        # readonly = no se puede escribir dentro, así no captura el teclado
        self.cbo = ttk.Combobox(top2, width=9, state="readonly",
                                values=puertos_disponibles())
        self.cbo.pack(side="left", padx=2)
        self.cbo.bind("<<ComboboxSelected>>", lambda e: self.foco_cuadricula())
        self.btn_con = tk.Button(top2, text="Conectar", command=self.conectar)
        self.btn_con.pack(side="left")

        # ---- cuerpo: cuadrícula a la izquierda, unidades a la derecha ----
        cuerpo = tk.Frame(self.root, bg=FONDO)
        cuerpo.pack(fill="both", expand=True, padx=8)

        self.canvas = tk.Canvas(cuerpo, bg=FONDO, takefocus=1,
                                highlightthickness=3, highlightbackground=FONDO,
                                highlightcolor=CURSOR)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._click_celda)
        self.canvas.bind("<FocusIn>", lambda e: self.dibujar_grid())
        self.canvas.bind("<FocusOut>", lambda e: self.dibujar_grid())

        lista = tk.Frame(cuerpo, bg=PANEL)
        lista.pack(side="right", fill="y", padx=(8, 0))
        tk.Label(lista, text="Unidades", bg=PANEL, fg=AZUL,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
        tk.Label(lista, text="clic para (re)enviar una sola", bg=PANEL,
                 fg="#777777", font=("Segoe UI", 8)).pack(anchor="w", padx=8)
        self.marco_unidades = tk.Frame(lista, bg=PANEL)
        self.marco_unidades.pack(padx=8, pady=6)
        self.botones = []
        tk.Button(lista, text="copiar esta unidad", width=20,
                  command=lambda: self.copiar(False)).pack(pady=1)
        tk.Button(lista, text="copiar bloque entero", width=20,
                  command=lambda: self.copiar(True)).pack(pady=(1, 8))

        # ---- abajo: las dos luces y los controles ----
        bajo = tk.Frame(self.root, bg=FONDO)
        bajo.pack(fill="x", padx=8, pady=(4, 8))

        izq = tk.Frame(bajo, bg=FONDO)
        izq.pack(side="left")
        self.luces = tk.Canvas(izq, width=330, height=150, bg=FONDO,
                               highlightthickness=0)
        self.luces.pack()

        # Prender y apagar las luces SIN transmitir nada: para apuntarlas, para
        # comprobar que el cableado responde y para avisar al receptor.
        manual = tk.Frame(izq, bg=FONDO)
        manual.pack(pady=(4, 0))
        for estado, tecla, nombre, color in LUCES:
            tk.Button(manual, text="%s\n%s" % (tecla, nombre), bg=color,
                      fg="#dddddd" if estado == M.SEP else "#000000",
                      font=("Segoe UI", 9, "bold"), width=8,
                      command=lambda e=estado: self.luz_manual(e)).pack(side="left", padx=2)
        tk.Button(manual, text="*\nAVISO", bg="#e0a020", fg="black",
                  font=("Segoe UI", 9, "bold"), width=8,
                  command=self.avisar).pack(side="left", padx=(10, 0))

        der = tk.Frame(bajo, bg=FONDO)
        der.pack(side="left", fill="both", expand=True, padx=10)

        self.lbl_pos = tk.Label(der, text="", bg=FONDO, fg=AMBAR,
                                font=("Consolas", 12, "bold"), anchor="w")
        self.lbl_pos.pack(fill="x")
        self.lbl_sig = tk.Label(der, text="", bg=FONDO, fg="#888888",
                                font=("Consolas", 11), anchor="w")
        self.lbl_sig.pack(fill="x", pady=2)
        self.lbl_est = tk.Label(der, text="", bg=FONDO, fg=AZUL,
                                font=("Segoe UI", 10), anchor="w")
        self.lbl_est.pack(fill="x", pady=2)

        bot = tk.Frame(der, bg=FONDO)
        bot.pack(anchor="w", pady=6)
        self.btn_modo = tk.Button(bot, text="TRANSMITIR (F5)", bg=CURSOR,
                                  fg="white", font=("Segoe UI", 11, "bold"),
                                  command=self.cambiar_modo)
        self.btn_modo.pack(side="left")
        self.btn_play = tk.Button(bot, text="INICIAR (espacio)", width=16,
                                  command=self.alternar)
        self.btn_play.pack(side="left", padx=6)
        tk.Button(bot, text="◀", width=3, command=self.atras).pack(side="left")
        tk.Button(bot, text="▶", width=3, command=self.adelante).pack(side="left", padx=2)
        tk.Button(bot, text="repetir esta unidad",
                  command=self.repetir).pack(side="left", padx=8)

        # ---- teclado ----
        # Las teclas de las luces van por su cuenta y devuelven "break" para
        # que no lleguen también a on_key.
        for _, tecla, _, _ in LUCES:
            self.root.bind(tecla, self._tecla_luz)
        self.root.bind("<asterisk>", self._tecla_luz)
        self.root.bind("<Key>", self.on_key)
        self.root.bind("<F5>", lambda e: self.cambiar_modo())
        self.root.bind("<Escape>", lambda e: self.foco_cuadricula())
        self.root.bind("<Control-z>", lambda e: self.deshacer())
        self.root.bind("<Configure>", lambda e: self.dibujar_grid())
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

    # --------------------------------------------------------- cuadrícula --
    def cambiar_tamano(self, que, delta):
        """Los + y - cambian el tamaño SIN borrar lo escrito: lo que sobra se
        recorta y lo que falta se rellena con negro."""
        f, c = self.filas, self.cols
        if que == "filas":
            f = max(1, min(M.MAX_FILAS, f + delta))
        else:
            c = max(1, min(M.MAX_COLS, c + delta))
        if (f, c) == (self.filas, self.cols):
            return
        self._guardar_undo()
        self.grid = [[self.grid[i][j] if i < self.filas and j < self.cols
                      else M.NEGRO for j in range(c)] for i in range(f)]
        self.filas, self.cols = f, c
        self.cur = [min(self.cur[0], f - 1), min(self.cur[1], c - 1)]
        self._regenerar()
        self.foco_cuadricula()

    def nueva_cuadricula(self, filas, cols):
        self.filas, self.cols = filas, cols
        self.grid = [[M.NEGRO] * cols for _ in range(filas)]
        self.cur = [0, 0]
        self.t0 = None
        self.historial = []
        self.lbl_t.config(text="00.0 s")
        self.modo = "editar"
        self.btn_modo.config(text="TRANSMITIR (F5)", bg=CURSOR)
        self._regenerar()
        self.foco_cuadricula()

    def limpiar(self):
        self._guardar_undo()
        self.grid = [[M.NEGRO] * self.cols for _ in range(self.filas)]
        self.cur = [0, 0]
        self._regenerar()
        self.foco_cuadricula()

    def _guardar_undo(self):
        self.historial.append(([f[:] for f in self.grid], self.filas,
                               self.cols, list(self.cur)))
        if len(self.historial) > 60:
            self.historial.pop(0)

    def deshacer(self):
        if not self.historial:
            return
        self.grid, self.filas, self.cols, self.cur = self.historial.pop()
        self._regenerar()
        self.foco_cuadricula()

    def _regenerar(self):
        """Vuelve a calcular las unidades a partir de la cuadrícula actual."""
        try:
            self.unidades = M.bloque(self.grid)
        except ValueError as e:
            self.unidades = []
            self.lbl_est.config(text="cuadrícula no válida: %s" % e, fg=ROJO)
        self.enviadas = set()
        self.k = min(self.k, max(0, len(self.unidades) - 1))
        self.i = 0
        self.fase = 0

        self.lbl_filas.config(text=str(self.filas))
        self.lbl_cols.config(text=str(self.cols))
        n = self.filas * self.cols
        if n > MAX_CELDAS:
            self.lbl_celdas.config(text="%d celdas · el enunciado pide máximo %d"
                                        % (n, MAX_CELDAS), fg=AMBAR)
        else:
            self.lbl_celdas.config(text="%d celdas · %.0f s en total"
                                        % (n, M.duracion(self.unidades)),
                                   fg="#888888")
        self.refrescar()

    # ------------------------------------------------------------ teclado --
    # Widgets que pueden quedarse con el teclado. Con los + y - ya no hay
    # ninguna casilla de texto, pero el deslizador sí recibe foco, así que se
    # sigue comprobando antes de escribir en la cuadrícula.
    _CLASES_TEXTO = ("Entry", "TEntry", "TCombobox", "Spinbox", "Text", "Scale")

    def _foco_en_texto(self):
        try:
            w = self.root.focus_get()
        except Exception:
            return False
        return w is not None and w.winfo_class() in self._CLASES_TEXTO

    def _tiene_foco(self):
        try:
            return self.root.focus_get() is self.canvas
        except Exception:
            return False

    def foco_cuadricula(self, *_):
        """Devuelve el teclado a la cuadrícula."""
        self.canvas.focus_set()
        self.dibujar_grid()

    def on_key(self, ev):
        if self._foco_en_texto():
            return
        if self.modo == "transmitir":
            return self._tecla_transmitir(ev)
        return self._tecla_editar(ev)

    def _tecla_editar(self, ev):
        k, ch = ev.keysym, ev.char
        if self.t0 is None and (ch or k == "BackSpace"):
            self.t0 = time.time()          # el cronómetro arranca al digitar

        if k in ("Right", "Left", "Down", "Up"):
            self._mover({"Right": (0, 1), "Left": (0, -1),
                         "Down": (1, 0), "Up": (-1, 0)}[k])
            self.dibujar_grid()
            return
        if k == "Return":
            self.cur = [min(self.cur[0] + 1, self.filas - 1), 0]
            self.dibujar_grid()
            return

        if k == "BackSpace":
            self._guardar_undo()
            self._mover((0, -1))
            self.grid[self.cur[0]][self.cur[1]] = M.NEGRO
        elif ch in (".", " ", "#"):
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = M.NEGRO
            self._mover((0, 1))
        elif ch in ("-", "_"):          # el 0 ya no: es la tecla de apagar
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = M.BLANCO
            self._mover((0, 1))
        elif ch and ch.upper() in M.ALFABETO:
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = ch.upper()
            self._mover((0, 1))
        else:
            return
        self._regenerar()

    def _mover(self, paso):
        """Mueve el cursor. Al salirse por un lado pasa a la fila de al lado,
        como al escribir en una hoja (idea sacada de crear_matriz.py)."""
        di, dj = paso
        i, j = self.cur[0] + di, self.cur[1] + dj
        if dj:
            if j < 0:
                j, i = self.cols - 1, i - 1
            elif j >= self.cols:
                j, i = 0, i + 1
        self.cur = [max(0, min(i, self.filas - 1)), max(0, min(j, self.cols - 1))]

    def _tecla_transmitir(self, ev):
        if ev.keysym == "space":
            self.alternar()
        elif ev.keysym == "Right":
            self.adelante()
        elif ev.keysym == "Left":
            self.atras()

    def _tecla_luz(self, ev):
        """1/2/3/0 y * mandan sobre las luces en cualquiera de los dos modos.

        No chocan con nada: en la cuadrícula esos caracteres no son celdas
        válidas (una celda es una letra, # o _), así que estaban libres.
        """
        if self._foco_en_texto():
            return
        if ev.keysym == TECLA_AVISO:
            self.avisar()
            return "break"
        for estado, tecla, _, _ in LUCES:
            if ev.char == tecla:
                self.luz_manual(estado)
                return "break"

    def _click_celda(self, ev):
        self.canvas.focus_set()            # el clic recupera el teclado
        if self.modo == "editar" and self.geom:
            x0, y0, s = self.geom
            j, i = int((ev.x - x0) // s), int((ev.y - y0) // s)
            if 0 <= i < self.filas and 0 <= j < self.cols:
                self.cur = [i, j]
        self.dibujar_grid()

    # -------------------------------------------------------------- modos --
    def cambiar_modo(self):
        self.parar()
        self.modo = "transmitir" if self.modo == "editar" else "editar"
        if self.modo == "transmitir":
            self._regenerar()
            self.btn_modo.config(text="EDITAR (F5)", bg="#8a6d00")
        else:
            self.btn_modo.config(text="TRANSMITIR (F5)", bg=CURSOR)
        self.foco_cuadricula()
        self.refrescar()

    # ------------------------------------------------------------ Arduino --
    def conectar(self):
        if self.arduino:
            self.arduino.cerrar()
            self.arduino = None
            self.btn_con.config(text="Conectar")
            self.lbl_est.config(text="Arduino desconectado", fg=AZUL)
            return
        try:
            self.arduino = Arduino(self.cbo.get())
            self.arduino.velocidad(self.periodo)
            self.btn_con.config(text="Soltar")
            self.lbl_est.config(text="Arduino en %s: transmite él solo"
                                     % self.cbo.get(), fg=VERDE)
        except Exception as e:
            self.arduino = None
            messagebox.showerror("Arduino", "%s\n\n(sin Arduino se transmite a "
                                            "mano: no pasa nada)" % e)
        self.foco_cuadricula()

    def _on_periodo(self, valor):
        self.periodo = float(valor)
        if self.arduino:
            self.arduino.velocidad(self.periodo)

    # -------------------------------------------- control manual de luces --
    def luz_manual(self, estado):
        """Prende o apaga las luces a mano, sin transmitir nada.

        Tomar el control manual PARA la reproducción: si no, la animación
        seguiría pisando el estado que se acaba de poner.

        Si se vuelve a pulsar el estado que YA está puesto, no se queda igual:
        hace el MINI PARPADEO. Eso es justo lo que hace falta para mandar dos
        símbolos iguales seguidos, que si no se verían como uno solo largo.
        """
        self.parar()
        # Un parpadeo a medias se cancela: si no, al pulsar rápido dos veces se
        # solaparían y la luz podría no llegar a apagarse entre medias.
        if self._job_parpadeo is not None:
            self.root.after_cancel(self._job_parpadeo)
            self._job_parpadeo = None

        # Se compara con el estado PEDIDO, no con el que se ve: durante el
        # parpadeo lo que se ve es "apagado", y sin esta distinción una tercera
        # pulsación seguida no parpadearía y dos símbolos se fundirían en uno.
        repetido = (estado == self.luz_pedida and estado != M.SEP)
        self.luz_pedida = estado
        if repetido:
            corto = int(self.periodo * 1000 / M.SUBRANURAS)
            self._poner_luz(M.SEP)
            self._job_parpadeo = self.root.after(corto, self._fin_parpadeo, estado)
        else:
            self._poner_luz(estado)
        self._avanzar_a_mano(estado)

    def _fin_parpadeo(self, estado):
        self._job_parpadeo = None
        self._poner_luz(estado)

    def _poner_luz(self, estado):
        """Deja las luces en ese estado, en la pantalla y en la placa."""
        self.luz_fija = estado
        if self.arduino:
            self.arduino.fijar(estado)
        self.refrescar()

    def _avanzar_a_mano(self, estado):
        """Si lo que se acaba de pulsar es el símbolo que tocaba, avanza.

        Así se puede transmitir la unidad ENTERA a mano: la lista de la derecha
        va corriendo sola y siempre se ve cuál es el siguiente. Si se pulsa
        otra cosa el contador no se mueve, para no perder el sitio por un
        dedazo.
        """
        sim = self._actual()
        if self.modo == "transmitir" and self.i < len(sim) and sim[self.i] == estado:
            self.i += 1
            if self.i >= len(sim):
                self.enviadas.add(self.k)
        self.refrescar()

    def avisar(self):
        """AVISO: las dos luces parpadeando rápido, para decirle al receptor
        'prepárate, voy a transmitir'. Va a AVISO_T_S por destello, mucho más
        rápido que un símbolo, así que no se puede confundir con datos."""
        self.parar()
        patron = M.aviso()
        if self.arduino:
            # El Arduino emite a ritmo fijo: se le baja el período, se le manda
            # el patrón y se le devuelve el suyo. Las tres órdenes se procesan
            # en orden, así que la última no le pisa el aviso.
            self.arduino.periodo_us(M.AVISO_T_S * 1e6)
            self.arduino.emitir(patron)
            self.arduino.velocidad(self.periodo)
        self._animar_aviso(patron, 0)
        self.lbl_est.config(text="AVISO enviado · espera a que el receptor "
                                 "confirme antes de transmitir", fg=AMBAR)

    def _animar_aviso(self, patron, k):
        """Pinta el aviso en pantalla al mismo ritmo que lo emite la placa,
        para que quien lo hace a mano lleve el compás."""
        if k >= len(patron):
            self.luz_fija = M.SEP
            self.refrescar()
            return
        self.luz_fija = patron[k]
        self.refrescar()
        self.root.after(int(M.AVISO_T_S * 1000),
                        self._animar_aviso, patron, k + 1)

    def parar(self):
        """Detiene la reproducción AQUÍ Y EN LA PLACA.

        Lo segundo es lo que faltaba: al Arduino se le manda la unidad entera
        de una vez, así que parar solo la animación dejaba las luces
        conmutando solas hasta el final de la fila.
        """
        self.corriendo = False
        self.fase = 0
        if self.arduino:
            self.arduino.cortar()

    # ----------------------------------------------------- reproducción ---
    def elegir(self, j):
        self.parar()
        self.k, self.i, self.fase = j, 0, 0
        if self.modo == "editar":
            self.cambiar_modo()
        else:
            self.refrescar()

    def repetir(self):
        self.parar()
        self.i, self.fase = 0, 0
        self.refrescar()

    def _actual(self):
        return self.unidades[self.k][1] if self.unidades else []

    def alternar(self):
        """El botón / la barra espaciadora: arranca si está parado y para si
        está andando."""
        if not self.unidades:
            return
        if self.modo == "editar":
            self.cambiar_modo()

        if self.corriendo:
            self.parar()
            self.refrescar()
            return

        self.corriendo = True
        self.luz_fija = self.luz_pedida = None   # se acabó el control manual
        if self.t0 is None:
            self.t0 = time.time()
        if self.i >= len(self._actual()):
            self.i = 0
        # El Arduino recibe la unidad ENTERA de una vez, ya expandida a ranuras
        # (con los mini parpadeos), y la emite él solo; la animación de la
        # pantalla va en paralelo para acompañarlo. Por eso parar() tiene que
        # avisarle: la placa no se entera de que la pantalla se detuvo.
        if self.arduino:
            ranuras = M.emision(self._actual())
            self.arduino.emitir(ranuras[self.i * M.SUBRANURAS:])
        self._tic()
        self.refrescar()

    def _tic(self):
        """Un paso de la animación.

        Si el símbolo repite al anterior, primero se pinta el MINI PARPADEO
        (todo apagado durante 1/SUBRANURAS de tiempo) y solo después la luz.
        Así el operador ve la frontera y no tiene que contar tiempos.
        """
        sim = self._actual()
        if not self.corriendo:
            return
        if self.i >= len(sim):
            self.enviadas.add(self.k)
            self.corriendo = False
            self.fase = 0
            self.refrescar()
            return

        corto = self.periodo / M.SUBRANURAS
        if self.fase == 0 and M.repite(sim, self.i):
            self.fase = 1                          # el mini parpadeo
            self.refrescar()
            self.root.after(int(corto * 1000), self._tic)
            return

        espera = self.periodo - corto if self.fase == 1 else self.periodo
        self.fase = 0
        self.refrescar()
        self.i += 1
        self.root.after(int(espera * 1000), self._tic)

    def adelante(self):
        if not self.unidades:
            return
        self.fase = 0
        self.i = min(self.i + 1, len(self._actual()))
        if self.i >= len(self._actual()):
            self.enviadas.add(self.k)
        self.refrescar()

    def atras(self):
        self.fase = 0
        self.i = max(self.i - 1, 0)
        self.refrescar()

    def copiar(self, todo):
        """Deja la secuencia en el portapapeles, para pegarla en rx_manual.py."""
        if not self.unidades:
            return
        cuales = self.unidades if todo else [self.unidades[self.k]]
        texto = "\n".join("# %s (%d símbolos)\n%s"
                          % (n, len(s), M.a_texto(s)) for n, s in cuales)
        self.root.clipboard_clear()
        self.root.clipboard_append(texto)
        self.lbl_est.config(text="copiado al portapapeles", fg=VERDE)
        self.foco_cuadricula()

    # ------------------------------------------------------------- dibujo --
    def refrescar(self):
        self._pintar_botones()
        self.dibujar_grid()
        self.dibujar_luces()

    def _pintar_botones(self):
        if len(self.botones) != len(self.unidades):
            for b in self.botones:
                b.destroy()
            self.botones = [tk.Button(self.marco_unidades, width=20, anchor="w",
                                      command=lambda x=j: self.elegir(x))
                            for j in range(len(self.unidades))]
            for b in self.botones:
                b.pack(pady=1)
        for j, b in enumerate(self.botones):
            nombre, sim = self.unidades[j]
            if j == self.k:
                bg, fg = CURSOR, "white"
            elif j in self.enviadas:
                bg, fg = "#1f4a2a", "#bfe6c8"
            else:
                bg, fg = "#f0f0f0", "black"
            b.config(text="%s  ·  %d símbolos%s"
                          % (nombre, len(sim), "  ✓" if j in self.enviadas else ""),
                     bg=bg, fg=fg)

    def dibujar_grid(self):
        c = self.canvas
        if not c.winfo_exists():           # la ventana ya se cerró
            return
        c.delete("all")
        W = max(c.winfo_width(), 300)
        H = max(c.winfo_height(), 200)
        s = max(18, min((W - 30) // self.cols, (H - 40) // self.filas, 70))
        x0, y0 = (W - s * self.cols) // 2, 8
        self.geom = (x0, y0, s)

        for i in range(self.filas):
            for j in range(self.cols):
                v = self.grid[i][j]
                x, y = x0 + j * s, y0 + i * s
                c.create_rectangle(x, y, x + s, y + s, outline=BORDE,
                                   fill=NEGRO if v == M.NEGRO else BLANCO)
                if v not in (M.NEGRO, M.BLANCO):
                    c.create_text(x + s / 2, y + s / 2, text=v, fill="#000000",
                                  font=("Segoe UI", int(s * 0.55), "bold"))

        if self.modo == "editar":
            i, j = self.cur
            c.create_rectangle(x0 + j * s, y0 + i * s, x0 + (j + 1) * s,
                               y0 + (i + 1) * s, outline=CURSOR, width=3)
            ayuda = ". o espacio o # = negro     - o _ = blanco     letras = A..Z Ñ"
        else:
            ayuda = "modo TRANSMITIR: la cuadrícula está bloqueada (F5 para editar)"
        c.create_text(x0, y0 + s * self.filas + 16, anchor="w", fill="#888888",
                      text=ayuda, font=("Segoe UI", 10))

        # Aviso de que el teclado se fue a otra parte (el deslizador, la lista...)
        if self.modo == "editar" and not self._tiene_foco():
            c.create_rectangle(x0, y0, x0 + s * self.cols, y0 + s * self.filas,
                               outline="", fill="#000000", stipple="gray50")
            c.create_text(x0 + s * self.cols / 2.0, y0 + s * self.filas / 2.0,
                          text="haz clic aquí (o pulsa ESC) para escribir",
                          fill=AMBAR, font=("Segoe UI", 13, "bold"))

    def dibujar_luces(self):
        cv = self.luces
        if not cv.winfo_exists():
            return
        cv.delete("all")
        sim = self._actual()

        # Con el control manual puesto mandan las luces fijadas a mano, no la
        # unidad: eso es justo lo que se está mirando.
        if self.luz_fija is not None:
            self._pintar_bolas(cv, self.luz_fija)
            # La secuencia se sigue viendo: es lo que permite mandar la unidad
            # entera a mano, leyendo lo que falta mientras se pulsan las teclas.
            if self.modo == "transmitir" and sim:
                if self.i >= len(sim):
                    self.lbl_pos.config(
                        text="a mano  [%s]   ·   %s: unidad completa"
                             % (M.NOMBRE[self.luz_fija], self.unidades[self.k][0]))
                    self.lbl_sig.config(text="elige la siguiente unidad a la derecha")
                else:
                    self.lbl_pos.config(
                        text="a mano  [%s]   ·   %s: toca el símbolo %d/%d  ->  [%s]"
                             % (M.NOMBRE[self.luz_fija], self.unidades[self.k][0],
                                self.i + 1, len(sim), M.NOMBRE[sim[self.i]]))
                    self.lbl_sig.config(text="siguientes:  "
                                             + M.a_texto(sim[self.i:self.i + 12]))
            else:
                self.lbl_pos.config(text="control manual   [%s]   (F5 y espacio "
                                         "para transmitir solo)"
                                         % M.NOMBRE[self.luz_fija])
                self.lbl_sig.config(text="")
            return

        if self.modo == "editar" or not sim:
            cv.create_text(165, 75, fill="#666666", font=("Segoe UI", 11),
                           text="pulsa TRANSMITIR (F5), o usa 1 2 3 0 para "
                                "probar las luces")
            self.lbl_pos.config(text="")
            self.lbl_sig.config(text="")
            return

        if self.i >= len(sim):
            cv.create_text(165, 75, text="UNIDAD ENVIADA", fill=VERDE,
                           font=("Segoe UI", 18, "bold"))
            self.lbl_pos.config(text="%s: %d/%d  ·  completa"
                                     % (self.unidades[self.k][0], len(sim), len(sim)))
            self.lbl_sig.config(text="elige la siguiente unidad a la derecha")
            self.btn_play.config(text="INICIAR (espacio)")
            return

        estado = sim[self.i]
        # durante el mini parpadeo las dos luces se pintan apagadas
        self._pintar_bolas(cv, M.SEP if self.fase == 1 else estado)

        if self.fase == 1:
            etiqueta = "MINI PARPADEO -> vuelve la misma luz"
        elif estado == M.SEP:
            etiqueta = "SEPARADOR (fin de celda)"
        elif M.repite(sim, self.i):
            etiqueta = "otra vez la misma (parpadea antes)"
        else:
            etiqueta = "destello"
        self.lbl_pos.config(text="%s   símbolo %d/%d   [%s]  %s"
                                 % (self.unidades[self.k][0], self.i + 1,
                                    len(sim), M.NOMBRE[estado], etiqueta))
        self.lbl_sig.config(text="siguientes:  " + M.a_texto(sim[self.i + 1:self.i + 12]))
        self.btn_play.config(text="PARAR (espacio)" if self.corriendo
                             else "INICIAR (espacio)")

    def _pintar_bolas(self, cv, estado):
        """Las dos bolas grandes, en el estado que se le pase."""
        for cx, nombre, encendida, on, off in (
                (85, "ROJA (A)", estado & 1, "#ff3b30", "#3a1210"),
                (245, "VERDE (B)", estado & 2, "#34c759", "#0f2d17")):
            cv.create_oval(cx - 55, 10, cx + 55, 120,
                           fill=on if encendida else off,
                           outline="#ffffff" if encendida else "#444444",
                           width=4 if encendida else 1)
            cv.create_text(cx, 65, text="ON" if encendida else "off",
                           fill="#000000" if encendida else "#777777",
                           font=("Segoe UI", 22, "bold"))
            cv.create_text(cx, 137, text=nombre, fill="#cccccc",
                           font=("Segoe UI", 10, "bold"))

    # -------------------------------------------------------------- bucle --
    def _bucle(self):
        if not self.root.winfo_exists():
            return
        if self.arduino:
            for linea in self.arduino.leer():
                self.lbl_est.config(text="arduino: " + linea, fg=AZUL)
        if self.t0 is not None:
            self.lbl_t.config(text="%04.1f s" % (time.time() - self.t0))
        self._job = self.root.after(100, self._bucle)

    def cerrar(self):
        # Se cancela el bucle ANTES de destruir la ventana; si no, Tk se queja
        # de que la tarea pendiente apunta a algo que ya no existe.
        if self._job is not None:
            self.root.after_cancel(self._job)
            self._job = None
        if self.arduino:
            self.arduino.cerrar()
        self.root.destroy()


def main():
    root = tk.Tk()
    root.geometry("1080x780")
    TxManual(root)
    root.mainloop()


if __name__ == "__main__":
    main()
