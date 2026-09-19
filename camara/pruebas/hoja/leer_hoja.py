# -*- coding: utf-8 -*-
"""Lee la cuadricula de la hoja impresa: de una foto o de la camara.

    python leer_hoja.py foto.jpg              una foto
    python leer_hoja.py --camara 0            la webcam
    python leer_hoja.py --camara http://IP:8080/video     el celular

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
from pathlib import Path

import cv2
import numpy as np

ALFABETO = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"
NEGRO, BLANCO = "#", "_"

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


def celdas_de_la_tabla(derecha):
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
    for x, y, w, h, mx, my in cajas:
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
    papel = cv2.GaussianBlur(papel, (k, k), 0)
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

def leer_hoja(ruta, plantillas=None, devolver_debug=False):
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
    cajas, filas, cols = celdas_de_la_tabla(derecha)
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
        return grid, nota, (confianzas, derecha, xs, ys)
    return grid, nota, confianzas


def leer_de_la_camara(fuente, cuadros=25, avisar=print):
    """Lee la hoja de la camara y se queda con lo que MAS SE REPITE.

    En vivo hay una ventaja que la foto no tiene: se puede mirar muchas veces.
    Los errores que quedan dependen del ruido y de donde caiga la reticula, o
    sea que cambian de un cuadro a otro, mientras que el acierto se repite.
    Votar entre varias lecturas se lleva por delante casi todos.
    """
    cap = cv2.VideoCapture(int(fuente) if str(fuente).isdigit() else fuente)
    if not cap.isOpened():
        return None, "no se pudo abrir la camara", None
    plantillas = Plantillas()
    votos, leidas = {}, 0
    try:
        for _ in range(cuadros * 4):          # de sobra, por los cuadros malos
            ok, f = cap.read()
            if not ok:
                break
            gris = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
            grid, nota, _ = leer_hoja(gris, plantillas)
            if grid is None:
                continue
            leidas += 1
            forma = (len(grid), len(grid[0]))
            for i, fila in enumerate(grid):
                for j, v in enumerate(fila):
                    caja = votos.setdefault((forma, i, j), {})
                    caja[v] = caja.get(v, 0) + 1
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
            seg.append(caja[v] / float(sum(caja.values())))
        grid.append(fila); seguridad.append(seg)
    return grid, "%d x %d  (%d lecturas)" % (filas, cols, leidas), seguridad


# Por debajo de este margen entre la mejor plantilla y la segunda, la letra se
# marca para que la revises. Esta medido, no puesto a ojo: sobre los cuatro
# bancos (800 letras acertadas, 7 falladas) este umbral marca las 7 falladas y
# solo estorba en el 4,8% de las buenas. Con 0,08 no gana nada y estorba en el
# 25%. Ojo que 7 errores es muestra corta para presumir de cazarlos todos.
DUDA = 0.05


def pintar(grid, confianzas=None, duda=DUDA):
    """La matriz, marcando con ? al lado de lo que no quedo claro."""
    for i, fila in enumerate(grid):
        marcas = []
        for j, v in enumerate(fila):
            c = confianzas[i][j] if confianzas else 1.0
            marcas.append(("%s?" % v) if c < duda else ("%s " % v))
        print("   " + " ".join(marcas))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "--camara":
        fuente = args[1] if len(args) > 1 else "0"
        print("Mirando la hoja por la camara (%s)..." % fuente)
        grid, nota, seg = leer_de_la_camara(fuente)
        print("\n%s" % nota)
        if grid:
            pintar(grid, seg)
        return
    for ruta in args:
        grid, nota, conf = leer_hoja(ruta)
        print("\n%s  ->  %s" % (Path(ruta).name, nota))
        if grid:
            pintar(grid, conf)


if __name__ == "__main__":
    main()
