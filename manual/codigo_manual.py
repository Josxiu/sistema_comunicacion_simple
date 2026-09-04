# -*- coding: utf-8 -*-
"""EL CODIGO: como se convierte una celda en destellos de las dos luces.

Este es el unico archivo donde vive la codificacion. tx_manual.py y
rx_manual.py no la conocen: los dos llaman aqui. Para cambiar el codigo hay
dos sitios y solo dos:

    PARAMETROS       los tiempos (velocidad, parpadeo, aviso)
    TABLA DEL CODIGO que destellos es cada letra y cada recuadro

LOS CUATRO ESTADOS      LA CELDA
  --  las dos apagadas    --  A-      recuadro negro   #
  A-  solo la roja        --  -B      recuadro blanco  _
  -B  solo la verde       --  x x x   letra: 3 destellos
  AB  las dos

Todos los simbolos duran lo mismo. El '--' separa CELDAS, y las FILAS las
separa el preambulo A- -B A- -B: cuatro destellos seguidos, que dentro de los
datos son imposibles (una letra son tres como mucho).

    CABECERA  preambulo | -- 26 | -- filas | -- cols | --
    FILA i    preambulo | -- i  | -- n     | -- celda -- celda ... | -- suma | --

Cada fila viaja aparte con su suma de control, asi que se repite sola.

Un digito repetido dejaria la luz quieta dos tiempos y habria que contar
cuanto duro. Por eso emision() mete un MINI PARPADEO: corta la luz un cuarto
de tiempo antes de repetirla. Eso no cambia el codigo, solo como se emite.

Ejecutar este archivo imprime la tabla y comprueba que codificar y decodificar
dan lo mismo. La explicacion completa esta en LEEME.md.
"""


# ##########################################################################
#
#   P A R A M E T R O S
#
#   Todo lo que se puede ajustar esta aqui. Nada de esto esta repetido en
#   tx_manual.py ni en rx_manual.py: los dos leen estos valores.
#
# ##########################################################################

# --- velocidad ------------------------------------------------------------
# Segundos que dura CADA simbolo, destellos y separadores por igual.
#   1.0  comodo para aprender y para un receptor nuevo
#   0.7  ritmo de una pareja entrenada
#   0.5  rapido; solo si el receptor ya se sabe el codigo
T_SIMBOLO_S = 1.0

# --- mini parpadeo --------------------------------------------------------
# En cuantos trozos se parte cada simbolo. El parpadeo dura UN trozo, o sea
# 1/SUBRANURAS de simbolo. Con 4 el parpadeo es un cuarto de tiempo: corto
# para que no se confunda con el separador, largo para que se vea.
# Subirlo a 8 lo hace mas breve; bajarlo a 2 lo hace medio simbolo.
SUBRANURAS = 4

# --- separacion entre unidades --------------------------------------------
# Pausa despues de cada unidad (cabecera, fila 0, fila 1...). Le da tiempo al
# receptor de anotar y de prepararse para la fila siguiente. No forma parte
# del codigo: es tiempo muerto, se puede poner a 0 sin romper nada.
PAUSA_ENTRE_UNIDADES_S = 2.0

# --- aviso ("preparense, voy a transmitir") -------------------------------
# Las dos luces parpadeando rapido. Va mucho mas rapido que un simbolo, asi
# que es imposible confundirlo con datos.
AVISO_DESTELLOS = 6            # cuantas veces prenden y apagan
AVISO_T_S = 0.12               # cuanto dura cada prendida y cada apagada


# ------------------------------------------------------------ estados -----
SEP = 0          # --   las dos apagadas
LUZ_A = 1        # A-   solo la roja
LUZ_B = 2        # -B   solo la verde
AMBAS = 3        # AB   las dos

NOMBRE = {SEP: "--", LUZ_A: "A-", LUZ_B: "-B", AMBAS: "AB"}
ESTADO = {v: k for k, v in NOMBRE.items()}        # "-B" -> LUZ_B

# Los tres estados ENCENDIDOS, en orden, son los digitos en base 3.
DIGITOS = [LUZ_A, LUZ_B, AMBAS]                   # A-=0, -B=1, AB=2

NEGRO = "#"      # recuadro negro
BLANCO = "_"     # recuadro blanco

# El alfabeto espanol, en orden, para validar lo que se teclea y para
# imprimir la tabla ordenada.
ALFABETO = "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"


