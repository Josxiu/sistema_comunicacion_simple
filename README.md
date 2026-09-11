# Sistema de Comunicación Simple · dos luces

Redes de Computadores I · UdeA 2026-2 · Proyecto 01

Se transmite un bloque de celdas (letras y recuadros) prendiendo y apagando dos
luces, una roja y una verde.

Hay **dos modos**, y cada uno tiene su carpeta:

| modo | quién lee las luces | carpeta |
|---|---|---|
| **Manual** | una persona, pulsando teclas | [`manual/`](manual/) |
| **Cámara** | una cámara, con procesamiento de imagen | [`camara/`](camara/) |

Los dos mandan el mismo bloque por las mismas dos luces, pero **no usan la
misma codificación** y no se entienden entre sí: el manual está hecho para que
una persona pueda seguirlo a ojo, y el de cámara para exprimir el canal. Cada
carpeta es independiente y se puede usar sin la otra.

---

# Modo manual

Una persona opera las luces y otra las mira; no hace falta hacer cuentas ni
memorizar nada.

## Archivos

Están todos en la carpeta [`manual/`](manual/). Los tres `.py` van juntos en la
misma carpeta y se abren con el **botón de play de
VS Code**. No llevan argumentos.

| archivo | qué es |
|---|---|
| `tx_manual.py` | **Transmisor.** Se digita la cuadrícula y dice qué luces prender. |
| `rx_manual.py` | **Receptor.** Se pulsan teclas y va armando el bloque. |
| `codigo_manual.py` | La codificación. No se ejecuta, salvo para ver la tabla. |
| `relaylink/relaylink.ino` | Firmware del Arduino, opcional. |

Solo hace falta Python con Tkinter, que viene de fábrica. `pyserial` únicamente
si se usa el Arduino.

**Para cambiar algo hay dos sitios y solo dos**, los dos al principio de
`codigo_manual.py`: el bloque `PARAMETROS` (velocidad, duración del parpadeo,
pausa entre filas, tiempos del aviso) y el bloque `TABLA DEL CODIGO` (qué
destellos es cada letra y cada recuadro). Los otros dos programas leen de ahí,
así que no hay nada que tocar por duplicado.

---

## El código

**Cuatro estados.** Las dos luces juntas:

| se escribe | luz A (roja) | luz B (verde) | qué es |
|:---:|:---:|:---:|---|
| `--` | apagada | apagada | **separador** |
| `A-` | ON | apagada | dígito **0** |
| `-B` | apagada | ON | dígito **1** |
| `AB` | ON | ON | dígito **2** |

Todos los símbolos **duran lo mismo**, el separador incluido.

**Una celda** es oscuridad y después destellos:

* `-- A-` → recuadro **negro** `#`
* `-- -B` → recuadro **blanco** `_`
* `-- x x x` → **letra**, en base 3 (3×3×3 = 27 = las 27 letras justas)

O sea: se ve oscuridad y se cuentan los destellos hasta la siguiente oscuridad.
**1 destello = recuadro, 3 = letra.**

**El `--` separa celdas, no filas.** Las filas las separa el **preámbulo**,
`A- -B A- -B`: cuatro destellos seguidos. Dentro de los datos nunca puede haber
más de tres seguidos, así que el cuarto significa siempre "empieza algo nuevo".

**Mini parpadeo.** Si un dígito repite al anterior, la luz se corta **un cuarto
de tiempo** antes de volver. Sin eso la luz se quedaría quieta dos tiempos y
habría que contar cuánto duró. Con eso, para el receptor la regla es: *si
parpadea y vuelve igual, pulsa la misma tecla otra vez*. No se confunde con el
separador, que es un tiempo de oscuridad **entero**.

---

## Cómo viaja el mensaje

El bloque **no va de un solo golpe**. Va en trozos independientes que se llaman
unidades: primero la cabecera, después una unidad por cada fila.

```
CABECERA   preámbulo | -- 26 | -- filas | -- columnas | --
FILA i     preámbulo | -- i  | -- n     | -- celda -- celda ... | -- suma | --
```

Cada `--` de ahí es un tiempo de oscuridad, y cada número son tres destellos.

### La cabecera

Va primero y solo dice **de qué tamaño es el bloque**. Sus tres grupos son:

1. **`26`** (`AB AB AB`). Es un número reservado: las filas van de 0 a 25, así
   que el 26 no puede ser el índice de ninguna fila. Al receptor le sirve para
   distinguir "esto es la cabecera" de "esto es la fila número tal", sin
   necesidad de ninguna marca aparte.
2. **filas**, de 1 a 26.
3. **columnas**, de 1 a 26.

En cuanto llega, el receptor ya dibuja la cuadrícula vacía y sabe cuántas filas
tiene que esperar. Por eso va primero.

### Una fila

1. **índice** (0, 1, 2...). Dice *qué* fila es. Gracias a esto las filas pueden
   llegar en cualquier orden y se pueden repetir sueltas.
2. **n**, cuántas celdas trae. Es lo que le dice al receptor **dónde termina la
   fila**: cuenta n celdas y lo siguiente ya es la suma de control. Sin este
   número no sabría si la fila se acabó o si todavía falta una celda.
3. **las n celdas**, cada una precedida de su `--`.
4. **la suma de control**.

### La suma de control

Es la comprobación de que la fila llegó bien. Se hace así:

* cada celda vale un número — `#` vale 0, `_` vale 1, y una letra vale
  2 + su número de tres destellos;
* se suman los valores de todas las celdas de la fila;
* se toma el **resto de dividir entre 27**, que da un número de 0 a 26, o sea
  que cabe justo en tres destellos.

El transmisor la calcula y la manda al final de la fila; el receptor calcula la
suya con lo que recibió y las compara. Si no coinciden, esa fila llegó mal y se
marca en rojo. No corrige el error, solo lo detecta — pero es lo que hace
falta, porque **basta con pedir que repitan esa fila**.

Que sea módulo 27 no es casualidad: es el mismo rango que un grupo de tres
destellos, así que la suma se manda con el mismo mecanismo que todo lo demás.

### Cómo se sabe que una fila terminó

Por dos caminos a la vez, y ese es el punto:

* **por el contenido**: la fila dijo `n`, así que después de n celdas viene la
  suma y se acabó;
* **por la forma**: la unidad siguiente empieza con el preámbulo, cuatro
  destellos seguidos, que dentro de los datos es imposible.

Si se pierde algún símbolo y la cuenta de `n` se descuadra, el preámbulo
rescata la sincronización: el receptor sabe que empieza algo nuevo aunque lo
anterior quedara a medias. Se pierde esa fila, no el resto del mensaje.

### El aviso

Antes de empezar se manda el **aviso**: las dos luces parpadeando rápido, seis
veces. No lleva datos, solo quiere decir *prepárate, voy a transmitir*. Va
mucho más rápido que un símbolo, así que no se confunde con el mensaje. En el
transmisor es la tecla `*`.

---

## Tabla de letras

`⏱` = lleva mini parpadeo (repite algún dígito).

| letra | destellos | | letra | destellos |
|:---:|:---|:-:|:---:|:---|
| **A** | `A- -B AB` | | **Ñ** | `AB AB -B` ⏱ |
| **B** | `A- -B -B` ⏱ | | **O** | `A- AB A-` |
| **C** | `AB A- AB` | | **P** | `A- A- AB` ⏱ |
| **D** | `-B AB -B` | | **Q** | `-B -B AB` ⏱ |
| **E** | `A- -B A-` | | **R** | `-B A- -B` |
| **F** | `AB A- A-` ⏱ | | **S** | `A- AB -B` |
| **G** | `A- AB AB` ⏱ | | **T** | `AB -B A-` |
| **H** | `-B AB AB` ⏱ | | **U** | `AB -B AB` |
| **I** | `-B AB A-` | | **V** | `-B A- A-` ⏱ |
| **J** | `AB AB A-` ⏱ | | **W** | `-B -B -B` ⏱ |
| **K** | `AB AB AB` ⏱ | | **X** | `A- A- A-` ⏱ |
| **L** | `AB A- -B` | | **Y** | `-B -B A-` ⏱ |
| **M** | `A- A- -B` ⏱ | | **Z** | `AB -B -B` ⏱ |
| **N** | `-B A- AB` | | | |

**Recuadros:** `#` negro = `-- A-` · `_` blanco = `-- -B`

