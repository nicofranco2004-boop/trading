# DOS VACÍOS QUE NO EXPLICAN NADA

Sos el chat IMPLEMENTADOR. Todo lo anterior está **deployado en producción** (`e3ab0b0f`,
24 commits) y verificado: backend sirviendo nuestro commit, frontend con el bundle nuevo.

Esta ronda es **sólo copy y un estado deshabilitado**. Cero lógica, cero cálculo, cero backend.

Las dos cosas las encontró el dueño usando la app, y las dos tienen la misma forma: **la
pantalla le saca algo al usuario sin decirle por qué**, y el usuario concluye que la app está
rota. Le pasó a él, que escribió el producto.

---

## 1 · «¿No era que el certero mostraba dos años?»

El dueño abrió su cuenta y vio el certero arrancando el **29/06/2026** — dos meses. Esperaba
años, porque usa Rendi desde 2023.

**No está roto. Medido sobre la copia de producción:**

```
sus snapshots           55 filas, desde 2023-02-28
   al COSTO             44   2023-02-28 → 2026-06-30
   a MERCADO            11   2026-05-31 → 2026-08-16
```

Y no es su cuenta — **es todo el padrón**:

```
cuánto historial MEDIDO tiene cada usuario (= el largo del certero)
   < 1 mes        106 usuarios  (16,3 %)
   1-3 meses      543 usuarios  (83,7 %)
   1 año o más      0 usuarios  ( 0,0 %)
```

**Nadie tiene más de tres meses.** Ninguno de los 649. Y la causa está medida:

```
filas a mercado en TODA la base : 27.452, desde 2026-05-31
primera fila con fx_to_usd_blue : 2026-05-31
primera fila con holdings_json  : 2026-07-05
```

El clasificador necesita esos campos para afirmar que una fila la escribió el cron y no la
fabricó el import. **El cron empezó a estamparlos el 31 de mayo de 2026.** Todo lo anterior es
indistinguible de la contabilidad y cae al costo, para todos.

O sea: **la feature no está mal construida, nació hace tres meses**, y crece un día por día.

### 1.1 · Lo que hay que arreglar

El chip dice **«Medido desde 29/06/2026»** (`Insights.jsx:1025`). Es cierto y es insuficiente:
no prepara para que sean dos meses, así que el usuario cree que perdió su historia.

Agregale la explicación. Algo en la dirección de:

> **Medido desde el 29/06/2026** — Rendi empezó a medir a precio real hace poco, y esto crece
> todos los días.

⚠️ **No inventes la fecha del 31 de mayo en el texto.** Es la fecha de la primera fila medida en
la base, no la de este usuario, y meterla como si fuera suya sería exactamente el tipo de número
inventado que este proyecto viene sacando. La fecha que va es la que ya está: `perf.medido_desde`.

⚠️ **Y no digas "dos años" ni ningún plazo.** Ese número salió de una expectativa, no de una
medición — de hecho es lo que originó esta ronda.

## 2 · En pesos, el toggle desaparece sin decir nada

`Insights.jsx:2792` gatea el toggle Certero/Estimado con `currency === 'USD'`. En pesos **no se
dibuja**: el usuario ve un solo modo y ninguna pista de que exista el otro.

**El gate está bien puesto y no hay que sacarlo.** En ARS el modo estimado no se puede construir
hoy: `arsMonthly` se arma leyendo la cadena mensual cruda y nunca pasa por `applyMtmToMonthly`,
y eso **no se arregla donde está** — el re-anclaje usa los snapshots GLOBALES y la serie en pesos
es un SUBCONJUNTO (sólo brokers ARS). Verificado: la tabla `snapshots` **no tiene columna de
broker** y no hay otra tabla. Hace falta snapshots por broker, que es un cambio de modelo de
datos y no es esta ronda.

Lo que está mal es que **desaparezca en silencio**. Y el alcance no es chico:

```
usuarios con al menos un broker ARS : 758 de 854 (89 %)
```

### 2.1 · Lo que hay que arreglar

