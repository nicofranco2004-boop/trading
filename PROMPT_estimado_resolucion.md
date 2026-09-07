# EL ESTIMADO PIERDE PUNTOS QUE EL CERTERO SÍ MUESTRA

Sos el chat IMPLEMENTADOR. Esto lo encontró el dueño mirando la pantalla, y lo formuló como un
invariante que vale más que el bug:

> **El estimado tiene que ser un superconjunto del certero.** Si un dato está en el certero,
> tiene que estar en el estimado — porque el estimado es *lo que se sabe* (el certero) **más**
> lo que se puede estimar. No puede faltarle nada que el otro tenga.

Hoy no se cumple, y la parte que falta es justo la más valiosa: la medida.

---

## 1 · EL SÍNTOMA

Cuenta demo (`demo.metricas@rendi.test` / `demo1234`, `http://localhost:5199` →
Análisis → Métricas), modo **Estimado**:

- **1M** → un solo punto, `Ago '26`, rendimiento 0 %.
- **3M** → tres puntos: `Jun '26`, `Jul '26`, `Ago '26`.

En **Certero**, la misma cuenta y las mismas fechas muestran **45 puntos diarios**, con una
caída a −8,3 % el 07/08 y su recuperación. En Estimado ese pozo **no existe**.

## 2 · LA CAUSA, YA LOCALIZADA — no la busques de nuevo

**El backend ya entrega el dato bien.** Medido sobre la copia de producción con
`twr.curva_indexada` en los dos modos, 493 usuarios:

```
cumplen el invariante (estimado ⊇ certero) : 493
lo violan                                  :   0
fechas perdidas                            :   0
```

Y en la cuenta demo el artefacto trae los 56 puntos, con el detalle diario intacto:

```
Sep'25 → Jun'26    1 punto cada uno   (mensual: es lo único que existe)
Jul'26            21 puntos            (diarios, medidos)
Ago'26            25 puntos            (diarios, medidos)
```

**La pérdida ocurre en el frontend**, en tres piezas encadenadas de `pages/Insights.jsx`:

| línea | qué hace |
|---|---|
| `:1127` `resolucionChart` | llama a `resolucionDeSerie` con **todas** las claves de la serie |
| `insightsModel.js:806` | devuelve `'diaria'` si el span ≤ `RESOLUCION_DIARIA_DIAS` (92 días), si no `'mensual'` |
| `:1130-1144` `activeSeriesMonthly` | si es `'mensual'`, agrupa por `YYYY-MM` y **se queda con el último punto de cada mes** |
| `:1151-1166` `windowSeries` | si es `'mensual'`, recorta con `slice(-N)` tratando cada elemento como un mes |

Los números:

```
certero    span 2026-07-11 → 2026-08-25 =  45 días  ≤ 92  →  'diaria'   → 45 puntos ✅
estimado   span 2025-09-30 → 2026-08-25 = 329 días  > 92  →  'mensual'  → tira 44 de 46 diarios
```

Con `'mensual'`, julio y agosto quedan en **un punto cada uno**. Después `1M = slice(-1)` deja
uno solo: nada que dibujar, 0 %. `3M = slice(-3)` deja Jun/Jul/Ago. Exactamente lo reportado.

### ⚠️ Y ES EL PATRÓN DE LAS ONCE RONDAS, OTRA VEZ

`Insights.jsx:1124` documenta la decisión: *"La resolución la decide lo MEDIDO, no el botón de
rango"*. **Era correcta** — mientras la serie *fuera* la ventana. La Fase 2 alargó la serie de
45 días a 329, y `resolucionDeSerie`, que mira el span completo, dependía de esa propiedad.
El arreglo cambió una propiedad de la que dependía otro consumidor que nadie miró.

## 3 · QUÉ HACER

El invariante del §0 es el norte. Dos caminos, en orden de preferencia:

**A · Resolución MIXTA (recomendado).** La serie es genuinamente de dos resoluciones: la parte
contable es mensual **porque no existe nada más fino** (son cierres de mes), y la parte medida
es diaria. Forzar una sola sobre las dos tira información real de un lado sin poder inventarla
del otro. Dibujá cada tramo con lo que tiene.

**B · Decidir la resolución por la VENTANA VISIBLE, no por la serie entera.** Hay que dar vuelta
el orden actual: hoy `resolucionChart` (`:1127`) se calcula **antes** del recorte (`:1151`), y el
recorte la usa. Primero cortar por fecha, después decidir sobre lo que quedó adentro.

⚠️ **Por qué la B sola no alcanza**: sigue eligiendo *una* resolución para toda la ventana. En
`1A` vas a volver a colapsar los 46 días medidos a 2 puntos — el mismo bug, corrido a los rangos
largos. Si hacés la B, dejá dicho en el código que el invariante sigue sin cumplirse ahí.

## 4 · 🔴 LO QUE NO SE PUEDE ROMPER

