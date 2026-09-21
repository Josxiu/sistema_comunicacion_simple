# ¿Aprendizaje automatico en vez de plantillas?

Experimento aparte. **No esta enchufado a nada**: `leer_hoja.py` y
`tx_camara.py` siguen usando las plantillas. Esto solo contesta una pregunta:
si se cambiara el comparador de letras por un modelo entrenado, ¿se leeria
mejor?

Todo el PDI se queda igual —marco, homografia, contar celdas, umbrales—. Lo
unico que se cambia es el ultimo paso: de este trocito de 32x32, ¿que letra es?

Todo en numpy pelado, sin scikit-learn ni torch. No es purismo: el equipo del
dia de la prueba no tiene internet, y numpy y opencv ya son lo unico que el
lector necesita. Un modelo que obligue a instalar media biblioteca no se podria
usar aunque ganara.

## Como se corre

```
python sacar_celdas.py      # 754 celdas con letra, de las 27 fotos del banco
python hacer_datos.py 40    # ~9.900 letras de mentira, estropeadas a proposito
python probar_modelos.py    # la comparacion
python entrenar.py          # deja modelo.npz, medio mega
```

`celdas.npz` y `datos.npz` no se suben (14 MB): salen de correr los dos
primeros, que llevan la semilla fija y dan siempre lo mismo.

## El resultado

Sobre las **754 celdas con letra** de las 27 fotos, dejando **una hoja fuera**
cada vez:

| modelo | aciertos | errores que se cuelan |
|---|---|---|
| plantillas (lo de hoy) | 735/754 (97,5%) | 5 |
| 1 vecino | 725/754 (96,2%) | 0 |
| 5 vecinos | 736/754 (97,6%) | 0 |
| centroide | 717/754 (95,1%) | 5 |
| softmax lineal | 715/754 (94,8%) | 6 |
| **red de 1 capa** | **743/754 (98,5%)** | **0** |

Por hoja, la red gana o empata en las ocho, que es lo que hace creible el
total:

| | HAYLUZ | HXT | MENSAJE | NOCHE | POLSO | PULCO | TRAMANDA | YWP |
|---|---|---|---|---|---|---|---|---|
| plantillas | 93,3% | 100% | 92,0% | 100% | 99,1% | 100% | 99,0% | 100% |
| red 1 capa | 95,6% | 100% | 95,4% | 100% | 100% | 100% | 99,0% | 100% |

No es cosa de la semilla: con ocho semillas distintas la red da entre 742 y 744
aciertos, y **cero** errores colados en todas. Las plantillas dan 735 y 5.

Donde mas gana es en MENSAJE, la hoja de 4x20 con celdas de 9 mm, que es
justo la que peor se lee. Tiene sentido: es la unica donde la letra llega
rota, y romper letras a proposito es de lo que va el entrenamiento.

### Lo de "errores que se cuelan"

Cada modelo tiene su propia escala de confianza, asi que comparar con un umbral
fijo no compara nada. Lo que se hace es marcar en todos las **mismas 201
celdas** —las menos seguras de cada uno, que son las que hoy marcan las
plantillas— y contar cuantos errores quedan **sin marcar**. Esos son los que no
se ven, y son los unicos que hacen daño de verdad.

Ahi esta la diferencia gorda, y no en el acierto: **5 contra 0**. El modelo
entrenado no acierta mucho mas, pero sabe mucho mejor cuando NO sabe.

## Lo que esto NO dice

Es importante, porque el titular se lee mas facil que la letra pequeña.

1. **No bajaria los errores del lector de hoy, que ya son cero.** Esta tabla
   mide el comparador de letras SOLO. El lector completo lleva ademas la
   comprobacion de estabilidad, y con ella el banco entero da **VERDE-MAL 0**:
   ninguna celda mal leida y dada por buena. O sea que esos 5 que "se cuelan"
   aqui, alla los caza la estabilidad. Lo que la red compraria no es menos
   errores, es **dejar de depender de la estabilidad** para no tenerlos, y de
   paso menos celdas marcadas para revisar.
