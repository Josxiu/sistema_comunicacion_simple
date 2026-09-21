# -*- coding: utf-8 -*-
"""TRANSMISOR PARA LA CAMARA: se carga o se digita la cuadricula y las luces
la emiten.

    Se abre en VS Code y se le da al boton de play. No lleva argumentos.

Es el companero de rx_camara.py. La diferencia con el transmisor manual es
la velocidad: aqui las luces van a 5-20 simbolos por segundo, asi que NO las
puede mover una persona. Las mueve el Arduino, o se usa el modo PANTALLA para
probar sin montar nada.

    EDITAR       se escribe la cuadricula.  . espacio # = negro   - _ = blanco
                 letras A..Z N   flechas   ENTER = fila siguiente   Ctrl+Z
                 las filas y columnas se cambian con los botones + y -
    TRANSMITIR   F5, y despues espacio (o el boton) para lanzar y para parar


DESDE UNA FOTO DE LA HOJA
-------------------------
La matriz tambien se carga de una foto, que es mucho mas rapido y se equivoca
menos que digitar 80 celdas a mano con el reloj corriendo.

    Buscar foto      se escoge la foto y se abre el encuadre, con la tabla YA
                     marcada: normalmente basta con darle a Enter. Medido
                     contra 27 fotos del telefono de 8 hojas distintas: 1671 de
                     1693 celdas bien, y las 22 que fallan salen TODAS marcadas
                     con ?. Ninguna se da por buena estando mal, que es el
                     unico error que no se veria.
    Con la camara    lo mismo pero en vivo. La camara se escoge en el
                     desplegable de al lado y el ↻ vuelve a buscarlas, que
                     DroidCam aparece y desaparece al enchufar el telefono.
                     ESPACIO junta una lectura con las anteriores y al final
                     gana, celda por celda, lo que mas se haya repetido; Q
                     sale. Cada ESPACIO cuenta UNA lectura nueva: tenerlo
                     pulsado no sirve para juntar mas rapido.
                     En vivo la tabla se recorta sola y se marca en naranja,
                     porque la camara entrega en horizontal y la hoja sale
                     pequeña en medio.
    Ver diagnostico  la hoja enderezada al lado de la matriz leida, para
                     comparar celda por celda y corregir a mano. Es lo que hay
                     que mirar cuando algo no cuadra.
    Ctrl+R           volver a encuadrar la ultima foto, desde la ventana
                     principal o desde el diagnostico.

El ? rojo marca una celda que el lector no las tiene todas consigo. Escribir
encima de ella la da por revisada. Al transmitir se pregunta si quedan ?, y
con motivo: el CRC protege la TRAMA, no la FOTO, asi que una letra mal leida
llega al receptor con su CRC bueno y nadie se entera.

Quien lee es leer_hoja.py, que esta al lado, y se mide con el banco de
camara/pruebas/hoja/probar_fotos.py. Aqui solo estan las ventanas.

En cualquiera de los dos modos, 1 2 3 0 prenden y apagan las luces A MANO, sin
transmitir nada: sirve para apuntarlas y para comprobar el cableado. Son las
MISMAS teclas que usa el receptor manual. El * manda el AVISO, un parpadeo
rapido de las dos que quiere decir "preparate, voy a transmitir".

PARAR de verdad para las luces, no solo la cuenta de la pantalla: al Arduino
se le manda la trama entera de un golpe y se queda ocupado varios segundos,
asi que hay que decirle que corte (la orden Z del firmware).


DE DONDE SALE LA CODIFICACION
-----------------------------
De rx_camara.py, que esta al lado. No se copia aqui a proposito: si el emisor
y el receptor tuvieran cada uno su copia del codigo, cualquier cambio en uno
dejaria de entenderse con el otro y no habria manera de saberlo hasta el dia
de la transmision. El receptor sigue funcionando solo; es este el que depende
de el, y no al reves.


CUANTAS COPIAS MANDAR
---------------------
Con UNA basta. El receptor corta la grabacion en rafagas y le vale con que una
pase el CRC; probado sobre la grabacion buena, cada copia por separado se
descifra entera. Las copias de mas son un seguro por si a una le pasa algo
(alguien se cruza, la camara se mueve, la exposicion cambia), no un requisito:
2 es un termino medio comodo y 3 solo si el enlace esta feo.


EL ARDUINO
----------
Es el mismo firmware que el del modo manual (relaylink/relaylink.ino, v3.1) y
no hay que cambiarle nada: recibe una lista de estados y los sostiene el tiempo
que se le diga. Lo unico distinto es el periodo, que aqui son decenas de
milisegundos en vez de un segundo. Caben 512 simbolos por orden, y la trama mas
larga de un bloque de 80 celdas son unos 370.

    D9  -> luz A (roja)      D10 -> luz B (verde)

Redes de Computadores I - UdeA 2026-2 - Proyecto 01
"""

import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rx_camara as C          # la codificacion, compartida con el receptor

# cv2 y numpy no son opcionales: los trae rx_camara, que es de donde sale la
# codificacion, asi que si falta alguno este programa no arranca de todas
# formas. Por eso leer_hoja tampoco añade dependencias nuevas: solo usa esos.
import cv2

# --- lo que SI puede faltar ----------------------------------------------
# El dia de la prueba lo que no puede pasar es que el transmisor no abra. Todo
# lo de la foto es un extra encima de digitar la matriz a mano, asi que si algo
# de eso falta el programa arranca igual y lo unico que se pierde es el boton.
#
#   leer_hoja      el lector y plantillas.npz, los dos en esta misma carpeta
#   PIL            solo para ENSEÑAR imagenes dentro de Tkinter (recorte y
#                  diagnostico). Sin ella la foto se puede leer igual, solo
#                  que sin poder encuadrarla ni revisarla lado a lado.
#   pygrabber      solo para saber el NOMBRE de cada camara; sin ella salen
#                  numerados. Ya era opcional dentro de rx_camara.
try:
    import leer_hoja as LH
except Exception as _e:                 # falta el modulo o plantillas.npz
    LH, FALTA_LECTOR = None, str(_e)
else:
    FALTA_LECTOR = None

try:
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None


# ##########################################################################
#  0. PARAMETROS
#     Todo lo ajustable, junto. Los del receptor estan en rx_camara.py.
# ##########################################################################

# Velocidad de arranque, en simbolos por segundo. El deslizador la cambia.
SIMBOLOS_POR_SEGUNDO = 5.0
VELOCIDAD_MIN = 1.0
VELOCIDAD_MAX = 20.0

# Copias de la trama que se mandan seguidas. Ver la nota del encabezado: con
# una basta, las demas son un seguro.
COPIAS = 2

# Cuanto se espera, en fracciones de simbolo, antes de pasarle a la placa la
# copia siguiente. No es un capricho: mientras la placa este emitiendo, lo que
# le llegue se queda en su buffer, y si ahi hay una orden esperando, la Z de
# cortar queda detras y PARAR no surte efecto hasta que acabe la copia.
#
# Mandandola un pelin DESPUES de la frontera, la placa ya termino y su buffer
# esta vacio, asi que la Z entra sola. El hueco son milisegundos de luces
# apagadas entre copia y copia, que al receptor le da igual porque corta la
# grabacion en rafagas de todos modos.
#
# Con el firmware v3.2 esto sobra -alli la Z se busca en todo lo que haya
# llegado- pero asi PARAR funciona tambien con la placa sin reprogramar.
HUECO_ENTRE_COPIAS = 0.35

# Cuadros por simbolo que necesita la camara del receptor. Sirve para avisar
# en la propia ventana si la velocidad elegida se pasa de lo que puede seguir.
# Es el mismo numero que usa rx_camara.py, y esta medido, no inventado.
CUADROS_POR_SIMBOLO = C.CUADROS_POR_SIMBOLO_MIN
FPS_CAMARA_RECEPTORA = 60

# El maximo de celdas que pide el enunciado.
MAX_CELDAS = 80

