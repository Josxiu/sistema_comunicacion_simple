# Bitácora del proyecto

Apuntes de lo que se fue cambiando, por qué, y qué se probó y no funcionó.
El README cuenta **cómo se usa** el sistema; esto cuenta **cómo llegó a ser
así**, que es lo que no se ve leyendo el código.

Si algo de aquí contradice al código, manda el código.

---

## Las ramas

| Rama | Qué lleva |
|---|---|
| `main` | La versión que estaba antes de todo esto. |
| `claude/video-camera-processing-review-wckd0u` | La rama de trabajo. Todo lo de abajo menos las dos técnicas nuevas. |
| `claude/pdi-tecnicas-nuevas` | Lo anterior **más** el mapa de parpadeo por filtros IIR. |
| `claude/decodificacion-blanda` | Lo anterior **más** la decisión blanda (implementada y apagada). |

Cada una tiene la anterior mergeada dentro, así que van en fila: trabajo →
IIR → blanda. Falta decidir cuál se lleva a `main`; ver el final.

---

## Lo que se arregló en el receptor

### La búsqueda de luces escogía mal los píxeles

El mapa de parpadeo hacía una FFT por píxel de toda la escena y eso tardaba
casi cuatro segundos. Para acelerarlo se intentó mirar solo el 2 % de píxeles
**más brillantes**, y eso rompió un video que antes sí descifraba.

Medido en ese video: la luz tenía brillo 0,425 y el corte del 2 % estaba en
0,817, porque el cielo quemado ocupaba **el 38,5 % del cuadro** y era más
brillante que la luz. La luz se quedaba fuera de la selección.

Lo que funciona es escoger por **recorrido temporal** (cuánto cambia cada
píxel a lo largo del tramo), no por brillo: una luz que parpadea cambia,
el cielo quemado no. Mismos mapas que antes y de 3978 ms a 184 ms.

Está en `FRACCION_PIXELES_FFT = 0.05` y `RECORRIDO_MINIMO_FFT = 6.0`.
El caso "una luz tenue con el cielo quemado" quedó metido en
`--autoprueba-pdi` para que no vuelva a colarse.

### Medir el color y el nivel

- `UMBRAL_SATURADO_BGR = 240` y `UMBRAL_SATURADO_LUZ = 230`: son dos porque
  el camino rápido del plano Y viene en rango limitado (máximo 235) y el BGR
  en rango completo. Con un solo umbral, uno de los dos caminos medía mal.
- `MODO_CROMA = "ponderado"`: el croma `(R−G)/(R+G)` se promedia pesando por
  brillo² sobre los píxeles no saturados de todo el recuadro. Antes se miraba
  solo el núcleo, que está quemado y ahí no hay color.
- `tres_grupos()`: las fronteras entre los tres estados de color salen de un
  k-means de una dimensión con k=3 (sembrado en los percentiles 10/50/90),
  en vez de partir el rango en tercios fijos. Con las luces desiguales los
  tercios fijos caían en mitad de un grupo.

### Emparejar las luces

- Los picos se separan borrando la componente conexa, no con un radio fijo.
  Con radio fijo, una luz grande se contaba como varias.
- Para que dos picos formen pareja no basta con que estén a una separación
  plausible: tienen que tener **señales distintas**. Un reflejo en un vidrio
  repite la señal de su luz el 100 % del tiempo, así que se detecta y se
  descarta por ahí.
- Las parejas se ordenan por **constancia entre tramos**: la que aparece en
  los diez tramos gana a la que aparece en tres, aunque esa brille más.
- `buscar_parejas(..., sueltos=2)`: los picos solitarios se proponen
  **siempre**, no solo cuando no se formó ninguna pareja. Es el caso de las
  dos luces tan juntas que se ven como una sola mancha.

### Videos del teléfono (.MOV)

Dos cosas distintas, y conviene no confundirlas:

1. **No salían en el diálogo de abrir.** Tk compara las extensiones
   respetando mayúsculas y el iPhone graba `.MOV`. Arreglado con
   `EXT_VIDEO` y `PATRONES_VIDEO`, que ahora llevan las dos grafías.
2. **El camino rápido del plano Y devuelve basura con video de 10 bits**,
   que es lo que graba el iPhone en HDR. Ahora `_plano_creible()` descifra
   el mismo cuadro por el camino normal y correla; si no se parecen, se cae
   al camino lento en vez de leer ruido.

