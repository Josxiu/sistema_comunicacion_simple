# Sistema de dos luces · MODO MANUAL

Redes de Computadores I · UdeA 2026-2 · Proyecto 01

Versión reducida: **solo la parte manual**. No hay cámara, ni procesamiento de
imagen, ni tramas con CRC de 16 bits. Una persona prende y apaga dos luces, y
otra persona mira y pulsa teclas.

---

## Los archivos

| archivo | qué hace | ¿se ejecuta? |
|---|---|---|
| `codigo_manual.py` | **La codificación.** Alfabeto, cabecera, filas, suma de control. | solo para ver la tabla |
| `tx_manual.py` | Transmisor: se digita la cuadrícula y dice qué luces prender. | ▶ sí |
| `rx_manual.py` | Receptor: se pulsan teclas y va armando el bloque. | ▶ sí |
| `relaylink/relaylink.ino` | Firmware del Arduino. **Opcional.** | en el Arduino IDE |

Los tres `.py` van en la misma carpeta y se abren con el **botón de play de VS
Code**. No hay opciones de línea de comandos: todo se maneja desde la ventana.

`codigo_manual.py` va **aparte a propósito**: es el único sitio donde vive la
codificación, y los otros dos la llaman. Si mañana se cambia el alfabeto o la
suma de control, se cambia ahí y los dos programas quedan al día solos. Además,
es el archivo que hay que leer para entender el sistema; los otros dos solo
dibujan ventanas.

Ejecutar `codigo_manual.py` directamente imprime la tabla de letras y hace una
prueba de ida y vuelta. Sirve para revisar que todo esté bien sin montar nada.

---

## Cómo funciona el mensaje

### Los cuatro estados

Hay dos luces: **A (roja)** y **B (verde)**. Entre las dos dan 4 estados:

| se escribe | luz A | luz B | qué significa |
|:---:|:---:|:---:|---|
| `--` | apagada | apagada | **SEPARADOR** |
| `A-` | **ON** | apagada | dígito **0** |
| `-B` | apagada | **ON** | dígito **1** |
| `AB` | **ON** | **ON** | dígito **2** |

**Todos los símbolos duran lo mismo**, incluido el separador. El `--` no es una
pausa larga: es un tiempo de oscuridad igual de largo que cualquier destello. Lo
único que lo hace especial es que nunca lleva información.

### Una celda

Cada celda empieza con oscuridad y sigue con destellos:

| celda | se transmite | |
|---|---|---|
| recuadro **negro** `#` | `-- A-` | separador + **1** destello |
| recuadro **blanco** `_` | `-- -B` | separador + **1** destello |
| una **letra** | `-- x x x` | separador + **3** destellos |

Con tres destellos en base 3 salen 3×3×3 = **27** combinaciones, y el alfabeto
español tiene exactamente **27** letras. Encaja justo, sin desperdiciar nada.

O sea que el receptor solo hace esto: ve oscuridad, cuenta los destellos hasta
la siguiente oscuridad. **1 destello = recuadro, 3 = letra.** No cuenta tiempos
ni consulta la tabla.

*(Un solo destello `AB` queda reservado: por ahora no significa nada.)*

### Cómo se separan las filas

Respondiendo directamente a la duda: **el `--` separa CELDAS, no filas.**

Las filas se separan con el **PREÁMBULO**, que son cuatro destellos alternados
seguidos, sin oscuridad en medio:

```
A- -B A- -B
```

Eso no se puede confundir con nada, porque **dentro de los datos nunca hay más
de TRES destellos seguidos** (una letra), y siempre vienen detrás de una
oscuridad. Así que ver el cuarto destello seguido significa siempre lo mismo:
*aquí empieza algo nuevo*.

### Las unidades

El bloque no viaja de un solo golpe. Viaja en **unidades independientes**: la
cabecera, y después una unidad por fila.

```
CABECERA   A- -B A- -B  |  -- 26  |  -- filas  |  -- columnas  |  --

FILA i     A- -B A- -B  |  -- i   |  -- n  |  -- celda -- celda ...  |  -- suma  |  --
```

* **26** = `AB AB AB` es el índice reservado que marca "esto es la cabecera".
  Las filas de verdad van de 0 a 25.
* **n** es cuántas celdas trae la fila (así el receptor sabe dónde termina).
* **suma** es la suma de control: se suman los valores de las celdas y se toma
  el resto de dividir por 27. Si no cuadra, esa fila llegó mal.