# ##########################################################################
#
#   T A B L A   D E L   C O D I G O
#
#   Esto es el codigo. Se lee tal cual: la letra A son los tres destellos
#   A- -B AB, o sea roja, verde, las dos. Para cambiar el reparto basta con
#   reescribir estas lineas; el resto del programa se entera solo.
#
#   Las 27 letras usan las 27 combinaciones de 3 destellos (3x3x3), asi que
#   no sobra ni falta ninguna. El orden NO es alfabetico a proposito: 12 de
#   las 27 combinaciones no repiten ningun digito y por tanto salen sin
#   ningun parpadeo; esas 12 se les dieron a las 12 letras mas frecuentes
#   del espanol (E A O S R N I D L C T U). Las que si repiten van marcadas
#   con (p) de parpadeo.
#
# ##########################################################################

CODIGO_LETRAS = {
    "A": "A- -B AB",      "J": "AB AB A-",      "R": "-B A- -B",
    "B": "A- -B -B",      "K": "AB AB AB",      "S": "A- AB -B",
    "C": "AB A- AB",      "L": "AB A- -B",      "T": "AB -B A-",
    "D": "-B AB -B",      "M": "A- A- -B",      "U": "AB -B AB",
    "E": "A- -B A-",      "N": "-B A- AB",      "V": "-B A- A-",
    "F": "AB A- A-",      "Ñ": "AB AB -B",      "W": "-B -B -B",
    "G": "A- AB AB",      "O": "A- AB A-",      "X": "A- A- A-",
    "H": "-B AB AB",      "P": "A- A- AB",      "Y": "-B -B A-",
    "I": "-B AB A-",      "Q": "-B -B AB",      "Z": "AB -B -B",
}

# Los recuadros son UN solo destello, por eso son mucho mas baratos que una
# letra. El tercer estado encendido (AB) queda libre: un destello suelto AB
# esta reservado y hoy no significa nada.
CODIGO_RECUADROS = {
    NEGRO:  "A-",
    BLANCO: "-B",
}

# --- lo anterior, ya masticado para el programa ---------------------------
# Se calcula una sola vez al importar. DESTELLOS traduce celda -> tupla de
# estados, y CELDA hace el camino de vuelta.
DESTELLOS = {}
for _c, _txt in list(CODIGO_LETRAS.items()) + list(CODIGO_RECUADROS.items()):
    DESTELLOS[_c] = tuple(ESTADO[p] for p in _txt.split())
CELDA = {v: k for k, v in DESTELLOS.items()}

# Comprobacion de que la tabla esta bien escrita. Salta al importar, no al
# ejecutar, para que un error de dedo se vea enseguida y no en mitad de la
# transmision.
assert set(CODIGO_LETRAS) == set(ALFABETO), "faltan o sobran letras en la tabla"
assert len(CELDA) == len(DESTELLOS), "hay dos celdas con los mismos destellos"
assert all(len(d) == 3 for d in map(DESTELLOS.get, ALFABETO)), \
    "toda letra son 3 destellos"
assert all(SEP not in d for d in DESTELLOS.values()), \
    "un destello no puede ser el separador"


# ------------------------------------------------------------ unidades ----
PREAMBULO = [LUZ_A, LUZ_B, LUZ_A, LUZ_B]    # 4 destellos seguidos
INDICE_CABECERA = 26                        # AB AB AB, no es una fila
MAX_FILAS = 26                              # las filas van de 0 a 25
MAX_COLS = 26


