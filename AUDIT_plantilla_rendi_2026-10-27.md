# AUDITORÍA — La plantilla de Rendi (`rendi_generic`) y el rendimiento

**Fecha:** 2026-10-27 · **Rama:** `claude/affectionate-wright-uvbnbl` · **No se arregló nada todavía.**

La plantilla es el CSV que la persona descarga del importador ("Descargar template de
ejemplo") y completa a mano: `fecha, tipo, broker, activo, cantidad, precio, monto,
monto_usd, tc, comisiones, moneda, notas`. Es el camino de quien no tiene un broker con
importador propio, o quiere cargar su historia a mano.

## Cómo se midió

Con el mismo arnés de la auditoría del CSV (`audit/rendimiento_csv/`), por el camino de
producción (vista previa y confirm HTTP, reconstrucción, cron real día por día), con el
mercado inventado donde la verdad se conoce exacta. Script nuevo:
`audit/rendimiento_csv/plantilla_rendi.py`.

1. **Movimientos:** cada tipo de movimiento escrito como lo escribiría una persona, en
   una cuenta chica propia; se lee qué tenencia, caja y aportes dejó el importador.
2. **Escenarios:** el inversor de la auditoría (2024-01 → hoy, pesos y dólares, CEDEARs,
   acciones, un bono, MEP, cupones, ventas) escrito en la plantilla, con las variantes
   que aparecen al cargarla a mano. Cada caso dos veces: con el broker **creado por la
   importación** (lo que pasa hoy si no existía) y con el broker **ya creado en pesos**.
3. Los mismos escenarios sobre el **código original** (`1e1f785`) y con los arreglos de
   esta rama, para ver qué cambió.

Salidas (no se commitean): `_comparacion/plantilla/`.

## Resumen para el dueño

**Con la plantilla completa y bien escrita, el rendimiento sale exacto** (Certero y
Estimado +141,4 % contra +141,3 % real, desde el primer mes). Pero hay cuatro problemas
graves, todos con la misma consecuencia: un número muy errado con apariencia de exacto.

1. **Un broker nuevo puede quedar en dólares y guardar los pesos como dólares.** Si el
   broker no existía, Rendi lo crea con la moneda de la MAYORÍA de las filas; con empate
   o más filas en dólares, queda en dólares. Los pesos se guardan como dólares, el MEP se
   rechaza y el rendimiento sale **~0 % cuando la verdad es +25 %**. Con la historia
   completa salía bien de casualidad (10 filas en pesos contra 9 en dólares): quitar una
   sola venta en pesos alcanzó para darlo vuelta. *(Ya pasaba antes de esta rama.)*

2. **Sin foto de tenencia, el Certero ahora confía en la plantilla sola — y si le falta
   algo, inventa.** *(Regresión de MIS arreglos, Fase A.)* Antes, sin foto, el Certero
   medía sólo desde el cron. Ahora mide toda la historia del archivo: exacto si está
   completo, pero si falta algo:

   | a la plantilla le falta | código original (Certero) | con los arreglos (Certero) | verdad |
   |---|---|---|---|
   | los depósitos (sólo compras y ventas) | +45,5 % desde ago-26 (verdad +25,2) | **+1.841 %** desde abr-24 | +157,8 % |
   | una venta | +33,6 % desde ago-26 (verdad +25,2) | **+193,2 %** | +141,3 % |
   | lo anterior a 2025 | sin número | **+43,9 %** | +87,6 % |
   | los dividendos y cupones | +26,2 % desde ago-26 (verdad +25,2) | +133,1 % | +141,3 % |
   | el dólar MEP | +25,4 % desde ago-26 (verdad +25,2) | +139,5 % | +141,3 % |

   **No es sólo la plantilla:** lo mismo pasa con un archivo de Balanz o IEB cuando la
   persona no sube la foto (falta una venta: Certero +162 % contra +121 % real, donde
   antes no publicaba). Con la foto, el Certero da exacto en todos los casos probados.

3. **Los números escritos a la argentina se rompen.** "1.000.000" se **rechaza** (si la
   persona confirma igual, faltan esos depósitos: Certero +214 % contra +133 %), y
   "150.000" en un depósito se lee como **$150, sin ningún aviso**. "1.500,50" sí anda.
   *(Ya pasaba antes.)*

4. **Sin depósitos, el "Estado inicial" no alcanza.** El importador ofrece cargar la caja
   de hoy y crea un depósito el día antes del primer movimiento: la caja queda bien, pero
   toda la plata figura entrando el primer día. Certero +108 % contra +141 % real. *(Ya
   pasaba antes.)*

Problemas menores (la persona ve el error, o el efecto es acotado): "CUPON"/"Cupón" no
se reconoce; "Suscripción" a un FCI entra como **depósito** de plata (infla lo aportado
y no crea el FCI); no hay forma de cargar títulos traídos de otro broker; y la plantilla
se descarga **con 6 filas de ejemplo** (GGAL en Cocos, un dividendo en IBKR…) que, si la
persona no las borra, entran como operaciones reales y crean esos brokers.

## Hallazgos en detalle

### PL1 · El broker nuevo toma la moneda de la mayoría de filas — CONFIRMADO

- **Eslabón:** `importing/pipeline.py` (~línea 740, "Auto-crear brokers"): sin formato
  con moneda base (la plantilla no tiene), `ars_count > usd_count` → ARS; si no, USD.
- **Qué pasa en un broker en dólares con filas en pesos:** la caja en pesos se suma como
  dólares (cuenta de prueba: depósito de $1.000.000 + US$500 → caja "US$1.000.500"), las
  conversiones MEP se rechazan (`FX_BROKER_MISMATCH`), y un broker en pesos con su
  sub-cuenta "· USD" —la combinación que sí funciona— nunca se arma.
- **Medido:** historia completa 10 filas en pesos / 9 en dólares → ARS, exacto. Sin una
  venta en pesos (9/9) → USD: Certero y Estimado **+0,2 %** contra +25,2 % real. Lo mismo
  arrancando en 2025 (5/5) y con números a la argentina (filas rechazadas).
- **Pantalla:** el asistente avisa "Brokers nuevos creados … con la moneda inferida
  (podés cambiarla después en Posiciones)". Cambiarla después no arregla lo ya cargado.
- **Arreglo propuesto:** si un broker nuevo trae filas en pesos, crearlo en pesos (los
  dólares van solos a "· USD", que ya funciona); o preguntar la moneda en el asistente.
- **Medir en prod:** brokers en USD/USDT sin padre que tienen lotes en pesos.
- **Estado (2026-10-27):** arreglado y en producción —
  [PR #36](https://github.com/nicofranco2004-boop/trading/pull/36), mergeado a `main`
  (`acf6dbf`)—: broker nuevo con pesos → en pesos; broker en dólares vacío → se cura al re-importar; con
  datos → la fila en pesos se rechaza (también al confirmar con "Estado inicial").
  Exchanges cripto (Binance & cía.) quedan como estaban: mandan pares en pesos a
  propósito y falta medir cuántos son. Las cuentas que YA quedaron mal no se tocan
  solas: `backend/scripts/diag_brokers_moneda.py <copia de prod>` las lista.
- **La foto de tenencia, la misma falla por otra puerta (2026-10-27):** la foto va a un
  broker que ya existe y da por hecho que es en pesos; si quedó en dólares, metía los
  pesos como dólares (reproducido: $1.500.000 → "US$1.500.000"). Arreglado y en
  producción en [PR #37](https://github.com/nicofranco2004-boop/trading/pull/37)
  (`7fca3ef`), con la misma regla que el import (vacío → pesos; con datos o historia →
  se rechaza). La auditoría de ese PR encontró dos fallas en la curación de #36, ya
  corregidas:
  - la caja curada conservaba sus marcas en "USD", y metas, IA y reportes valuaban los
    pesos como dólares;
  - un broker que vendió y retiró todo contaba como vacío.

### PL2 · Sin foto, el Certero confía en el archivo (regresión de la Fase A) — CONFIRMADO

- **Eslabón:** Fase A hizo apta la reconstrucción con cobertura ≥ 90 % y caja verificada
  (`_verificar_caja`). Pero la caja se verifica contra `positions`, que sale del MISMO
  archivo: con la plantilla (o un export sin foto) la verificación siempre pasa. La única
  prueba independiente es la foto de tenencia (`_foto_que_contradice`), y sin foto no hay
  nada que contradecir.
- **Medido:** tabla del resumen. La comparación de la auditoría no lo vio porque medía
  el resultado final DESPUÉS de subir la foto (y el escenario genérico era sólo el
  completo).
- **Arreglo propuesto (decisión tuya):** una foto reconstruida es certera sólo si una
  foto de tenencia posterior la confirmó. Sin foto → la historia es Estimado (con su %
  a precio real) y el Certero mide desde el cron, como antes. Con foto, se conserva toda
  la mejora de la Fase A (exacto en todos los casos probados). Para quien usa la
  plantilla y su broker no tiene foto: un paso "¿esto es lo que tenés hoy?" que haga de
  foto manual.

### PL3 · Números a la argentina — CONFIRMADO

- `importing/normalizer.py:parse_number`: con sólo puntos asume decimal; "1.000.000"
  no parsea (`INVALID_NUMBER`, fila rechazada). "150.000" (un punto y tres dígitos) es
  ambiguo y sólo se resuelve en compras/ventas por precio × cantidad = monto
  (`_desambiguar_por_triangulo`); en un depósito queda **150** sin aviso.
- **Arreglo propuesto:** en la plantilla (no en los exports de broker, que generan esos
  números por su cuenta) decidir el formato por archivo: si algún número tiene coma
  decimal o dos puntos de miles, todo el archivo es formato argentino; o preguntarlo.

### PL4 · "Estado inicial" pone toda la plata el primer día — CONFIRMADO

- `importing/seed.py`: el depósito sintético va 1 día antes del primer movimiento.
  Medido: caja exacta, Certero +108,4 % contra +141,3 %.
- **Propuesta:** la historia cuya caja depende del Estado inicial no es certera
  (Estimado), igual que PL2.

### PL5 · Tipos de movimiento — CONFIRMADO

| escrito | resultado | ¿bien? |
|---|---|---|
| COMPRA / VENTA con `comisiones` | lote y caja correctos (la comisión sale de la caja) | ✔ |
| COMPRA con `monto` sin `precio` | precio calculado | ✔ |
| DEPOSITO / RETIRO en pesos y dólares (broker en pesos) | caja en su sub-cuenta | ✔ |
| COMPRA de CEDEAR en dólares | sale de la caja en dólares | ✔ (con broker en pesos) |
| DIVIDENDO en dólares de un CEDEAR | a "· USD" | ✔ |
| CONVERSION_ARS_USD (completa, o con `monto` + `tc`) | pesos → dólares | ✔ |
| MEP con bono puente (COMPRA AL30 + VENTA AL30D) | netea, mueve las dos cajas | ✔ |
| COMISION / IMPUESTO sueltos | restan de la caja | ✔ |
| RENTA / "Pago de renta" | cobro | ✔ |
| AMORTIZACION | cobro, el nominal no baja | ✔ coherente con la cotización por valor nominal original |
| **CUPON / Cupón** | **rechazado** (`UNKNOWN_OP_TYPE`) | ✗ agregar el sinónimo |
| **SUSCRIPCION (FCI)** | **depósito de plata**: infla lo aportado, no crea el FCI | ✗ |
| **RESCATE sin cantidad** | rechazado | ✗ (pide cuotapartes) |
| **TRANSFERENCIA de títulos** | rechazado, y el mensaje sugiere DEPOSITO/RETIRO | ✗ no hay forma de cargarlo |
| VENTA sin compra previa | la plata aparece sin aporte (H5-a) | ✗ (igual que en los exports) |
| moneda vacía | el lote queda sin moneda (toma la del broker) | ~ |
| fecha "5/1/26" o de EE.UU. | rechazada con mensaje claro | ✔ |

### PL6 · La plantilla trae filas de ejemplo que se importan — CONFIRMADO

`importing/parsers/generic.py:template_csv` devuelve 6 filas de ejemplo (2024, Cocos e
IBKR). Subida tal cual: crea los brokers Cocos e IBKR, 40 GGAL, un MEP de $1.200.000 y
una caja de −$936.018. Nada las detecta. **Propuesta:** plantilla sin filas (las
instrucciones en otra hoja o en la pantalla), o detectar y descartar las de ejemplo.

## Prioridad sugerida

1. **PL2 antes de mergear la rama** (es una regresión mía): Certero sólo con foto.
2. **PL1** (broker nuevo en pesos si trae pesos): chico y evita el peor caso.
3. **PL3** (formato de números de la plantilla).
4. **PL5 y PL6** (sinónimos, FCI, títulos de otro broker, filas de ejemplo).
5. **Producto:** "foto manual" al terminar de cargar la plantilla.

## Para medir en producción (en tu Mac)

```bash
# cuántas cuentas cargaron con la plantilla y si tienen foto de tenencia
sqlite3 'file:<ruta>?immutable=1' "SELECT COUNT(DISTINCT b.user_id), SUM(EXISTS(SELECT 1 FROM import_batches t WHERE t.user_id=b.user_id AND t.parser_format LIKE '%tenencia%' AND t.status='confirmed')) FROM import_batches b WHERE b.parser_format='rendi_generic' AND b.status='confirmed'"
# PL1: brokers en dólares con lotes en pesos
sqlite3 'file:<ruta>?immutable=1' "SELECT br.user_id, br.name, br.currency, COUNT(*) FROM brokers br JOIN positions p ON p.user_id=br.user_id AND p.broker=br.name WHERE br.currency IN ('USD','USDT') AND br.parent_broker_id IS NULL AND p.currency='ARS' GROUP BY 1,2,3"
```

## 🔴 Qué no verifiqué

- Producción: cuántas personas usan la plantilla, con qué broker y si suben foto.
- El paso de "mapear tus columnas" con un CSV propio (otra forma de usar el genérico):
  probé la plantilla con sus columnas, no el mapeo.
- Cómo se ve en pantalla el aviso de "Estado inicial" y el de brokers nuevos.
- Un archivo real completado por una persona: todo es el inversor inventado.