**Números** (índice de fila, número de columnas, suma de control): los mismos
tres destellos leídos en base 3 — `0` = `A- A- A-`, `1` = `A- A- -B`,
`2` = `A- A- AB`, `3` = `A- -B A-`, … `26` = `AB AB AB`.

El alfabeto no está en orden alfabético a propósito: solo 12 de las 27
combinaciones no repiten ningún dígito, o sea que salen sin parpadeo, y esas 12
se les dieron a las 12 letras más frecuentes del español.

### Ejemplo

Cuadrícula 2×2 con `S I` arriba y `# _` abajo:

```
cabecera   A- -B A- -B  --  AB AB AB  --  A- A- AB  --  A- A- AB  --
fila 0     A- -B A- -B  --  A- A- A-  --  A- A- AB  --  A- AB -B  --  -B AB A-  --  AB AB AB  --
fila 1     A- -B A- -B  --  A- A- -B  --  A- A- AB  --  A-  --  -B  --  A- A- -B  --
```

En la fila 1 se ven los recuadros: `-- A-` es un `#` y `-- -B` es un `_`, un
solo destello cada uno.

---

## Cómo se usa

**Transmisor.** Arranca en modo **EDITAR**: `.` o espacio o `#` = negro,
`-` o `_` = blanco, letras `A..Z Ñ`. El tamaño se cambia con **+** y **−** sin
borrar lo escrito, y `Ctrl+Z` deshace. **F5** pasa a **TRANSMITIR**: se elige
una unidad a la derecha y **espacio** la reproduce (y la para); las dos bolas
grandes van diciendo qué prender.

En cualquiera de los dos modos, estas teclas mandan sobre las luces **sin
transmitir nada**. Son las **mismas teclas del receptor**, para que los dos
lados hablen igual:

```
1 = solo ROJA     2 = solo VERDE     3 = LAS DOS     0 = NINGUNA     * = AVISO
```

Sirven para apuntar las luces y comprobar el cableado, pero también para
**transmitir del todo a mano**: mientras se usan, la secuencia de la unidad
elegida se sigue viendo al lado y va avanzando sola cada vez que se pulsa el
símbolo que toca. Si se pulsa otra cosa el contador no se mueve, para no perder
el sitio por un dedazo.

Y si se vuelve a pulsar la tecla del estado que **ya está puesto**, la luz no se
queda igual: hace el **mini parpadeo**. Es justo lo que hace falta para mandar
dos símbolos iguales seguidos.

**Receptor.** Se pulsa la tecla del estado que se ve, cada vez que las luces
cambian:

```
1 = solo ROJA     2 = solo VERDE     3 = LAS DOS     0 = NINGUNA
```

Más la regla del parpadeo: si se corta un instante y vuelve igual, la misma
tecla otra vez.

La tira de arriba dice, fila por fila, cómo va la cosa: **verde `ok`**,
**ámbar `error`** (la suma de control no cuadró) o **rojo `falta`**. La fila con
error se marca además con un recuadro ámbar en la cuadrícula. Eso es exactamente
lo que hay que pedir que repitan.

**Equivocarse no arruina lo anterior.** No hace falta ningún botón de "repetir
fila": basta con que la fila llegue otra vez entera y bien.

* Las teclas sueltas o al azar **se descartan solas**. El preámbulo corta por
  donde toca y el campo `n` dice dónde acaba cada fila, así que lo que sobra se
  ignora.
* Una fila que ya pasó su suma de control **no se pisa con una peor**, aunque
  después llegue basura con ese mismo índice.
* Una fila que llegó con error **sí** se reemplaza en cuanto llega bien.
* Y siempre están `RETROCESO` (deshace el último símbolo) y `SUPR` (borra todo).

Lo único que el receptor no puede hacer es *pedirlo él*: no hay canal de vuelta,
se pide de viva voz o con una linterna. Por eso lo importante es que la pantalla
diga con claridad qué fila pedir.

**Para practicar sin luces:** en el transmisor, *copiar bloque entero*; en el
receptor, pegarlo en la caja y darle a *reproducir*.

