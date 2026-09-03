# Sistema de Comunicación Simple · dos luces

Redes de Computadores I · UdeA 2026-2 · Proyecto 01

Se transmite un bloque de celdas (letras y recuadros) prendiendo y apagando
**dos luces**, una roja y una verde. Una persona las opera y otra las mira: no
hace falta ninguna cuenta ni memorizar nada.

Carpeta [`manual/`](manual/) — explicación larga en [`manual/LEEME.md`](manual/LEEME.md).

---

## Arrancar

Los tres archivos van en la misma carpeta. Se abren con el **botón de play de
VS Code**; no llevan argumentos.

| archivo | qué es |
|---|---|
| [`manual/tx_manual.py`](manual/tx_manual.py) | **Transmisor.** Se digita la cuadrícula y dice qué luces prender. |
| [`manual/rx_manual.py`](manual/rx_manual.py) | **Receptor.** Se pulsan teclas y va armando el bloque. |
| [`manual/codigo_manual.py`](manual/codigo_manual.py) | La codificación. No se ejecuta (salvo para ver la tabla). |
| [`manual/relaylink/relaylink.ino`](manual/relaylink/relaylink.ino) | Firmware del Arduino. **Opcional.** |

Solo hace falta Python con Tkinter (viene de fábrica). `pyserial` únicamente si
se va a usar el Arduino.

---

## El código, en una pantalla

**Cuatro estados.** Las dos luces juntas:

| se escribe | luz A (roja) | luz B (verde) | qué es |
|:---:|:---:|:---:|---|
| `--` | apagada | apagada | **separador** |
| `A-` | ON | apagada | dígito **0** |
| `-B` | apagada | ON | dígito **1** |
| `AB` | ON | ON | dígito **2** |

Todos los símbolos **duran lo mismo**, el separador incluido.

**Una celda** = oscuridad + destellos:

* `-- A-` → recuadro **negro** `#`
* `-- -B` → recuadro **blanco** `_`
* `-- x x x` → **letra**, en base 3 (3×3×3 = 27 = las 27 letras justas)

O sea: ves oscuridad, cuentas los destellos hasta la siguiente oscuridad.
**1 destello = recuadro, 3 = letra.**

**El `--` separa celdas, no filas.** Las filas las separa el **preámbulo**,
`A- -B A- -B`: cuatro destellos seguidos. Dentro de los datos nunca hay más de
tres seguidos, así que el cuarto significa siempre "empieza algo nuevo".

**Mini parpadeo.** Si un dígito repite al anterior, la luz se corta **un cuarto
de tiempo** antes de volver. Así ninguna letra obliga a contar tiempos: para el
receptor la regla es *si parpadea y vuelve igual, pulsa la misma tecla otra vez*.
No hay que confundirlo con el separador, que es un tiempo de oscuridad entero.

**Las unidades.** El bloque va en trozos independientes, uno por fila:

```
CABECERA   preámbulo | -- 26 | -- filas | -- columnas | --
FILA i     preámbulo | -- i  | -- n     | -- celda -- celda ... | -- suma | --
```

`26` (`AB AB AB`) marca la cabecera; las filas van de 0 a 25. `suma` es la suma
de las celdas módulo 27. **Si una fila llega mal se repite solo esa fila.**

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

El alfabeto no está en orden alfabético a propósito: las 12 combinaciones sin
dígito repetido (las que no parpadean) se les dieron a las 12 letras más
frecuentes del español. Ver `manual/LEEME.md`.

---

## Cómo se usa

**Transmisor.** Arranca en modo **EDITAR**: `.` o espacio o `#` = negro,
`-` o `_` = blanco, letras `A..Z Ñ`. El tamaño se cambia con **+** y **−** (no
borra lo escrito), `Ctrl+Z` deshace. **F5** pasa a **TRANSMITIR**: se elige una
unidad a la derecha y **espacio** arranca; las dos bolas grandes dicen qué luces
prender.

**Receptor.** Se pulsa la tecla del estado que se ve, cada vez que las luces
cambian:

```
1 = solo ROJA     2 = solo VERDE     3 = LAS DOS     0 = NINGUNA
```

La tira de arriba dice qué fila llegó **ok**, cuál con **error** y cuál
**falta** — eso es lo que hay que pedir que repitan.

**Para practicar sin luces:** en el transmisor, *copiar bloque entero*; en el
receptor, pegarlo en la caja y darle a *reproducir*.

**Arduino** (opcional): `D9` → luz roja, `D10` → luz verde. LED de 5 mm directo
al pin con una resistencia de 220 Ω; para 110 V, un módulo de relé. Se elige el
puerto en la ventana del transmisor y se pulsa **Conectar**
(`python -m pip install pyserial`).
