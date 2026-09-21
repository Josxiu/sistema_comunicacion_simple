# -*- coding: utf-8 -*-
"""Banco de pruebas: el lector contra fotos REALES, con la verdad escrita a mano.

    python probar_fotos.py            mide camara/leer_hoja.py, el de verdad
    python probar_fotos.py otro.py    mide otra version, para comparar

El lector vive en camara/, al lado de rx_camara.py y del transmisor que lo
usa; aqui solo esta el banco que lo mide.

Lo que se mide, en este orden de importancia:

  1. errores en VERDE: celda mal leida que el programa da por segura. Es el
     unico error que no se ve, y por tanto el unico grave: todo lo demas lo
     pesca quien revisa las ? antes de transmitir.
  2. errores en naranja: mal leida pero avisada.
  3. falsas alarmas: bien leida pero marcada con ?. Molestan, no hacen dano.

Las fotos estan en fotos/, reducidas a 1400 px y sin EXIF. La verdad de cada
hoja esta copiada a mano mirando la foto: si se añade una foto, hay que
añadir su hoja en H y la pareja en CASOS. La hoja POLSO es la impresa con
marco negro grueso; las matrices de la prueba no lo llevan, asi que sus
errores cuentan menos de lo que parece.

OJO AL CONTAR: son 27 fotos pero solo OCHO hojas distintas, porque cada hoja
se fotografio varias veces. Un arreglo que gane celdas en una hoja las gana en
todas sus fotos a la vez, asi que el total exagera; mirar tambien la columna
de cada foto y cuantas hojas distintas mejoran. Por eso mismo, para el
experimento de aprendizaje hay que separar entrenamiento y prueba por HOJA.
"""
import sys, os, time, importlib.util
import cv2

AQUI = os.path.dirname(os.path.abspath(__file__))
FOTOS = os.path.join(AQUI, "fotos")
LECTOR = os.path.join(AQUI, "..", "..", "leer_hoja.py")

H = {
    "TRAMANDA": ["###_T#M#", "#BITRÑEO", "#_##A#NN", "#__#M#SD",
                 "###_A#AA", "####N#JA", "###_D#EL", "####A#E#", "__##_###"],
    "HAYLUZ":   ["HAYLUZ", "##_##A", "TRAMAQ", "#####U", "_####I", "##_###"],
    "HXT":      ["_#_M_CM#H", "H#I#QX_W_", "X##ÑONEQK", "T#YULK_UK",
                 "_##UWPXGI", "L_#_#_Ñ_G", "_Y_####W_"],
    "PULCO":    ["##PULCO", "#####L#", "#C_##A#", "MLTRAVA", "#ABITEA",
                 "#V#####", "#E#####"],
    "YWP":      ["#_MY#YWP", "DK___Ñ__", "KFWG#VQ#", "D#_G_E##",
                 "_AUUQFY_", "_KYXÑ#JX"],
    "POLSO":    ["###POLSO##", "_##_N#####", "L__#D#F#F#", "UQUIA#A#A#",
                 "Z___BIRAR#", "_####LOZO#", "######A_#_", "######L###"],
    "MENSAJE":  ["_###OF##F##########_", "####NMENSAJELE####_#",
                 "#_##DREDES#######_##", "##REDES#OTRAMACLAVE_"],
    "NOCHE":    ["P######", "U#####T", "NOCHE#R", "S#####A", "OACLAVM",
                 "MENSAJE", "##_####"],
}