**Arduino.** Es opcional, y opcional quiere decir que el programa hace lo mismo
sin él: lo único que cambia es quién mueve el interruptor. Sin Arduino lo mueve
una persona mirando la pantalla; con Arduino lo mueve la placa, con
temporización exacta (que ayuda sobre todo con el mini parpadeo, porque a mano
sale como un toque rápido y no siempre igual de corto).

`D9` → luz roja, `D10` → luz verde. Un LED de 5 mm va directo al pin con una
resistencia de 220 Ω; para 110 V hace falta un módulo de relé. Se elige el
puerto en la ventana del transmisor y se pulsa **Conectar**
(`python -m pip install pyserial`).

El PC le manda la fila **entera** de una vez y la placa se queda emitiéndola
varios segundos, así que para poder pararla a medias el firmware atiende una
orden de corte entre símbolo y símbolo. Si se usa una versión vieja del sketch,
darle a PARAR detiene la pantalla pero las luces siguen hasta el final de la
fila: hay que **volver a subir** `relaylink.ino` (v3.1 o posterior).

---

# Modo cámara

El mismo bloque, leído por una cámara. Sirve para grabar la transmisión con un
celular y descifrarla después, o para escuchar en vivo.

## Archivos

| archivo | qué es |
|---|---|
| `camara/tx_camara.py` | **Transmisor.** Se digita la cuadrícula y las luces la emiten. |
| `camara/rx_camara.py` | **Receptor.** Un solo archivo, no necesita ningún otro. Supone la cámara quieta. |
| `camara/rx_camara_con_seguimiento.py` | El mismo receptor para tomas **a pulso**: sigue las luces mientras la cámara se mueve. Tarda más, así que solo si hace falta. |
| `camara/pruebas/hacer_video_caja.py` | Genera videos de prueba con el fondo real del balcón y los halos de las dos luces. |

Hace falta `numpy` y `opencv-python`. Funciona en Windows, macOS y Linux.

```
python -m pip install numpy opencv-python
```

El firmware del Arduino es el mismo del modo manual, sin cambiarle nada. Lo
único distinto es el período: aquí son decenas de milisegundos.

## El transmisor

Se escribe la cuadrícula igual que en el modo manual. **F5** pasa a TRANSMITIR
y **espacio** lanza la trama. A 5–20 símbolos por segundo no hay mano que siga
el ritmo, así que las luces las mueve el Arduino o el **modo PANTALLA** (F8),
que parpadea dos círculos a pantalla completa para apuntarles la cámara.

**PARAR** (Esc) corta también las luces, no solo la cuenta de la pantalla: al
Arduino se le manda la trama entera de un golpe y se queda ocupado varios
segundos.

La ventana avisa si la velocidad elegida se pasa de lo que la cámara puede
seguir. Es la comprobación más útil, porque pasarse no da un error: da una
grabación que no se puede descifrar, y eso no se descubre hasta después.

**Con una copia basta.** El receptor corta la grabación en ráfagas y le vale
con que una pase el CRC. Dos es un término medio cómodo.

## El receptor

Sin argumentos sale una ventana con los videos que encuentre al lado. Lo demás:

| | |
|---|---|
| `--video "toma.mp4"` | descifra ese archivo |
| `--camara 1` · `--camara "iriun"` | escucha en vivo (número, parte del nombre, o una URL) |
| `--camaras` | lista las cámaras que responden |
| `--simular-vivo "toma.mp4"` | pasa un video grabado por el camino de la cámara en vivo |
| `--tiempo-real` | con el anterior, a la velocidad de la toma (hace falta para juzgarlo de verdad) |
| `--zona 860,520,140,90` | dónde buscar las luces, sin marcarlo con el mouse |
| `--sin-zona` | no preguntar: buscar en todo el cuadro |
| `--banco "carpeta"` | descifra todos los videos de una carpeta y saca una tabla |
| `--simbolos 7` | forzar la velocidad en vez de medirla |

Para comprobar que nada se rompió después de tocar un parámetro:

```
python rx_camara.py --autoprueba --autoprueba-pdi
```

La primera parte revisa la codificación y el decodificador; la segunda fabrica
un video y lo descifra, que es lo único que prueba la parte que mira la imagen.

**Todo lo ajustable está junto**, en el bloque `PARAMETROS` del principio.

## Las dos luces

