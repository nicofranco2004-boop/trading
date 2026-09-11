# Plan — el traspaso de títulos entre dos brokers

> Estado: **listo para arrancar** — las tres decisiones resueltas (§12), sin escribir una línea todavía. Escrito 2026-09-10, después de
> auditar los archivos reales de Agustín Sapino (Bull Market → Balanz).
> Relacionado: `project_traspaso_entre_brokers.md` en la memoria.

---

## 1. El problema, con números

Agustín operó en Bull Market entre 2021 y 2024, y en enero/febrero de 2024 **se
llevó los títulos a Balanz** (no la plata: los papeles).

**Bull Market no declara que los títulos salieron.** Su export es el libro de
caja, y mover papeles no mueve plata, así que no hay ninguna fila que los saque.
Lo único que queda es lo que costó el trámite:

```
22/01/24  DTRT  $1.210   GTOS. TRANS. TITULOS
05/02/24  DTRT  $2.420   GTOS TRANS. TITULOS
```

**Balanz sí declara la entrada**, en esas mismas dos fechas, con el precio de
mercado del día — no con lo que él había pagado.

Consecuencias medidas:

| | |
|---|---:|
| Posiciones que Rendi deja abiertas en Bull Market y él no tiene | **21** |
| De ésas, que empatan una a una con lo que entró a Balanz | **9** |
| Lo que le costaron en Bull Market | **$2.439.243** |
| Lo que valían al pasar a Balanz | **$8.089.864** |
| **Ganancia que Rendi no ve** | **$5.650.621 (+232 %)** |
| De su "capital aportado" en pesos que no es plata que puso | **$8.493.784 (18 %)** |

*(pesos de enero/febrero 2024)*

**Hoy cargar Bull Market EMPEORA las cosas**: los nueve títulos quedarían
abiertos en los dos brokers a la vez — doble tenencia y doble capital aportado.
Por eso la recomendación actual es que use sólo Balanz.

---

## 2. La decisión ya tomada

> Cuando alguien mueve títulos de un broker a otro, **el broker de origen cierra
> según si el destino está cargado en Rendi**:
>
> - **Destino EN Rendi** → el origen cierra **al valor del pase**. Realiza la
>   ganancia del tramo viejo, y su retiro netea contra el depósito del destino,
>   así el capital aportado no se cuenta dos veces.
> - **Destino FUERA de Rendi** → el origen cierra **a costo** (`transfer_out`,
>   P&L 0). Es lo que ya está deployado (`6f398518`) y lo correcto para el caso
>   de Facu: no inventa una ganancia por papeles que sólo cambiaron de lugar.

---

## 3. ⭐ El hallazgo que cambia el tamaño del trabajo

**No hace falta un paso nuevo en el pipeline.** Toda la infraestructura existe:

1. **El persister ya aplica un batch con varios brokers.** Trabaja con
   `unique_brokers = {tx.broker for tx in sorted_txs}`; cada movimiento dice a
   qué broker va. Es lo que ya hace el modo "mezcla de brokers".
2. **Ya existe el precedente de movimientos que NO vienen del archivo.** La foto
   de tenencia genera movimientos sintéticos con `row_index = -20000 - i` y
   entran por el mismo camino.
3. **El deshacer sale gratis.** `revert_batch` deshace *todos* los movimientos
   del batch, incluidos los de otro broker. No hay que escribir nada.
4. **Los datos ya están a mano.** `run_preview` llama a
   `fetch_existing_positions`, que devuelve `{(broker, activo): cantidad}` —
   justo lo que hace falta para encontrar la posición abierta del otro broker.

**Entonces el trabajo es**: durante la *vista previa*, agregar al lote los
movimientos de cierre del broker de origen. Se guardan con los demás, el usuario
**los ve antes de confirmar**, el confirm los aplica y el deshacer los revierte.

---

## 4. Cómo detectar un traspaso

Un traspaso es un par **entrada ↔ salida** entre dos brokers del mismo usuario.

### La entrada
La declara el broker que recibe. Hoy Balanz la manda como
`Transferencia Externa (Crédito)`, con fecha, ticker, cantidad y precio. El
parser ya la reconoce (rama `kind == "transfer"`); falta **marcarla**, igual que
se hizo con `transfer_out`.

### La salida
Tres formas, según el broker:

| Broker | Cómo aparece |
|---|---|
| Balanz | `Transferencia Externa (Débito)`, cantidad negativa — **ya soportada** |
| IEB | código `RETR` — **ya soportada** |
| PPI | `Retiro de Títulos` — **ya soportada** |
| **Bull Market** | **no existe.** Sólo el gasto `DTRT` |

### El emparejamiento
> **Por (ticker, fecha), NUNCA por cantidad.**

Medido: VIST pasó de **28 a 84** (cambio de ratio del CEDEAR ×3) y AMZN de
**154 a 230**. Exigir que la cantidad coincida falla en 2 de los 9 casos reales.