**Sobre la toma que no descifraba: no era el formato, era la exposición.**
Se recomprimió el video que sí funciona al formato, perfil y bitrate
idénticos al del teléfono y siguió descifrando, conservando 56 niveles de
oscilación. La toma del teléfono tenía 12-13. Está sobreexpuesta: la cámara
subió la exposición por la escena oscura y las luces quedaron quemadas
contra un fondo también claro, así que apenas hay diferencia entre
encendido y apagado.

**1080p no hace falta.** El mp4 que pasó por WhatsApp (832×464) descifra un
bloque de 9×8 sin problema. Lo que importa es que las luces se distingan
entre sí y que haya oscilación, no los píxeles.

### Fiabilidad

El banco sintético (12 videos: follaje, gente pasando, reflejos, deriva,
luces fundidas, 30 y 60 fps) pasó de **8/12 a 12/12**, y el tiempo total de
380 s a unos 110-195 s según la rama.

---

## El seguimiento de la cámara

`rx_camara_con_seguimiento.py` pasó de 3134 líneas a 429. Era una copia
entera del receptor con el seguimiento encima, así que cada arreglo había
que hacerlo dos veces y se desincronizaron. Ahora importa `rx_camara` y se
queda solo con lo suyo: `_orientar`, `semillas_de_luces`, `seguir_luces`,
`afinar_camino`, y reusa `base.medir_en_video` con anclas densas.

Funciona con y sin temblor de cámara.

### Lo que se probó y NO funcionó

**`cv2.phaseCorrelate` para compensar el movimiento global.** Acumulaba unos
**11 px de deriva en 40 segundos** y la ventana se salía de la luz. (El
primer intento acumulaba 1140 px, pero eso era culpa de los bordes
replicados del generador, no del método.) Descartado; está explicado en la
cabecera del archivo para que no se vuelva a intentar.

**Estimar la frecuencia contando cruces por cero.** El primer intento de IIR
hacía eso y perdió 4 de 17 videos. La señal de datos no tiene una frecuencia
dominante —es un código de transiciones, no una portadora—, así que contar
cruces no mide nada. Cambiado por energía en banda con un pasa-altas de
primer orden: 17/17.

---

## El transmisor de cámara

Tres fallos, todos de lo mismo: temporizadores de Tk sueltos.

1. **STOP no paraba.** Había `after` huérfanos que nadie cancelaba. Ahora
   `self._job_tic` y `self._job_aviso` se guardan y `_cancelar_temporizadores()`
   los mata; `parar()` lo llama.
2. **Al editar, el parpadeo se reiniciaba y ya no se podía parar.** Cada
   arranque dejaba viva la cadena anterior y se sumaban en paralelo.
   `emitir()` y `_regenerar()` ahora empiezan por `self.parar()`.
3. **La GUI y la placa iban desacopladas.** Cada paso programaba el
   siguiente a 1/velocidad de distancia y el retraso de Tk se acumulaba; a
   los trescientos símbolos la pantalla iba segundos por detrás. Ahora el
   índice se calcula **desde el reloj** (`int(transcurrido * velocidad)`) y
   la pantalla se recoloca sola en cada paso.

### Lo del Arduino

El firmware `relaylink.ino` está en **v3.2**. El cambio: `cortar()` ahora
recorre **todo** el buffer de entrada buscando la `Z`, conservando los bytes
que no lo son. La v3.1 usaba `Serial.peek()`, que solo ve el byte
**siguiente**; si delante de la `Z` había quedado una `X:` de la copia
siguiente, la `Z` pasaba desapercibida.

**El transmisor nuevo de Python funciona con la placa sin reprogramar.** Por
eso se añadió `HUECO_ENTRE_COPIAS = 0.35`: la copia siguiente se le manda a
la placa 0,35 símbolos **después** de la frontera, cuando ya terminó la
anterior y su buffer está vacío, así que la `Z` entra sola. Sin ese hueco
quedaban 0,01 símbolos de margen y bastaba con que el reloj de la placa
fuera un pelo por detrás para que PARAR no hiciera nada durante una copia
entera. Son unos milisegundos de luces apagadas entre copia y copia y al
receptor le da igual, que corta la grabación en ráfagas de todos modos.

