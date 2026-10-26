# Estrategia de Jaime Merino (Trading Latino): ADX + Squeeze Momentum

Informe para definir la base del análisis técnico de Rendi.
Fecha: 2026-10-26.

## 0. Antes de leer: qué tan firme es este informe

**No pude ver sus videos ni sus directos.** Desde esta sesión no hay acceso a YouTube ni a
transcripciones, y las páginas web completas no se pueden abrir. Armé el informe con lo que sí
pude leer:

- Notas de seguidores y apuntes de la estrategia (Scribd, PDFCoffee, blogs).
- Descripciones de scripts de TradingView hechos por terceros que dicen copiar su método.
- Notas de prensa (Decrypt, CriptoNoticias) donde él explica sus operaciones.

Por eso cada punto lleva una marca de confianza:

- **[Firme]**: lo dicen varias fuentes que coinciden, o lo dijo él en una nota de prensa.
- **[Probable]**: lo dice una sola fuente de seguidores, o las fuentes se contradicen en los detalles.
- **[A confirmar]**: no lo pude verificar. Hay que mirarlo en sus videos.

Ninguna de las fuentes es oficial. El propio script de la comunidad aclara que *no es una
estrategia oficial de Jaime Merino*. Tampoco encontré un registro de resultados (cuánto ganó o
perdió siguiendo esta estrategia) que alguien haya auditado.

**Qué hay que hacer para cerrar los huecos:** mirar entre 5 y 10 de sus videos (los que
explican la estrategia y algunos directos recientes) con el informe al lado y tildar qué se
cumple. Si me pasás las transcripciones, lo completo yo.

---

## 1. La idea en una frase

Mira **dos cosas a la vez**:

1. **El ADX** responde: «¿el mercado tiene fuerza hoy, o está dormido?»
2. **El Squeeze Momentum (SQZMOM)** responde: «¿para qué lado empuja el precio, y ese empuje
   está creciendo o se está apagando?»

Entra cuando el ADX dice que la fuerza **se está recuperando** y el SQZMOM dice que el empuje
**da vuelta hacia arriba** (para comprar). Sale o evita cuando pasa lo contrario.
**[Firme]** que esa es la base. Los detalles abajo.

---

## 2. Los dos indicadores, explicados simple

### 2.1 ADX (fuerza de la tendencia)

- Es una línea que va de 0 a 100. **No dice si el precio sube o baja: dice cuánta fuerza tiene
  el movimiento**, sea para arriba o para abajo.
- Se calcula con 14 períodos (estándar). **[Firme]**
- **El número clave es 23.** Por encima de 23 hay fuerza; por debajo, el mercado está flojo o
  lateral. **[Firme]** Otras guías de seguidores usan 20, 25 o 30. Esas parecen mezclas con otras
  estrategias; el 23 es el que aparece en los scripts que copian su método y en lo que él dijo
  en prensa.
- **Lo que más importa es la pendiente, no el valor.** Es decir, si la línea del ADX sube o baja.
  **[Firme]**
  - ADX **subiendo** = la fuerza crece.
  - ADX **bajando** = la fuerza se apaga.
- Un script que copia su método define «pendiente positiva» como un ángulo de unos 45 grados
  hacia arriba, y «pendiente negativa» como unos 45 grados hacia abajo. **[Probable]** Es una
  forma de poner un número a algo que él mira a ojo.
- Junto al ADX están las líneas **DI+ y DI-**: DI+ es la fuerza de los compradores y DI- la de
  los vendedores. Un script exige una diferencia mínima entre ellas para confirmar una señal.
  **[Probable]** No pude confirmar cuánto la usa él.
- **Colores del ADX en su versión de TradingView [A confirmar]:** las fuentes describen verde
  oscuro = fuerza compradora, rojo oscuro = fuerza vendedora, y tonos claros o naranja =
  pérdida de fuerza. Los colores varían de un script a otro. No los uses en Rendi sin verlos
  en sus videos.

Ejemplo de cómo lo usa él (nota de Decrypt, 2025): *«Al notar que el ADX ya está saliendo por
debajo del punto 23, estamos llegando a una zona de no fuerza en un semanal»*. Ese día cerró
sus posiciones de Bitcoin cerca de US$ 125.000. **[Firme]**

### 2.2 Squeeze Momentum, SQZMOM (empuje y compresión)

Es un indicador de LazyBear (en TradingView), basado en el «TTM Squeeze» de John Carter. Tiene
dos partes:

**a) Las barras (el histograma): el empuje**

- Barras **arriba de la línea cero** = el precio empuja hacia arriba. **Abajo** = hacia abajo.
- El color dice si ese empuje **crece o se apaga**. Con los colores estándar de LazyBear:
  - Verde claro: empuje alcista que crece.
  - Verde oscuro: empuje alcista que se debilita.
  - Rojo claro: empuje bajista que crece.
  - Rojo oscuro: empuje bajista que se debilita.
