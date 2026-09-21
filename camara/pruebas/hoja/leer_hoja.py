# -*- coding: utf-8 -*-
"""Lee la cuadricula de la hoja impresa: de una foto o de la camara.

    python leer_hoja.py                       pregunta que foto abrir
    python leer_hoja.py foto.jpg              esa foto
    python leer_hoja.py --camara 0            la webcam, VIENDO lo que mira
    python leer_hoja.py --camara http://IP:8080/video     el celular
    python leer_hoja.py --tamaño 9x8 foto.jpg   diciendole cuantas celdas son

Sin argumentos abre el dialogo de archivos, asi no hay que escribir rutas.

Con --camara se abre una ventana con lo que ve la camara, la rejilla que ha
encontrado dibujada encima y las letras que va leyendo: ESPACIO junta esa
lectura con las anteriores y Q sale. Sin ver la imagen no hay forma de apuntar.

Lo de --tamaño no es un capricho: contar cuantas celdas hay es la parte que
peor se porta, y el dia de la prueba el tamaño se sabe con mirar la hoja.
Dandolo se salta el conteo y solo queda leer las celdas, que es lo que si va
bien. Eso si, no arregla una foto en la que el marco salga torcido.

Sale la matriz lista para pegar en el transmisor. Solo necesita numpy y
opencv, igual que rx_camara.py; las plantillas de las letras vienen ya
cocinadas en plantillas.npz (las genera hacer_plantillas.py, que si necesita
PIL, pero eso se corre una sola vez).

COMO FUNCIONA

  1. QUITAR EL GIRO, con Hough, y es lo PRIMERO. Las rayas se sacan luego con
     un nucleo recto largo; con la hoja a 6 grados una raya se desvia 8 px a lo
     largo del nucleo y, como tiene 2 px de grosor, no queda ni una fila con
     los pixeles seguidos que el nucleo pide: la raya no aparece.
  2. APLANAR LA LUZ. Una foto con sombra de un lado no se binariza con un
     umbral unico. El blanco del papel se estima con el maximo local sobre una
     ventana de varias celdas, no con un desenfoque: dentro de un bloque de
     recuadros negros el desenfoque se aclara solo y el negro desaparece.
  3. SACAR LAS RAYAS con morfologia, quitando antes los recuadros negros
     rellenos: un negro es tan ancho como una raya y mete columnas fantasma.
  4. ENDEREZAR. El contorno de rayas y negros juntos es el marco; sus cuatro
     esquinas dan la homografia. Lo que sobre de sesgo se mide sobre las
     propias rayas y se quita.
  5. CONTAR LAS CELDAS. Las celdas son los HUECOS que dejan las rayas, pero de
     ahi no se toma la lista sino CUANTAS hay: dos negros pegados no tienen
     borde entre ellos -no es que el codigo no lo vea, en el papel no esta-,
     asi que esas celdas no dan hueco. Con la cuenta se tiende la reticula.
  6. LEER CADA CELDA. Casi toda tinta = recuadro negro, casi nada = blanco, en
     medio = letra, y la letra se compara por forma contra plantillas de 20
     fuentes distintas.

Cada celda sale con una confianza, para poder resaltar las dudosas en vez de
creerle a ciegas.
"""
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ALFABETO = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
NEGRO, BLANCO = "#", "_"

_HAY_PANTALLA = None


def hay_pantalla():
    """Comprueba si OpenCV puede abrir ventanas en esta sesión."""
    global _HAY_PANTALLA
    if _HAY_PANTALLA is None:
        try:
            cv2.namedWindow("_prueba_", cv2.WINDOW_NORMAL)
            cv2.destroyWindow("_prueba_")
            _HAY_PANTALLA = True
        except Exception:
            _HAY_PANTALLA = False
    return _HAY_PANTALLA

LADO_PLANTILLA = 32       # la letra normalizada, en pixeles
LADO_CELDA = 64           # a cuanto se lleva cada celda al enderezar
MARGEN_CELDA = 0.18       # cuanto se recorta por dentro para no coger la raya

# Tinta de la celda por encima de esto = recuadro negro; por debajo del otro
# = celda vacia. En medio hay una letra. Medido sobre las hojas de prueba:
# una letra ocupa entre 0,04 y 0,30 de la celda, un negro pasa de 0,80.
TINTA_NEGRO = 0.65
TINTA_VACIA = 0.02


# ------------------------------------------------- 1. preparar la imagen --

def aplanar_luz(gris, radio=81):
    """Quita el gradiente de iluminacion dividiendo por un desenfoque grande.

    Es lo que separa una foto usable de una que no: con una sombra cruzando la
    hoja, cualquier umbral global se come media tabla.
    """
    fondo = cv2.GaussianBlur(gris, (radio | 1, radio | 1), 0)
    plano = gris.astype(np.float32) / np.maximum(fondo.astype(np.float32), 1)
    return np.clip(plano * 180, 0, 255).astype(np.uint8)


def binarizar(gris):
    """Tinta = blanco."""
    return cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 41, 10)


def sin_solidos(binaria, lado_min):
    """Borra los recuadros NEGROS rellenos, que no son rayas.

    Hace falta y no es un adorno: un recuadro negro es tan ancho como una raya
    horizontal, asi que la apertura horizontal lo deja intacto y la rejilla
    sale con lineas de mas (una hoja de 2x3 se leia 2x5). Un solido es ancho
    Y alto a la vez; una raya solo una de las dos cosas.
    """
    k = max(5, lado_min // 2)
    solidos = cv2.morphologyEx(
        binaria, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    solidos = cv2.dilate(solidos, np.ones((5, 5), np.uint8))
    return cv2.bitwise_and(binaria, cv2.bitwise_not(solidos))


def rayas(binaria, lado_min):
    """Las rayas horizontales y verticales de la tabla, sin letras ni solidos."""
    n = max(8, lado_min)
    limpia = sin_solidos(binaria, n)

    hor = cv2.morphologyEx(limpia, cv2.MORPH_OPEN,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (n, 1)))
    ver = cv2.morphologyEx(limpia, cv2.MORPH_OPEN,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (1, n)))
    return hor, ver