Que en ARS el toggle **se vea deshabilitado con el motivo**, en vez de no existir. Algo como
*«disponible en dólares»* en el `title`, y los dos botones en gris sin poder clickearse.

El usuario tiene que poder enterarse de que el modo existe y de qué le falta para usarlo. Un
control ausente se lee como una app incompleta; uno deshabilitado con motivo se lee como una
app honesta.

## 3 · 🔴 LO QUE NO SE PUEDE ROMPER

**Nada de lógica.** Esta ronda toca textos y un `disabled`. Si te encontrás editando `twr.py`,
`performance.py`, `insightsModel.js`, `evolution.js` o cualquier cálculo, **parate**: estás
arreglando el lugar equivocado.

Lo que está deployado y verificado, y no se toca:
- certero bit-idéntico · estimado ⊇ certero · el clamp 95→71 · el eje temporal
- la suite en **29 fallas conocidas** (`tests/fallas_conocidas.txt`)

**Y en USD nada puede cambiar.** El gate nuevo es sobre la rama ARS; verificá que con
`currency === 'USD'` la pantalla quede idéntica.

## 4 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (= origin/main, e3ab0b0f, árbol limpio)
```

- ❌ **NO pushees.** Esto ya está en producción; un push deploya de nuevo.
- ✅ Podés commitear.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala).
- La suite: `python3 -m pytest tests/` (≈55 s). Frontend: `npx vitest run` + `npx vite build`.

### Instrumento — diez trampas que ya cobraron en este proyecto

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. Compará **CONJUNTOS de nombres**, nunca conteos.
5. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.** El auditor lo
   hizo: el sandbox había mergeado contra refs distintas, pisó `main.py` y se llevó funciones
   de producción. Commiteó marcas de conflicto con el build roto. Resolvé SIEMPRE en el lugar.
6. **Verificá ANTES de commitear**, no después. El mismo error se cometió porque el script
   imprimió «queda 1 archivo con marcas» y siguió igual.
7. Midiendo el gráfico por DOM los dos chats se equivocaron **siete** veces: selector que mezcla
   dos `.recharts-wrapper`, sesión expirada tomada por bug, contar `M`/`L` cuando Recharts usa
   `C`, contar `dots`, contar un solo path, adivinar nombres de claves. Lo que funciona: leer
   `chartData` del fiber, o los ticks **acotados al primer wrapper**.
8. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.
9. **Un número sin su consulta no es reproducible.** El auditor pasó «21 alertas» sin decir cómo
   lo medía; el implementador midió 24, probó seis definiciones y no pudo reconciliar. Las dos
   eran correctas. Si pasás una medición, pasá la query.
10. `which` no es el inventario del entorno: hay PostgreSQL real vía el paquete pip `pgserver`.

**Datos**: copia de producción estampada en `.../scratchpad/pico.db`. App local:
`http://localhost:5199`, `demo.metricas@rendi.test` / `demo1234`.

## 5 · CRITERIO DE SALIDA

1. En USD, el chip explica **por qué** el historial medido es corto, sin inventar fechas ni plazos.
2. En ARS, el toggle **se ve deshabilitado con el motivo** en vez de desaparecer.
3. En USD la pantalla queda **idéntica** salvo el texto del chip.
4. Sin fallas nuevas; `fallas_conocidas.txt` no crece. `vite build` limpio.
5. **Capturas**: USD y ARS, en los dos modos.

## 6 · QUÉ ENTREGAR

1. Los cambios, con `file:line`.
2. Las capturas del §5.5.
3. Los conjuntos de tests, antes y después.
4. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito.

## 7 · FUERA DE ALCANCE

- 🔴 **La ruta de cobro sin tests** — `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:~25939`). Migraron de proveedor y los
  tests no siguieron. **Es el mayor riesgo no medido que queda en el repo.**
- `test_bond_conduit.py` — 640 donde se espera 720.
- El POST del browser sin guarda de cobertura (el cron sí la tiene).
- **Snapshots por broker** — lo que habilitaría el estimado en ARS de verdad. Proyecto, no ronda.
- Postgres, Fases 3 y 4.