- ⚠️ **Hay una advertencia de la comunidad:** en la versión que usa Trading Latino, los verdes
  vienen **invertidos** respecto del LazyBear original. Esto hay que verlo en sus videos antes
  de programar nada. **[A confirmar]**
- Los seguidores hablan de **«valles rojos»** (barras bajo cero que ya tocaron fondo) y
  **«montañas verdes»** (barras sobre cero). Un valle rojo es la zona donde se busca comprar.
  **[Probable]**

**b) Las cruces sobre la línea cero: la compresión**

- **Cruz negra** = el mercado está comprimido, con poca volatilidad (como un resorte apretado).
- **Cruz gris** = el resorte se soltó; empieza el movimiento.
- Regla de Carter: esperar la primera cruz gris después de una negra y entrar en la dirección
  de las barras. **[Firme]** para el indicador. **[A confirmar]** cuánto peso le da Merino.

Parámetros estándar: bandas de Bollinger de 20 períodos x 2, canal de Keltner de 20 períodos x
1,5, con rango verdadero. **[Firme]** (son los que traen los scripts que copian su método).

---

## 3. Cómo se combinan: las reglas de entrada y salida

### 3.1 Compra («zona de compra») **[Probable, lo más repetido]**

La descripción que más se repite en las fuentes:

> La compra se activa cuando **termina un movimiento bajista marcado por la pendiente negativa
> del ADX** y el SQZMOM **toma dirección alcista**.

En palabras simples:

1. El precio vino cayendo y el ADX bajaba (la fuerza vendedora se agotaba).
2. Las barras del SQZMOM están en un **valle rojo** (bajo cero) y **empiezan a subir**, o
   cruzan a verde.
3. El ADX deja de caer y **gira hacia arriba**.
4. Con eso, hay zona de compra. Mejor si el ADX queda **por encima de 23** y subiendo.

### 3.2 Venta o salida **[Probable]**

- Espejo de la compra: el ADX gira hacia abajo desde arriba y las barras del SQZMOM empiezan a
  caer o pasan a rojo.
- Una salida concreta: el ADX **por encima de 23 pero con pendiente negativa**, junto con el
  SQZMOM bajista. El precio entonces tiende a lateralizar o caer.
- Otra señal de salida: las barras alcanzan un pico y **empiezan a bajar** (el empuje se
  gasta).
- **Divergencia bajista**: el precio hace un máximo nuevo pero el SQZMOM o el ADX hacen uno más
  bajo. Él la usa para anticipar el techo. Lo dijo en octubre de 2025, cuando vendió Bitcoin
  entre US$ 120.000 y 125.000. **[Firme]**

### 3.3 Cuándo NO operar **[Probable]**

- ADX por debajo de 23 y plano: mercado sin fuerza. No hay tendencia que seguir.
- Cruces negras (compresión) sin disparo todavía: se espera.

---

## 4. Lo que rodea a los dos indicadores

### 4.1 Varias temporalidades

- «**El gráfico grande define la dirección, el chico el momento de entrar.**» **[Firme]**
  (lo escribió él).
- Los scripts de la comunidad se diseñan para 4 horas, y usan el semanal y el diario para la
  tendencia. Él mismo habla de semanal, diario, 4 h y 1 h en sus notas de prensa. **[Firme]**

### 4.2 Filtro de tendencia con medias móviles **[Probable]**

- Dos promedios móviles exponenciales: de **10 y de 55** períodos, en un gráfico más grande.
- Rápida (10) **sobre** lenta (55) = tendencia alcista → sólo se toman compras.
- Rápida **bajo** lenta = sólo ventas.
- Decrypt dice que él combina «medias móviles, zonas de volumen y la relación entre el ADX y el
  SQZMOM». El 10 y el 55 salen del script de la comunidad. **[A confirmar]** que sean los suyos.

### 4.3 Zonas de volumen (soportes y resistencias) **[Probable]**

- Mira dónde se operó más volumen (el precio «justo» donde se concentró la plata). Un script usa
  el punto de mayor volumen de los últimos 3 días y el perfil de volumen de las últimas 100
  velas de 4 horas.
- Las «zonas de rechazo» que él marca (por ejemplo US$ 68.500–69.000 en Bitcoin) salen de acá.
  **[Firme]** que usa zonas; **[A confirmar]** cómo las calcula exactamente.

---

## 5. Gestión del riesgo (esto es lo que más importa para proteger al usuario)

Lo que él dijo en la prensa **[Firme]**:

- **Reparte la plata:** 40 % en Bitcoin a largo plazo, 30 % en operaciones sobre el gráfico
  semanal, 20 % en el diario, 10 % en futuros (con apalancamiento).
- **Usa stop loss.** Dice que es mucho mejor perder un 10 % en una operación que toda la
  posición por no tener stop.
- **Vende por partes.** En la caída de 2025: «vendo la mitad en esta zona y la otra mitad entre
  US$ 130.000 y 135.000».