# --- modo PANTALLA (probar sin LEDs) -------------------------------------
# Parpadea dos circulos en una ventana a pantalla completa, para apuntarle la
# camara y probar el sistema entero sin montar nada.
#   False  los dos circulos SEPARADOS -> el receptor los lee por posicion
#   True   pegados, como dos luces que se funden a lo lejos -> por color
PANTALLA_LUCES_JUNTAS = False
PANTALLA_COLOR_A = "#ff2020"       # luz A
PANTALLA_COLOR_B = "#20ff40"       # luz B

# --- aviso ---------------------------------------------------------------
# Parpadeo rapido de las dos luces: "preparate, voy a transmitir". Va mucho
# mas rapido que un simbolo, asi que no se puede confundir con datos.
AVISO_DESTELLOS = 6
AVISO_T_S = 0.12

# --- colores de la ventana ----------------------------------------------
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

# Las cuatro teclas del control manual son LAS MISMAS que usa el receptor
# manual para apuntar lo que ve.  (estado, tecla, rotulo, color)
LUCES = [
    (C.LUZ_A, "1", "solo ROJA", "#ff3b30"),
    (C.LUZ_B, "2", "solo VERDE", "#34c759"),
    (C.AMBAS, "3", "LAS DOS", "#ffd54f"),
    (C.APAGADO, "0", "NINGUNA", "#555555"),
]
TECLA_AVISO = "asterisk"


# ##########################################################################
#  1. EL ARDUINO
#     Opcional para apuntar y avisar; obligatorio para transmitir de verdad,
#     porque a estas velocidades no hay mano que siga el ritmo.
# ##########################################################################

def puertos_disponibles():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