2. **El techo esta cerca y no lo pone el modelo.** Solo 5 de las 754 celdas
   (0,7%) las fallan TODOS los modelos, y las cinco son de MENSAJE. Mirandolas
   se ve por que: son trazos rotos, letras a las que ya les falta media raya en
   los pixeles. El mejor modelo saca 743 y el techo de todos juntos es 749, asi
   que queda sitio para 6 celdas. **Por eso no se hizo la CNN**: no es que no
   quepa, es que lo que sobra por ganar son 6 celdas de 754, y el que manda es
   el numero de pixeles de la celda, no el clasificador. Para MENSAJE lo que
   ayuda de verdad es acercar el telefono, o lo que ya hace el lector, que es
   leer la letra de una enderezada mas grande.
3. **Son 8 hojas, una impresora y un telefono.** Separar por hoja evita el
   engaño gordo —la misma hoja sale hasta en 4 fotos, con la misma tinta y el
   mismo grano— pero 8 hojas siguen siendo 8.
4. **Entrenado con letras de mentira.** Ninguna hoja real entra en el
   entrenamiento, asi que no hay filtracion por ahi. Pero eso tambien quiere
   decir que lo que se aprende es mi idea de como se estropea una letra, y si
   la impresora del dia hace otra cosa, esto no la ha visto.

## Dos errores que tuve que arreglar en la medicion

Los dejo escritos porque los dos daban numeros mucho peores y los dos parecian
resultados de verdad hasta que mire las celdas:

- **Celdas que el clasificador no ve nunca.** La primera version guardaba el
  trocito de toda celda cuya verdad fuera una letra, incluidas las que el
  lector ya habia dado por recuadro negro por la fraccion de tinta. Entre las
  "imposibles" salian 19 cuadrados completamente negros. Eso no es un fallo del
  comparador de letras: es del umbral, y se cuenta aparte.
- **Vueltas mezcladas.** `leer_hoja_girando` prueba hasta ocho maneras de mirar
  la foto y cada una llama a `leer_celda` con sus propias coordenadas. Guardando
  la primera que pasaba por cada coordenada, lo que quedaba era una ensalada de
  orientaciones: aparecian letras del reves —una A boca abajo, una U puesta como
  ∩, una J que era una S— apuntadas como si el clasificador las hubiera fallado.
  Ahora el cuaderno se vacia al empezar cada pasada y solo queda la ultima, que
  es la que produjo la matriz.

Las dos veces lo que destapo el fallo fue pintar las celdas y mirarlas, no
pensar en los numeros.

## Si se quisiera enchufar

`modelo.npz` son cuatro matrices; se carga con numpy y se usa en lugar de
`Plantillas.letra`. Antes de hacerlo conviene decidir dos cosas:

- La confianza de la red es `p1 - p2` de un softmax, no el coseno contra
  plantillas. `DUDA = 0.08` esta calibrado para lo segundo y **no vale** para lo
  primero: habria que recalibrarlo contra el banco.
- Si se queda la comprobacion de estabilidad. Con la red probablemente sobre,
  pero eso hay que medirlo con el banco entero (`probar_fotos.py`), no con esta
  tabla, que solo mira el comparador de letras.

## Los archivos

| | |
|---|---|
| `sacar_celdas.py` | saca de las 27 fotos el trocito de cada celda con letra, enganchando `leer_celda` por dentro para que sea exactamente lo que el lector compara |
| `hacer_datos.py` | fabrica letras de mentira y las estropea siguiendo la cadena de la foto: girar, engordar, encoger, desenfocar, aclarar, ruido, umbralizar |
| `modelos.py` | 1-NN, k-NN, centroide, softmax y red de una capa, todo en numpy |
| `probar_modelos.py` | la comparacion, dejando una hoja fuera |
| `entrenar.py` | entrena la red con todo y guarda `modelo.npz` |