* Cada unidad **cierra con oscuridad**. Sin eso, el último grupo se pegaría al
  preámbulo de la unidad siguiente.

Que cada fila sea independiente es lo importante: si la fila 3 llega mal, se
pide **la fila 3** y se repite **solo la fila 3**. No hay que volver a mandar el
bloque entero.

---

## El mini parpadeo

Hay letras con dos dígitos iguales seguidos (`A- A-`, por ejemplo). Ahí la luz
se quedaría quieta dos tiempos y habría que **contar** cuánto duró.

Se arregla con un **mini parpadeo**: cuando un dígito repite al anterior, la luz
se corta un instante (**un cuarto de tiempo**) antes de volver a encenderse.

```
sin parpadeo (mal)    A-------A-------     ¿fue uno largo o dos?
con parpadeo (bien)   A------ A-------     dos, se ve el corte
```

Así **ninguna letra obliga a contar tiempos**. El parpadeo es corto a propósito:
no se confunde con el separador, que es un tiempo de oscuridad **entero**. Es la
diferencia entre "la luz tembló" y "la luz se apagó".

Para el receptor la regla es una sola línea: **si la luz parpadea y vuelve
igual, pulsa la misma tecla otra vez.**

Esto **no cambia el código**: los símbolos son los mismos y el decodificador es
el mismo. Solo cambia cómo se emiten. Por dentro cada símbolo se parte en 4
ranuras (`SUBRANURAS` en `codigo_manual.py`) y el parpadeo ocupa una; por eso
tampoco alarga la transmisión ni un segundo.

---

## Tabla de letras

`⏱` = esa letra lleva mini parpadeo (repite algún dígito).

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

**Números** (para el índice de fila, el número de columnas y la suma de
control): el mismo esquema de tres destellos, leídos en base 3.

| número | destellos | | número | destellos |
|:---:|:---|:-:|:---:|:---|
| 0 | `A- A- A-` | | 5 | `A- -B AB` |
| 1 | `A- A- -B` | | 6 | `A- AB A-` |
| 2 | `A- A- AB` | | 9 | `-B A- A-` |
| 3 | `A- -B A-` | | 18 | `AB A- A-` |
| 4 | `A- -B -B` | | 26 | `AB AB AB` |

### Ejemplo completo

Cuadrícula de 2×2 con `S I` arriba y `# _` abajo:

```
cabecera   A- -B A- -B  --  AB AB AB  --  A- A- AB  --  A- A- AB  --
fila 0     A- -B A- -B  --  A- A- A-  --  A- A- AB  --  A- AB -B  --  -B AB A-  --  AB AB AB  --
fila 1     A- -B A- -B  --  A- A- -B  --  A- A- AB  --  A-  --  -B  --  A- A- -B  --
```

En la fila 1 se ve clarito lo de los recuadros: `-- A-` es un `#` y `-- -B` es
un `_`, un solo destello cada uno.

---

## Por qué el alfabeto no está en orden alfabético

Es la única decisión rara del código, y tiene motivo.

De las 27 combinaciones, solo **12** no repiten ningún dígito, o sea que salen
**sin ningún parpadeo**, con las tres luces bien distintas. Esas 12 se le dieron
a las 12 letras **más frecuentes del español** (E A O S R N I D L C T U), y las
15 restantes a las raras (K W X Y Z Ñ...), para que un texto normal se vea lo
más limpio posible.

Medido sobre `REDESDECOMPUUNOUDEA`, se pasa de 9 letras con parpadeo a solo 2.

Con el mini parpadeo esto ya **no es una necesidad** — antes sí lo era, porque
sin parpadeo esas letras obligaban a contar tiempos —, pero sale gratis, así que
se deja.

Por eso el orden de transmisión es:

```
X M P E B A O S G V R N Y W Q I D H F L C T Z U J Ñ K
   (la posición en esta cadena es el número que viaja por las luces)
```

---

## Cómo se usa

### Transmisor · `tx_manual.py`

1. **Modo EDITAR** (así arranca). Se escribe la cuadrícula con el teclado:
   `.` o espacio o `#` = negro · `-` o `_` = blanco · letras `A..Z Ñ`.
   Flechas para moverse (al salirse por un lado pasa a la fila de al lado),
   ENTER va a la fila siguiente, `Ctrl+Z` deshace. El cronómetro arranca con la
   primera tecla.
   El tamaño se cambia con los botones **+** y **−**, que **conservan lo ya
   escrito**. No hay casillas de texto a propósito: así el teclado siempre es de
   la cuadrícula y nunca se queda una letra escrita en el número de filas. (Si
   aun así el teclado se va a otra parte, la cuadrícula se ve atenuada y con
   `ESC` o un clic vuelve.)