Para Bull Market, que no declara la salida, la señal de confirmación es el
**gasto de transferencia de ese día**. Sin él no se toca nada: es la diferencia
entre "se lo llevó" y "casualmente tiene el mismo papel en dos brokers".

⚠️ **El gasto solo no alcanza.** Hubo **dos traspasos parciales** (22/01: cuatro
títulos; 05/02: los otros ocho). Cerrar todo lo abierto en el primero habría
cerrado los doce el 22 de enero. **El gasto dice CUÁNDO; el destino dice QUÉ.**

---

## 5. El orden de importación (la parte delicada)

Hay tres situaciones y **no son la misma**:

### A. Primero el origen, después el destino
Importa Bull Market, después Balanz. Al previsualizar Balanz, sus entradas por
traspaso están en el lote actual y las posiciones de Bull Market ya en la base.
**Es el caso fácil y el que hay que resolver primero.**

### B. Primero el destino, después el origen ← *el caso de Agustín*
Ya importó Balanz. Al previsualizar Bull Market, las entradas están en un lote
**ya confirmado**: hay que buscarlas en `import_normalized_tx` de lotes
confirmados, no en el lote actual. Es la misma lógica mirando para el otro lado.

### C. Ya importó los dos
No hay ninguna importación nueva donde engancharse. Sólo se arregla
**re-importando** uno de los dos, o con una herramienta de reparación aparte.
**Fuera de alcance de esta tanda** — se resuelve pidiéndole que re-importe.

---

## 6. Qué se genera

Para cada par encontrado, movimientos sintéticos en el **broker de origen**, con
`row_index` negativo único (la convención que ya usa la foto de tenencia):

1. **VENTA** del ticker, con la cantidad que tenía abierta, **al valor del pase**
   (el precio que declara el broker que recibe).
2. **RETIRO** por ese mismo valor → el capital aportado del origen baja
   exactamente lo que sube en el destino. **No se cuenta dos veces.**

La caja no se mueve en ninguno de los dos lados: la venta acredita y el retiro
debita el mismo importe.

---

## 7. Casos límite que hay que resolver ANTES de escribir código

Ninguno es teórico: todos salen de los archivos reales.

1. **Cambio de ratio.** VIST 28 → 84. Se cierra **lo que el origen tenga
   abierto**, no la cantidad del destino. El valor del pase se toma del destino.
2. **Traspaso parcial.** ¿Y si movió la mitad? Con Balanz se sabe (declara la
   cantidad). Con Bull Market no. **Propuesta: si el origen tiene más de lo que
   entró al destino, cerrar sólo lo que empata y avisar del resto.**
3. **El mismo papel en dos brokers sin traspaso.** Es lo normal. Por eso hace
   falta la señal de salida (débito, `RETR`, `Retiro de Títulos` o el gasto de
   Bull Market). **Sin señal, no se toca nada.**
4. **Correr dos veces.** Si el usuario sube el mismo archivo de nuevo, no se
   pueden generar los cierres otra vez. El dedup por huella no cubre movimientos
   sintéticos: **hay que darles una huella propia**.
5. **Deshacer el lote del destino.** Si revierte Balanz, el cierre de Bull Market
   se deshace con él (viaja en el mismo lote) — pero el destino ya no tiene los
   títulos. Queda consistente. **Verificar con una prueba de punta a punta.**
6. **Cambia de nombre el broker.** Los brokers se enlazan por NOMBRE, no por id
   (`project_broker_data_model`). Renombrar rompe el par. Fuera de alcance.
7. **El ticker cambia en el camino.** CSDOO (Bull Market) → CS38O (Balanz): fue
   un canje, no un traspaso. **No se empareja. Queda abierto y se avisa.**

---

## 8. Fases

### Fase 1 — marcar y emparejar en un solo sentido *(el caso A)*
- Marcar la entrada por traspaso en el parser (como se hizo con `transfer_out`).
- Emparejador en `run_preview`: entradas del lote actual ↔ posiciones abiertas de
  otros brokers, con señal de salida.
- Generar VENTA + RETIRO sintéticos y mostrarlos en la vista previa.
- **Se verifica con**: Bull Market y después Balanz, de punta a punta, y las
  nueve posiciones tienen que quedar en cero.

### Fase 2 — el otro sentido *(el caso B, el de Agustín)*
- Buscar también las entradas en lotes ya confirmados.
- **Se verifica con**: sus archivos reales, en el orden en que él los tiene.

### Fase 3 — Bull Market
- El gasto de transferencia como señal de fecha.
- **Se verifica con**: sus dos archivos. Nueve posiciones cerradas, y CSDOO,
  GOLD y los saldos negativos **quedan abiertos y avisados** (no son traspasos).