Hay dos maneras de saber cuál está prendida, y cuál sirve depende de cómo se
vean en la imagen:

| | cuándo | exige |
|---|---|---|
| **por posición** | se ven como dos puntos separados | nada: sirven dos luces iguales, blancas incluidas |
| **por color** | caen en el mismo punto y se funden | colores distintos |

Se prueban las dos. Dentro de la primera hay a su vez dos lecturas, y el
receptor las intenta en este orden:

| | mide | cuándo manda |
|---|---|---|
| **quemados** | cuántos píxeles tiene saturados cada luz | de día. Con la escena iluminada el LED nunca se ve oscuro, así que el nivel no distingue nada; lo que desaparece al apagarse no es el nivel sino el **área** |
| **brillo** | la luminancia de cada luz | de noche, o tan lejos que el LED no llega a saturar |
| **color** | el croma del par | la única que sirve si se funden |

### Cuánta separación hace falta

Para que se vean como dos puntos hacen falta unos **14 px** en el cuadro
original. Con un celular a 1080p y zoom 1×:

```
separación_px  ≈  1500 × (separación_de_las_luces_m) / (distancia_m)
```

O sea, **un centímetro de separación por cada metro de distancia** para llegar
al mínimo, y el doble para ir cómodo. A 40 m eso son 40 cm entre los dos LED,
y mejor cerca de un metro.

### Si se va a usar el modo por color

Los dos LED tienen que verse **igual de brillantes** en la cámara, no solo de
colores distintos. Si uno alumbra más, el estado "las dos encendidas" se corre
hacia el brillante en vez de caer en el medio. El receptor lo aguanta, pero
cuanto más parejos, más margen hay. Se ajusta con las resistencias.

## Cómo encuentra las luces

No hay detector de objetos: no reconoce la caja ni el poste. Busca **dos
puntos** que cumplan cuatro cosas a la vez.

1. **Que parpadeen al ritmo que toca.** Transformada de Fourier de cada píxel
   a lo largo de 90 cuadros, mirando la amplitud entre **2 y 25 Hz**. Un LED va
   a 5–12 Hz; una persona caminando, por debajo de 2. Lo que además tenga mucha
   energía lenta se castiga.
2. **Que alumbren.** El mapa se multiplica por el brillo al cuadrado.
3. **Que estén a una distancia razonable**, entre 14 y 520 px.
4. **Que lleven señales distintas.** Las luces salen también reflejadas en un
   vidrio, y el reflejo parpadea igual de fuerte y al mismo ritmo. Un reflejo
   coincide con su luz el 100 % del tiempo; las dos luces de verdad difieren en
   un tercio de los cuadros. Sin esto, la pareja ganadora era "una luz y su
   propio reflejo".

Y por encima de todo manda la **constancia**: se catan varios tramos y se
ordena por en cuántos apareció cada pareja. Las hojas de un árbol parpadean a
9 o 10 Hz igual que las luces, pero la pareja buena vuelve a salir tramo tras
tramo en el mismo sitio.

El parpadeo se mide con un **paso-alto de primer orden por píxel**: se resta
una media que sigue al fondo lento y lo que queda es lo que se mueve más rápido
que una persona caminando. Dos números por píxel, sin guardar el tramo. La
alternativa es la transformada de Fourier sobre 90 cuadros, que da lo mismo y
tarda el doble; se cambia con `METODO_MAPA` y se comparan con
`camara/pruebas/comparar_mapas.py`.

Con la transformada, además, solo se transforma el 5 % de píxeles que **más
cambian**. Que sea el que más cambia y no el que más alumbra importa: en las
tomas de la caja la luz está en la repisa a la sombra y el 38 % del cuadro es
más brillante que ella.

### Lo que se mide dentro del recuadro

```
brillo     media del 5 % de píxeles más brillantes
quemados   cuántos píxeles pasan del umbral de saturación
croma      (R−G)/(R+G)     roja (+) · verde (−) · las dos (~0)
```

El croma sale de una media de todo el recuadro pesada por el brillo al
cuadrado, para que las dos luces aporten cuando están las dos encendidas.
Dividir por (R+G) lo hace independiente de la exposición.

Se resta el verde y no el azul a propósito: el LED rojo se ve **magenta** en la
cámara, porque satura también el canal azul.