2. **F5** pasa a **modo TRANSMITIR**. A la derecha aparecen las unidades:
   cabecera, fila 0, fila 1... Se hace clic en una.
3. **Espacio** arranca. Las dos bolas grandes dicen, símbolo por símbolo, qué
   luces prender. El operador solo copia lo que ve.
4. Cuando termina una unidad queda marcada con ✓ y se pasa a la siguiente.
   Si el receptor pide repetir una fila, se hace clic en esa fila y ya.

El deslizador **seg/símbolo** cambia el ritmo. 1,0 s es cómodo; 0,5 s solo si el
receptor ya se sabe el código.

Los botones **copiar** dejan la secuencia en el portapapeles, para pegarla en el
receptor y practicar sin montar las luces.

### Receptor · `rx_manual.py`

La persona que mira **no hace cuentas ni consulta tablas**. Solo pulsa la tecla
del estado que ve, cada vez que las luces cambian:

```
1 = solo ROJA      2 = solo VERDE      3 = LAS DOS      0 = NINGUNA
```

Y la regla del parpadeo: **si la luz se corta un instante y vuelve igual, se
pulsa la misma tecla otra vez.** Si se apaga un tiempo entero, eso es el
separador y se pulsa `0`.

La tira de arriba muestra, fila por fila, cuál llegó **ok**, cuál llegó con
**error** y cuál **falta**. Eso es lo que hay que pedirle al transmisor.

`RETROCESO` deshace el último símbolo, `SUPR` limpia todo.

En la caja **pegar secuencia** se pega lo que copió el transmisor: *cargar* lo
mete de golpe, *reproducir* lo va metiendo de a un símbolo para ver cómo se arma
la matriz.

### Arduino · `relaylink/relaylink.ino` (opcional)

Sin Arduino todo funciona igual: el programa le dice a una persona qué luces
prender. El Arduino solo automatiza esa parte (y hace los mini parpadeos con una
precisión que a mano no se consigue).

* `D9` → luz A (roja) · `D10` → luz B (verde) · `D13` → LED de la placa
* LED de 5 mm: pin → resistencia de 220 Ω → LED → GND. Directo, sin relé.
* Bombilla de 110 V: pin → módulo de relé.

Se sube el sketch con el Arduino IDE, se elige el puerto en la ventana del
transmisor y se pulsa **Conectar**. Necesita `pyserial`:

```bash
python -m pip install pyserial
```

El Arduino es tonto a propósito: solo recibe una lista de estados y los
sostiene. Toda la codificación vive en el PC, así que se puede cambiar el código
sin volver a programar la placa.

---

## Qué se quitó respecto a la versión completa

De la carpeta `codigos tarea` no se trajo nada de esto, porque el modo manual no
lo usa:

* `rx_camara.py` — receptor por cámara y procesamiento de imagen (654 líneas).
* `codigo_linea.py` + `trama.py` — el código de 4 estados **por transición** y
  la trama con CRC-16. Es otro código distinto, pensado para la cámara: mete los
  bits de todo el bloque en un solo paquete, y por eso **no se puede leer celda
  por celda** (una letra queda repartida entre varios símbolos). Para una
  persona es intratable; para la cámara es lo más eficiente.
* `relay_link.py` — la cola de envío, los tiempos en microsegundos, el handshake.
* `hacer_video_prueba.py` — generador de video sintético.
* El enredo de `tx_gui.py`: la versión completa **parcheaba en caliente** la
  interfaz del proyecto anterior (`importlib` + reasignar los métodos de otra
  clase desde fuera). Funcionaba, pero era ilegible. Aquí es una clase normal
  en un archivo normal.

> ⚠️ **Aviso sobre `Redes/codigos tarea`:** esa copia **no corre tal cual**.
> Le falta `protocol.py`, que en el proyecto original vive un nivel más arriba
> (`Documents/Udea/.../2026-2/software/`), y `trama.py` lo importa. Además es
> del 24 de agosto y en el PC hay una versión más nueva, del 28.
> La carpeta `manual/` sí es autónoma: no depende de nada de afuera.