# ==========================================================================
#  NUMEROS  <->  DESTELLOS
#  Los numeros (indice de fila, cuantas celdas, suma de control) van en base
#  3 con los tres estados encendidos, igual que las letras.
# ==========================================================================
def num_a_simbolos(n):
    """0..26 -> tres destellos en base 3."""
    if not 0 <= n <= 26:
        raise ValueError("número fuera de rango: %d" % n)
    return [DIGITOS[n // 9], DIGITOS[(n // 3) % 3], DIGITOS[n % 3]]


def simbolos_a_num(destellos):
    """Inverso. Falla si llega un separador donde debía haber un dígito."""
    if len(destellos) != 3:
        raise ValueError("se esperaban 3 destellos, llegaron %d" % len(destellos))
    d = [DIGITOS.index(s) for s in destellos]      # ValueError si hay un SEP
    return d[0] * 9 + d[1] * 3 + d[2]


# ==========================================================================
#  CELDAS  <->  DESTELLOS   (aquí solo se consulta la tabla de arriba)
# ==========================================================================
def celda_a_simbolos(c):
    """Una celda -> [separador, destello] o [separador, d, d, d]."""
    c = c.upper()
    if c in (" ", ""):
        c = BLANCO
    if c not in DESTELLOS:
        raise ValueError("carácter no válido en la celda: %r" % c)
    return [SEP] + list(DESTELLOS[c])


def simbolos_a_celda(destellos):
    """Los destellos de UNA celda (ya sin el separador) -> el carácter."""
    c = CELDA.get(tuple(destellos))
    if c is None:
        raise ValueError("esos %d destellos no son ninguna celda: %s"
                         % (len(destellos), " ".join(NOMBRE[d] for d in destellos)))
    return c


def valor_celda(c):
    """Valor numérico de una celda, solo para la suma de control.

    Se saca de la propia tabla: los tres destellos leídos como número en base
    3. Los recuadros, que son un destello, valen 0 y 1. Así, si se cambia la
    tabla, la suma de control se ajusta sola.
    """
    d = DESTELLOS[c.upper() if c not in (NEGRO, BLANCO) else c]
    if len(d) == 1:
        return DIGITOS.index(d[0])
    return 2 + simbolos_a_num(list(d))


def suma_control(celdas):
    """Suma de control de una fila: la suma de sus celdas, módulo 27."""
    return sum(valor_celda(c) for c in celdas) % 27


# ==========================================================================
#  ARMAR LO QUE SE TRANSMITE
# ==========================================================================
def cabecera(filas, cols):
    """preámbulo | -- 26 | -- filas | -- cols | --"""
    if not (1 <= filas <= MAX_FILAS and 1 <= cols <= MAX_COLS):
        raise ValueError("dimensiones fuera de rango (máximo %d x %d)"
                         % (MAX_FILAS, MAX_COLS))
    s = list(PREAMBULO)
    s += [SEP] + num_a_simbolos(INDICE_CABECERA)
    s += [SEP] + num_a_simbolos(filas)
    s += [SEP] + num_a_simbolos(cols)
    return s + [SEP]


def fila(indice, celdas):
    """preámbulo | -- índice | -- n | -- celda -- celda ... | -- suma | --"""
    if not 0 <= indice < MAX_FILAS:
        raise ValueError("índice de fila fuera de rango")
    s = list(PREAMBULO)
    s += [SEP] + num_a_simbolos(indice)
    s += [SEP] + num_a_simbolos(len(celdas))
    for c in celdas:
        s += celda_a_simbolos(c)
    s += [SEP] + num_a_simbolos(suma_control(celdas))
    # Cada unidad CIERRA con oscuridad. Sin esto, el último grupo se pegaría al
    # preámbulo de la unidad siguiente y formarían una racha de destellos que
    # el receptor no sabría dónde cortar.
    return s + [SEP]


def bloque(grid):
    """La cuadrícula completa -> [(nombre, símbolos), ...] lista para emitir."""
    unidades = [("cabecera", cabecera(len(grid), len(grid[0])))]
    for i, f in enumerate(grid):
        unidades.append(("fila %d" % i, fila(i, f)))
    return unidades


def aviso():
    """El AVISO: las dos luces parpadeando rápido, sin datos.

    Quiere decir "prepárense, voy a transmitir". Va a AVISO_T_S por destello,
    mucho más rápido que un símbolo, así que no se puede confundir con nada
    del mensaje. Se devuelve como lista de estados; los tiempos los pone quien
    la emita, con AVISO_T_S.
    """
    return [AMBAS, SEP] * AVISO_DESTELLOS


# ==========================================================================
#  EL MINI PARPADEO
# ==========================================================================
def repite(simbolos, i):
    """¿El símbolo i es igual al anterior? Entonces necesita mini parpadeo.

    Es lo único que hay que preguntarse: si la luz va a quedar igual que en el
    tiempo anterior, hay que cortarla un instante para que se note la frontera.
    """
    return 0 < i < len(simbolos) and simbolos[i] == simbolos[i - 1]


def emision(simbolos):
    """Símbolos -> ranuras de duración T_SIMBOLO/SUBRANURAS, con los parpadeos.

    Cada símbolo ocupa SUBRANURAS ranuras iguales. Si repite al anterior, la
    primera ranura va apagada: ese es el mini parpadeo.

    Sirve para el Arduino, que emite a ritmo fijo: se le manda esta lista y se
    le pone el período a T_SIMBOLO/SUBRANURAS. No hay que tocarle el firmware.
    """
    ranuras = []
    for i, s in enumerate(simbolos):
        if repite(simbolos, i):
            ranuras.append(SEP)                       # el parpadeo
            ranuras += [s] * (SUBRANURAS - 1)
        else:
            ranuras += [s] * SUBRANURAS
    return ranuras


# ==========================================================================
#  LEER LO QUE SE RECIBIÓ
# ==========================================================================
def segmentar(simbolos):
    """Corta una secuencia larga en unidades sueltas (cabecera, filas...).

    Se apoya en el preámbulo: una racha de 4 o más destellos seguidos solo
    puede ser el arranque de una unidad nueva.
    """
    unidades, inicio, i = [], 0, 0
    while i < len(simbolos):
        if simbolos[i] == SEP:
            i += 1
            continue
        j = i
        while j < len(simbolos) and simbolos[j] != SEP:
            j += 1
        if j - i >= 4:                       # es un preámbulo
            if i > inicio:
                unidades.append(simbolos[inicio:i])
            inicio = i
        i = j
    unidades.append(simbolos[inicio:])
    return [u for u in unidades if u]


def _grupos(simbolos):
    """Parte UNA unidad en los grupos de destellos que hay entre oscuridades.

    Todo lo anterior al primer separador (o sea, el preámbulo) se ignora.
    """
    grupos, actual, visto_sep = [], [], False
    for s in simbolos:
        if s == SEP:
            if visto_sep:
                grupos.append(actual)
            actual, visto_sep = [], True
        elif visto_sep:
            actual.append(s)
    if visto_sep:
        grupos.append(actual)
    return [g for g in grupos if g]


def analizar(simbolos):
    """Decodifica UNA unidad. Devuelve un diccionario:

        {'tipo': 'cabecera', 'filas': f, 'cols': c}
        {'tipo': 'fila', 'indice': i, 'n': n, 'celdas': [...],
         'control_ok': True/False/None, 'completa': True/False}
        {'tipo': 'incompleto'}   todavía no han llegado todos los grupos
    """
    g = _grupos(simbolos)
    if not g:
        return {"tipo": "vacio"}

    try:
        primero = simbolos_a_num(g[0])
    except ValueError:
        return {"tipo": "incompleto"}

    # ---- ¿es la cabecera? ----
    if primero == INDICE_CABECERA:
        if len(g) < 3:
            return {"tipo": "incompleto"}
        try:
            return {"tipo": "cabecera", "filas": simbolos_a_num(g[1]),
                    "cols": simbolos_a_num(g[2])}
        except ValueError:
            return {"tipo": "incompleto"}

    # ---- es una fila ----
    if len(g) < 2:
        return {"tipo": "incompleto", "indice": primero}
    try:
        n = simbolos_a_num(g[1])
    except ValueError:
        return {"tipo": "incompleto", "indice": primero}

    celdas, errores = [], 0
    for grupo in g[2:2 + n]:
        try:
            celdas.append(simbolos_a_celda(grupo))
        except ValueError:
            celdas.append("?")           # celda dudosa; se pinta en rojo
            errores += 1

    # La suma de control es el grupo que viene justo después de las n celdas.
    control_ok = None
    if len(g) >= 2 + n + 1:
        try:
            esperado = simbolos_a_num(g[2 + n])
            real = suma_control([c for c in celdas if c != "?"])
            control_ok = (esperado == real) and errores == 0
        except ValueError:
            control_ok = False

    return {"tipo": "fila", "indice": primero, "n": n, "celdas": celdas,
            "control_ok": control_ok, "completa": len(celdas) == n}


# ==========================================================================
#  UTILIDADES DE TEXTO (para copiar y pegar secuencias sin montar las luces)
# ==========================================================================
_MAPA_TEXTO = {"A-": LUZ_A, "-B": LUZ_B, "AB": AMBAS, "--": SEP,
               "1": LUZ_A, "2": LUZ_B, "3": AMBAS, "0": SEP}


def a_texto(simbolos):
    """[1, 2, 0, 3] -> 'A- -B -- AB'"""
    return " ".join(NOMBRE[s] for s in simbolos)


def de_texto(texto):
    """Acepta 'A- -B AB --', '1 2 3 0' y también '1230' todo pegado.

    Todo lo que venga después de un '#' es comentario y se ignora hasta el
    final de esa línea. Las palabras que no sean símbolos también se ignoran:
    ojo, se descarta la PALABRA ENTERA, no letra por letra. Si no fuera así,
    un comentario como 'fila 0 (17 simbolos)' metería símbolos falsos.
    """
    simbolos = []
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0]                    # fuera comentarios
        for pieza in linea.replace(",", " ").replace("|", " ").split():
            if pieza in _MAPA_TEXTO:
                simbolos.append(_MAPA_TEXTO[pieza])
            elif all(ch in "0123" for ch in pieza):
                simbolos += [_MAPA_TEXTO[ch] for ch in pieza]
    return simbolos


def tabla_letras(orden_alfabetico=True):
    """[(letra, ['A-', '-B', 'AB'], lleva_parpadeo), ...] para la tarjeta.

    'lleva_parpadeo' es True cuando la letra repite algún dígito, o sea cuando
    en algún punto la luz se corta un instante y vuelve igual.
    """
    filas = []
    for L in CODIGO_LETRAS:
        d = DESTELLOS[L]
        filas.append((L, [NOMBRE[x] for x in d],
                      d[0] == d[1] or d[1] == d[2]))
    if orden_alfabetico:
        filas.sort(key=lambda f: ALFABETO.index(f[0]))
    return filas


def duracion(unidades):
    """Segundos que tarda transmitir esa lista de unidades, a mano."""
    n = sum(len(sim) for _, sim in unidades)
    return n * T_SIMBOLO_S + max(0, len(unidades) - 1) * PAUSA_ENTRE_UNIDADES_S


# ==========================================================================
#  AUTOPRUEBA: ejecuta este archivo directamente para ver la tabla y
#  comprobar que codificar y decodificar dan lo mismo.
# ==========================================================================
if __name__ == "__main__":
    import sys
    try:                                  # que los acentos salgan bien en Windows
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("TABLA DE LETRAS  (* = lleva mini parpadeo)")
    print("-" * 46)
    for k, (L, d, parpadea) in enumerate(tabla_letras()):
        print("   %s   %s %s %s  %s" % (L, d[0], d[1], d[2], "*" if parpadea else " "),
              end="\n" if k % 2 else "     ")
    print("\n\nRECUADROS      #  (negro) = --  A-        _  (blanco) = --  -B")
    print("SEPARADOR      --   entre celdas y al cerrar cada unidad")
    print("PREÁMBULO      %s   arranque de cabecera o fila" % a_texto(PREAMBULO))
    print("PARPADEO       si la luz vuelve igual, se corta 1/%d de tiempo antes"
          % SUBRANURAS)
    print("AVISO          %d parpadeos de las dos luces a %.2f s"
          % (AVISO_DESTELLOS, AVISO_T_S))

    grid = [["S", "I"], [NEGRO, BLANCO]]
    print("\nEJEMPLO  cuadrícula 2x2 = [['S','I'], ['#','_']]\n")
    for nombre, sim in bloque(grid):
        print("  %-10s (%2d símbolos)  %s" % (nombre, len(sim), a_texto(sim)))
        print("  %-10s  -> %s\n" % ("", analizar(sim)))

    # ida y vuelta completa
    todo = []
    for _, sim in bloque(grid):
        todo += sim
    leidas = {}
    for u in segmentar(todo):
        info = analizar(u)
        if info["tipo"] == "fila":
            leidas[info["indice"]] = info["celdas"]
    assert leidas == {0: ["S", "I"], 1: [NEGRO, BLANCO]}, leidas

    # toda celda de la tabla codifica y decodifica bien
    for c in list(ALFABETO) + [NEGRO, BLANCO]:
        assert simbolos_a_celda(celda_a_simbolos(c)[1:]) == c, c

    # El parpadeo no cambia el mensaje: solo parte los símbolos en ranuras.
    for _, sim in bloque(grid):
        ranuras = emision(sim)
        assert len(ranuras) == len(sim) * SUBRANURAS
        for k, s in enumerate(sim):
            trozo = ranuras[k * SUBRANURAS:(k + 1) * SUBRANURAS]
            assert trozo[-1] == s, (k, trozo, s)

    print("codigo_manual.py OK  ·  %.0f s para este bloque a %.1f s/símbolo"
          % (duracion(bloque(grid)), T_SIMBOLO_S))