Subir la v3.2 es lo recomendable —quita la dependencia del hueco— pero no
es obligatorio.

---

## Las dos técnicas nuevas

### Mapa de parpadeo por IIR (`claude/pdi-tecnicas-nuevas`)

En vez de una FFT por píxel, un pasa-altas de primer orden cortado en
`BANDA_PARPADEO[0]` y un seguidor de amplitud con `TAU_AMPLITUD_S = 0.50`.
Idea de "Frequency Cam" (arXiv 2211.00198).

Mismo resultado en la mitad de tiempo. `METODO_MAPA = "iir"` es el valor por
defecto en esa rama; `mapa_de_parpadeo()` escoge entre los dos y
`pruebas/comparar_mapas.py` los enfrenta (picos, ms, si descifra).

### Decisión blanda (`claude/decodificacion-blanda`)

Cuando una racha queda cerca del umbral de glitch, probar las dos lecturas
en vez de decidir a la brava.

**Implementada, medida y apagada** (`DECISION_BLANDA = False`), con los
números escritos al lado: **rescató 0 de 5** casos y tardó entre un 50 y un
70 % más. La causa se midió: a 2,1 cuadros por símbolo hay 242 símbolos
donde una copia tiene 334 —unos 90 nunca se llegan a muestrear—. No es que
la decisión sea dudosa, es que el símbolo no está en el video. Contra eso no
hay decodificación que valga; hay que grabar a más fps o transmitir más
despacio.

Se deja en el repositorio porque el trabajo de medirlo ya está hecho y la
conclusión es útil: **el cuello de botella es el muestreo, no la decisión.**

---

## Cosas que conviene tener claras del diseño

- **Cada racha de estado constante ES un símbolo.** El código de
  transiciones garantiza que dos símbolos seguidos nunca son iguales, así
  que el receptor no necesita el reloj del transmisor: la velocidad solo se
  usa para el umbral de glitch y para partir en ráfagas. Por eso es inmune a
  que la cámara y el Arduino vayan cada uno a lo suyo.
- **1,5 bits por símbolo**, el 95 % de log₂3. Cada símbolo lleva un trit.
- **Regla de fps/3**: la velocidad máxima es `fps/3`. Tres cuadros por
  símbolo es el mínimo para no perder rachas.
- **De día lo que se mide es el área, no el nivel.** Con sol, la luz no baja
  de nivel: encoge. Por eso `saturados` (cuántos píxeles pasan del umbral)
  funciona mejor que `brillo` al aire libre.
- **El recuadro que se marca a mano dice dónde BUSCAR**, no dónde están las
  luces. Dentro de él se vuelve a buscar.

---

## Cómo se prueba

```bash
# el generador de videos de la caja (los .mp4 no se suben, ver .gitignore)
cd camara/pruebas && python hacer_video_caja.py

# el transmisor: ocho bloques de comprobaciones, con una placa de mentira
cd camara/pruebas && python probar_tx.py

# las autopruebas del receptor, sin necesidad de video
python camara/rx_camara.py --autoprueba-pdi
```

En la rama de IIR hay además `comparar_mapas.py`, que enfrenta los dos
mapas, y en la de decisión blanda `escalera.py`, que degrada un video a
propósito (decimando cuadros y metiendo ruido) para ver dónde se rompe cada
decodificación.

`probar_tx.py` **falla con el código de antes** y pasa con el de ahora, que
es lo que hace que sirva de algo.

---

## Lo que queda por decidir

**Qué rama va a `main`.** Las tres funcionan y las tres pasan el banco. La
diferencia:

- La rama de trabajo es la más conservadora y la que menos código nuevo
  mete.
- La de IIR hace lo mismo en la mitad de tiempo, y es la que tiene más
  sentido si se va a usar en vivo.
- La de decisión blanda añade código que está apagado.

Lo razonable es llevar **`claude/pdi-tecnicas-nuevas`** a `main` (trabajo +
IIR, que es ganancia real sin coste) y dejar la de decisión blanda como
está, de registro de que se probó.

Y falta lo obvio: **volver a grabar sin sobreexponer** y comprobar con una
toma real de verdad, porque todo lo de arriba se validó contra el banco
sintético y una toma buena antigua.