### Fase 4 — que se vea *(ya casi no es trabajo, ver 12.3)*
- Los cierres se generan con `[requiere-aprobacion]`: no se aplican solos y el
  mecanismo de mostrarlos y aprobarlos **ya existe** (los bonos amortizantes).
- Sólo queda redactar el texto en castellano: *"Estos 9 títulos se van a cerrar
  en Bull Market porque entraron a Balanz el 22/01/2024"*.

---

## 9. Cómo se sabe que funcionó

**No contra el mismo archivo que estamos auditando.** Se compara contra el
resumen que emite el broker, que es lo que hicimos hoy:

| Prueba | Tiene que dar |
|---|---|
| Bull Market después del cruce | **0 posiciones** de las 9 |
| Balanz | 9 de 9 contra el resumen (**no se puede romper**) |
| Caja de Balanz | $713.772,28 y USD 314,44 (**no se puede romper**) |
| Capital aportado | **baja** $8.493.784: deja de contar dos veces lo mismo |
| Deshacer el lote | vuelve todo a como estaba, en los dos brokers |

Y las de siempre: la suite entera en verde, y los tests nuevos tienen que
**fallar contra el código de hoy** — si no, no prueban nada.

---

## 10. Riesgos

| Riesgo | Cómo se acota |
|---|---|
| **Cerrar posiciones que el usuario sí tiene** | **Tres frenos**: sin señal de salida no se toca nada; se cierra el mínimo de los dos (12.1); y nada se aplica sin aprobación (12.3). Es el riesgo grave: le borra tenencia real |
| Toca el camino de importación recién estabilizado | Fase 1 aislada + la suite entera en cada paso |
| Afecta a todos los usuarios de Balanz, IEB y PPI | La vista previa lo muestra antes de confirmar; nada es silencioso |
| Falsos pares por casualidad | Ticker + fecha + señal de salida. Tres condiciones, no una |

---

## 11. Lo que NO entra

- **El caso C** (ya importó los dos): se resuelve re-importando.
- **Arrastrar el costo original** en vez de realizar la ganancia en el origen.
  Se descartó: obligaría a que el importador conozca el costo del otro broker.
- **Bull Market con traspasos parciales de un mismo ticker.** Su archivo no
  alcanza para saberlo.
- **Renombrar un broker** después del cruce.

---

## 12. Las tres decisiones — resueltas

### 12.1 Traspaso parcial → **cerrar el MÍNIMO de los dos**

Se cierra `min(lo que el origen tiene abierto, lo que entró al destino)`. Si
sobra, queda abierto y se avisa.

**Por qué**: los dos errores posibles no pesan igual.

| Si cierro de MÁS | Si cierro de MENOS |
|---|---|
| Le borro tenencia **real**. Ve menos plata y no sabe por qué | Le queda una posición fantasma parcial |
| **Grave** | Leve: **es exactamente el estado de hoy** |

El mínimo falla del lado seguro y, además, **funciona en los tres casos reales**:

| | Origen | Destino | Cierra |
|---|---:|---:|---|
| AL30 | 6.460 | 6.460 | 6.460 — todo ✓ |
| VIST (ratio ×3) | 28 | 84 | 28 — todo ✓ |
| Parcial hipotético | 100 | 60 | 60, quedan 40 abiertos + aviso ✓ |

### 12.2 La vista previa → **desglosado**

Una línea por título, no "9 títulos". Es una acción que **modifica un broker que
el usuario ni siquiera está importando**: eso sorprende, y merece verse entero.
Son nueve líneas, no novecientas. Si alguna vez son más de 20, ahí sí resumir.

### 12.3 ¿Desactivable? → **⭐ que no se apliquen solos**

**No hace falta un interruptor de configuración**, y no hay que construir nada:
el repo ya resolvió esta misma clase de problema.

`importing/tenencia.py` define `MARCA_APROBACION = "[requiere-aprobacion]"`: una
fila sintética con esa marca en las notas **no se aplica sola**; hay que
aprobarla en el confirm (`aprobar_tickers`). Se usa hoy para los bonos
amortizantes, por un motivo idéntico al nuestro: *no se puede distinguir un hueco
real de un desajuste, y sembrar el faltante puede fabricar una compra que nunca
pasó.*

El comentario del repo dice por qué la marca va **en la fila** y no en una lista
aparte:

> «con la marca en la propia fila, el default es NO aplicar aunque el frontend no
> implemente nada: **falla CERRADO**».

Es exactamente lo que necesitamos. Los cierres del broker de origen se generan
**marcados**, el usuario los ve en la vista previa y los aprueba. Quien tenga el
mismo papel en dos brokers a propósito, simplemente no los aprueba.

Y se aprueba **por ticker**, no por fila — así Agustín aprueba sus nueve de una.

**Efecto en el plan**: la Fase 4 ("que se vea") deja de ser trabajo nuevo. El
mecanismo de mostrar y aprobar filas sintéticas ya existe de punta a punta.
