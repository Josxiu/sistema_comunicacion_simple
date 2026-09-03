# Sistema de Comunicación Simple · dos luces

Redes de Computadores I · UdeA 2026-2 · Proyecto 01

Se transmite un bloque de celdas (letras y recuadros) prendiendo y apagando dos
luces, una roja y una verde. Una persona las opera y otra las mira; no hace
falta hacer cuentas ni memorizar nada.

## Archivos

Están todos en la carpeta [`manual/`](manual/). Los tres `.py` van juntos en la
misma carpeta y se abren con el **botón de play de VS Code**. No llevan
argumentos.

| archivo | qué es |
|---|---|
| `tx_manual.py` | **Transmisor.** Se digita la cuadrícula y dice qué luces prender. |
| `rx_manual.py` | **Receptor.** Se pulsan teclas y va armando el bloque. |
| `codigo_manual.py` | La codificación. No se ejecuta, salvo para ver la tabla. |
| `relaylink/relaylink.ino` | Firmware del Arduino, opcional. |

Solo hace falta Python con Tkinter, que viene de fábrica. `pyserial` únicamente
si se usa el Arduino.

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

**Las unidades.** El bloque va en trozos independientes, uno por fila:

```
CABECERA   preámbulo | -- 26 | -- filas | -- columnas | --
FILA i     preámbulo | -- i  | -- n     | -- celda -- celda ... | -- suma | --
```

`26` (`AB AB AB`) marca la cabecera; las filas van de 0 a 25. `n` es cuántas
celdas trae la fila y `suma` es la suma de sus celdas módulo 27. **Si una fila
llega mal se repite solo esa fila.**

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
una unidad a la derecha y **espacio** la reproduce; las dos bolas grandes van
diciendo qué prender.

**Receptor.** Se pulsa la tecla del estado que se ve, cada vez que las luces
cambian:

```
1 = solo ROJA     2 = solo VERDE     3 = LAS DOS     0 = NINGUNA
```

Más la regla del parpadeo: si se corta un instante y vuelve igual, la misma
tecla otra vez. La tira de arriba dice qué fila llegó **ok**, cuál con **error**
y cuál **falta**: eso es lo que hay que pedir que repitan.

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
