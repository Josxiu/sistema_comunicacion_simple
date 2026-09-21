# -*- coding: utf-8 -*-
"""TRANSMISOR PARA LA CAMARA: se digita la cuadricula o se carga desde foto.
(Versión integrada con leer_hoja.py en camara/pruebas/hoja)

    Se abre en VS Code y se le da al boton de play. No lleva argumentos.

Es el companero de rx_camara.py. Permite:
  1. Digitar o editar la matriz a mano.
  2. Cargarla automaticamente desde una fotografía de la hoja ("Buscar foto")
     usando el pipeline de visión por computador de leer_hoja.py (homografía,
     eliminación de sombras y plantillas, SIN depender de Tesseract).
  3. Ver el diagnóstico visual ("Ver diagnóstico") para comparar la foto real
     con la matriz detectada y revisar celdas dudosas marcadas con '?'.
  4. Transmitir por Arduino a 1-20 símbolos/s o probar en pantalla (F8).

Redes de Computadores I - UdeA 2026-2 - Proyecto 01
"""

import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

# Rutas relativas para importar rx_camara (en camara/) y leer_hoja (en esta misma carpeta)
DIR_ACTUAL = Path(__file__).resolve().parent
sys.path.insert(0, str(DIR_ACTUAL.parent.parent))      # camara/
sys.path.insert(0, str(DIR_ACTUAL))                    # camara/pruebas/hoja/

import rx_camara as C          # la codificacion compartida con el receptor
import leer_hoja as LH         # pipeline de PDI para leer la hoja impresa


# ##########################################################################
#  0. PARAMETROS
# ##########################################################################

SIMBOLOS_POR_SEGUNDO = 5.0
VELOCIDAD_MIN = 1.0
VELOCIDAD_MAX = 20.0

COPIAS = 2
HUECO_ENTRE_COPIAS = 0.35

CUADROS_POR_SIMBOLO = C.CUADROS_POR_SIMBOLO_MIN
FPS_CAMARA_RECEPTORA = 60
MAX_CELDAS = 80

PANTALLA_LUCES_JUNTAS = False
PANTALLA_COLOR_A = "#ff2020"
PANTALLA_COLOR_B = "#20ff40"

AVISO_DESTELLOS = 6
AVISO_T_S = 0.12

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

LUCES = [
    (C.LUZ_A, "1", "solo ROJA", "#ff3b30"),
    (C.LUZ_B, "2", "solo VERDE", "#34c759"),
    (C.AMBAS, "3", "LAS DOS", "#ffd54f"),
    (C.APAGADO, "0", "NINGUNA", "#555555"),
]
TECLA_AVISO = "asterisk"


# ##########################################################################
#  1. EL ARDUINO
# ##########################################################################

def puertos_disponibles():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