def _empaquetar(simbolos):
    """Estados -> hexadecimal, 2 bits por simbolo y 4 simbolos por byte."""
    datos = bytearray((len(simbolos) + 3) // 4)
    for i, s in enumerate(simbolos):
        datos[i >> 2] |= (s & 3) << (6 - 2 * (i & 3))
    return datos.hex().upper()


class Arduino(object):
    """Enlace con relaylink.ino. Escribe y sigue: no se queda esperando, para
    que la ventana no se congele mientras las luces conmutan."""

    MAX_SIMBOLOS = 512          # el mismo limite que declara el firmware

    def __init__(self, puerto):
        import serial                       # pyserial: pip install pyserial
        self.ser = serial.Serial(puerto, 115200, timeout=0.1)
        time.sleep(2.0)                     # el Arduino se reinicia al abrir
        self.ser.reset_input_buffer()

    def velocidad(self, simbolos_por_s):
        """Periodo de simbolo. Aqui una ranura del firmware ES un simbolo: el
        modo manual las parte en cuatro para el mini parpadeo, pero el codigo
        de linea de la camara nunca repite simbolo, asi que no hace falta."""
        self.ser.write(b"S:%d\n" % int(1e6 / max(0.1, simbolos_por_s)))

    def periodo_us(self, us):
        """Periodo directo, en microsegundos. Lo usa el aviso, que va rapido."""
        self.ser.write(b"S:%d\n" % int(us))

    def emitir(self, simbolos):
        self.ser.write(b"X:%d:%s\n" % (len(simbolos),
                                       _empaquetar(simbolos).encode()))

    def cortar(self):
        """Aborta lo que la placa este emitiendo ahora mismo.

        Hace falta porque emitir() le manda la trama ENTERA de un golpe y la
        placa se queda ocupada varios segundos: sin esto, PARAR solo detendria
        la cuenta de la pantalla y las luces seguirian solas hasta el final.
        El firmware mira si llego una 'Z' entre simbolo y simbolo.
        """
        self.ser.write(b"Z\n")

    def fijar(self, estado):
        """Deja las luces en uno de los 4 estados, sin transmitir nada."""
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
#     Lo unico que sabe este archivo de codificacion: como pasar de la
#     cuadricula a la lista de estados. Todo lo demas lo hace rx_camara.
# ##########################################################################

def simbolos_del_bloque(grid):
    """Cuadricula -> (simbolos, bits, payload) listos para emitir."""
    payload = C.celdas_a_bits(grid)
    bits = C.construir_trama(C.TIPO_BLOQUE, len(grid), len(grid[0]), payload)
    return C.codificar_linea(bits), bits, payload


def patron_aviso():
    """Las dos luces parpadeando: encendidas y apagadas, varias veces."""
    return [C.AMBAS if i % 2 == 0 else C.APAGADO
            for i in range(AVISO_DESTELLOS * 2)]


# ##########################################################################
#  2.5 CARGAR LA MATRIZ DESDE UNA FOTO DE LA HOJA
#
#     Todo esto es un EXTRA encima de digitar la matriz a mano: si falta
#     alguna pieza (ver los import de arriba) el transmisor arranca igual y
#     solo se apagan los botones. Lo que nunca puede pasar el dia de la
#     prueba es que el programa no abra.
#
#     El lector de verdad es leer_hoja.py, que esta al lado; aqui solo esta
#     la parte de ventanas. La misma separacion que con rx_camara.py: una
#     sola copia de cada cosa, y el banco de camara/pruebas/hoja mide
#     exactamente el codigo que corre aqui.
# ##########################################################################

# Donde van las fotos que el programa guarda mientras se usa. NO es la carpeta
# de fotos del banco de pruebas, que esta versionada: capturas/ esta en
# .gitignore, se crea sola y se puede borrar entera sin perder nada.
CARPETA_CAPTURAS = Path(__file__).resolve().parent / "capturas"


def hay_lector():
    """Si se puede leer una hoja de una foto, y si no por que no.

    Devuelve (si_se_puede, motivo). El motivo sale en la barra de estado, que
    es mas util que un boton apagado sin explicacion.
    """
    if LH is None:
        return False, "falta leer_hoja.py (%s)" % FALTA_LECTOR
    try:
        LH.Plantillas()
    except Exception as e:
        return False, "falta plantillas.npz al lado de leer_hoja.py (%s)" % e
    return True, ""


def guardar_captura(nombre, imagen):
    """Guarda una foto de trabajo en capturas/ y devuelve su ruta, o None.

    Si no se puede escribir -carpeta de solo lectura, disco lleno- no pasa
    nada: la foto ya esta cargada en memoria y el programa sigue. Lo unico que
    se pierde es poder volver a recortarla desde el disco.
    """
    try:
        CARPETA_CAPTURAS.mkdir(parents=True, exist_ok=True)
        ruta = CARPETA_CAPTURAS / nombre
        if cv2.imwrite(str(ruta), imagen):
            return ruta
    except Exception:
        pass
    return None


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
        # Ctrl+R tambien aqui: esta ventana es la que se mira para decidir si
        # hay que volver a encuadrar, y el atajo de la principal no llega a
        # ella por ser otra ventana con su propio foco.
        self.bind("<Control-r>", lambda e: self._reencuadrar())
        self.bind("<Control-R>", lambda e: self._reencuadrar())
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

        self.lbl_q = tk.Label(top, text="", bg=PANEL,
                              font=("Segoe UI", 10, "bold"))
        self.lbl_q.pack(side="left", padx=4)
        self._estado_lectura()

        tk.Button(top, text="✓ Listo / Cerrar (Esc)", bg=CURSOR, fg="white",
                  font=("Segoe UI", 9, "bold"),
                  command=self.destroy).pack(side="right", padx=4)
        tk.Button(top, text="✂️ Re-recortar foto", bg="#2b6b55", fg="white",
                  font=("Segoe UI", 9),
                  command=self._reencuadrar).pack(side="right", padx=4)
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

    def _reencuadrar(self):
        self.destroy()
        self.tx.recortar_fotografia()

    def _estado_lectura(self):
        """Lo que queda por hacer antes de transmitir, dicho sin rodeos.

        Antes aqui se recalculaba la calidad con _calidad() sobre las
        confianzas de la cuadricula. Ya no vale: esas confianzas llevan
        los ceros de la comprobacion de estabilidad y las que el usuario
        limpia al corregir, asi que el numero no se podia comparar con
        CALIDAD_FIRME. Lo que importa es si la lectura fue floja y cuantas
        ? quedan, y eso si cambia bien a medida que se corrige.
        """
        pendientes = self.tx.celdas_por_revisar()
        if self.tx.lectura_floja:
            txt, col = ("LECTURA FLOJA: revisa todas las celdas, "
                        "no solo las ?  (%d ?)" % pendientes), ROJO
        elif pendientes:
            txt, col = "%d celdas por revisar (?)" % pendientes, AMBAR
        else:
            txt, col = "Nada pendiente de revisar", VERDE
        self.lbl_q.config(text="  ·  " + txt, fg=col)

    def redibujar(self):
        if not self.winfo_exists():
            return
        self._estado_lectura()

        f_act, c_act = self.cur
        val_act = (self.tx.grid[f_act][c_act]
                   if f_act < len(self.tx.grid) and c_act < len(self.tx.grid[0])
                   else "?")
        duda_act = LH.es_dudosa(self.tx.confianzas, f_act, c_act)

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
                es_dudosa = LH.es_dudosa(self.tx.confianzas, f, c)

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


def detectar_camaras_disponibles(hasta=8):
    """Detecta las cámaras conectadas mostrando sus nombres reales (vía pygrabber / DirectShow)
    y su resolución activa probando los backends del sistema (DSHOW, MSMF, ANY),
    exactamente igual que en rx_camara.py.
    """
    nombres = C.nombres_camaras(hasta)
    encontradas = []

    limite = max(len(nombres), hasta) if nombres else hasta
    for i in range(limite):
        nom_disp = nombres[i] if (nombres and i < len(nombres)) else ("Cámara %d" % i)
        res_txt = None
        cap = None
        for backend in C.backends_de_camara():
            try:
                cap = cv2.VideoCapture(i, backend)
                if cap.isOpened():
                    ok, f = C.leer_cuadro(cap)
                    if not ok:
                        for _ in range(3):
                            ok2, f2 = C.leer_cuadro(cap)
                            if ok2:
                                ok, f = ok2, f2
                                break
                    if ok and f is not None:
                        res_txt = "%dx%d" % (f.shape[1], f.shape[0])
                        break
            except Exception:
                pass
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        if res_txt:
            encontradas.append((str(i), "%d: %s (%s)" % (i, nom_disp, res_txt)))
        elif nombres and i < len(nombres):
            encontradas.append((str(i), "%d: %s (disponible)" % (i, nom_disp)))

    if not encontradas and nombres:
        for i, nom in enumerate(nombres):
            encontradas.append((str(i), "%d: %s" % (i, nom)))

    if not encontradas:
        encontradas.append(("0", "0: Cámara por defecto"))

    return encontradas


class DialogoSelectorCamara(tk.Toplevel):
    """Diálogo para escoger entre cámaras locales o conectar celular por URL."""

    def __init__(self, master, on_conectar):
        super().__init__(master)
        self.on_conectar = on_conectar
        self.title("Tomar foto con cámara / celular")
        self.configure(bg=FONDO)
        self.resizable(False, False)
        self.geometry("500x280")

        self._camaras = detectar_camaras_disponibles()

        tk.Label(self, text="Seleccionar cámara o celular", bg=FONDO, fg=AZUL,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(self, text="Apunta la cámara a la hoja para ver la rejilla en vivo.\n"
                            "En el visor: ESPACIO captura la foto, Q o Esc sale.",
                 bg=FONDO, fg="#aaaaaa", font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=16, pady=(0, 8))

        frame_disp = tk.Frame(self, bg=FONDO)
        frame_disp.pack(fill="x", padx=16, pady=4)
        tk.Label(frame_disp, text="Dispositivo detectado:", bg=FONDO, fg="white",
                 font=("Segoe UI", 9)).pack(anchor="w")

        opciones = [etiq for _, etiq in self._camaras]
        self.cbo = ttk.Combobox(frame_disp, values=opciones, state="readonly", width=46)

        # Si DroidCam está conectada, auto-seleccionarla; si no, la primera disponible
        idx_defecto = 0
        for i, (_, etiq) in enumerate(self._camaras):
            if "droidcam" in etiq.lower():
                idx_defecto = i
                break
        self.cbo.current(idx_defecto)
        self.cbo.pack(fill="x", pady=2)

        frame_url = tk.Frame(self, bg=FONDO)
        frame_url.pack(fill="x", padx=16, pady=6)
        tk.Label(frame_url, text="O escribe la URL del celular (IP Webcam / Wi-Fi):",
                 bg=FONDO, fg="#cccccc", font=("Segoe UI", 9)).pack(anchor="w")
        self.ent_url = tk.Entry(frame_url, font=("Consolas", 9), bg="#2b2b2b",
                                fg="white", insertbackground="white")
        self.ent_url.pack(fill="x", pady=2)
        tk.Label(frame_url, text="Ejemplo: http://192.168.1.50:8080/video (déjalo vacío si usas webcam o DroidCam)",
                 bg=FONDO, fg="#777777", font=("Segoe UI", 8)).pack(anchor="w")

        bot = tk.Frame(self, bg=FONDO)
        bot.pack(fill="x", padx=16, pady=(12, 10))

        tk.Button(bot, text="📸 Iniciar visor en vivo", bg="#1b6ca8", fg="white",
                  font=("Segoe UI", 10, "bold"),
                  command=self._iniciar).pack(side="left")
        tk.Button(bot, text="Cancelar", bg="#333333", fg="white",
                  font=("Segoe UI", 10),
                  command=self.destroy).pack(side="right")

        self.transient(master)
        self.grab_set()

    def _iniciar(self):
        url = self.ent_url.get().strip()
        if url:
            fuente = url
        else:
            idx = self.cbo.current()
            fuente = self._camaras[idx][0] if 0 <= idx < len(self._camaras) else "0"
        self.destroy()
        self.on_conectar(fuente)


class VentanaRecorte(tk.Toplevel):
    """Ventana interactiva para revisar, recortar y encuadrar la matriz de una fotografía.

    Permite:
      - Arrastrar un recuadro con el ratón alrededor de la cuadrícula (opcional).
      - Girar la imagen 90° si está de lado.
      - Continuar directamente con la foto completa o con el área recortada.
    """

    def __init__(self, master, imagen, on_aplicar, titulo="Foto"):
        super().__init__(master)
        self.master = master
        self.imagen_original = imagen.copy()
        self.imagen_actual = imagen.copy()
        self.on_aplicar = on_aplicar
        self.titulo = titulo

        self.title("📷 Revisar y Recortar Foto")
        self.configure(bg=FONDO)
        self.geometry("960x720")
        self.minsize(750, 520)

        self.start_x = None
        self.start_y = None
        self.sel_rect = None       # (ix0, iy0, ix1, iy1) en coords de imagen_actual
        self._escala = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._disp_w = 100
        self._disp_h = 100
        self._img_tk = None

        # La tabla se busca sola y se deja YA SELECCIONADA, asi que lo normal
        # es abrir y darle a Enter. No se recorta por las bravas a proposito:
        # sobre el banco, recortando siempre aparecian dos celdas mal leidas y
        # dadas por buenas, y el margen del recorte resulto puntiagudo (0,14
        # daba treinta y cuatro). Sugerirlo y que lo confirme una persona da lo
        # bueno de las dos cosas: rapido, pero con alguien mirando.
        self.sel_rect = self._sugerir_recorte()
        self.sugerido = self.sel_rect is not None

        self._construir()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._aplicar())
        self.after(60, self._cargar_imagen)

    def _sugerir_recorte(self):
        """Donde cree leer_hoja que esta la tabla, o None."""
        if LH is None:
            return None
        try:
            caja = LH.buscar_la_tabla(self.imagen_actual)
        except Exception:
            return None
        if caja is None:
            return None
        x0, y0, x1, y1 = caja
        H, W = self.imagen_actual.shape[:2]
        # Si lo que propone es casi la foto entera, no vale la pena proponerlo:
        # mejor dejarlo sin seleccion y que se vea que no hace falta recortar.
        if (x1 - x0) * (y1 - y0) > 0.85 * W * H:
            return None
        return (x0, y0, x1, y1)

    def _construir(self):
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="📷 " + self.titulo,
                 bg=PANEL, fg=AZUL, font=("Segoe UI", 12, "bold")).pack(side="left")

        tk.Button(top, text="✓ Continuar y Analizar (Enter)", bg="#2b6b55", fg="white",
                  font=("Segoe UI", 9, "bold"),
                  command=self._aplicar).pack(side="right", padx=4)
        tk.Button(top, text="🖼️ Foto completa", bg="#3a4f66", fg="white",
                  font=("Segoe UI", 9),
                  command=self._quitar_recorte).pack(side="right", padx=4)
        tk.Button(top, text="🔄 Girar 90°", bg="#444444", fg="white",
                  font=("Segoe UI", 9),
                  command=self._girar_90).pack(side="right", padx=6)
        tk.Button(top, text="↺ Restablecer", bg="#444444", fg="white",
                  font=("Segoe UI", 9),
                  command=self._restablecer).pack(side="right", padx=2)
        tk.Button(top, text="Cancelar (Esc)", bg="#333333", fg="white",
                  font=("Segoe UI", 9),
                  command=self.destroy).pack(side="right", padx=4)

        self.lbl_dims = tk.Label(
            self,
            text="Arrastra con el ratón sobre la foto para recortar la matriz si lo deseas, o pulsa Enter para continuar completa.",
            bg=FONDO, fg=AMBAR, font=("Segoe UI", 10, "bold"), anchor="w")
        self.lbl_dims.pack(fill="x", padx=14, pady=(2, 4))

        marco_canvas = tk.Frame(self, bg=NEGRO, bd=1, relief="sunken")
        marco_canvas.pack(fill="both", expand=True, padx=10, pady=4)

        self.canvas = tk.Canvas(marco_canvas, bg="#0d0d0d", cursor="cross", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda e: self._cargar_imagen())

        pie = tk.Frame(self, bg=FONDO)
        pie.pack(fill="x", padx=10, pady=(2, 8))
        tk.Label(pie, text="💡 Consejo: Si recortas, deja un borde pequeño de papel blanco alrededor de la tabla. Enter para aplicar.",
                 bg=FONDO, fg="#888888", font=("Segoe UI", 9)).pack(side="left")

    def _cargar_imagen(self):
        if not self.winfo_exists():
            return
        cw = max(200, self.canvas.winfo_width())
        ch = max(200, self.canvas.winfo_height())
        H, W = self.imagen_actual.shape[:2]

        factor = min(cw / float(W), ch / float(H), 1.0)
        disp_w = max(20, int(W * factor))
        disp_h = max(20, int(H * factor))
        self._escala = factor
        self._disp_w = disp_w
        self._disp_h = disp_h
        self._offset_x = (cw - disp_w) // 2
        self._offset_y = (ch - disp_h) // 2

        res = cv2.resize(self.imagen_actual, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
        if res.ndim == 2:
            rgb = cv2.cvtColor(res, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(res, cv2.COLOR_BGR2RGB)
        self._img_tk = ImageTk.PhotoImage(Image.fromarray(rgb))

        self.canvas.delete("all")
        self.canvas.create_image(self._offset_x, self._offset_y, anchor="nw", image=self._img_tk)

        if self.sel_rect:
            self._dibujar_seleccion()
        else:
            self.lbl_dims.config(
                text="Arrastra con el ratón sobre la foto para recortar la matriz si lo deseas, o pulsa Enter para continuar completa.")
            self.sugerido = False

    def _quitar_recorte(self):
        self.sel_rect = None
        self.canvas.delete("sel_box")
        self.canvas.delete("sel_temp")
        self.lbl_dims.config(
            text="Foto completa seleccionada (sin recorte)  ·  Pulsa Enter para analizar")

    def _on_press(self, ev):
        self.start_x = max(self._offset_x, min(self._offset_x + self._disp_w, ev.x))
        self.start_y = max(self._offset_y, min(self._offset_y + self._disp_h, ev.y))

    def _on_drag(self, ev):
        if self.start_x is None:
            return
        cur_x = max(self._offset_x, min(self._offset_x + self._disp_w, ev.x))
        cur_y = max(self._offset_y, min(self._offset_y + self._disp_h, ev.y))
        self.canvas.delete("sel_temp")
        self.canvas.create_rectangle(self.start_x, self.start_y, cur_x, cur_y,
                                    outline="#ffd54f", width=2, dash=(6, 3), tags="sel_temp")
        w_px = int(abs(cur_x - self.start_x) / self._escala)
        h_px = int(abs(cur_y - self.start_y) / self._escala)
        self.lbl_dims.config(text="Área de recorte: %d × %d píxeles" % (w_px, h_px))

    def _on_release(self, ev):
        if self.start_x is None:
            return
        cur_x = max(self._offset_x, min(self._offset_x + self._disp_w, ev.x))
        cur_y = max(self._offset_y, min(self._offset_y + self._disp_h, ev.y))
        x0, x1 = min(self.start_x, cur_x), max(self.start_x, cur_x)
        y0, y1 = min(self.start_y, cur_y), max(self.start_y, cur_y)

        # Si el arrastre fue insignificante, ignorar
        if (x1 - x0) > 15 and (y1 - y0) > 15:
            ix0 = (x0 - self._offset_x) / self._escala
            iy0 = (y0 - self._offset_y) / self._escala
            ix1 = (x1 - self._offset_x) / self._escala
            iy1 = (y1 - self._offset_y) / self._escala
            H, W = self.imagen_actual.shape[:2]
            ix0 = max(0, min(W - 20, int(ix0)))
            iy0 = max(0, min(H - 20, int(iy0)))
            ix1 = max(ix0 + 20, min(W, int(ix1)))
            iy1 = max(iy0 + 20, min(H, int(iy1)))
            self.sel_rect = (ix0, iy0, ix1, iy1)
            self.sugerido = False

        self.start_x, self.start_y = None, None
        self._dibujar_seleccion()

    def _dibujar_seleccion(self):
        self.canvas.delete("sel_box")
        self.canvas.delete("sel_temp")
        if not self.sel_rect:
            return
        ix0, iy0, ix1, iy1 = self.sel_rect
        sx0 = self._offset_x + ix0 * self._escala
        sy0 = self._offset_y + iy0 * self._escala
        sx1 = self._offset_x + ix1 * self._escala
        sy1 = self._offset_y + iy1 * self._escala

        self.canvas.create_rectangle(sx0, sy0, sx1, sy1,
                                    outline="#ffd54f", width=3, tags="sel_box")
        # Esquinas marcadas
        for ex, ey in ((sx0, sy0), (sx1, sy0), (sx0, sy1), (sx1, sy1)):
            self.canvas.create_oval(ex - 4, ey - 4, ex + 4, ey + 4,
                                    fill="#2f7de1", outline="white", tags="sel_box")

        w_px, h_px = int(ix1 - ix0), int(iy1 - iy0)
        if getattr(self, "sugerido", False):
            self.lbl_dims.config(
                text="Aquí cree el programa que está la matriz (%d × %d px)  ·  "
                     "Enter para aceptar, arrastra para cambiarlo, o "
                     "'Foto completa'" % (w_px, h_px))
        else:
            self.lbl_dims.config(
                text="Recorte seleccionado: %d × %d píxeles  (Enter para aplicar, o 'Foto completa' para quitar)" % (w_px, h_px))

    def _girar_90(self):
        self.imagen_actual = cv2.rotate(self.imagen_actual, cv2.ROTATE_90_CLOCKWISE)
        # la sugerencia se rehace sobre la imagen girada, que la de antes ya no
        # cae donde estaba
        self.sel_rect = self._sugerir_recorte()
        self.sugerido = self.sel_rect is not None
        self._cargar_imagen()

    def _restablecer(self):
        self.imagen_actual = self.imagen_original.copy()
        self.sel_rect = self._sugerir_recorte()
        self.sugerido = self.sel_rect is not None
        self._cargar_imagen()

    def _aplicar(self):
        if self.sel_rect is None:
            recorte = self.imagen_actual.copy()
            es_recorte = False
        else:
            x0, y0, x1, y1 = self.sel_rect
            recorte = self.imagen_actual[y0:y1, x0:x1].copy()
            es_recorte = True
        self.destroy()
        # Antes esto iba en un try/except TypeError con una segunda llamada de
        # respaldo. Era una trampa: un TypeError de DENTRO de on_aplicar -o sea,
        # un error de verdad- se tragaba y la foto se analizaba DOS veces. El
        # unico que la llama le pasa los dos argumentos.
        self.on_aplicar(recorte, es_recorte)


# ##########################################################################
#  3. LA VENTANA
# ##########################################################################

class TxCamara(object):

    def __init__(self, root):
        self.root = root
        root.title("Tx CAMARA · dos luces · Redes I")
        root.configure(bg=FONDO)

        self.filas, self.cols = 4, 4
        self.grid = []
        self.cur = [0, 0]
        self.geom = None
        self.t0 = None                  # cronometro: arranca con la 1a tecla
        self.historial = []             # para deshacer (Ctrl+Z)

        # --- lo que deja una lectura desde foto (None si se digito a mano) ---
        # Que tan segura quedo cada celda. Es lo que pinta los ? en la
        # cuadricula y lo que hace preguntar antes de transmitir.
        self.confianzas = None
        # Si la ultima lectura no llego a CALIDAD_FIRME. Con una lectura floja
        # los VERDES tampoco son de fiar, asi que no basta con mirar los ?:
        # hay que revisarla entera o repetir la foto.
        self.lectura_floja = False
        self.debug_foto = None          # (hoja enderezada, cajas) del panel
        self.imagen_original = None     # la foto tal cual, para re-recortarla
        self.ruta_fotografia = None
        self._motivo_sin_lector = ""    # por que no se puede leer de foto
        self._camaras = []              # las que encontro la ultima busqueda
        self._camaras_nuevas = None     # recado del hilo que las busca

        self.modo = "editar"
        self.simbolos = []
        self.velocidad = SIMBOLOS_POR_SEGUNDO
        self.copias = COPIAS
        self.copia_actual = 0
        self.copias_enviadas = 0        # cuantas se le han pasado a la placa
        self.i = 0                      # simbolo que toca
        self.corriendo = False
        self.luz_fija = None            # estado puesto a mano, o None
        self.arduino = None
        self.pantalla = None            # ventana del modo PANTALLA
        self.t_inicio_envio = None
        # Los dos temporizadores de Tk que hay en marcha, para poder
        # CANCELARLOS. Sin esto, parar() dejaba el after pendiente: volvia a
        # disparar, se encontraba corriendo=True otra vez y arrancaba una
        # segunda cadena de _tic en paralelo a la primera. De ahi venia que la
        # pantalla fuera al doble de velocidad que el Arduino y que a veces no
        # hubiera manera de detenerla.
        self._job_tic = None
        self._job_aviso = None

        self._construir()
        self.nueva_cuadricula(self.filas, self.cols)
        if self._motivo_sin_lector:
            self.lbl_est.config(
                text="Cargar la matriz desde una foto no está disponible: %s."
                     "  Se puede digitar a mano igual."
                     % self._motivo_sin_lector, fg=AMBAR)

    # ------------------------------------------------------------ montaje --
    def _contador(self, padre, texto, que):
        """Rotulo + botones - y +. No hay casilla de texto a proposito: asi
        nunca se queda el teclado atrapado fuera de la cuadricula."""
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
        # ---- barra 1: tamaño de la cuadricula ----
        top = tk.Frame(self.root, bg=FONDO)
        top.pack(fill="x", padx=8, pady=(6, 0))

        self.lbl_filas = self._contador(top, "Filas:", "filas")
        tk.Frame(top, bg=FONDO, width=18).pack(side="left")
        self.lbl_cols = self._contador(top, "Columnas:", "cols")

        tk.Button(top, text="Limpiar", command=self.limpiar).pack(side="left", padx=14)
        tk.Button(top, text="Deshacer (Ctrl+Z)", command=self.deshacer).pack(side="left")

        # ---- cargar la matriz desde una foto de la hoja ----
        # Si falta el lector, los botones se quedan apagados y el motivo sale
        # en la barra de estado. Digitar a mano sigue funcionando igual.
        puede, motivo = hay_lector()
        self.btn_foto = tk.Button(top, text="📷 Buscar foto", bg="#2a5298",
                                  fg="white", font=("Segoe UI", 9, "bold"),
                                  command=self.buscar_fotografia)
        self.btn_foto.pack(side="left", padx=(14, 2))
        self.btn_camara = tk.Button(top, text="📱 Con la cámara", bg="#1b6ca8",
                                    fg="white", font=("Segoe UI", 9, "bold"),
                                    command=self.tomar_foto_camara)
        self.btn_camara.pack(side="left", padx=2)

        # La camara se escoge AQUI, en la barra, y no en un dialogo aparte: el
        # dia de la prueba son dos clics menos y se ve de un vistazo con cual
        # va a tirar. El dialogo sigue existiendo para el caso de la URL.
        self.cbo_camara = ttk.Combobox(top, width=22, state="readonly",
                                       values=["(buscando cámaras...)"])
        self.cbo_camara.current(0)
        self.cbo_camara.pack(side="left", padx=(6, 0))
        self.cbo_camara.bind("<<ComboboxSelected>>",
                             lambda e: self.foco_cuadricula())
        # El ↻ hace falta de verdad: DroidCam aparece y desaparece al enchufar
        # o desenchufar el telefono, y sin esto habria que reiniciar el
        # programa para que se entere.
        self.btn_refrescar = tk.Button(top, text="↻", width=2,
                                       command=self.buscar_camaras)
        self.btn_refrescar.pack(side="left", padx=(2, 0))

        self.btn_diag = tk.Button(top, text="🔍 Ver diagnóstico",
                                  command=self.ver_diagnostico_foto)
        self.btn_diag.pack(side="left", padx=(8, 2))
        if not puede:
            for b in (self.btn_foto, self.btn_camara, self.btn_diag,
                      self.btn_refrescar):
                b.config(state="disabled")
            self.cbo_camara.config(state="disabled")
            self._motivo_sin_lector = motivo
        else:
            # Buscar camaras abre cada una para ver que resolucion da, y eso
            # tarda un par de segundos. En otro hilo, que si no la ventana
            # tarda en aparecer y parece que el programa se colgo al abrir.
            self.buscar_camaras(callado=True)

        self.lbl_celdas = tk.Label(top, text="", bg=FONDO, fg="#888888",
                                   font=("Segoe UI", 9))
        self.lbl_celdas.pack(side="left", padx=12)

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
        # ESC para: si esta emitiendo, PARAR; si no, devolver el teclado
        self.root.bind("<Escape>", self._escape)
        self.root.bind("<Control-z>", lambda e: self.deshacer())
        # Ctrl+R para volver a encuadrar: es lo que mas se repite cuando una
        # foto no sale a la primera, y buscar el boton cada vez cansa.
        self.root.bind("<Control-r>", lambda e: self.recortar_fotografia())
        self.root.bind("<Control-R>", lambda e: self.recortar_fotografia())
        self.root.bind("<Configure>", lambda e: self.dibujar_grid())
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)
        self._bucle()

    # --------------------------------------------- la matriz de una foto --
    def buscar_fotografia(self):
        """Abre el explorador de archivos e inmediatamente muestra la foto para revisarla y recortarla si se desea."""
        ruta = filedialog.askopenfilename(
            title="Seleccionar fotografía de la hoja",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.heic *.PNG *.JPG *.JPEG *.BMP"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not ruta:
            return

        img_leida = cv2.imread(str(ruta))
        if img_leida is None:
            messagebox.showerror("Leer fotografía", "No se pudo abrir la imagen seleccionada.")
            return

        self.imagen_original = img_leida
        self.ruta_fotografia = str(ruta)

        # Sin PIL no se puede ENSEÑAR la foto dentro de Tkinter, pero leerla si
        # se puede: se salta el encuadre y se analiza la foto entera. Es peor
        # -recortar ayuda cuando la hoja sale pequeña dentro del encuadre- pero
        # es mucho mejor que no poder cargarla.
        if ImageTk is None:
            self._aplicar_recorte(img_leida, False)
            return
        VentanaRecorte(self.root, self.imagen_original, self._aplicar_recorte,
                       titulo=Path(ruta).name)

    OPCION_URL = "Otra / por URL (celular por Wi-Fi)..."

    def buscar_camaras(self, callado=False):
        """Rellena el desplegable con las camaras que haya AHORA.

        Va en otro hilo porque abrir cada camara para preguntarle la
        resolucion tarda un par de segundos, y hacerlo en el hilo de la
        ventana la deja congelada: al arrancar parecia que el programa se
        habia colgado.
        """
        if LH is None:
            return
        self.cbo_camara.config(values=["(buscando cámaras...)"])
        self.cbo_camara.current(0)
        if not callado:
            self.lbl_est.config(text="Buscando cámaras...", fg=AMBAR)

        def trabajo():
            try:
                encontradas = detectar_camaras_disponibles()
            except Exception:
                encontradas = []
            # A Tkinter NO se le habla desde otro hilo, y eso incluye
            # root.after(): registrar la llamada toca las estructuras de Tk y
            # revienta con "main thread is not in main loop". Lo que se hace
            # es dejar el resultado en una variable y que lo recoja _bucle(),
            # que ya corre en el hilo de la ventana cada 100 ms.
            self._camaras_nuevas = (encontradas, callado)

        threading.Thread(target=trabajo, daemon=True).start()

    def _pintar_camaras(self, encontradas, callado=False):
        if not self.cbo_camara.winfo_exists():
            return
        self._camaras = encontradas
        etiquetas = [e for _, e in encontradas] + [self.OPCION_URL]
        self.cbo_camara.config(values=etiquetas)
        # DroidCam es la que se usa con el telefono, asi que si esta se escoge
        # sola; si no, la primera que haya.
        cual = 0
        for i, (_, e) in enumerate(encontradas):
            if "droidcam" in e.lower():
                cual = i
                break
        self.cbo_camara.current(cual if etiquetas else 0)
        if not callado:
            n = len(encontradas)
            self.lbl_est.config(
                text="%d cámara%s encontrada%s" % (n, "" if n == 1 else "s",
                                                   "" if n == 1 else "s"),
                fg=VERDE if n else AMBAR)

    def camara_elegida(self):
        """El indice (o la URL) de la camara del desplegable, o None."""
        etiqueta = self.cbo_camara.get()
        if etiqueta == self.OPCION_URL or not getattr(self, "_camaras", None):
            return None
        for fuente, e in self._camaras:
            if e == etiqueta:
                return fuente
        return None

    def tomar_foto_camara(self):
        """Abre el visor en vivo con la camara del desplegable.

        Si la escogida es la de la URL -o si todavia no se ha buscado ninguna-
        se abre el dialogo de siempre, que es donde se escribe la direccion.
        """
        fuente = self.camara_elegida()
        if fuente is None:
            DialogoSelectorCamara(self.root, self._capturar_con_camara)
            return
        self._capturar_con_camara(fuente)

    def _capturar_con_camara(self, fuente):
        """Abre el visor en vivo con la rejilla y lectura en tiempo real."""
        self.t0 = time.time()
        etiq_fuente = fuente
        if str(fuente).isdigit():
            nombres = C.nombres_camaras()
            idx = int(fuente)
            if idx < len(nombres):
                etiq_fuente = "%s (%s)" % (fuente, nombres[idx])

        self.lbl_est.config(
            text="Abriendo visor en vivo (%s)... ESPACIO = capturar foto, Q = salir" % etiq_fuente,
            fg=AMBAR)
        self.root.update_idletasks()

        try:
            salida = LH.mirar_con_la_camara(fuente, devolver_debug=True)
            if not salida or salida[0] is None:
                self.lbl_est.config(
                    text="Captura cancelada o no se detectó cuadrícula.", fg=AMBAR)
                return
            grid, nota, seguridad, debug, frame = salida
        except Exception as error:
            messagebox.showerror("Cámara en vivo", str(error))
            self.lbl_est.config(text="Error con la cámara: %s" % error, fg=ROJO)
            return

        # La foto que se guarda es la del cuadro VOTADO, no la del ultimo que
        # se miro: leer_hoja.mirar_con_la_camara congela las dos cosas -foto y
        # diagnostico- en el momento del ESPACIO.
        ruta_guardada = (guardar_captura("captura_camara.jpg", frame)
                         if frame is not None else None)
        if frame is not None:
            self.imagen_original = frame.copy()
            self.ruta_fotografia = (str(ruta_guardada) if ruta_guardada
                                    else "Cámara en vivo (%s)" % fuente)
        else:
            self.ruta_fotografia = "Cámara en vivo (%s)" % fuente
            self.imagen_original = None

        self.parar()
        self.filas, self.cols = len(grid), len(grid[0])
        self.grid = grid
        self.confianzas = seguridad
        self.lectura_floja = False      # la votacion no mide calidad global
        self.debug_foto = debug
        self.cur = [0, 0]
        self.historial = []
        self.modo = "editar"
        self.btn_modo.config(text="TRANSMITIR (F5)", bg=CURSOR)
        self._regenerar()
        self.foco_cuadricula()

        dudas = 0
        if seguridad:
            for f in range(self.filas):
                for c in range(self.cols):
                    if LH.es_dudosa(seguridad, f, c):
                        dudas += 1

        msg = "Matriz %dx%d capturada con cámara" % (self.filas, self.cols)
        if dudas > 0:
            msg += " · ⚠️ %d celdas dudosas marcadas con '?'" % dudas
            self.lbl_est.config(text=msg, fg=AMBAR)
        else:
            self.lbl_est.config(text=msg, fg=VERDE)

        # Abrir inmediatamente el Editor de Diagnóstico para comparar y editar lado a lado
        # Se abre el diagnostico solo, que es lo primero que uno quiere ver.
        # Si no hay PIL no se puede: entonces NO se llama, porque si no saldria
        # el aviso de que falta cada vez que se carga una foto, y ya lo dice la
        # barra de estado. Los ? de la cuadricula siguen saliendo igual.
        if debug and debug[0] is not None and ImageTk is not None:
            self.ver_diagnostico_foto()

    def recortar_fotografia(self):
        """Abre la herramienta interactiva de recorte y encuadre."""
        if getattr(self, "imagen_original", None) is None:
            self.buscar_fotografia()
            return
        if ImageTk is None:
            messagebox.showinfo(
                "Recortar",
                "Para encuadrar la foto hace falta PIL (Pillow):\n\n"
                "    pip install pillow\n\n"
                "Sin ella la foto se lee entera, que suele bastar.")
            return

        VentanaRecorte(self.root, self.imagen_original, self._aplicar_recorte,
                       titulo=Path(self.ruta_fotografia).name if self.ruta_fotografia else "Foto")

    def _aplicar_recorte(self, recorte, es_recorte=False):
        """Aplica la foto (recortada o completa), analiza con leer_hoja y actualiza la matriz."""
        self.lbl_est.config(
            text="Analizando matriz con leer_hoja (quitar giro, homografía y plantillas)...",
            fg=AMBAR)
        self.root.update_idletasks()

        try:
            grid, nota, conf, debug = LH.leer_hoja_girando(recorte, devolver_debug=True)
            if not grid:
                raise ValueError("No se detectó la cuadrícula en la imagen (%s)" % nota)
        except Exception as error:
            resp = messagebox.askretrycancel(
                "Detección de matriz",
                "%s\n\n¿Deseas volver a encuadrar la imagen dejando un pequeño borde de papel blanco alrededor de la tabla?" % error)
            self.lbl_est.config(text="No se detectó cuadrícula en la imagen", fg=ROJO)
            if resp and getattr(self, "imagen_original", None) is not None:
                self.root.after(80, self.recortar_fotografia)
            return

        # Guardar en disco copia del recorte o de la foto usada
        nombre_arch = "recorte_actual.jpg" if es_recorte else "captura_actual.jpg"
        ruta_guardada = guardar_captura(nombre_arch, recorte)
        if ruta_guardada is not None:
            self.ruta_fotografia = str(ruta_guardada)

        self.parar()
        self.filas, self.cols = len(grid), len(grid[0])
        self.grid = grid
        self.confianzas = conf
        self.lectura_floja = LH.AVISO_FLOJA in (nota or "")
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
                    if LH.es_dudosa(conf, f, c):
                        dudas += 1

        msg = "Matriz %dx%d cargada desde %s" % (
            self.filas, self.cols,
            "recorte" if es_recorte else Path(self.ruta_fotografia).name)
        if self.lectura_floja:
            msg += " · ⚠️ LECTURA FLOJA: revísala entera o repite la foto"
            self.lbl_est.config(text=msg, fg=ROJO)
        elif dudas > 0:
            msg += " · ⚠️ %d celdas dudosas marcadas con '?'" % dudas
            self.lbl_est.config(text=msg, fg=AMBAR)
        else:
            self.lbl_est.config(text=msg, fg=VERDE)

        # Se abre el diagnostico solo, que es lo primero que uno quiere ver.
        # Si no hay PIL no se puede: entonces NO se llama, porque si no saldria
        # el aviso de que falta cada vez que se carga una foto, y ya lo dice la
        # barra de estado. Los ? de la cuadricula siguen saliendo igual.
        if debug and debug[0] is not None and ImageTk is not None:
            self.ver_diagnostico_foto()

    def ver_diagnostico_foto(self):
        """Abre la ventana interactiva de diagnóstico lado a lado para comparar y editar."""
        if not self.debug_foto or not self.ruta_fotografia:
            messagebox.showinfo(
                "Diagnóstico",
                "Primero carga una foto usando '📷 Buscar foto' o '📱 Tomar foto con cámara'.")
            return
        if ImageTk is None:
            messagebox.showinfo(
                "Diagnóstico",
                "Para ver la foto al lado de la matriz hace falta PIL "
                "(Pillow):\n\n    pip install pillow\n\n"
                "Mientras tanto, las celdas dudosas salen con un ? rojo en la "
                "cuadrícula de la ventana principal.")
            return
        derecha, cajas = self.debug_foto
        EditorDiagnostico(self.root, self, derecha, cajas,
                          titulo=Path(self.ruta_fotografia).name)

    # --------------------------------------------------------- cuadricula --

    # --------------------------------------------------------- cuadricula --
    def cambiar_tamano(self, que, delta):
        """Los + y - cambian el tamaño SIN borrar lo escrito: lo que sobra se
        recorta y lo que falta se rellena con negro."""
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
        # Las confianzas se recortan y crecen igual que la cuadricula, porque
        # si no quedan descuadradas: una celda nueva no la ha leido nadie, asi
        # que entra como revisada (1.0) y no como dudosa.
        if self.confianzas:
            self.confianzas = [
                [self.confianzas[i][j] if i < self.filas and j < self.cols
                 else 1.0 for j in range(c)] for i in range(f)]
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
        self.cur = [0, 0]
        self.t0 = None
        self.historial = []
        # Esta cuadricula ya no viene de ninguna foto: fuera las dudas, el
        # aviso de lectura floja y el panel de diagnostico, que si se quedaran
        # estarian hablando de una matriz que ya no existe.
        self.olvidar_foto()
        self.lbl_t.config(text="00.0 s")
        self.modo = "editar"
        self.btn_modo.config(text="TRANSMITIR (F5)", bg=CURSOR)
        self._regenerar()
        self.foco_cuadricula()

    def limpiar(self):
        self._guardar_undo()
        self.grid = [[C.NEGRO] * self.cols for _ in range(self.filas)]
        self.cur = [0, 0]
        self.olvidar_foto()
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

    def olvidar_foto(self):
        """Borra todo rastro de la ultima lectura desde foto."""
        self.confianzas = None
        self.lectura_floja = False
        self.debug_foto = None
        self.ruta_fotografia = None
        self.imagen_original = None

    def celdas_por_revisar(self):
        """Cuantas celdas siguen marcadas como dudosas (editarla la limpia)."""
        if not self.confianzas:
            return 0
        return sum(1 for f in range(self.filas) for c in range(self.cols)
                   if LH.es_dudosa(self.confianzas, f, c))

    def _regenerar(self):
        """Vuelve a armar la trama a partir de la cuadricula actual.

        Lo primero es PARAR. Se llama al editar una celda, al cambiar el
        tamaño, las copias o la velocidad, y ponia self.i = 0 sin mirar si
        habia una emision en curso: la animacion volvia al principio y se
        quedaba dando vueltas sin terminar nunca. Editar mientras se transmite
        para la transmision, que es lo que uno espera.
        """
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
        """Dice si la camara del receptor va a poder seguir esta velocidad.

        Es la comprobacion mas util de toda la ventana: pasarse de velocidad no
        da un error, da una grabacion que no se puede descifrar, y eso no se
        descubre hasta que ya se hizo la transmision.
        """
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
        """Devuelve el teclado a la cuadricula."""
        self.canvas.focus_set()
        self.dibujar_grid()

    def _escape(self, _=None):
        """ESC para lo que esté emitiendo; si no hay nada, recupera el teclado."""
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
            self.t0 = time.time()          # el cronometro arranca al digitar

        if k in ("Right", "Left", "Down", "Up"):
            self._mover({"Right": (0, 1), "Left": (0, -1),
                         "Down": (1, 0), "Up": (-1, 0)}[k])
            self.dibujar_grid()
            return
        if k == "Return":
            self.cur = [min(self.cur[0] + 1, self.filas - 1), 0]
            self.dibujar_grid()
            return

        # Escribir encima de una celda es revisarla: se le quita el ?. Ojo al
        # orden, BackSpace primero RETROCEDE y luego escribe, asi que la duda
        # que hay que limpiar es la de la celda donde se acaba, no la de
        # donde se estaba. Por eso se limpia despues de mover, no antes.
        if k == "BackSpace":
            self._guardar_undo()
            self._mover((0, -1))
            self.grid[self.cur[0]][self.cur[1]] = C.NEGRO
            self._revisada(self.cur[0], self.cur[1])
        elif ch in (".", " ", "#"):
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = C.NEGRO
            self._revisada(self.cur[0], self.cur[1])
            self._mover((0, 1))
        elif ch in ("-", "_"):          # el 0 no: es la tecla de apagar
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = C.BLANCO
            self._revisada(self.cur[0], self.cur[1])
            self._mover((0, 1))
        elif ch and ch.upper() in C.ALFABETO:
            self._guardar_undo()
            self.grid[self.cur[0]][self.cur[1]] = ch.upper()
            self._revisada(self.cur[0], self.cur[1])
            self._mover((0, 1))
        else:
            return
        self._regenerar()

    def _revisada(self, f, c):
        """La celda (f, c) queda dada por buena: se le quita el ?."""
        if (self.confianzas and f < len(self.confianzas)
                and c < len(self.confianzas[f])):
            self.confianzas[f][c] = 1.0

    def _mover(self, paso):
        """Mueve el cursor. Al salirse por un lado pasa a la fila de al lado,
        como al escribir en una hoja."""
        di, dj = paso
        i, j = self.cur[0] + di, self.cur[1] + dj
        if dj:
            if j < 0:
                j, i = self.cols - 1, i - 1
            elif j >= self.cols:
                j, i = 0, i + 1
        self.cur = [max(0, min(i, self.filas - 1)), max(0, min(j, self.cols - 1))]

    def _tecla_luz(self, ev):
        """1/2/3/0 y * mandan sobre las luces en cualquiera de los dos modos.

        No chocan con nada: en la cuadricula esos caracteres no son celdas
        validas (una celda es una letra, # o _), asi que estaban libres.
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
        """Prende o apaga las luces a mano, sin transmitir nada.

        Tomar el control manual PARA la emision: si no, seguiria pisando el
        estado que se acaba de poner.
        """
        self.parar()
        self.luz_fija = estado
        if self.arduino:
            self.arduino.fijar(estado)
        self.refrescar()

    def avisar(self):
        """AVISO: las dos luces parpadeando rapido, para decirle al receptor
        'preparate, voy a transmitir'."""
        self.parar()
        patron = patron_aviso()
        if self.arduino:
            # el Arduino emite a ritmo fijo: se le baja el periodo, se le manda
            # el patron y se le devuelve el suyo. Las tres ordenes se procesan
            # en orden, asi que la ultima no le pisa el aviso.
            self.arduino.periodo_us(AVISO_T_S * 1e6)
            self.arduino.emitir(patron)
            self.arduino.velocidad(self.velocidad)
        self._animar_aviso(patron, 0)
        self.lbl_est.config(text="AVISO enviado · espera a que el receptor "
                                 "confirme antes de transmitir", fg=AMBAR)

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
        """El boton / la barra espaciadora: arranca si esta parado y para si
        esta andando."""
        if not self.simbolos:
            return
        if self.modo == "editar":
            self.cambiar_modo()
        if self.corriendo:
            self.parar_y_avisar()
            return
        self.emitir()

    def emitir(self):
        """Manda la trama, tantas copias como diga el contador."""
        if not self.simbolos:
            return
        # Lo que se transmite es lo que hay en la cuadricula, y una celda
        # dudosa sin revisar puede ser una letra mal leida que viaja tal cual
        # hasta el receptor, con su CRC bueno y todo: el CRC protege la TRAMA,
        # no la FOTO. Por eso se pregunta antes, que es la ultima ocasion.
        pendientes = self.celdas_por_revisar()
        if pendientes or self.lectura_floja:
            partes = []
            if self.lectura_floja:
                partes.append("La lectura de la foto salió FLOJA: ni siquiera "
                              "las celdas sin ? son de fiar. Revisa la matriz "
                              "entera contra la foto, o repite la foto.")
            if pendientes:
                partes.append("Quedan %d celdas dudosas (?) sin revisar. "
                              "Escribir encima de una la da por revisada."
                              % pendientes)
            if not messagebox.askyesno(
                    "Revisar antes de transmitir",
                    "\n\n".join(partes) + "\n\n¿Transmitir de todos modos?",
                    icon="warning"):
                return
            # Aceptado una vez para esta matriz, no se insiste mas con la
            # calidad global; con las ? si, mientras queden.
            self.lectura_floja = False
        if not self.arduino and self.pantalla is None:
            messagebox.showwarning(
                "Nada que mueva las luces",
                "Conecta el Arduino, o usa el modo PANTALLA (F8) para probar "
                "apuntándole la cámara.\n\nA %.1f símbolos por segundo no hay "
                "mano que siga el ritmo: por eso este transmisor no tiene modo "
                "manual." % self.velocidad)
            return

        self.parar()                      # nada de cadenas viejas sueltas
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
        """Le pasa a la placa UNA copia de la trama, no todas de golpe.

        Mandarlas todas seguidas era comodo pero rompia el PARAR: la placa se
        queda emitiendo la primera y las demas esperan en su buffer de
        entrada, asi que la Z de cortar queda DETRAS de ellas. El firmware
        mira si lo siguiente que llego es una Z, y lo siguiente era la X de la
        copia dos. Resultado: PARAR no hacia nada hasta que terminara la copia
        en curso, que con 370 simbolos a 5 por segundo son 74 segundos.

        Mandandolas de una en una, cuando toca, lo unico que puede haber en el
        buffer es la Z. El hueco entre copias es de milisegundos y al receptor
        le da igual: corta la grabacion en rafagas de todos modos.
        """
        if self.arduino and k < self.copias:
            self.arduino.emitir(self.simbolos)

    def _tic(self):
        """Un paso de la emision. Que simbolo toca lo dice EL RELOJ.

        Antes cada paso programaba el siguiente a 1/velocidad de distancia y se
        iba sumando: el retraso de Tk en cada salto se acumulaba y al cabo de
        trescientos simbolos la pantalla iba segundos por detras de la placa,
        que si lleva el ritmo exacto. Calculando el indice desde el reloj, la
        pantalla se recoloca sola en cada paso y las dos van juntas.
        """
        self._job_tic = None
        if not self.corriendo or not self.simbolos:
            return

        transcurrido = time.time() - self.t_inicio_envio
        k = int(transcurrido * self.velocidad)          # simbolo global
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
        # La copia siguiente se manda un poco DESPUES de la frontera, cuando la
        # placa ya termino la anterior: ver HUECO_ENTRE_COPIAS.
        dentro = transcurrido * self.velocidad - copia * len(self.simbolos)
        if copia >= self.copias_enviadas and dentro >= HUECO_ENTRE_COPIAS:
            self._mandar_copia(copia)
            self.copias_enviadas = copia + 1

        self.i = i + 1                                  # lo que ve la pantalla
        if self.pantalla:
            self._pintar_pantalla(self.simbolos[i])
        self.refrescar()

        # cuando toca el simbolo siguiente, en tiempo absoluto
        espera = (k + 1) / self.velocidad - transcurrido
        self._job_tic = self.root.after(max(1, int(espera * 1000)), self._tic)

    def _cancelar_temporizadores(self):
        """Mata los after pendientes. Tiene que llamarse antes de arrancar
        cualquier cosa nueva, o se acumulan cadenas en paralelo."""
        for nombre in ("_job_tic", "_job_aviso"):
            job = getattr(self, nombre, None)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
                setattr(self, nombre, None)

    def parar(self):
        """Detiene la emision AQUI Y EN LA PLACA.

        Lo segundo es lo que importa: al Arduino se le manda la trama y el
        solo la emite, asi que parar solo la animacion dejaria las luces
        conmutando hasta el final.
        """
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
        """Abre o cierra la ventana a pantalla completa con las dos luces.

        Sirve para probar el sistema entero sin montar nada: se le apunta la
        camara del receptor a la pantalla y se transmite.
        """
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
        """Las dos luces en la ventana a pantalla completa."""
        if self.pantalla is None:
            return
        cv = self.lienzo
        if not cv.winfo_exists():
            return
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        r = max(20, min(W, H) // 12)
        # juntas = como dos luces que a lo lejos se funden (el receptor las
        # separa por color); separadas = las lee por posicion
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
        if not c.winfo_exists():           # la ventana ya se cerro
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
                                   fill=NEGRO if v == C.NEGRO else BLANCO)
                if v not in (C.NEGRO, C.BLANCO):
                    c.create_text(x + s / 2, y + s / 2, text=v, fill="#000000",
                                  font=("Segoe UI", int(s * 0.55), "bold"))
                # El ? de una celda que se leyo de una foto sin convencer. La
                # regla de cuando dudar esta en un solo sitio, LH.es_dudosa, y
                # vale para cualquier celda: una letra tan desvaida que se lee
                # como casilla VACIA tambien tiene que salir marcada.
                if LH is not None and LH.es_dudosa(self.confianzas, i, j):
                    c.create_text(x + s - 7, y + 8, text="?", fill=ROJO,
                                  font=("Segoe UI", max(8, int(s * 0.28)), "bold"))

        if self.modo == "editar":
            i, j = self.cur
            c.create_rectangle(x0 + j * s, y0 + i * s, x0 + (j + 1) * s,
                               y0 + (i + 1) * s, outline=CURSOR, width=3)
            ayuda = (". o espacio o # = negro     - o _ = blanco     "
                     "letras = A..Z Ñ     (? rojo = celda dudosa de la foto)")
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
        """Las dos luces grandes, tal como habria que prenderlas."""
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
        # el recado que deja el hilo que busca camaras (ver buscar_camaras)
        pendiente, self._camaras_nuevas = self._camaras_nuevas, None
        if pendiente is not None:
            self._pintar_camaras(pendiente[0], pendiente[1])
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