### El recuadro que se marca a mano dice dónde **buscar**

Con la tecla `m` en vivo, o con `--zona` en un archivo. Sirve cuando hay muchas
cosas moviéndose alrededor, y además va más rápido. Dónde **medir** lo sigue
decidiendo el programa.

## Cuántos cuadros por segundo hacen falta

Como cada símbolo se reconoce por el **cambio** de las luces, para ver un
cambio hacen falta cuadros a los dos lados. La regla medida sobre grabaciones
reales es de **3 cuadros por símbolo como mínimo**:

| fps del video | cuadros/símbolo a 12,5 sím/s | resultado |
|---|---|---|
| 54,1 | 4,3 | CRC válido |
| 27,1 | 2,2 | nada — y es el mismo video, decimado |
| 23,8 | 1,9 | nada |

O sea: **la velocidad máxima es fps/3**. A 30 fps son 10 símbolos/s; a 60, 20.
Conviene grabar a 60 siempre que se pueda.

## La cámara en vivo

```
python rx_camara.py --camaras          lista las que responden
python rx_camara.py --camara 1         escucha esa
```

Mientras escucha: **q** sale · **r** reinicia · **m** limita la búsqueda a un
recuadro · **a** lo quita · **z** enciende y apaga la lupa · **+** y **−**
suben y bajan la exposición. Las teclas salen escritas en la ventana.

La **lupa** es un recuadro en una esquina con la zona ampliada y los recuadros
de medida dentro: sirve para apuntar la cámara sin acercarse a la pantalla,
porque a 40 m las luces son cuatro píxeles.

No guarda imágenes. De cada cuadro saca siete números por pareja candidata y
tira el cuadro; la historia son los últimos 3600 (un minuto a 60 fps). Cada dos
segundos, en otro hilo, intenta descifrar toda esa historia buscando el
preámbulo. No hay ningún detector de "empieza un mensaje": el preámbulo y el
CRC son el detector, así que un parpadeo al azar nunca cuadra. El bloque se
congela en cuanto un CRC cuadra.

### Conectar otra cámara

| qué | cómo |
|---|---|
| **Celular** (lo mejor: graba a 60 fps) | una app que publique la cámara en la red — `--camara http://192.168.1.5:8080/video`. Con DroidCam, Iriun o EpocCam salen como una cámara más en `--camaras` |
| **Réflex** | capturadora HDMI-USB, o el programa del fabricante |
| **Cámara IP** | `--camara "rtsp://usuario:clave@192.168.1.9:554/stream1"` |

Si la imagen sale negra: tapa de privacidad, otra aplicación que ya tiene la
cámara cogida, o exposición demasiado baja.

## La codificación

**Cuatro estados**, los mismos del modo manual:

| | luz A (roja) | luz B (verde) |
|:---:|:---:|:---:|
| `0` | apagada | apagada |
| `1` | **ON** | apagada |
| `2` | apagada | **ON** |
| `3` | **ON** | **ON** |

**La regla: dos símbolos seguidos nunca son iguales.** Desde un estado hay 3
destinos posibles, así que cada símbolo lleva un dígito en base 3. Eso tiene
dos consecuencias que importan:

* Cada frontera de símbolo se ve como un **cambio**, así que el receptor no
  tiene que recuperar el reloj ni saber la velocidad de antemano. Cada racha de
  estado constante *es* un símbolo, dure lo que dure.
* 3 bits caben en 2 dígitos base 3, o sea **1,5 bits por símbolo**. El límite
  teórico es log₂3 = 1,585: se aprovecha el 95 %.

**La trama** lleva todo el bloque de una vez:

```
PREÁMBULO      1 2 1 2 1 2 1 2 1 2 1 2     alternancia roja/verde
SFD            3 0                          los dos estados que el preámbulo no toca
CABECERA       tipo 4b · filas 5b · cols 5b · nbits 10b · CRC-8 8b
PAYLOAD        celdas: 00 = negro, 01 = blanco, 1+5 bits = letra
CRC-16         de la cabecera y el payload
```

La cabecera lleva CRC propio para que, si el payload se corrompe, todavía se
sepan las dimensiones y se pueda pintar lo que sí llegó (las celdas perdidas
salen en rojo).