**El modo CERTERO tiene que quedar idéntico.** Ahí la serie *es* la ventana y la heurística
actual funciona bien. Es la propiedad que el auditor verificó **bit-idéntica en los 822
usuarios** cuando se hizo la Fase 2, y es la que sostiene todo el trabajo anterior.

Verificalo como se verificó entonces: A/B de `curva_indexada`/`chartData` en modo certero sobre
los 822, y que la diferencia sea **cero**.

**Y no toques el backend.** El dato ya llega bien — medido, 493 de 493. Si te encontrás editando
`twr.py`, `performance.py` o el endpoint, parate: estás arreglando el lugar equivocado.

## 5 · LO QUE VA EN LA MISMA RONDA (copy)

Quedó pendiente de la ronda anterior, y ahora tenemos la redacción del dueño:

**5.1 · El texto de la línea.** Hoy el chip dice *"sólo cuenta lo que ya vendiste"* — correcto
pero incompleto: no explica por qué esa línea puede no parecerse a la del certero.
Reemplazar por algo en la línea de: **"sólo se mueve cuando vendés — no refleja lo que pasa con
lo que todavía tenés"**.

⚠️ **NO escribas "esta línea nunca baja".** El auditor lo afirmó y era falso: la línea baja
cuando realizás una pérdida. Medido en producción: **11,4 % de los meses tienen realizado
negativo, y 443 de 673 usuarios tienen al menos uno**.

**5.2 · El tooltip del `?` del toggle.** Ponele la explicación del dueño, que es mejor que
cualquier cosa que haya hoy en pantalla:

> *Tu rendimiento lo puedo medir de dos maneras: una de la que estoy seguro pero con menos
> historial, y otra que te da más meses pero es aproximada. El benchmark es el mismo y es
> exacto en las dos.*

**5.3 · ⛔ NO saques el benchmark del modo estimado.** El auditor lo sugirió y el dueño lo
corrigió, con razón: del S&P **conocemos toda la evolución en las dos ventanas** — verificado,
45 y 56 puntos, cero nulos. Es lo único exacto de la pantalla, y da el ancla fija contra la cual
leer el cambio de modo. Sacarlo sería quitar lo que sí se sabe para protegerse de lo que no.

## 6 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala).
- ❌ NO toques `schema_pg.sql`, `scripts/mkschema.py`, `scripts/verificar_copia.py`, el hook de
  `estampar_base` en `main.py`, ni `pytest.ini`.
- ⚠️ **Respaldá antes de empezar.** Hay ocho rondas sin commitear.
- La suite ahora corre: **`python3 -m pytest tests/`**, 52 s, baseline **29 fallas conocidas**
  (`tests/fallas_conocidas.txt`). El hook de `conftest.py` grita en rojo si aparece una nueva.

### Instrumento — siete trampas que ya cobraron

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff` mezcla capas sin commitear. Árboles de referencia en `.../scratchpad/`:
   `pre1`, `r1tree`, `pre2`, `pre2r2`.
4. `which` no es el inventario: hay PostgreSQL real vía el paquete pip **`pgserver`**.
5. Copiá el harness a un directorio tuyo antes de usarlo.
6. Compará **CONJUNTOS de nombres**, nunca conteos.
7. 🔴 **Midiendo el gráfico por DOM, el auditor se equivocó tres veces seguidas**: leyó ticks de
   dos `.recharts-wrapper` distintos como si fueran uno, tomó por bug lo que era su sesión
   expirada (403), y contó vértices con `M`/`L` cuando Recharts dibuja con curvas `C`.
   Si medís el chart por DOM: scopeá al wrapper correcto, verificá que la sesión viva, y contá
   los datos de la serie, no los comandos del path.

## 7 · CRITERIO DE SALIDA

1. **El invariante se cumple en pantalla**: para la cuenta demo y en cada rango, el conjunto de
   fechas dibujadas en Estimado **contiene** al de Certero. Demostralo con una medición, no
   leyendo.
2. En Estimado, `1M` muestra los días de agosto que existen — no un punto con 0 %.
3. **Certero idéntico**, verificado usuario por usuario sobre los 822.
4. El chip y el tooltip dicen lo del §5, y el benchmark sigue en los dos modos.
5. Sin fallas nuevas: el conjunto de `fallas_conocidas.txt` no creció.
6. **Capturas del browser** de los dos modos en `1M`, `3M`, `1A` y `MAX`.

## 8 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line`.
2. La medición del invariante, antes y después.
3. El A/B de certero mostrando cero diferencias.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito y sin maquillar.

## 9 · FUERA DE ALCANCE

- El **clamp de plausibilidad** (21 de 95 alertas del asesor con pico ≥5× la cartera) — espera
  decisión del dueño.
- **La cobertura de la ruta de cobro**: `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:25939`). Migraron de proveedor y los
  tests no siguieron.
- `test_bond_conduit.py` — las 3 fallas dan 640 donde se espera 720; el mejor candidato a bug
  real de las 29.
- ARS, Postgres, Fases 3 y 4.