CASOS = [
    ("tramanda.jpg", "TRAMANDA"), ("tramanda_2_sinflash.jpg", "TRAMANDA"),
    ("tramanda_camara.jpg", "TRAMANDA"),
    ("hayluz.jpg", "HAYLUZ"), ("hayluz2.jpg", "HAYLUZ"),
    ("hxt.jpg", "HXT"), ("pulco.jpg", "PULCO"),
    ("ywp_2_vertical.jpg", "YWP"), ("ywp_horizontal.jpg", "YWP"),
    ("polso.jpg", "POLSO"), ("polso2_sinmarcos_gemini.jpg", "POLSO"),
    ("mensajele3_vertical_recortado.jpg", "MENSAJE"),
    ("mensajele_horizontal.jpg", "MENSAJE"),
    ("mensajele2_vertical.jpg", "MENSAJE"),
    ("noche.jpg", "NOCHE"),
    # Segunda tanda, de la misma noche. Son OTRAS TOMAS de las mismas ocho
    # hojas, no hojas nuevas: sirven para ver si un arreglo aguanta un encuadre
    # distinto o solo estaba aprendido de memoria sobre la foto de antes. Su
    # verdad se copio mirando la hoja enderezada, no la salida del lector.
    # Casi todas salieron giradas un cuarto de vuelta, que es justo el caso que
    # mas se da con el telefono en la mano.
    ("20260919_193140.jpg", "POLSO"), ("20260919_224856.jpg", "POLSO"),
    ("20260919_224909.jpg", "MENSAJE"), ("20260919_224921.jpg", "MENSAJE"),
    ("20260919_224936.jpg", "HAYLUZ"), ("20260919_224951.jpg", "TRAMANDA"),
    ("20260919_225003.jpg", "YWP"), ("20260919_225012.jpg", "HXT"),
    ("20260919_225021.jpg", "HXT"), ("20260919_225026.jpg", "YWP"),
    ("20260919_225042.jpg", "NOCHE"), ("20260919_225049.jpg", "PULCO"),
]


def cargar(ruta):
    sp = importlib.util.spec_from_file_location("lh_banco", ruta)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def medir(LH, verbose=True):
    P = LH.Plantillas()
    tot = {"celdas": 0, "bien": 0, "verde_mal": 0, "naranja_mal": 0,
           "falsa_alarma": 0, "forma_mal": 0, "perfectas": 0, "t": 0.0}
    filas_out = []
    for nombre, clave in CASOS:
        verdad = H[clave]
        im = cv2.imread(os.path.join(FOTOS, nombre))
        t0 = time.time()
        grid, nota, conf = LH.leer_hoja_girando(im, P)
        dt = time.time() - t0
        tot["t"] += dt
        F, Cc = len(verdad), len(verdad[0])
        n = F * Cc
        tot["celdas"] += n
        if grid is None or (len(grid), len(grid[0])) != (F, Cc):
            forma = "no lee" if grid is None else "%dx%d" % (len(grid), len(grid[0]))
            tot["forma_mal"] += 1
            filas_out.append("%-36s FORMA MAL (%s, era %dx%d)  %4.1fs"
                             % (nombre, forma, F, Cc, dt))
            continue
        bien = vm = nm = fa = 0
        verdes_mal = []
        for i in range(F):
            for j in range(Cc):
                v, e = grid[i][j], verdad[i][j]
                dudosa = conf[i][j] < LH.DUDA
                if v == e:
                    bien += 1
                    if dudosa:
                        fa += 1
                elif dudosa:
                    nm += 1
                else:
                    vm += 1
                    verdes_mal.append("(%d,%d) %s->%s" % (i, j, e, v))
        tot["bien"] += bien; tot["verde_mal"] += vm
        tot["naranja_mal"] += nm; tot["falsa_alarma"] += fa
        if bien == n:
            tot["perfectas"] += 1
        filas_out.append("%-36s %3d/%-3d  verde-mal %2d  naranja-mal %2d  "
                         "falsa-alarma %2d  %4.1fs  %s"
                         % (nombre, bien, n, vm, nm, fa, dt,
                            " ".join(verdes_mal)))
    if verbose:
        for f in filas_out:
            print(f)
        print()
    print("TOTAL: %d/%d celdas bien  |  VERDE-MAL %d  |  naranja-mal %d  |  "
          "falsas alarmas %d  |  forma mal %d  |  perfectas %d/%d  |  %.0fs"
          % (tot["bien"], tot["celdas"], tot["verde_mal"], tot["naranja_mal"],
             tot["falsa_alarma"], tot["forma_mal"], tot["perfectas"],
             len(CASOS), tot["t"]))
    return tot


if __name__ == "__main__":
    medir(cargar(sys.argv[1] if len(sys.argv) > 1
                 else LECTOR))