- **No dice que predice:** «No vendí porque sepa que va a caer, eso no lo sabe nadie. Lo que sí
  sé es que va a dejar de subir.»
- Un script que lo copia aclara que él **normalmente pone el stop en el precio de entrada**
  (cuando la operación ya va ganando). **[Probable]**

Lo que agrega un script de la comunidad (**no es de él**): stop de 7 % por defecto, y topes de
pérdida de 1 % por operación, 6 % por día, 8 % por semana y 10 % por mes.

---

## 6. Límites que hay que tener presentes

1. **Es una estrategia hecha para cripto** (Bitcoin, con futuros). No hay evidencia en lo que
   leí de que haya sido probada en CEDEARs, acciones argentinas o bonos, que son lo que tiene
   un usuario de Rendi.
2. **No hay resultados verificados.** Ni él ni terceros publican un historial auditado.
3. **Es muy de criterio personal.** Él «lee» el gráfico y decide. Los scripts que lo copian
   son una simplificación y varían entre sí (umbral 20/23/25/30, colores, stops).
4. **Sus llamados se equivocan** como los de cualquier analista; en la prensa se ven aciertos y
   errores. Sin números no se puede saber la proporción.

---

## 7. Cómo llevarlo a Rendi (propuesta mía, no es de él)

**Principio:** que Rendi muestre una **lectura** («el ADX tiene fuerza y está subiendo; el
empuje se está dando vuelta hacia arriba»), no una **orden** («comprá»). Es más honesto con lo
que la estrategia puede prometer, y reduce el riesgo de que el aviso se lea como asesoramiento
de inversión (convendría revisarlo con el abogado antes de lanzar).

**Qué construiría, en orden:**

1. **Calcular los dos indicadores con las fórmulas estándar** (ADX de 14 y SQZMOM de LazyBear
   con los parámetros de la sección 2.2) sobre las velas diarias, que ya se guardan en Rendi
   (commit `e4ffed5`, 22/10). Las velas de 4 horas hay que ver si se pueden conseguir.
2. **Mostrarlos con colores claros** y una frase en lenguaje simple por activo.
3. **Definir estados**, no señales de compra:
   - «Sin fuerza» (ADX < 23, plano)
   - «Fuerza recuperándose, empuje alcista» (la lectura de la sección 3.1)
   - «Fuerza cayendo, empuje bajista» (la sección 3.2)
   - «Compresión» (cruces negras)
4. **Probar antes de lanzar (backtest):** correr las reglas sobre el historial de los activos
   que tienen los usuarios (CEDEARs, acciones EE.UU., acciones argentinas) y ver cuántas veces
   funcionó. Si no funciona fuera de cripto, hay que decírselo al usuario.
5. **Sumar el filtro de medias de 10 y 55** y las zonas de volumen en una segunda etapa.

**Qué tengo que ver en sus videos antes de programar nada (la lista de huecos):**

- [ ] Los colores exactos del SQZMOM y del ADX que usa él (están invertidos o no).
- [ ] Si el 23 es el único umbral, o si hay otros para el ADX.
- [ ] Qué pendiente del ADX considera «positiva» (el ángulo de 45° es de un seguidor).
- [ ] Si exige que el ADX supere 23 para entrar, o entra con el ADX todavía abajo y subiendo.
- [ ] Cuánto pesan las cruces negras y grises.
- [ ] Si usa las medias de 10 y 55, u otras.
- [ ] Qué temporalidad usa para cada decisión.
- [ ] Cómo decide el stop y la salida en la práctica.

---

## Fuentes

- Scripts y estrategias de la comunidad: https://es.tradingview.com/script/2qapmnO6/ (Ruckard
  TradingLatino), https://de.tradingview.com/script/PjaGa5pl (SQZMOM + ADX),
  https://www.tradingview.com/script/93yYDjuA-Latino-Trading-by-Panda-Trading-Squeeze-Momentum-ADX-4-EMA/
- Notas de seguidores: https://tpotraders.com/estrategia-squeeze-momentum-adx/,
  https://tagstrading.com/como-usar-la-estrategia-de-trading-latino-con-indicadores/?lang=es,
  https://api-developers.com/como-usar-el-squeeze-momentum-indicator-adx-pro/,
  https://www.scribd.com/document/554500429/Estrategia-de-Jaime-Merino,
  https://pdfcoffee.com/estrategia-tradinglatino-pdf-free.html
- Prensa con sus palabras: https://decrypt.co/es/236956/jaime-merino-tradinglatino-caida-bitcoin-btc,
  https://decrypt.co/es/343268/que-significa-la-divergencia-bajista-que-tradinglatino-detecto-en-bitcoin,
  https://decrypt.co/es/334839/tradinglatino-explica-por-que-vendio-bitcoin-en-120-000,
  https://decrypt.co/es/363035/tradinglatino-bitcoin-zona-rechazo-69000-correccion-bajista
- Código y límites de riesgo del script de Ruckard: https://github.com/ruckard/trading/blob/main/tradingview-indicators.md