def quitar_giro(gris):
    """Pone la tabla derecha ANTES de buscarle las rayas.

    Es lo primero que hay que hacer, y hacerlo despues no sirve de nada. La
    apertura que saca las rayas usa un nucleo RECTO de unos 76 px; con la hoja
    girada 6 grados una raya se desvia 8 px a lo largo de esos 76, y como la
    raya impresa tiene 2 px de grosor no queda ni una fila con 76 pixeles
    seguidos de tinta: la raya no aparece. En la hoja de 8x11 la mascara de
    rayas salia hecha pedazos y el marco era irreconocible.

    El angulo sale del rectangulo minimo que cubre toda la tinta, que para una
    hoja con una tabla es la tabla.
    """
    b = binarizar(aplanar_luz(gris))
    largo = max(20, min(gris.shape) // 20)
    segmentos = cv2.HoughLinesP(b, 1, np.pi / 720.0, threshold=largo,
                                minLineLength=largo, maxLineGap=largo // 3)
    if segmentos is None:
        return gris
    # El rectangulo minimo de toda la tinta no sirve -el ruido llega hasta el
    # borde y devuelve la imagen entera-, pero los trozos de raya si: aunque
    # esten partidos, todos llevan el mismo angulo.
    angulos = []
    for x1, y1, x2, y2 in np.asarray(segmentos).reshape(-1, 4):
        a = np.degrees(np.arctan2(float(y2 - y1), float(x2 - x1)))
        a = (a + 180.0) % 180.0
        if a < 25.0:
            angulos.append(a)
        elif a > 155.0:
            angulos.append(a - 180.0)
        elif 65.0 < a < 115.0:
            angulos.append(a - 90.0)
    if len(angulos) < 5:
        return gris
    ang = float(np.median(angulos))
    # No se gira por un angulo chico. Girar cuesta un remuestreo, y el
    # remuestreo suaviza una raya impresa de 2 px lo bastante como para
    # partirla: una hoja que estaba a 0,5 grados y se leia perfecta paso a
    # leerse de 21 filas por haberla "enderezado".
    if abs(ang) < 1.5 or abs(ang) > 30.0:
        return gris
    H, W = gris.shape
    M = cv2.getRotationMatrix2D((W / 2.0, H / 2.0), ang, 1.0)
    return cv2.warpAffine(gris, M, (W, H), flags=cv2.INTER_CUBIC,
                          borderValue=255)


# ------------------------------------------------- 2. enderezar la hoja ---

def esquinas_de_la_tabla(marco):
    """Las cuatro esquinas del contorno mas grande, en orden."""
    cont, _ = cv2.findContours(marco, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cont:
        return None
    c = max(cont, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.02 * marco.shape[0] * marco.shape[1]:
        return None
    # El contorno se cierra con su envolvente convexa -un negro pegado al borde
    # muerde el marco y deja entrantes que confunden la aproximacion- y luego
    # se busca el epsilon que deje exactamente cuatro lados en vez de fijar uno
    # solo: con un epsilon fijo unas hojas daban 4 puntos y otras 11, y las que
    # no daban 4 caian al rectangulo girado, que con perspectiva de verdad
    # devuelve un marco de proporcion equivocada (una tabla cuadrada de 8x8
    # salia de 688x900 y la cuenta de columnas se iba a la mitad).
    casco = cv2.convexHull(c)
    perimetro = cv2.arcLength(casco, True)
    pts = None
    for paso in np.arange(0.005, 0.12, 0.005):
        aprox = cv2.approxPolyDP(casco, paso * perimetro, True)
        if len(aprox) == 4:
            pts = aprox.reshape(-1, 2).astype(np.float32)
            break
        if len(aprox) < 4:
            break
    if pts is None:
        pts = cv2.boxPoints(cv2.minAreaRect(casco)).astype(np.float32)
    suma, resta = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[np.argmin(suma)], pts[np.argmin(resta)],
                       pts[np.argmax(suma)], pts[np.argmax(resta)]])


def enderezar(gris, esquinas, lado=900):
    """Homografia a un rectangulo, conservando mas o menos la proporcion."""
    a, b, c, d = esquinas
    ancho = (np.linalg.norm(b - a) + np.linalg.norm(c - d)) / 2
    alto = (np.linalg.norm(d - a) + np.linalg.norm(c - b)) / 2
    esc = lado / max(ancho, alto)
    W, H = max(40, int(ancho * esc)), max(40, int(alto * esc))
    M = cv2.getPerspectiveTransform(
        esquinas, np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    return cv2.warpPerspective(gris, M, (W, H), flags=cv2.INTER_CUBIC,
                               borderValue=255)


def sesgo(mascara, vertical, largo_min):
    """Cuanto se inclinan las rayas, en pixeles de desvio por pixel de avance.

    Las cuatro esquinas del marco nunca salen perfectas, y un par de grados que
    sobren bastan para arruinarlo todo: sobre una hoja de 579 px de alto, 3
    grados corren cada raya vertical 37 px, y al proyectarla sobre el eje se
    unta sobre 40 columnas en vez de dar un pico. Las rayas ya encontradas
    dicen mejor que nadie cuanto falta por girar.
    """
    n, etq, est, _ = cv2.connectedComponentsWithStats((mascara > 0).astype(np.uint8), 8)
    col = cv2.CC_STAT_HEIGHT if vertical else cv2.CC_STAT_WIDTH
    pendientes = []
    for i in range(1, n):
        if est[i, col] < largo_min:
            continue
        ys, xs = np.nonzero(etq == i)
        a, b = (ys, xs) if vertical else (xs, ys)
        if a.std() < 1e-6:
            continue
        pendientes.append(float(np.cov(b, a)[0, 1] / np.var(a)))
    return float(np.median(pendientes)) if pendientes else 0.0


def afinar(derecha):
    """Quita el giro y el sesgo que quedaron tras la homografia."""
    H, W = derecha.shape
    b = binarizar(aplanar_luz(derecha))
    hor, ver = rayas(b, max(12, min(derecha.shape) // 12))
    sv = sesgo(ver, True, H * 0.25)       # dx por cada dy
    sh = sesgo(hor, False, W * 0.25)      # dy por cada dx
    if abs(sv) < 1e-3 and abs(sh) < 1e-3:
        return derecha
    M = np.float32([[1.0, -sv, sv * H / 2.0],
                    [-sh, 1.0, sh * W / 2.0]])
    return cv2.warpAffine(derecha, M, (W, H), flags=cv2.INTER_CUBIC,
                          borderValue=255)


# ------------------------------------------------- 3. encontrar la rejilla -

def agrupar(valores, holgura):
    """Parte una lista de numeros donde haya un hueco grande."""
    grupos, actual = [], [valores[0]]
    for v in valores[1:]:
        if v - actual[-1] > holgura:
            grupos.append(actual); actual = [v]
        else:
            actual.append(v)
    grupos.append(actual)
    return grupos


def cuantas_celdas(centros, largo, tam_celda, maximo=31):
    """Cuantas celdas caben a lo largo de un eje, a partir de los centros vistos.

    El marco ya esta enderezado a [0, largo], asi que si hay n celdas sus
    centros caen en largo*(i+1/2)/n. Se prueba cada n y se mira que tan lejos
    queda cada centro visto del centro previsto mas cercano, medido EN CELDAS
    y no en pixeles: asi un n mas grande no gana solo por tener la reticula mas
    tupida, que es lo que arruinaba el intento anterior.

    Las celdas que faltan -las negras pegadas, que no dejan hueco que ver- no
    estorban: simplemente no votan.

    Hace falta el tope de 'tam_celda' y no es por si acaso: sin el, para n
    grande la reticula queda tan tupida que el error normalizado se estanca en
    un cuarto de celda pase lo que pase, y con la hoja torcida eso le ganaba al
    n verdadero (una de 5x5 se leia de 16 columnas). El paso nunca puede ser
    menor que una celda que ya se vio.
    """
    c = np.asarray(centros, dtype=np.float64)
    if not len(c) or largo <= 0 or tam_celda <= 0:
        return None
    maximo = min(maximo, max(1, int(largo / (tam_celda * 0.85))))
    mejor, mejor_n = None, None
    for n in range(1, maximo + 1):
        previstos = largo * (np.arange(n) + 0.5) / n
        d = np.abs(c[:, None] - previstos[None, :]).min(axis=1)
        error = float(d.mean()) / (largo / n)      # en fracciones de celda
        if mejor is None or error < mejor - 1e-9:
            mejor, mejor_n = error, n
    return mejor_n if mejor is not None and mejor < 0.25 else None


def celdas_de_la_tabla(derecha, tamaño=None):
    """Las celdas son los HUECOS que dejan las rayas. Devuelve (cajas, f, c).

    Este es el unico camino que aguanto las hojas anchas. Los tres anteriores
    -picos del perfil, enrejado regular ajustado, y periodicidad- suponian que
    la cuadricula queda perfectamente regular despues de enderezarla, y no
    queda: las cuatro esquinas del marco nunca salen exactas y lo que sobra de
    perspectiva estira un lado respecto del otro. Con dos grados de sobra una
    hoja de 5x8 se leia de 3 columnas, y con el espaciado desigual una de 4x4
    se leia de 8.

    Buscar los huecos no supone nada de eso: cada celda es una region cerrada
    por rayas, se encuentra sola, y lo unico que se hace despues es agrupar sus
    centros por filas y por columnas.
    """
    b = binarizar(aplanar_luz(derecha))
    hor, ver = rayas(b, max(12, min(derecha.shape) // 12))
    rejas = cv2.dilate(cv2.bitwise_or(hor, ver), np.ones((3, 3), np.uint8))
    n, etq, est, cen = cv2.connectedComponentsWithStats(
        cv2.bitwise_not(rejas), 4)

    H, W = derecha.shape
    cajas = []
    for i in range(1, n):
        x, y, w, h, area = (est[i, cv2.CC_STAT_LEFT], est[i, cv2.CC_STAT_TOP],
                            est[i, cv2.CC_STAT_WIDTH], est[i, cv2.CC_STAT_HEIGHT],
                            est[i, cv2.CC_STAT_AREA])
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue                       # lo de afuera del marco
        if area < 0.3 * w * h:             # no es un rectangulo lleno
            continue
        cajas.append((x, y, w, h, float(cen[i][0]), float(cen[i][1])))
    if len(cajas) < 2:
        return None, 0, 0

    # fuera lo que no tenga el tamaño tipico de una celda
    med = np.median([c[2] * c[3] for c in cajas])
    cajas = [c for c in cajas if 0.35 * med <= c[2] * c[3] <= 3.0 * med]
    if not cajas:
        return None, 0, 0

    # De los huecos NO se toma la lista de celdas, se toma CUANTAS hay. Dos
    # recuadros negros pegados no tienen borde visible entre ellos -es negro
    # sobre negro, no es que el codigo no lo vea: en el papel tampoco esta- asi
    # que esas celdas no apareceran nunca como hueco. Con el numero de celdas y
    # el marco ya enderezado se tiende la reticula y no falta ninguna.
    # Para el tope se toma un percentil BAJO, no la mediana: dos recuadros
    # negros pegados en horizontal dan un solo hueco del ancho de dos celdas, y
    # con varios asi la mediana sale doble y el tope parte la cuenta por la
    # mitad (una hoja de 8x8 se leia de 4 columnas). Una celda fusionada
    # siempre es MAS grande que una suelta, nunca mas chica.
    ancho = float(np.percentile([c[2] for c in cajas], 25))
    alto = float(np.percentile([c[3] for c in cajas], 25))
    if tamaño:
        # Contar cuantas celdas hay es la parte que peor se porta, y el dia de
        # la prueba el tamaño se sabe: se mira la hoja. Dandolo, se salta el
        # conteo entero y solo queda leer las celdas, que es lo que si va bien.
        filas, cols = tamaño
    else:
        cols = cuantas_celdas([c[4] for c in cajas], W, ancho)
        filas = cuantas_celdas([c[5] for c in cajas], H, alto)
    if not cols or not filas:
        return None, 0, 0

    # La reticula dice CUANTAS celdas hay y donde caen las que no se vieron;
    # para las que si se vieron se usa su caja de verdad, que con la
    # perspectiva que queda no cae exactamente donde la reticula la pondria.
    rejilla_cajas = {}
    for f in range(filas):
        for c in range(cols):
            rejilla_cajas[(f, c)] = (W * c / cols, H * f / filas,
                                     W * (c + 1) / cols, H * (f + 1) / filas)
    # ...pero SOLO si el hueco medido es UNA celda. Arriba ya se dijo que los
    # huecos fusionados existen -dos celdas blancas cuya raya de en medio salio
    # floja dan un solo hueco del ancho de dos-, y contarlos se arreglo con el
    # percentil; usarlos como caja, no. Una caja doble le mete DOS letras al
    # comparador, que entonces no compara una letra contra sus plantillas sino
    # un borron contra todas: la fila NOCHE se leia NOCOE y MENSAJE se leia
    # MONSAJE, las dos veces cayendo en la O, que es la plantilla que mas se
    # parece a cualquier mancha redondeada. Si el hueco abarca mas de una
    # celda se deja la reticula, que ahi si separa las dos.
    paso_x, paso_y = W / float(cols), H / float(filas)
    for x, y, w, h, mx, my in cajas:
        if w > 1.5 * paso_x or h > 1.5 * paso_y:
            continue
        f = min(filas - 1, max(0, int(my * filas / H)))
        c = min(cols - 1, max(0, int(mx * cols / W)))
        rejilla_cajas[(f, c)] = (x, y, x + w, y + h)
    return rejilla_cajas, filas, cols


# ------------------------------------------------- 4. leer cada celda -----

def normalizar(tinta):
    """Recorta a la tinta, centra y lleva a LADO_PLANTILLA. Devuelve un vector.

    Centrar y escalar por separado es lo que hace que una 'M' de una fuente
    valga contra la 'M' de otra: lo que se compara es la FORMA, no el tamaño
    ni donde cayo dentro de la celda.
    """
    ys, xs = np.nonzero(tinta > 0)
    if len(xs) < 8:
        return None
    recorte = tinta[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = recorte.shape
    esc = (LADO_PLANTILLA - 6) / float(max(h, w))
    chico = cv2.resize(recorte, (max(1, int(round(w * esc))),
                                 max(1, int(round(h * esc)))),
                       interpolation=cv2.INTER_AREA)
    lienzo = np.zeros((LADO_PLANTILLA, LADO_PLANTILLA), np.float32)
    y0 = (LADO_PLANTILLA - chico.shape[0]) // 2
    x0 = (LADO_PLANTILLA - chico.shape[1]) // 2
    lienzo[y0:y0 + chico.shape[0], x0:x0 + chico.shape[1]] = chico
    # Se difumina ANTES de comparar, y los dos lados igual. La plantilla sale
    # de una fuente nitida y la celda de una foto con desenfoque y tinta mas
    # gorda; sin difuminar, la comparacion se juega en si el trazo cae en este
    # pixel o en el de al lado, que es justo lo que cambia entre una fuente y
    # otra. Con esto lo que pesa es la forma.
    lienzo = cv2.GaussianBlur(lienzo, (5, 5), 0)
    v = lienzo.ravel()
    n = np.linalg.norm(v)
    return v / n if n > 0 else None


class Plantillas:
    def __init__(self, ruta=None):
        ruta = Path(ruta or Path(__file__).with_name("plantillas.npz"))
        d = np.load(ruta, allow_pickle=False)
        self.pilas = d["pilas"]                  # ya normalizadas
        self.etiquetas = d["etiquetas"]
        self.alfabeto = "".join(d["alfabeto"].tolist())

    def letra(self, vector):
        """La letra mas parecida y que tan segura es (0 a 1)."""
        p = self.pilas @ vector                  # coseno: ambos unitarios
        k = int(np.argmax(p))
        mejor = float(p[k])
        cual = int(self.etiquetas[k])
        otras = p[self.etiquetas != cual]
        segunda = float(otras.max()) if len(otras) else 0.0
        return self.alfabeto[cual], mejor, mejor - segunda


def desenfoque_grande(gris, k):
    """Un GaussianBlur de nucleo enorme, pero hecho en pequeno.

    Con celdas de 120 px el nucleo sale de 485x485, y ese desenfoque costaba
    485 ms: el 62% de lo que tardaba leer una hoja entera, y en vivo dejaba la
    camara en 1.4 cuadros por segundo.

    Se puede hacer a un cuarto de tamano sin perder nada, y no es una
    aproximacion de las que se pagan luego: lo que se desenfoca aqui ya viene
    de una dilatacion de 485 px, o sea que por construccion no tiene un solo
    detalle mas pequeno que eso. Reducir a 1/4 no tiene que tirar informacion
    que no exista. Medido contra el desenfoque entero sobre la hoja de ejemplo:
    9 ms en vez de 485, diferencia media de 0.00 niveles de gris.

    Con nucleos pequenos el rodeo no compensa y ademas si empezaria a notarse,
    asi que por debajo de 60 px se hace el desenfoque de siempre.
    """
    if k < 60:
        return cv2.GaussianBlur(gris, (k | 1, k | 1), 0)
    escala = 0.25
    ch = cv2.resize(gris, None, fx=escala, fy=escala,
                    interpolation=cv2.INTER_AREA)
    kc = max(3, int(k * escala)) | 1
    ch = cv2.GaussianBlur(ch, (kc, kc), 0)
    return cv2.resize(ch, (gris.shape[1], gris.shape[0]),
                      interpolation=cv2.INTER_LINEAR)


def tinta_de_la_hoja(derecha, lado_celda):
    """Binariza la hoja ENTERA de una vez. Tinta = blanco.

    Dos cosas que parecen detalle y no lo son:

    - Se binariza una sola vez, no celda por celda. Binarizar cada celda con
      Otsu parece mas fino y es un desastre: sobre una celda UNIFORME -vacia o
      negra del todo- Otsu no tiene dos grupos que separar y parte el ruido por
      la mitad, o sea que inventa una forma. Asi se leian 18 celdas vacias y 13
      negras como si fueran una M.
    - El blanco del papel se estima con el MAXIMO local, no con un desenfoque.
      Dividir por un desenfoque funciona para un gradiente suave, pero dentro
      de un recuadro negro grande el propio recuadro tira la media hacia abajo
      y el negro se aclara solo hasta desaparecer. El maximo local en una
      ventana mas grande que una celda siempre cae sobre papel.
    """
    # La ventana se mide contra la HOJA, no contra la celda. Con una ventana de
    # una celda y pico basta un bloque de tres o cuatro negros pegados -que es
    # justo como son las hojas de crucigrama- para que dentro de la ventana no
    # quede nada de papel: el negro se normaliza contra si mismo y desaparece.
    # Se veian celdas completamente negras con 0,15 de tinta y se leian como
    # letra. Un cuarto de la hoja siempre alcanza papel, y la sombra varia lo
    # bastante despacio como para que siga siguiendola.
    k = int(max(9, lado_celda * 4)) | 1
    papel = cv2.dilate(derecha, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    papel = desenfoque_grande(papel, k)
    plano = np.clip(derecha.astype(np.float32) * 220.0
                    / np.maximum(papel.astype(np.float32), 1), 0, 255)
    _, b = cv2.threshold(plano.astype(np.uint8), 0, 255,
                         cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def leer_celda(binaria, x0, x1, y0, y1, plantillas):
    """Que hay en una celda: recuadro negro, vacia, o una letra."""
    m = MARGEN_CELDA
    dx, dy = (x1 - x0) * m, (y1 - y0) * m
    b = binaria[int(y0 + dy):int(y1 - dy), int(x0 + dx):int(x1 - dx)]
    if b.size < 16:
        return BLANCO, 0.0
    # Se mide y se normaliza sobre el recorte TAL CUAL, sin llevarlo antes a un
    # tamaño fijo: reescalar una mascara binaria y volver a umbralizarla
    # adelgaza los trazos finos hasta borrarlos, y letras enteras -K, B, S, O-
    # se leian como celda vacia.
    tinta = float((b > 0).mean())
    if tinta >= TINTA_NEGRO:
        return NEGRO, 1.0
    if tinta <= TINTA_VACIA:
        return BLANCO, 1.0
    v = normalizar(b.astype(np.float32))
    if v is None:
        return BLANCO, 1.0
    letra, parecido, margen = plantillas.letra(v)
    return letra, margen


# ------------------------------------------------- 5. todo junto ----------

def leer_hoja(ruta, plantillas=None, devolver_debug=False,
              tamaño=None):
    """De la foto a la matriz. Devuelve (grid, nota, confianzas)."""
    # acepta una ruta o un cuadro ya cargado (la camara entrega cuadros)
    img = (ruta if isinstance(ruta, np.ndarray)
           else cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE))
    if img is None:
        return None, "no se pudo abrir la imagen", None
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    esc = min(1.0, 1400.0 / max(img.shape))
    if esc < 1.0:
        img = cv2.resize(img, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)

    img = quitar_giro(img)
    b = binarizar(aplanar_luz(img))
    n = max(12, min(img.shape) // 14)
    hor, ver = rayas(b, n)
    # Para el MARCO se juntan las rayas con los recuadros negros. Buscarlo solo
    # con las rayas falla en cuanto hay negros pegados al borde: ahi el borde
    # es negro sobre negro, la raya no existe y el contorno del marco se parte
    # en pedazos (en la hoja de 8x11 el trozo mayor medía 690x708 dentro de
    # 1400x1068 y las esquinas salian de un cuadrado girado 19 grados).
    solidos = cv2.morphologyEx(
        b, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, n // 2),) * 2))
    esquinas = esquinas_de_la_tabla(cv2.dilate(
        cv2.bitwise_or(cv2.bitwise_or(hor, ver), solidos),
        np.ones((5, 5), np.uint8)))
    if esquinas is None:
        return None, "no se ve el marco de la tabla", None

    derecha = afinar(enderezar(img, esquinas))
    cajas, filas, cols = celdas_de_la_tabla(derecha, tamaño)
    if not cajas:
        return None, "se ve el marco pero no las celdas de adentro", None

    lado = np.median([x1 - x0 for x0, y0, x1, y1 in cajas.values()])
    binaria = tinta_de_la_hoja(derecha, lado)

    plantillas = plantillas or Plantillas()
    grid, confianzas = [], []
    for f in range(filas):
        fila, conf = [], []
        for c in range(cols):
            caja = cajas.get((f, c))
            if caja is None:
                fila.append(BLANCO); conf.append(0.0); continue
            x0, y0, x1, y1 = caja
            v, m = leer_celda(binaria, x0, x1, y0, y1, plantillas)
            fila.append(v); conf.append(m)
        grid.append(fila); confianzas.append(conf)
    nota = "%d x %d" % (len(grid), len(grid[0]))
    if devolver_debug:
        # 'cajas' y la escala hacen falta para pintar la rejilla encima del
        # cuadro de la camara: van en coordenadas de la hoja ya enderezada.
        return grid, nota, (confianzas, derecha, cajas)
    return grid, nota, confianzas


def leer_cuadro(cap):
    """Lee un cuadro y dice si la camara lo entrego BIEN.

    cap.read() no solo devuelve False cuando no hay imagen: tambien puede
    reventar con un cv2.error si el tamano que la camara DICE tener no es el
    del buffer que entrega. Pasa con DroidCam cuando se gira el telefono y
    cambia de formato en caliente. Es un cuadro que hay que tirar, no un
    motivo para morirse: el mismo criterio que en rx_camara.py.
    """
    try:
        ok, cuadro = cap.read()
    except cv2.error:
        return False, None
    return bool(ok), cuadro


def abrir_camara(fuente, ancho=1920, alto=1080):
    """Abre la camara pidiendole el tamano ANTES del primer cuadro.

    Soporta indice (0, 1, ...), nombre de camara ('droidcam', 'iriun') o URL (http://...).
    Prueba backends adecuados (DSHOW, MSMF, ANY) para compatibilidad total con DroidCam y webcams.
    """
    if isinstance(fuente, str) and "://" in fuente:
        cap = cv2.VideoCapture(fuente, cv2.CAP_FFMPEG)
        if cap.isOpened():
            return cap
        return cv2.VideoCapture(fuente)

    # Si se paso texto con el nombre de la camara, resolver indice
    if isinstance(fuente, str) and not fuente.isdigit():
        try:
            from pygrabber.dshow_graph import FilterGraph
            for i, nom in enumerate(FilterGraph().get_input_devices()):
                if fuente.lower() in nom.lower():
                    fuente = i
                    break
        except Exception:
            pass

    cual = int(fuente) if str(fuente).isdigit() else fuente
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]

    for be in backends:
        try:
            cap = cv2.VideoCapture(cual, be)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            if leer_cuadro(cap)[0]:
                return cap
            cap.release()
            cap = cv2.VideoCapture(cual, be)
            if cap.isOpened() and leer_cuadro(cap)[0]:
                return cap
            cap.release()
        except Exception:
            pass

    return cv2.VideoCapture(cual)


class LectorDeFondo:
    """Lee la hoja en OTRO HILO para que la camara no se pare.

    leer_hoja tarda del orden de 300 ms por cuadro, casi todo en el Hough de
    quitar_giro. Llamandola dentro del bucle de dibujo la ventana se refresca
    tres veces por segundo, y con tres cuadros por segundo no se puede apuntar:
    se mueve la mano y la imagen va un tercio de segundo por detras. Por eso
    "el de los rx va mas rapido" -rx_camara.py hace justo esto, lo caro en
    hilos aparte y el bucle de captura solo capturando.

    El hilo trabaja siempre sobre el ULTIMO cuadro ofrecido, no sobre una cola:
    los cuadros atrasados no le importan a nadie, lo que importa es lo que la
    camara esta viendo ahora. Los que llegan mientras esta ocupado se tiran, y
    eso es lo correcto, no una perdida.
    """

    def __init__(self, plantillas, tamaño=None):
        self.plantillas, self.tamaño = plantillas, tamaño
        self._pendiente = None
        self._salida = None
        self._parar = False
        self._cerrojo = threading.Lock()
        self._hilo = threading.Thread(target=self._trabajar, daemon=True)
        self._hilo.start()

    def ofrecer(self, gris):
        """Deja un cuadro para analizar, pisando el que hubiera sin analizar."""
        with self._cerrojo:
            self._pendiente = gris

    def ultimo(self):
        """La ultima lectura terminada: (grid, nota, extra), o None."""
        with self._cerrojo:
            return self._salida

    def parar(self):
        self._parar = True
        self._hilo.join(timeout=2.0)

    def _trabajar(self):
        while not self._parar:
            with self._cerrojo:
                gris, self._pendiente = self._pendiente, None
            if gris is None:
                time.sleep(0.005)
                continue
            try:
                salida = leer_hoja(gris, self.plantillas, devolver_debug=True,
                                   tamaño=self.tamaño)
            except Exception as e:                  # un cuadro malo no mata
                salida = (None, "no se pudo leer: %s" % e, None)
            with self._cerrojo:
                self._salida = salida


def leer_de_la_camara(fuente, cuadros=25, avisar=print):
    """Lee la hoja de la camara y se queda con lo que MAS SE REPITE.

    En vivo hay una ventaja que la foto no tiene: se puede mirar muchas veces.
    Los errores que quedan dependen del ruido y de donde caiga la reticula, o
    sea que cambian de un cuadro a otro, mientras que el acierto se repite.
    Votar entre varias lecturas se lleva por delante casi todos.
    """
    cap = abrir_camara(fuente)
    if not cap.isOpened():
        return None, "no se pudo abrir la camara", None
    plantillas = Plantillas()
    votos, margenes, leidas = {}, {}, 0
    try:
        for _ in range(cuadros * 4):          # de sobra, por los cuadros malos
            ok, f = leer_cuadro(cap)
            if not ok:
                break
            gris = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
            grid, nota, conf = leer_hoja(gris, plantillas)
            if grid is None:
                continue
            leidas += 1
            forma = (len(grid), len(grid[0]))
            for i, fila in enumerate(grid):
                for j, v in enumerate(fila):
                    clave = (forma, i, j)
                    caja = votos.setdefault(clave, {})
                    caja[v] = caja.get(v, 0) + 1
                    margenes.setdefault(clave, {}).setdefault(v, []).append(
                        conf[i][j] if conf else 1.0)
            if avisar and leidas % 5 == 0:
                avisar("   %d lecturas buenas (%s)" % (leidas, nota))
            if leidas >= cuadros:
                break
    finally:
        cap.release()
    if not votos:
        return None, "no se vio ninguna cuadricula", None

    # la forma que mas veces se vio manda; las lecturas de otra forma se tiran
    formas = {}
    for (forma, _, _), caja in votos.items():
        formas[forma] = formas.get(forma, 0) + sum(caja.values())
    forma = max(formas, key=formas.get)
    filas, cols = forma
    grid, seguridad = [], []
    for i in range(filas):
        fila, seg = [], []
        for j in range(cols):
            caja = votos.get((forma, i, j), {})
            if not caja:
                fila.append(BLANCO); seg.append(0.0); continue
            v = max(caja, key=caja.get)
            fila.append(v)
            # Igual que en mirar_con_la_camara: el acuerdo entre lecturas y el
            # margen contra las plantillas son dudas distintas y hacen falta
            # las dos. Ver el comentario largo de alla.
            acuerdo = caja[v] / float(sum(caja.values()))
            suyos = margenes.get((forma, i, j), {}).get(v, [])
            seg.append(0.0 if acuerdo < ACUERDO_MIN
                       else (float(np.median(suyos)) if suyos else 1.0))
        grid.append(fila); seguridad.append(seg)
    return grid, "%d x %d  (%d lecturas)" % (filas, cols, leidas), seguridad


# Por debajo de este margen entre la mejor plantilla y la segunda, la letra se
# marca con ? para que la revises. El numero esta medido sobre las DIEZ FOTOS
# REALES de la hoja impresa (183 letras acertadas, 16 falladas):
#
#   0,05 -> marca el 31% de los errores y estorba en el  8,7% de los aciertos
#   0,08 -> marca el 62% de los errores y estorba en el 21,9% de los aciertos
#   0,12 -> marca el 81% de los errores y estorba en el 43,7% de los aciertos
#
# Antes estaba en 0,05 porque sobre el banco sintetico ese umbral cazaba TODOS
# los errores estorbando en el 4,8%. En papel no se parece: las dos
# distribuciones se solapan mucho mas (los errores tienen margen mediano 0,073
# y los aciertos 0,143), asi que no hay ningun umbral que cace todo sin
# marcar media hoja. 0,08 es el compromiso; subirlo caza mas y marca mas.
DUDA = 0.08

# Cuando se vota entre varias lecturas, por debajo de este acuerdo la celda se
# marca como dudosa aunque cada lectura suelta pareciera segura.
ACUERDO_MIN = 0.6


def pintar(grid, confianzas=None, duda=DUDA):
    """La matriz, marcando con ? al lado de lo que no quedo claro."""
    for i, fila in enumerate(grid):
        marcas = []
        for j, v in enumerate(fila):
            c = confianzas[i][j] if confianzas else 1.0
            marcas.append(("%s?" % v) if c < duda else ("%s " % v))
        print("   " + " ".join(marcas))


def _calidad(grid, conf):
    """Que tan convencido esta el comparador de letras de esta lectura.

    Es el criterio para elegir entre las cuatro orientaciones. Una hoja bien
    puesta da letras que se parecen mucho a alguna plantilla y poco a la
    siguiente; la misma hoja de lado da trazos que no son ninguna letra y el
    margen se hunde. Se mira solo las celdas con letra: los recuadros negros y
    los blancos puntuan igual gire como gire.
    """
    if not grid or not conf:
        return -1.0
    margenes = [c for fila, fc in zip(grid, conf)
                for v, c in zip(fila, fc) if v not in (NEGRO, BLANCO)]
    if len(margenes) < 3:
        return -1.0
    return float(np.mean(margenes))


# Por debajo de esta calidad la lectura no es de fiar y conviene repetir la
# foto. Medido sobre las doce fotos del telefono: las que salieron perfectas
# dan de 0,136 para arriba (64% de letras seguras) y las equivocadas se quedan
# en 0,112 para abajo (57%). El hueco entre las dos es limpio.
CALIDAD_FIRME = 0.125


def leer_hoja_girando(ruta, plantillas=None, tamaño=None, avisar=None,
                      devolver_debug=False):
    """Prueba varias maneras de mirar la foto y se queda con la que convence.

    Se prueban las cuatro vueltas de cuarto y, de cada una, la foto tal cual y
    con un margen de papel añadido alrededor. Son ocho intentos y gana el que
    deje las letras mas parecidas a alguna plantilla.

    Por que las cuatro vueltas: las fotos salen giradas un cuarto mas a menudo
    de lo que parece, y eso quitar_giro no lo puede arreglar -ese mide cuanto
    se desvian las rayas, y a 90 grados el desvio es cero: la rejilla de una
    cuadricula girada un cuarto de vuelta sigue siendo una rejilla perfecta-.
    Lo unico que distingue las cuatro es la LETRA, que es el mismo criterio que
    usa el detector de orientacion de Tesseract. Sobre el banco del telefono
    tres fotos pasaron de ilegibles a perfectas solo con esto.

    Por que el margen: si la tabla llega hasta el borde del encuadre, las
    celdas del borde tocan el limite de la imagen y se descartan, y a veces se
    va con ellas el marco entero. Añadir papel alrededor no inventa nada y
    devuelve el caso al terreno normal; una foto paso de 37% a 100% asi.
    """
    plantillas = plantillas or Plantillas()
    img = (ruta if isinstance(ruta, np.ndarray)
           else cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE))
    if img is None:
        if devolver_debug:
            return None, "no se pudo abrir la imagen", None, None
        return None, "no se pudo abrir la imagen", None
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    papel = int(np.percentile(img, 90))
    ancho = max(40, int(0.05 * max(img.shape)))
    con_marco = cv2.copyMakeBorder(img, ancho, ancho, ancho, ancho,
                                   cv2.BORDER_CONSTANT, value=papel)

    # Se prueba primero la foto tal cual y sin girar, que es el caso normal, y
    # si ya convence no se prueban las otras siete: ocho intentos cuestan ocho
    # veces mas y la mayoria de las fotos salen bien a la primera.
    mejor = (None, "no se ve ninguna cuadricula", None, -1.0, 0, False, None)
    for base, orillado in ((img, False), (con_marco, True)):
        if mejor[3] >= CALIDAD_FIRME:
            break
        vueltas = ((0, base),
                   (90, cv2.rotate(base, cv2.ROTATE_90_CLOCKWISE)),
                   (180, cv2.rotate(base, cv2.ROTATE_180)),
                   (270, cv2.rotate(base, cv2.ROTATE_90_COUNTERCLOCKWISE)))
        for grados, vista in vueltas:
            if mejor[3] >= CALIDAD_FIRME:
                break
            t = tamaño
            if t and grados in (90, 270):
                t = (t[1], t[0])       # de canto, filas y columnas se cambian
            if devolver_debug:
                grid, nota, extra = leer_hoja(
                    vista, plantillas, tamaño=t, devolver_debug=True)
                conf = extra[0] if extra else None
            else:
                grid, nota, conf = leer_hoja(vista, plantillas, tamaño=t)
                extra = None
            q = _calidad(grid, conf)
            if avisar:
                avisar("   %3d grados%s -> %-12s calidad %.3f"
                       % (grados, " con margen" if orillado else "          ",
                          nota if grid else "no lee", q))
            if q > mejor[3]:
                mejor = (grid, nota, conf, q, grados, orillado, extra)

    grid, nota, conf, q, grados, orillado, extra = mejor
    if grid is None:
        if devolver_debug:
            return None, nota, None, None
        return None, nota, None
    detalles = []
    if grados:
        detalles.append("girada %d grados" % grados)
    if orillado:
        detalles.append("con margen añadido")
    if detalles:
        nota = "%s  (%s)" % (nota, ", ".join(detalles))
    if q < CALIDAD_FIRME:
        nota += "\n   OJO: lectura floja (calidad %.3f). Repite la foto mas " \
                "cerca, mas plana y sin sombras encima." % q
    if devolver_debug:
        debug_info = (extra[1], extra[2]) if (extra and len(extra) >= 3) else (None, None)
        return grid, nota, conf, debug_info
    return grid, nota, conf


def escoger_archivo():
    """Abre el dialogo de siempre para buscar la foto, sin escribir rutas."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("No hay tkinter: pasa la ruta de la foto como argumento.")
        return None
    raiz = tk.Tk()
    raiz.withdraw()
    ruta = filedialog.askopenfilename(
        title="Escoge la foto de la hoja",
        filetypes=[("Fotos", "*.jpg *.JPG *.jpeg *.JPEG *.png *.PNG "
                             "*.bmp *.BMP *.heic *.HEIC"),
                   ("Todos", "*.*")])
    raiz.destroy()
    return ruta or None


def panel_de_lectura(derecha, cajas, grid, conf, duda=DUDA):
    """La hoja ENDEREZADA con la rejilla y las letras leidas encima.

    Esto es lo que de verdad hay que poder mirar: no el cuadro de la camara,
    sino lo que el programa cree que esta viendo. Si la hoja sale torcida, si
    la rejilla no cae sobre las celdas o si una letra esta mal, aqui se ve de
    un vistazo y no hay que leer la consola al final para enterarse.

    Se dibuja sobre la hoja enderezada y no sobre el cuadro de la camara por
    una razon concreta: las cajas de las celdas estan en coordenadas de la hoja
    enderezada, que es otro sistema. Llevarlas de vuelta al cuadro habria que
    deshacer la homografia Y el giro de quitar_giro, y aun asi quedarian mal
    encajadas porque el analisis va un poco por detras de la imagen. Sobre la
    hoja enderezada siempre cuadran, porque salieron de ahi.

    Verde = la celda se leyo con holgura. Naranja = la mejor plantilla y la
    segunda quedaron demasiado cerca (o los votos no se pusieron de acuerdo);
    son las que hay que mirar a ojo.
    """
    vista = cv2.cvtColor(derecha, cv2.COLOR_GRAY2BGR)
    for (f, c), (x0, y0, x1, y1) in cajas.items():
        if f >= len(grid) or c >= len(grid[0]):
            continue
        v = grid[f][c]
        seguro = (conf[f][c] >= duda) if conf else True
        color = (90, 200, 90) if seguro else (60, 180, 255)
        p0, p1 = (int(x0), int(y0)), (int(x1), int(y1))
        cv2.rectangle(vista, p0, p1, color, 2)
        if v not in (NEGRO, BLANCO):
            escala = max(0.5, (x1 - x0) / 90.0)
            cv2.putText(vista, v, (p0[0] + 6, p1[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), 5,
                        cv2.LINE_AA)
            cv2.putText(vista, v, (p0[0] + 6, p1[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, escala, color, 2,
                        cv2.LINE_AA)
    return vista


def lado_a_lado(izquierda, derecha, alto=620):
    """Junta el cuadro de la camara y el panel, los dos al mismo alto."""
    def a_ese_alto(im):
        f = alto / float(im.shape[0])
        return cv2.resize(im, (max(1, int(im.shape[1] * f)), alto),
                          interpolation=cv2.INTER_AREA)
    izquierda = a_ese_alto(izquierda)
    if derecha is None:
        return izquierda
    derecha = a_ese_alto(derecha)
    separador = np.full((alto, 6, 3), 40, np.uint8)
    return np.hstack([izquierda, separador, derecha])


def tablero_digital(grid, conf=None, alto_target=620, duda=DUDA):
    """Genera una imagen BGR con la matriz digital limpia y contrastada."""
    filas = len(grid)
    cols = len(grid[0])
    lado = max(26, min(alto_target // filas, 75))
    ancho = cols * lado
    alto = filas * lado
    t = np.full((alto, ancho, 3), 35, dtype=np.uint8)
    for f in range(filas):
        for c in range(cols):
            x0, y0 = c * lado, f * lado
            x1, y1 = x0 + lado, y0 + lado
            v = grid[f][c]
            seguro = (conf[f][c] >= duda) if conf else True
            if v == NEGRO:
                cv2.rectangle(t, (x0, y0), (x1, y1), (20, 20, 20), -1)
                cv2.rectangle(t, (x0, y0), (x1, y1), (70, 70, 70), 1)
            elif v == BLANCO:
                cv2.rectangle(t, (x0, y0), (x1, y1), (245, 245, 245), -1)
                cv2.rectangle(t, (x0, y0), (x1, y1), (180, 180, 180), 1)
            else:
                fondo = (240, 240, 240) if seguro else (180, 215, 255)
                cv2.rectangle(t, (x0, y0), (x1, y1), fondo, -1)
                borde = (90, 200, 90) if seguro else (30, 90, 240)
                cv2.rectangle(t, (x0, y0), (x1, y1), borde, 2 if not seguro else 1)
                escala = max(0.5, lado / 46.0)
                (tw, th), _ = cv2.getTextSize(v, cv2.FONT_HERSHEY_SIMPLEX, escala, 2)
                tx = x0 + (lado - tw) // 2
                ty = y0 + (lado + th) // 2
                cv2.putText(t, v, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, escala, (15, 15, 15), 2, cv2.LINE_AA)
                if not seguro:
                    cv2.putText(t, '?', (x1 - 13, y0 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 220), 1, cv2.LINE_AA)
    return t


def graficar_lectura(grid, nota, conf=None, derecha=None, cajas=None,
                     titulo="Matriz detectada", esperar=True):
    """Muestra una ventana grafica con la hoja detectada y la matriz digital.

    Permite ver al instante:
      - Si el marco y la homografia encajaron bien sobre la hoja.
      - Si las casillas detectadas (verde = seguro, naranja = dudoso) corresponden.
      - La matriz final decodificada al lado para contrastar errores con facilidad.
    """
    if not hay_pantalla():
        return

    alto_vista = 600
    if derecha is not None and cajas:
        izq = panel_de_lectura(derecha, cajas, grid, conf)
    else:
        izq = None

    der = tablero_digital(grid, conf, alto_target=alto_vista)
    if izq is not None:
        cuerpo = lado_a_lado(izq, der, alto=alto_vista)
    else:
        cuerpo = der

    ancho_total = cuerpo.shape[1]
    banner_alto = 54
    pie_alto = 32

    banner = np.full((banner_alto, ancho_total, 3), 26, dtype=np.uint8)
    q = _calidad(grid, conf)
    if q >= CALIDAD_FIRME:
        color_q = (90, 200, 90)
        estado_q = "Lectura Firme"
    elif q > 0:
        color_q = (50, 120, 240)
        estado_q = "Lectura Dudosa (revisar naranja ?)"
    else:
        color_q = (180, 180, 180)
        estado_q = "Calidad N/D"

    texto_izq = "%s   -   %s" % (titulo, nota.split("\n")[0])
    texto_der = "Calidad: %.3f (%s)" % (q, estado_q) if q > 0 else estado_q
    cv2.putText(banner, texto_izq, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                (240, 240, 240), 2, cv2.LINE_AA)
    (tw, _), _ = cv2.getTextSize(texto_der, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    cv2.putText(banner, texto_der, (max(14, ancho_total - tw - 14), 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color_q, 2, cv2.LINE_AA)

    pie = np.full((pie_alto, ancho_total, 3), 26, dtype=np.uint8)
    leyenda = "[Verde: seguro]   [Naranja: dudoso ?]   [Negro: #]   [Blanco: _]   |   Cualquier tecla / Q para cerrar"
    cv2.putText(pie, leyenda, (14, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                (180, 180, 180), 1, cv2.LINE_AA)

    completa = np.vstack([banner, cuerpo, pie])

    # Redimensionar si se pasa del tamaño estándar de pantalla
    H, W = completa.shape[:2]
    max_w, max_h = 1366, 740
    if W > max_w or H > max_h:
        factor = min(float(max_w) / W, float(max_h) / H)
        completa = cv2.resize(completa, (int(W * factor), int(H * factor)),
                              interpolation=cv2.INTER_AREA)

    nom_ventana = "Diagnostico Matriz - %s" % titulo
    cv2.namedWindow(nom_ventana, cv2.WINDOW_NORMAL)
    cv2.imshow(nom_ventana, completa)
    print("   (grafica abierta: pulsa cualquier tecla o 'q' en la ventana para continuar)")
    if esperar:
        cv2.waitKey(0)
        cv2.destroyWindow(nom_ventana)


def mirar_con_la_camara(fuente, tamaño=None, cuadros=25, devolver_debug=False):
    """Como leer_de_la_camara, pero ENSEÑANDO lo que ve la camara.

    Sin ver la imagen no se puede apuntar: el programa encuentra algo y quien
    sostiene el telefono no sabe a que. Aqui se ve el cuadro, la rejilla que
    ha encontrado dibujada encima y las letras que va leyendo, asi que se
    corrige la punteria mirando.
    """
    if not hay_pantalla():
        print("(sin pantalla: se lee a ciegas)")
        res = leer_de_la_camara(fuente, cuadros)
        if devolver_debug:
            return res[0], res[1], res[2], (None, None), None
        return res

    cap = abrir_camara(fuente)
    if not cap.isOpened():
        if devolver_debug:
            return None, "no se pudo abrir la camara", None, (None, None), None
        return None, "no se pudo abrir la camara", None
    plantillas = Plantillas()
    ventana = "Hoja - ESPACIO lee, Q sale"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)

    # La lectura va en otro hilo: aqui solo se captura y se dibuja, asi que la
    # ventana corre a la velocidad de la camara y no a la del analisis.
    lector = LectorDeFondo(plantillas, tamaño)
    votos, margenes, leidas, ultimo = {}, {}, 0, None
    forma_ultima, panel = None, None
    ultimo_debug = (None, None)
    ultimo_frame = None
    try:
        while True:
            ok, f = leer_cuadro(cap)
            if not ok:
                break
            gris = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
            vista = f.copy() if f.ndim == 3 else cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            lector.ofrecer(gris)

            salida = lector.ultimo()
            grid, nota = (salida[0], salida[1]) if salida else (None, "mirando...")
            if grid is not None:
                conf, derecha, cajas = salida[2]
                forma_ultima = (len(grid), len(grid[0]))
                ultimo = (grid, conf)
                ultimo_debug = (derecha, cajas)
                ultimo_frame = f.copy()
                panel = panel_de_lectura(derecha, cajas, grid, conf)
                aviso = "%s  -  ESPACIO para leerla" % nota
                color = (90, 200, 90)
            else:
                aviso = str(nota)
                color = (60, 60, 230)

            cv2.putText(vista, aviso, (14, 32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(vista, aviso, (14, 32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, color, 1, cv2.LINE_AA)
            if leidas:
                pie = "%d lecturas juntadas" % leidas
                cv2.putText(vista, pie, (14, vista.shape[0] - 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4,
                            cv2.LINE_AA)
                cv2.putText(vista, pie, (14, vista.shape[0] - 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 230), 1,
                            cv2.LINE_AA)
            cv2.imshow(ventana, lado_a_lado(vista, panel))

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            if tecla == 32 and ultimo is not None:
                # juntar esta lectura con las anteriores de la misma forma
                grid, conf = ultimo
                leidas += 1
                for i, fila in enumerate(grid):
                    for j, v in enumerate(fila):
                        clave = (forma_ultima, i, j)
                        caja = votos.setdefault(clave, {})
                        caja[v] = caja.get(v, 0) + 1
                        # El margen contra las plantillas se guarda junto al
                        # voto: es la unica senal que distingue una letra leida
                        # con holgura de una que gano por los pelos, y sin el
                        # la confianza final solo sabria de acuerdos.
                        margenes.setdefault(clave, {}).setdefault(v, []).append(
                            conf[i][j] if conf else 1.0)
                if leidas >= cuadros:
                    break
    finally:
        lector.parar()
        cap.release()
        cv2.destroyWindow(ventana)

    if not votos:
        if devolver_debug:
            return None, "no se leyo ninguna cuadricula", None, (None, None), None
        return None, "no se leyo ninguna cuadricula", None
    forma = max(set(k[0] for k in votos),
                key=lambda fm: sum(sum(votos[k].values())
                                   for k in votos if k[0] == fm))
    filas, cols = forma
    grid, seguridad = [], []
    for i in range(filas):
        fila, seg = [], []
        for j in range(cols):
            caja = votos.get((forma, i, j), {})
            if not caja:
                fila.append(BLANCO); seg.append(0.0); continue
            v = max(caja, key=caja.get)
            fila.append(v)
            # Dos maneras distintas de dudar, y hacen falta las dos. Con la
            # camara quieta las lecturas salen identicas y el acuerdo es
            # siempre 1.0: creerle solo a el da un 100% de confianza a una
            # letra mal leida. El margen de plantilla si la caza -las dos que
            # fallaban en la hoja de prueba tenian 0.042 y 0.037, por debajo
            # del 0.08 de DUDA-. Y al reves, si las lecturas NO se ponen de
            # acuerdo da igual lo holgada que fuera cada una.
            acuerdo = caja[v] / float(sum(caja.values()))
            suyos = margenes.get((forma, i, j), {}).get(v, [])
            seg.append(0.0 if acuerdo < ACUERDO_MIN
                       else (float(np.median(suyos)) if suyos else 1.0))
        grid.append(fila); seguridad.append(seg)
    res_nota = "%d x %d  (%d lecturas)" % (filas, cols, leidas)
    if devolver_debug:
        return grid, res_nota, seguridad, ultimo_debug, ultimo_frame
    return grid, res_nota, seguridad


def main():
    args = [a for a in sys.argv[1:]]
    tamaño = None
    sin_grafica = False
    for i, a in enumerate(list(args)):
        if a in ("--sin-grafica", "--no-gui"):
            sin_grafica = True
            args = [x for j, x in enumerate(args) if j != i]
            break

    for i, a in enumerate(list(args)):
        if a in ("--tamaño", "--tamano", "-t") and i + 1 < len(args):
            try:
                f, c = args[i + 1].lower().replace("x", " ").split()
                tamaño = (int(f), int(c))
            except ValueError:
                print("El tamaño se escribe asi:  --tamaño 9x8")
                return
            args = [x for j, x in enumerate(args) if j not in (i, i + 1)]
            break

    if args and args[0] in ("--camaras", "-c", "--listar-camaras"):
        try:
            from pygrabber.dshow_graph import FilterGraph
            nombres = list(FilterGraph().get_input_devices())
        except Exception:
            nombres = []
        print("Buscando camaras...")
        for i in range(len(nombres) if nombres else 4):
            nom = nombres[i] if (nombres and i < len(nombres)) else ("camara %d" % i)
            cap = abrir_camara(i)
            if cap.isOpened():
                ok, f = leer_cuadro(cap)
                res = "%dx%d" % (f.shape[1], f.shape[0]) if ok else "sin imagen"
                print("  --camara %d   %-34s  %s" % (i, nom[:34], res))
                cap.release()
            elif nombres and i < len(nombres):
                print("  --camara %d   %-34s  (disponible)" % (i, nom[:34]))
        return

    if args and args[0] == "--camara":
        fuente = args[1] if len(args) > 1 else "0"
        # Si se paso texto con nombre de camara (ej. --camara droidcam), resolverlo
        if not fuente.isdigit() and "://" not in fuente:
            try:
                from pygrabber.dshow_graph import FilterGraph
                for i, nom in enumerate(FilterGraph().get_input_devices()):
                    if fuente.lower() in nom.lower():
                        fuente = str(i)
                        break
            except Exception:
                pass
        print("Mirando la hoja por la camara (%s). ESPACIO lee, Q sale."
              % fuente)
        grid, nota, seg = mirar_con_la_camara(fuente, tamaño)
        print("\n%s" % nota)
        if grid:
            pintar(grid, seg)
        return

    if not args:
        # Sin argumentos se pregunta, que es mas comodo que escribir la ruta.
        ruta = escoger_archivo()
        if not ruta:
            print(__doc__)
            return
        args = [ruta]

    for ruta in args:
        grid, nota, conf, debug = leer_hoja_girando(
            ruta, tamaño=tamaño, devolver_debug=True)
        print("\n%s  ->  %s" % (Path(ruta).name, nota))
        if grid:
            pintar(grid, conf)
            if hay_pantalla() and not sin_grafica:
                derecha, cajas = debug if debug else (None, None)
                graficar_lectura(grid, nota, conf, derecha, cajas,
                                 titulo=Path(ruta).name)
        else:
            print("   %s" % nota)


if __name__ == "__main__":
    main()