def _empaquetar(simbolos):
    datos = bytearray((len(simbolos) + 3) // 4)
    for i, s in enumerate(simbolos):
        datos[i >> 2] |= (s & 3) << (6 - 2 * (i & 3))
    return datos.hex().upper()


class Arduino(object):

    MAX_SIMBOLOS = 512

    def __init__(self, puerto):
        import serial
        self.ser = serial.Serial(puerto, 115200, timeout=0.1)
        time.sleep(2.0)
        self.ser.reset_input_buffer()

    def velocidad(self, simbolos_por_s):
        self.ser.write(b"S:%d\n" % int(1e6 / max(0.1, simbolos_por_s)))

    def periodo_us(self, us):
        self.ser.write(b"S:%d\n" % int(us))

    def emitir(self, simbolos):
        self.ser.write(b"X:%d:%s\n" % (len(simbolos),
                                       _empaquetar(simbolos).encode()))

    def cortar(self):
        self.ser.write(b"Z\n")

    def fijar(self, estado):
        self.ser.write(b"B:%d\n" % (estado & 3))

    def apagar(self):
        self.fijar(C.APAGADO)

    def cerrar(self):
        try:
            self.apagar()
            self.ser.close()
        except Exception:
            pass


# ##########################################################################
#  2. LA TRAMA
# ##########################################################################

def simbolos_del_bloque(grid):
    payload = C.celdas_a_bits(grid)
    bits = C.construir_trama(C.TIPO_BLOQUE, len(grid), len(grid[0]), payload)
    return C.codificar_linea(bits), bits, payload


def patron_aviso():
    return [C.AMBAS if i % 2 == 0 else C.APAGADO
            for i in range(AVISO_DESTELLOS * 2)]


# ##########################################################################
#  2.5 EDITOR DE DIAGNÓSTICO INTERACTIVO (FOTO LADO A LADO)
# ##########################################################################

class EditorDiagnostico(tk.Toplevel):
    """Ventana interactiva de diagnóstico lado a lado.

    Muestra:
      - A la izquierda: la fotografía rectificada con la rejilla detectada.
      - A la derecha: la matriz digital decodificada.

    Permite hacer clic sobre cualquier celda (sea en la foto o en la matriz)
    y editarla inmediatamente con el teclado, actualizando ambas vistas y la
    ventana principal del transmisor en tiempo real.
    """

    def __init__(self, master, tx, derecha, cajas, titulo="Diagnóstico"):
        super().__init__(master)
        self.tx = tx
        self.derecha = derecha
        self.cajas = cajas
        self.titulo = titulo
        self.cur = list(tx.cur) if tx.cur else [0, 0]
        self.historial = []
        self._foto_tk = None
        self._escala_foto = 1.0
        self._lado_matriz = 35
        self._geom_matriz = (10, 10)

        self.title("Diagnóstico y Edición · Foto vs Matriz")
        self.configure(bg=FONDO)
        self.geometry("1100x720")
        self.minsize(800, 500)

        self._construir()
        self.bind("<Key>", self._on_key)
        self.bind("<Control-z>", lambda e: self.deshacer())
        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(50, self.redibujar)

    def _construir(self):
        # 1. Barra superior: info y botones
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x", padx=10, pady=8)

        lbl_tit = tk.Label(top, text=self.titulo, bg=PANEL, fg=AZUL,
                           font=("Segoe UI", 12, "bold"))
        lbl_tit.pack(side="left")

        q = LH._calidad(self.tx.grid, self.tx.confianzas)
        if q >= LH.CALIDAD_FIRME:
            txt_q, col_q = "Lectura Firme (calidad %.3f)" % q, VERDE
        elif q > 0:
            txt_q, col_q = "Lectura Dudosa (calidad %.3f · revisar ?)" % q, AMBAR
        else:
            txt_q, col_q = "Calidad N/D", "#aaaaaa"

        self.lbl_q = tk.Label(top, text="  ·  " + txt_q, bg=PANEL, fg=col_q,
                              font=("Segoe UI", 10, "bold"))
        self.lbl_q.pack(side="left", padx=4)

        tk.Button(top, text="✓ Listo / Cerrar (Esc)", bg=CURSOR, fg="white",
                  font=("Segoe UI", 9, "bold"),
                  command=self.destroy).pack(side="right", padx=4)
        tk.Button(top, text="Deshacer (Ctrl+Z)", bg="#333333", fg="white",
                  font=("Segoe UI", 9),
                  command=self.deshacer).pack(side="right", padx=6)

        # Barra de estado de celda activa
        barra_info = tk.Frame(self, bg=FONDO)
        barra_info.pack(fill="x", padx=12, pady=(2, 4))
        self.lbl_activa = tk.Label(barra_info, text="", bg=FONDO, fg=AMBAR,
                                   font=("Consolas", 11, "bold"), anchor="w")
        self.lbl_activa.pack(side="left")

        # 2. Área central: Paneles lado a lado
        cuerpo = tk.Frame(self, bg=FONDO)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=4)

        # Lado izquierdo: Foto
        marco_foto = tk.Frame(cuerpo, bg=PANEL, bd=1, relief="ridge")
        marco_foto.pack(side="left", fill="both", expand=True, padx=(0, 5))
        tk.Label(marco_foto, text="📷 Fotografía (clic en cualquier casilla para seleccionarla)",
                 bg=PANEL, fg="#cccccc", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=6, pady=4)
        self.cv_foto = tk.Canvas(marco_foto, bg=NEGRO, highlightthickness=0)
        self.cv_foto.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.cv_foto.bind("<Button-1>", self._click_foto)
        self.cv_foto.bind("<Configure>", lambda e: self.redibujar())

        # Lado derecho: Matriz digital
        marco_matriz = tk.Frame(cuerpo, bg=PANEL, bd=1, relief="ridge")
        marco_matriz.pack(side="left", fill="both", expand=True, padx=(5, 0))
        tk.Label(marco_matriz, text="🔲 Matriz decodificada (clic o digita para corregir)",
                 bg=PANEL, fg="#cccccc", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=6, pady=4)
        self.cv_matriz = tk.Canvas(marco_matriz, bg=FONDO, highlightthickness=0)
        self.cv_matriz.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.cv_matriz.bind("<Button-1>", self._click_matriz)
        self.cv_matriz.bind("<Configure>", lambda e: self.redibujar())

        # 3. Pie de atajos y ayuda
        pie = tk.Frame(self, bg=FONDO)
        pie.pack(fill="x", padx=10, pady=(2, 8))
        ayuda = ("💡 Clic en la foto o en la matriz para seleccionar casilla  ·  "
                 "Teclas: Letras A..Z, Ñ  |  . o # o espacio = negro  |  _ o - = blanco  |  "
                 "Flechas = mover  |  Ctrl+Z = deshacer")
        tk.Label(pie, text=ayuda, bg=FONDO, fg="#888888",
                 font=("Segoe UI", 9)).pack(side="left")

    def _click_foto(self, ev):
        if not hasattr(self, "_escala_foto") or self._escala_foto <= 0:
            return
        img_x = ev.x / self._escala_foto
        img_y = ev.y / self._escala_foto

        mejor_dist = float("inf")
        mejor_celda = None
        for (f, c), (x0, y0, x1, y1) in self.cajas.items():
            if x0 <= img_x <= x1 and y0 <= img_y <= y1:
                mejor_celda = [f, c]
                break
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            d = (img_x - cx) ** 2 + (img_y - cy) ** 2
            if d < mejor_dist:
                mejor_dist = d
                mejor_celda = [f, c]

        if mejor_celda is not None:
            self.cur = mejor_celda
            self.tx.cur = list(self.cur)
            self.redibujar()

    def _click_matriz(self, ev):
        if not hasattr(self, "_lado_matriz") or self._lado_matriz <= 0:
            return
        x0, y0 = getattr(self, "_geom_matriz", (0, 0))
        c = int((ev.x - x0) // self._lado_matriz)
        f = int((ev.y - y0) // self._lado_matriz)
        if 0 <= f < self.tx.filas and 0 <= c < self.tx.cols:
            self.cur = [f, c]
            self.tx.cur = list(self.cur)
            self.redibujar()

    def _on_key(self, ev):
        k, ch = ev.keysym, ev.char
        if k in ("Left", "Right", "Up", "Down"):
            di, dj = {"Left": (0, -1), "Right": (0, 1),
                      "Up": (-1, 0), "Down": (1, 0)}[k]
            f = max(0, min(self.tx.filas - 1, self.cur[0] + di))
            c = max(0, min(self.tx.cols - 1, self.cur[1] + dj))
            self.cur = [f, c]
            self.tx.cur = list(self.cur)
            self.redibujar()
            return
        if k == "Return":
            self.cur = [min(self.cur[0] + 1, self.tx.filas - 1), 0]
            self.tx.cur = list(self.cur)
            self.redibujar()
            return

        if k == "BackSpace":
            self._guardar_undo()
            self._mover_retroceso()
            self.tx.grid[self.cur[0]][self.cur[1]] = C.NEGRO
            self._limpiar_duda(self.cur[0], self.cur[1])
        elif ch in (".", " ", "#"):
            self._guardar_undo()
            self.tx.grid[self.cur[0]][self.cur[1]] = C.NEGRO
            self._limpiar_duda(self.cur[0], self.cur[1])
            self._mover_avance()
        elif ch in ("-", "_"):
            self._guardar_undo()
            self.tx.grid[self.cur[0]][self.cur[1]] = C.BLANCO
            self._limpiar_duda(self.cur[0], self.cur[1])
            self._mover_avance()
        elif ch and ch.upper() in C.ALFABETO:
            self._guardar_undo()
            self.tx.grid[self.cur[0]][self.cur[1]] = ch.upper()
            self._limpiar_duda(self.cur[0], self.cur[1])
            self._mover_avance()
        else:
            return

        self.tx._regenerar()
        self.redibujar()

    def _limpiar_duda(self, f, c):
        if self.tx.confianzas and f < len(self.tx.confianzas) and c < len(self.tx.confianzas[f]):
            self.tx.confianzas[f][c] = 1.0

    def _mover_avance(self):
        f, c = self.cur
        c += 1
        if c >= self.tx.cols:
            c = 0
            f += 1
        if f >= self.tx.filas:
            f = self.tx.filas - 1
            c = self.tx.cols - 1
        self.cur = [f, c]
        self.tx.cur = list(self.cur)

    def _mover_retroceso(self):
        f, c = self.cur
        c -= 1
        if c < 0:
            c = self.tx.cols - 1
            f -= 1
        if f < 0:
            f = 0
            c = 0
        self.cur = [f, c]
        self.tx.cur = list(self.cur)

    def _guardar_undo(self):
        self.historial.append(([f[:] for f in self.tx.grid],
                               [fc[:] for fc in self.tx.confianzas] if self.tx.confianzas else None,
                               list(self.cur)))
        if len(self.historial) > 50:
            self.historial.pop(0)

    def deshacer(self):
        if not self.historial:
            return
        g, cnf, cur = self.historial.pop()
        self.tx.grid = g
        self.tx.confianzas = cnf
        self.cur = cur
        self.tx.cur = list(cur)
        self.tx._regenerar()
        self.redibujar()

    def redibujar(self):
        if not self.winfo_exists():
            return

        f_act, c_act = self.cur
        val_act = (self.tx.grid[f_act][c_act]
                   if f_act < len(self.tx.grid) and c_act < len(self.tx.grid[0])
                   else "?")
        duda_act = False
        if (self.tx.confianzas and f_act < len(self.tx.confianzas)
                and c_act < len(self.tx.confianzas[f_act])):
            if (val_act not in (C.NEGRO, C.BLANCO)
                    and self.tx.confianzas[f_act][c_act] < LH.DUDA):
                duda_act = True

        info_txt = "Celda seleccionada: [Fila %d, Col %d]  ·  Valor: '%s'  [%s]" % (
            f_act + 1, c_act + 1, val_act, "⚠️ DUDOSA (?)" if duda_act else "✓ SEGURA"
        )
        self.lbl_activa.config(text=info_txt, fg=AMBAR if duda_act else VERDE)

        # 1. Dibujar Foto con recuadro
        h_disponible = max(350, self.cv_foto.winfo_height())
        w_disponible = max(300, self.cv_foto.winfo_width())

        factor = min(h_disponible / float(self.derecha.shape[0]),
                     w_disponible / float(self.derecha.shape[1]), 1.2)
        ancho_foto = max(40, int(self.derecha.shape[1] * factor))
        alto_foto = max(40, int(self.derecha.shape[0] * factor))
        self._escala_foto = factor

        foto_bgr = LH.panel_de_lectura(
            self.derecha, self.cajas, self.tx.grid, self.tx.confianzas)
        foto_res = cv2.resize(foto_bgr, (ancho_foto, alto_foto),
                              interpolation=cv2.INTER_AREA)
        foto_rgb = cv2.cvtColor(foto_res, cv2.COLOR_BGR2RGB)
        self._foto_tk = ImageTk.PhotoImage(Image.fromarray(foto_rgb))

        self.cv_foto.delete("all")
        self.cv_foto.create_image(0, 0, anchor="nw", image=self._foto_tk)

        # Resaltar la celda activa sobre la foto
        caja = self.cajas.get((f_act, c_act))
        if caja:
            bx0, by0, bx1, by1 = caja
            self.cv_foto.create_rectangle(
                bx0 * factor, by0 * factor, bx1 * factor, by1 * factor,
                outline=AMBAR, width=3
            )

        # 2. Dibujar Matriz Digital
        filas, cols = self.tx.filas, self.tx.cols
        h_mat_disp = max(350, self.cv_matriz.winfo_height())
        w_mat_disp = max(250, self.cv_matriz.winfo_width())

        lado = max(20, min((h_mat_disp - 30) // filas,
                           (w_mat_disp - 30) // cols, 60))
        self._lado_matriz = lado
        ancho_mat = cols * lado
        alto_mat = filas * lado

        mx0 = max(10, (w_mat_disp - ancho_mat) // 2)
        my0 = max(10, (h_mat_disp - alto_mat) // 2)
        self._geom_matriz = (mx0, my0)

        self.cv_matriz.delete("all")

        for f in range(filas):
            for c in range(cols):
                v = self.tx.grid[f][c]
                x = mx0 + c * lado
                y = my0 + f * lado
                es_dudosa = False
                if (self.tx.confianzas and f < len(self.tx.confianzas)
                        and c < len(self.tx.confianzas[f])):
                    if (v not in (C.NEGRO, C.BLANCO)
                            and self.tx.confianzas[f][c] < LH.DUDA):
                        es_dudosa = True

                color_fondo = NEGRO if v == C.NEGRO else (BLANCO if not es_dudosa else "#ffe0b2")
                self.cv_matriz.create_rectangle(x, y, x + lado, y + lado,
                                                fill=color_fondo, outline=BORDE)

                if v not in (C.NEGRO, C.BLANCO):
                    self.cv_matriz.create_text(
                        x + lado / 2, y + lado / 2, text=v, fill="#000000",
                        font=("Segoe UI", int(lado * 0.55), "bold")
                    )

                if es_dudosa:
                    self.cv_matriz.create_text(
                        x + lado - 7, y + 8, text="?", fill=ROJO,
                        font=("Segoe UI", max(8, int(lado * 0.28)), "bold")
                    )

                # Cursor activo
                if f == f_act and c == c_act:
                    self.cv_matriz.create_rectangle(
                        x, y, x + lado, y + lado, outline=AMBAR, width=3
                    )


# ##########################################################################
#  3. LA VENTANA
# ##########################################################################

class TxCamara(object):

    def __init__(self, root):
        self.root = root
        root.title("Tx CAMARA · Reconocimiento de Hoja · Redes I")
        root.configure(bg=FONDO)

        self.filas, self.cols = 4, 4
        self.grid = []
        self.confianzas = None          # matriz de confianza de lectura de foto
        self.debug_foto = None          # (derecha, cajas) para graficar
        self.ruta_fotografia = None
        self.cur = [0, 0]
        self.geom = None
        self.t0 = None
        self.historial = []

        self.modo = "editar"
        self.simbolos = []
        self.velocidad = SIMBOLOS_POR_SEGUNDO
        self.copias = COPIAS
        self.copia_actual = 0
        self.copias_enviadas = 0
        self.i = 0
        self.corriendo = False
        self.luz_fija = None
        self.arduino = None
        self.pantalla = None
        self.t_inicio_envio = None
        self._job_tic = None
        self._job_aviso = None

        self._construir()
        self.nueva_cuadricula(self.filas, self.cols)

    # ------------------------------------------------------------ montaje --
    def _contador(self, padre, texto, que):
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
        # ---- barra 1: tamaño de la cuadricula y carga de fotos ----
        top = tk.Frame(self.root, bg=FONDO)
        top.pack(fill="x", padx=8, pady=(6, 0))

        self.lbl_filas = self._contador(top, "Filas:", "filas")
        tk.Frame(top, bg=FONDO, width=14).pack(side="left")
        self.lbl_cols = self._contador(top, "Columnas:", "cols")

        tk.Button(top, text="Limpiar", command=self.limpiar).pack(side="left", padx=10)
        tk.Button(top, text="Deshacer (Ctrl+Z)", command=self.deshacer).pack(side="left")

        # Botones de fotografía
        tk.Button(top, text="📷 Buscar foto", bg="#2a5298", fg="white",
                  font=("Segoe UI", 9, "bold"),
                  command=self.buscar_fotografia).pack(side="left", padx=(10, 2))
        self.btn_diag = tk.Button(top, text="🔍 Ver diagnóstico",
                                  command=self.ver_diagnostico_foto)
        self.btn_diag.pack(side="left", padx=2)

        self.lbl_celdas = tk.Label(top, text="", bg=FONDO, fg="#888888",
                                   font=("Segoe UI", 9))
        self.lbl_celdas.pack(side="left", padx=10)

        self.lbl_t = tk.Label(top, text="00.0 s", bg=FONDO, fg=VERDE,
                              font=("Consolas", 18, "bold"))
        self.lbl_t.pack(side="right", padx=8)

        # ---- barra 2: velocidad y copias ----
        top2 = tk.Frame(self.root, bg=FONDO)
        top2.pack(fill="x", padx=8, pady=(2, 2))

        tk.Label(top2, text="símbolos/s:", bg=FONDO, fg="white").pack(side="left")
        self.esc_v = tk.Scale(top2, from_=VELOCIDAD_MIN, to=VELOCIDAD_MAX,
                              resolution=0.5, orient="horizontal", length=200,
                              bg=FONDO, fg="white", troughcolor="#333333",
                              highlightthickness=0, sliderrelief="flat",
                              command=self._on_velocidad)
        self.esc_v.set(self.velocidad)
        self.esc_v.pack(side="left", padx=4)

        tk.Label(top2, text="   copias:", bg=FONDO, fg="white").pack(side="left")
        tk.Button(top2, text="−", width=2, command=lambda: self.cambiar_copias(-1)
                  ).pack(side="left")
        self.lbl_copias = tk.Label(top2, text=str(self.copias), bg="#2b2b2b",
                                   fg="white", width=2, relief="sunken", bd=1,
                                   font=("Consolas", 12, "bold"))
        self.lbl_copias.pack(side="left", padx=2)
        tk.Button(top2, text="+", width=2, command=lambda: self.cambiar_copias(1)
                  ).pack(side="left")
        tk.Label(top2, text="(con 1 basta; las demás son un seguro)", bg=FONDO,
                 fg="#777777", font=("Segoe UI", 8)).pack(side="left", padx=6)

        # ---- barra 3: como se emite ----
        top3 = tk.Frame(self.root, bg=FONDO)
        top3.pack(fill="x", padx=8, pady=(0, 4))

        tk.Label(top3, text="Emitir con:", bg=FONDO, fg="white").pack(side="left")
        self.cbo = ttk.Combobox(top3, width=9, state="readonly",
                                values=puertos_disponibles())
        self.cbo.pack(side="left", padx=2)
        self.cbo.bind("<<ComboboxSelected>>", lambda e: self.foco_cuadricula())
        self.btn_con = tk.Button(top3, text="Conectar Arduino", command=self.conectar)
        self.btn_con.pack(side="left")
        self.btn_pant = tk.Button(top3, text="Modo PANTALLA (F8)",
                                  command=self.alternar_pantalla)
        self.btn_pant.pack(side="left", padx=8)
        tk.Label(top3, text="para probar sin LEDs: se le apunta la cámara",
                 bg=FONDO, fg="#777777", font=("Segoe UI", 8)).pack(side="left")

        # ---- cuerpo: cuadricula y panel de la trama ----
        cuerpo = tk.Frame(self.root, bg=FONDO)
        cuerpo.pack(fill="both", expand=True, padx=8)

        self.canvas = tk.Canvas(cuerpo, bg=FONDO, takefocus=1,
                                highlightthickness=3, highlightbackground=FONDO,
                                highlightcolor=CURSOR)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._click_celda)
        self.canvas.bind("<FocusIn>", lambda e: self.dibujar_grid())
        self.canvas.bind("<FocusOut>", lambda e: self.dibujar_grid())

        panel = tk.Frame(cuerpo, bg=PANEL)
        panel.pack(side="right", fill="y", padx=(8, 0))
        tk.Label(panel, text="La trama", bg=PANEL, fg=AZUL,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.lbl_trama = tk.Label(panel, text="", bg=PANEL, fg="#cccccc",
                                  font=("Consolas", 9), justify="left", anchor="w")
        self.lbl_trama.pack(anchor="w", padx=8)
        self.lbl_camara = tk.Label(panel, text="", bg=PANEL, fg=VERDE,
                                   font=("Segoe UI", 9), justify="left",
                                   anchor="w", wraplength=210)
        self.lbl_camara.pack(anchor="w", padx=8, pady=8)

        # ---- abajo: las dos luces y los controles ----
        bajo = tk.Frame(self.root, bg=FONDO)
        bajo.pack(fill="x", padx=8, pady=(4, 8))

        izq = tk.Frame(bajo, bg=FONDO)
        izq.pack(side="left")
        self.luces = tk.Canvas(izq, width=330, height=130, bg=FONDO,
                               highlightthickness=0)
        self.luces.pack()

        manual = tk.Frame(izq, bg=FONDO)
        manual.pack(pady=(4, 0))
        for estado, tecla, nombre, color in LUCES:
            tk.Button(manual, text="%s\n%s" % (tecla, nombre), bg=color,
                      fg="#dddddd" if estado == C.APAGADO else "#000000",
                      font=("Segoe UI", 9, "bold"), width=8,
                      command=lambda e=estado: self.luz_manual(e)
                      ).pack(side="left", padx=2)
        tk.Button(manual, text="*\nAVISO", bg="#e0a020", fg="black",
                  font=("Segoe UI", 9, "bold"), width=8,
                  command=self.avisar).pack(side="left", padx=(10, 0))

        der = tk.Frame(bajo, bg=FONDO)
        der.pack(side="left", fill="both", expand=True, padx=10)

        self.lbl_pos = tk.Label(der, text="", bg=FONDO, fg=AMBAR,
                                font=("Consolas", 12, "bold"), anchor="w")
        self.lbl_pos.pack(fill="x")
        self.lbl_est = tk.Label(der, text="", bg=FONDO, fg=AZUL,
                                font=("Segoe UI", 10), anchor="w", justify="left")
        self.lbl_est.pack(fill="x", pady=2)

        bot = tk.Frame(der, bg=FONDO)
        bot.pack(anchor="w", pady=6)
        self.btn_modo = tk.Button(bot, text="TRANSMITIR (F5)", bg=CURSOR,
                                  fg="white", font=("Segoe UI", 11, "bold"),
                                  command=self.cambiar_modo)
        self.btn_modo.pack(side="left")
        self.btn_play = tk.Button(bot, text="INICIAR (espacio)", width=18,
                                  font=("Segoe UI", 10, "bold"),
                                  command=self.alternar)
        self.btn_play.pack(side="left", padx=6)
        self.btn_parar = tk.Button(bot, text="PARAR (Esc)", width=12, bg=ROJO,
                                   fg="black", font=("Segoe UI", 10, "bold"),
                                   command=self.parar_y_avisar)
        self.btn_parar.pack(side="left")

        # ---- teclado ----
        for _, tecla, _, _ in LUCES:
            self.root.bind(tecla, self._tecla_luz)
        self.root.bind("<asterisk>", self._tecla_luz)
        self.root.bind("<Key>", self.on_key)
        self.root.bind("<F5>", lambda e: self.cambiar_modo())
        self.root.bind("<F8>", lambda e: self.alternar_pantalla())
        self.root.bind("<Escape>", self._escape)
        self.root.bind("<Control-z>", lambda e: self.deshacer())
        self.root.bind("<Configure>", lambda e: self.dibujar_grid())
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self._bucle()

    # ------------------------------------------------ carga desde foto --
    def buscar_fotografia(self):
        """Carga una fotografía de la hoja y llena la cuadrícula con lo que lee."""
        self.t0 = time.time()
        ruta = filedialog.askopenfilename(
            title="Seleccionar fotografía de la hoja",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.heic *.PNG *.JPG *.JPEG *.BMP"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not ruta:
            return

        self.lbl_est.config(
            text="Analizando fotografía con leer_hoja (quitar giro, homografía y plantillas)...",
            fg=AMBAR)
        self.root.update_idletasks()

        try:
            # Pipeline de PDI robusto (sin tesseract): devuelve grid y debug para graficar
            grid, nota, conf, debug = LH.leer_hoja_girando(ruta, devolver_debug=True)
            if not grid:
                raise ValueError("No se pudo detectar la cuadrícula en la foto (%s)" % nota)
        except Exception as error:
            messagebox.showerror("Leer fotografía", str(error))
            self.lbl_est.config(text="Error al leer foto: %s" % error, fg=ROJO)
            return

        self.ruta_fotografia = ruta
        self.parar()
        self.filas, self.cols = len(grid), len(grid[0])
        self.grid = grid
        self.confianzas = conf
        self.debug_foto = debug
        self.cur = [0, 0]
        self.historial = []
        self.modo = "editar"
        self.btn_modo.config(text="TRANSMITIR (F5)", bg=CURSOR)
        self._regenerar()
        self.foco_cuadricula()

        dudas = 0
        if conf:
            for f in range(self.filas):
                for c in range(self.cols):
                    if grid[f][c] not in (C.NEGRO, C.BLANCO) and conf[f][c] < LH.DUDA:
                        dudas += 1

        msg = "Matriz %dx%d cargada desde %s" % (self.filas, self.cols, Path(ruta).name)
        if dudas > 0:
            msg += " · ⚠️ %d celdas dudosas marcadas con '?'" % dudas
            self.lbl_est.config(text=msg, fg=AMBAR)
        else:
            self.lbl_est.config(text=msg, fg=VERDE)

        # Abrir inmediatamente el editor de diagnóstico lado a lado
        self.ver_diagnostico_foto()

    def ver_diagnostico_foto(self):
        """Abre la ventana interactiva de diagnóstico lado a lado para comparar y editar."""
        if not self.debug_foto or not self.ruta_fotografia:
            messagebox.showinfo(
                "Diagnóstico",
                "Primero carga una foto usando el botón '📷 Buscar foto'.")
            return
        derecha, cajas = self.debug_foto
        EditorDiagnostico(self.root, self, derecha, cajas,
                          titulo=Path(self.ruta_fotografia).name)

    # --------------------------------------------------------- cuadricula --
    def cambiar_tamano(self, que, delta):
        f, c = self.filas, self.cols
        if que == "filas":
            f = max(1, min(C.MAX_FILAS, f + delta))
        else:
            c = max(1, min(C.MAX_COLS, c + delta))
        if (f, c) == (self.filas, self.cols):
            return
        self._guardar_undo()
        self.grid = [[self.grid[i][j] if i < self.filas and j < self.cols
                      else C.NEGRO for j in range(c)] for i in range(f)]
        self.confianzas = None
        self.filas, self.cols = f, c
        self.cur = [min(self.cur[0], f - 1), min(self.cur[1], c - 1)]
        self._regenerar()
        self.foco_cuadricula()

    def cambiar_copias(self, delta):
        self.copias = max(1, min(5, self.copias + delta))
        self.lbl_copias.config(text=str(self.copias))
        self._regenerar()
        self.foco_cuadricula()

    def nueva_cuadricula(self, filas, cols):
        self.filas, self.cols = filas, cols
        self.grid = [[C.NEGRO] * cols for _ in range(filas)]
        self.confianzas = None
        self.debug_foto = None
        self.ruta_fotografia = None
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
        self.grid = [[C.NEGRO] * self.cols for _ in range(self.filas)]
        self.confianzas = None
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
        self.parar()
        try:
            self.simbolos, bits, payload = simbolos_del_bloque(self.grid)
            error = None
        except ValueError as e:
            self.simbolos, bits, payload = [], "", ""
            error = str(e)

        self.i = 0
        self.copia_actual = 0
        self.lbl_filas.config(text=str(self.filas))
        self.lbl_cols.config(text=str(self.cols))

        n = self.filas * self.cols
        if n > MAX_CELDAS:
            self.lbl_celdas.config(text="%d celdas · el enunciado pide máximo %d"
                                        % (n, MAX_CELDAS), fg=AMBAR)
        else:
            self.lbl_celdas.config(text="%d celdas" % n, fg="#888888")

        if error:
            self.lbl_trama.config(text="cuadrícula no válida:\n%s" % error)
            self.lbl_camara.config(text="")
        else:
            una = len(self.simbolos) / self.velocidad
            self.lbl_trama.config(
                text=("%d celdas\n%d bits útiles\n+%d de cabecera y CRC\n"
                      "= %d bits\n\n%d símbolos\n%.1f s por copia\n"
                      "%.1f s en total (x%d)"
                      % (n, len(payload), len(bits) - len(payload), len(bits),
                         len(self.simbolos), una, una * self.copias, self.copias)))
            self._avisar_camara()
        self.refrescar()

    def _avisar_camara(self):
        necesarios = self.velocidad * CUADROS_POR_SIMBOLO
        if necesarios <= 30:
            self.lbl_camara.config(
                text="La cámara necesita %d fps: vale con 30." % necesarios,
                fg=VERDE)
        elif necesarios <= FPS_CAMARA_RECEPTORA:
            self.lbl_camara.config(
                text="La cámara necesita %d fps: hay que grabar a 60."
                     % necesarios, fg=AMBAR)
        else:
            self.lbl_camara.config(
                text="DEMASIADO RÁPIDO: harían falta %d fps. A 60 fps el "
                     "máximo son %.1f símbolos/s."
                     % (necesarios, FPS_CAMARA_RECEPTORA / CUADROS_POR_SIMBOLO),
                fg=ROJO)

    # ------------------------------------------------------------ teclado --
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
        self.canvas.focus_set()
        self.dibujar_grid()

    def _escape(self, _=None):
        if self.corriendo:
            self.parar_y_avisar()
        else:
            self.foco_cuadricula()

    def on_key(self, ev):
        if self._foco_en_texto():
            return
        if self.modo == "transmitir":
            if ev.keysym == "space":
                self.alternar()
            return
        return self._tecla_editar(ev)

    def _tecla_editar(self, ev):
        k, ch = ev.keysym, ev.char
        if self.t0 is None and (ch or k == "BackSpace"):
            self.t0 = time.time()

        if k in ("Right", "Left", "Down", "Up"):
            self._mover({"Right": (0, 1), "Left": (0, -1),
                         "Down": (1, 0), "Up": (-1, 0)}[k])
            self.dibujar_grid()
            return
        if k == "Return":
            self.cur = [min(self.cur[0] + 1, self.filas - 1), 0]
            self.dibujar_grid()
            return

        # Al editar manualmente, la marca de duda de esa celda se limpia
        ci, cj = self.cur[0], self.cur[1]
        if self.confianzas and ci < len(self.confianzas) and cj < len(self.confianzas[ci]):
            self.confianzas[ci][cj] = 1.0

        if k == "BackSpace":
            self._guardar_undo()
            self._mover((0, -1))
            self.grid[self.cur[0]][self.cur[1]] = C.NEGRO
        elif ch in (".", " ", "#"):
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = C.NEGRO
            self._mover((0, 1))
        elif ch in ("-", "_"):
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = C.BLANCO
            self._mover((0, 1))
        elif ch and ch.upper() in C.ALFABETO:
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = ch.upper()
            self._mover((0, 1))
        else:
            return
        self._regenerar()

    def _mover(self, paso):
        di, dj = paso
        i, j = self.cur[0] + di, self.cur[1] + dj
        if dj:
            if j < 0:
                j, i = self.cols - 1, i - 1
            elif j >= self.cols:
                j, i = 0, i + 1
        self.cur = [max(0, min(i, self.filas - 1)), max(0, min(j, self.cols - 1))]

    def _tecla_luz(self, ev):
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
        self.canvas.focus_set()
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

    def _on_velocidad(self, valor):
        self.velocidad = float(valor)
        if self.arduino:
            self.arduino.velocidad(self.velocidad)
        self._regenerar()

    # ------------------------------------------------------------ Arduino --
    def conectar(self):
        if self.arduino:
            self.arduino.cerrar()
            self.arduino = None
            self.btn_con.config(text="Conectar Arduino")
            self.lbl_est.config(text="Arduino desconectado", fg=AZUL)
            return
        try:
            self.arduino = Arduino(self.cbo.get())
            self.arduino.velocidad(self.velocidad)
            self.btn_con.config(text="Soltar")
            self.lbl_est.config(text="Arduino en %s" % self.cbo.get(), fg=VERDE)
        except Exception as e:
            self.arduino = None
            messagebox.showerror(
                "Arduino", "%s\n\nSin Arduino se puede usar el modo PANTALLA "
                           "(F8) para probar." % e)
        self.foco_cuadricula()

    # ------------------------------------------- control manual de luces --
    def luz_manual(self, estado):
        self.parar()
        self.luz_fija = estado
        if self.arduino:
            self.arduino.fijar(estado)
        self.refrescar()

    def avisar(self):
        self.parar()
        patron = patron_aviso()
        if self.arduino:
            self.arduino.periodo_us(AVISO_T_S * 1e6)
            self.arduino.emitir(patron)
            self.arduino.velocidad(self.velocidad)
        self._animar_aviso(patron, 0)
        self.lbl_est.config(text="AVISO enviado · espera confirmación del receptor", fg=AMBAR)

    def _animar_aviso(self, patron, k):
        self._job_aviso = None
        if k >= len(patron):
            self.luz_fija = C.APAGADO
            self.refrescar()
            return
        self.luz_fija = patron[k]
        self.refrescar()
        self._job_aviso = self.root.after(int(AVISO_T_S * 1000),
                                          self._animar_aviso, patron, k + 1)

    # ------------------------------------------------------- transmision --
    def alternar(self):
        if not self.simbolos:
            return
        if self.modo == "editar":
            self.cambiar_modo()
        if self.corriendo:
            self.parar_y_avisar()
            return
        self.emitir()

    def emitir(self):
        if not self.simbolos:
            return
        if not self.arduino and self.pantalla is None:
            messagebox.showwarning(
                "Nada que mueva las luces",
                "Conecta el Arduino, o usa el modo PANTALLA (F8) para probar "
                "apuntándole la cámara.\n\nA %.1f símbolos por segundo no hay "
                "mano que siga el ritmo." % self.velocidad)
            return

        self.parar()
        self.corriendo = True
        self.luz_fija = None
        self.i = 0
        self.copia_actual = 0
        self.t_inicio_envio = time.time()
        if self.t0 is None:
            self.t0 = time.time()

        self.copias_enviadas = 0
        if self.arduino:
            self.arduino.velocidad(self.velocidad)
            self._mandar_copia(0)
            self.copias_enviadas = 1
        self._tic()
        self.refrescar()

    def _mandar_copia(self, k):
        if self.arduino and k < self.copias:
            self.arduino.emitir(self.simbolos)

    def _tic(self):
        self._job_tic = None
        if not self.corriendo or not self.simbolos:
            return

        transcurrido = time.time() - self.t_inicio_envio
        k = int(transcurrido * self.velocidad)
        copia, i = divmod(k, len(self.simbolos))

        if copia >= self.copias:
            self.corriendo = False
            self.lbl_est.config(
                text="TRANSMISIÓN COMPLETA en %.1f s" % transcurrido, fg=VERDE)
            if self.pantalla:
                self._pintar_pantalla(C.APAGADO)
            self.refrescar()
            return

        self.copia_actual = copia
        dentro = transcurrido * self.velocidad - copia * len(self.simbolos)
        if copia >= self.copias_enviadas and dentro >= HUECO_ENTRE_COPIAS:
            self._mandar_copia(copia)
            self.copias_enviadas = copia + 1

        self.i = i + 1
        if self.pantalla:
            self._pintar_pantalla(self.simbolos[i])
        self.refrescar()

        espera = (k + 1) / self.velocidad - transcurrido
        self._job_tic = self.root.after(max(1, int(espera * 1000)), self._tic)

    def _cancelar_temporizadores(self):
        for nombre in ("_job_tic", "_job_aviso"):
            job = getattr(self, nombre, None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
                setattr(self, nombre, None)

    def parar(self):
        self.corriendo = False
        self._cancelar_temporizadores()
        if self.arduino:
            self.arduino.cortar()
        if self.pantalla:
            self._pintar_pantalla(C.APAGADO)

    def parar_y_avisar(self):
        estaba = self.corriendo
        self.parar()
        if estaba:
            self.lbl_est.config(text="PARADO: las luces se apagaron", fg=ROJO)
        self.refrescar()

    # -------------------------------------------------- modo PANTALLA -----
    def alternar_pantalla(self):
        if self.pantalla is not None:
            self.pantalla.destroy()
            self.pantalla = None
            self.btn_pant.config(text="Modo PANTALLA (F8)")
            self.foco_cuadricula()
            return
        self.pantalla = tk.Toplevel(self.root)
        self.pantalla.title("luces")
        self.pantalla.configure(bg="black")
        self.pantalla.attributes("-fullscreen", True)
        self.pantalla.bind("<Escape>", lambda e: self.alternar_pantalla())
        self.lienzo = tk.Canvas(self.pantalla, bg="black", highlightthickness=0)
        self.lienzo.pack(fill="both", expand=True)
        self.pantalla.protocol("WM_DELETE_WINDOW", self.alternar_pantalla)
        self.btn_pant.config(text="Cerrar PANTALLA (F8)")
        self.pantalla.after(100, lambda: self._pintar_pantalla(C.APAGADO))

    def _pintar_pantalla(self, estado):
        if self.pantalla is None:
            return
        cv = self.lienzo
        if not cv.winfo_exists():
            return
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        r = max(20, min(W, H) // 12)
        sep = r * 1.2 if PANTALLA_LUCES_JUNTAS else max(W // 5, r * 5)
        cx, cy = W // 2, H // 2
        for centro, color, encendida in (
                (cx - sep // 2, PANTALLA_COLOR_A, estado in (C.LUZ_A, C.AMBAS)),
                (cx + sep // 2, PANTALLA_COLOR_B, estado in (C.LUZ_B, C.AMBAS))):
            if encendida:
                cv.create_oval(centro - r, cy - r, centro + r, cy + r,
                               fill=color, outline="")

    # ------------------------------------------------------------- dibujo --
    def refrescar(self):
        self.dibujar_grid()
        self.dibujar_luces()

    def dibujar_grid(self):
        c = self.canvas
        if not c.winfo_exists():
            return
        c.delete("all")
        W = max(c.winfo_width(), 300)
        H = max(c.winfo_height(), 200)
        s = max(18, min((W - 30) // self.cols, (H - 40) // self.filas, 70))
        x0, y0 = (W - s * self.cols) // 2, 8
        self.geom = (x0, y0, s)

        conf = getattr(self, "confianzas", None)

        for i in range(self.filas):
            for j in range(self.cols):
                v = self.grid[i][j]
                x, y = x0 + j * s, y0 + i * s
                c.create_rectangle(x, y, x + s, y + s, outline=BORDE,
                                   fill=NEGRO if v == C.NEGRO else BLANCO)
                if v not in (C.NEGRO, C.BLANCO):
                    c.create_text(x + s / 2, y + s / 2, text=v, fill="#000000",
                                  font=("Segoe UI", int(s * 0.55), "bold"))

                # Resaltar si la celda se leyó de foto con duda
                if conf and i < len(conf) and j < len(conf[i]):
                    if v not in (C.NEGRO, C.BLANCO) and conf[i][j] < LH.DUDA:
                        c.create_text(x + s - 7, y + 8, text="?", fill=ROJO,
                                      font=("Segoe UI", max(8, int(s * 0.28)), "bold"))

        if self.modo == "editar":
            i, j = self.cur
            c.create_rectangle(x0 + j * s, y0 + i * s, x0 + (j + 1) * s,
                               y0 + (i + 1) * s, outline=CURSOR, width=3)
            ayuda = ". o espacio o # = negro     - o _ = blanco     letras = A..Z Ñ     (rojo ? = celda dudosa)"
        else:
            ayuda = "modo TRANSMITIR: la cuadrícula está bloqueada (F5 para editar)"
        c.create_text(x0, y0 + s * self.filas + 16, anchor="w", fill="#888888",
                      text=ayuda, font=("Segoe UI", 10))

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

        if self.luz_fija is not None:
            estado = self.luz_fija
            etiqueta = "control manual"
        elif self.corriendo and self.i > 0:
            estado = self.simbolos[self.i - 1]
            etiqueta = "emitiendo"
        else:
            estado = None
            etiqueta = ""

        if estado is None:
            cv.create_text(165, 65, fill="#666666", font=("Segoe UI", 11),
                           text="pulsa TRANSMITIR (F5), o usa 1 2 3 0 para\n"
                                "probar las luces", justify="center")
        else:
            self._pintar_bolas(cv, estado)

        if self.corriendo:
            self.lbl_pos.config(
                text="copia %d/%d   ·   símbolo %d/%d   ·   %.1f símbolos/s"
                     % (self.copia_actual + 1, self.copias, self.i,
                        len(self.simbolos), self.velocidad))
            self.btn_play.config(text="PARAR (espacio)")
        else:
            self.btn_play.config(text="INICIAR (espacio)")
            if etiqueta == "control manual":
                self.lbl_pos.config(text="control manual   [%s]"
                                         % C.NOMBRES_ESTADO[estado])
            elif self.modo == "transmitir":
                self.lbl_pos.config(text="listo: %d símbolos x%d copias"
                                         % (len(self.simbolos), self.copias))
            else:
                self.lbl_pos.config(text="")

    def _pintar_bolas(self, cv, estado):
        for k, (nombre, color, encendida) in enumerate((
                ("A (roja)", "#ff3b30", estado in (C.LUZ_A, C.AMBAS)),
                ("B (verde)", "#34c759", estado in (C.LUZ_B, C.AMBAS)))):
            x = 90 + k * 150
            cv.create_oval(x - 45, 15, x + 45, 105,
                           fill=color if encendida else "#2a2a2a",
                           outline=BORDE, width=2)
            cv.create_text(x, 120, text=nombre, fill="#aaaaaa",
                           font=("Segoe UI", 9))

    # -------------------------------------------------------------- bucle --
    def _bucle(self):
        if self.t0 is not None:
            self.lbl_t.config(text="%04.1f s" % (time.time() - self.t0))
        self.root.after(100, self._bucle)

    def cerrar(self):
        self.parar()
        if self.arduino:
            self.arduino.cerrar()
        if self.pantalla is not None:
            self.pantalla.destroy()
        self.root.destroy()


def main():
    root = tk.Tk()
    TxCamara(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
