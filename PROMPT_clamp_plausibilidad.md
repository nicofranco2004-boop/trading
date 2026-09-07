# EL CLAMP — la última superficie que publica algo imposible

Sos el chat IMPLEMENTADOR. Todo lo anterior está commiteado (`dca5a79c`, 54 archivos).

Esta ronda cierra la familia de bugs que llevaba once rondas, y cierra la **única pregunta que
nunca se hizo**.

---

## 1 · LA PREGUNTA QUE FALTA

Todo lo que se construyó estas diez rondas pregunta **con qué regla se midió este número**. Si
mezclaba mercado con contabilidad, no se publica. Eso funciona y está verificado.

**Nunca se preguntó si el resultado es posible.**

```
uid 513    pico  US$16.229.949    cartera hoy   US$108,96      148.953×
uid 756    pico  US$40.035.114    cartera hoy  US$3.069,64      13.042×
uid  54    pico   US$5.704.672    cartera hoy  US$9.334            611×
```

Una cartera de 108 dólares no valió dieciséis millones. Pero la fila que lo dice **pasa todos
los filtros**: `source='cron'`, clase `medicion`, `base='mercado'`, `apto=True`. No está mal
etiquetada — **está mal el dato**.

De ahí sale, **por mail al asesor**:

> *"Su ganancia cayó 492.864% desde el mejor momento — conviene que lo llames"*

Y el repo ya lo tiene diagnosticado, en `main.py:17511`:

> *"El guard exige que el borde sea una MEDICION, pero no que sea plausible. Si la medición del
> arranque es mala, el número se publica igual — y con el signo dado vuelta: en vez de una
> pérdida fantasma, una GANANCIA fantasma."*

## 2 · LA DECISIÓN DEL DUEÑO, YA TOMADA

**No publicar, y mandarlo a la cola de revisión.** Las dos mitades:

1. **La alerta no se emite** cuando el pico no es plausible. Un asesor no puede accionar sobre
   *"cayó 492.864%"*, y dejarlo visible le hace perder confianza en los otros 74 números, que
   están bien.
2. **La cuenta cae en la cola de admin** para que alguien mire el dato roto. Silenciar sin
   registrar sería esconder el problema.

## 3 · EL NÚMERO, MEDIDO — y por qué el umbral no es arbitrario

Sobre la copia de producción estampada, las 95 alertas de drawdown que quedan hoy:

```
pico >   5× la cartera actual :  21 alertas  (22 %)
pico >  10×                   :  21          ← EL MISMO CONJUNTO
pico >  50×                   :  14
pico > 100×                   :  11
```

**Entre 5× y 10× no hay un solo usuario.** Hay 21 alertas claramente fabricadas y 74
razonables, con un hueco vacío en el medio. El umbral no lo inventás vos ni yo: lo dicta la
forma de los datos. Elegí dónde cortar dentro de ese hueco y **dejá escrito el porqué con el
número al lado**, como hace el resto de este repo.

⚠️ **Medilo vos antes de tocar nada.** Si tu medición no reproduce estos números, algo cambió
y hay que entender qué antes de seguir.

## 4 · DÓNDE VA — y el precedente que ya existe

`backend/main.py:35715-35720`:

```python
if tv is not None and snap is not None and ms and ms["adj_mx"] >= 500:
    adj_now = tv - float(snap["net_deposited"] or 0)
    dd = (adj_now - ms["adj_mx"]) / ms["adj_mx"] * 100
    if dd <= -15:
        reasons.append({"kind": "drawdown",
                        "detail": f"Su ganancia cayó {abs(dd):.0f}% desde el mejor momento — conviene que lo llames"})
```

Fijate el `ms["adj_mx"] >= 500`, con su comentario: *"Piso USD 500 para no gritar drawdown
sobre resultados chiquitos"*. **Ya hay una cota de cordura ahí.** La tuya va al lado y es de la
misma naturaleza: el clamp no es un concepto nuevo en este archivo, es el segundo caso.

**La cola** es `@app.get("/api/admin/diagnose-reportes-basis")` (`main.py:17324`), que ya
devuelve `publicando_numeros_extremos` y `borde_contradice_la_cadena`. Sumá ahí lo que el clamp
silencie — o justificá por qué va en otro lado.

## 5 · CÓMO PENSARLO (esto importa más que el umbral)

**El clamp mide una RELACIÓN, no un valor absoluto.** "Más de un millón" no sirve: hay carteras
de un millón. Lo que no puede ser es que el pico sea 148.953 veces lo que la cartera vale hoy.
Elegí la relación que mejor exprese "esto no pudo pasar" y escribila.

⚠️ **Y cuidado con la dirección del error.** El repo ya avisa que el sesgo se da vuelta: no
todo dato roto produce una caída fantasma; algunos producen una **ganancia** fantasma. Si tu
clamp sólo mira drawdowns negativos, la mitad del problema queda afuera. Barré si el mismo dato
roto está publicando en otro lado con el signo invertido.

⚠️ **No arregles el dato.** No borres filas, no las corrijas, no las estampes distinto. El
clamp decide **qué se publica**, no qué está guardado. Corregir los snapshots es otro problema
—y otro riesgo— y no es esta ronda.

## 6 · 🔴 LO QUE NO SE PUEDE ROMPER

**Las 74 alertas plausibles tienen que seguir saliendo.** Un clamp que silencia de más es peor
que el bug: le apaga al asesor la herramienta que sí funciona. Medí cuántas sobreviven, antes
y después, y que sean las mismas.

**Y nada de lo anterior.** Certero bit-idéntico, el invariante estimado ⊇ certero, el eje
temporal, la suite en 29 fallas conocidas. Todo eso está commiteado y verificado: si tu cambio
lo mueve, no es tu cambio lo que está mal medido — es que tocaste de más.

## 7 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD dca5a79c, árbol limpio)
```

- ❌ NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ✅ Podés commitear encima: el árbol quedó limpio en `dca5a79c`, así que tu diff es sólo tuyo.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala).
- La suite corre: `python3 -m pytest tests/` (52 s), baseline **29 fallas conocidas** en
  `tests/fallas_conocidas.txt`; el hook de `conftest.py` avisa si aparece una nueva.
  ⚠️ Hay **una nueva que no es tuya**: `test_reporting.py::BuilderMetricsTest::test_live_value_overrides_for_current_period`
  fija el fin de período en `{mes}-28` y falla los días 29, 30 y 31. Verificado: falla también
  en el árbol anterior. Arreglala de paso (el `-28` por el último día del mes) o dejala anotada,
  pero no la metas en `fallas_conocidas.txt`: ese archivo no es una lista de perdón.

**Datos**: copia de producción **ya estampada** en `.../scratchpad/pico.db` — usá ésa, la cruda
no tiene `base`/`apto`. App local: `http://localhost:5199`,
`demo.metricas@rendi.test` / `demo1234`.

### Instrumento — nueve trampas que ya cobraron

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. `which` no es el inventario: hay PostgreSQL real vía el paquete pip **`pgserver`**.
5. Compará **CONJUNTOS de nombres**, nunca conteos.
6. Copiá el harness a un directorio tuyo antes de usarlo.
7. **Midiendo el gráfico, los dos chats se equivocaron siete veces**: selector que mezcla dos
   `.recharts-wrapper`, sesión expirada tomada por bug, contar `M`/`L` cuando Recharts dibuja
   con `C`, contar `dots`, contar un solo path, adivinar los nombres de las claves.
   Lo que funciona: leer `chartData` del fiber, o los ticks **acotados al primer wrapper**.
8. Comparar el `d` de los paths entre capturas no mide nada (ruido de 144 px en Y).
9. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.

## 8 · CRITERIO DE SALIDA

1. Ninguna alerta publica un drawdown cuyo pico sea implausible respecto de la cartera actual.
2. **Las 74 plausibles siguen saliendo** — medido, usuario por usuario.
3. Lo silenciado queda registrado en la cola de admin.
4. El umbral está escrito con su medición al lado, no como número suelto.
5. Sin fallas nuevas más allá de la del día 28.

## 9 · QUÉ ENTREGAR

1. Los cambios, con `file:line`.
2. La medición: cuántas alertas antes, cuántas después, cuáles se silenciaron y por qué.
3. Los conjuntos de tests, antes y después.
4. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito y sin maquillar.

## 10 · FUERA DE ALCANCE

- **La ruta de cobro sin tests**: `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:25939`). Migraron de proveedor y los
  tests no siguieron. Es el mayor riesgo no-medido que queda.
- `test_bond_conduit.py` — 640 donde se espera 720; el mejor candidato a bug real de las 29.
- **El POST del browser no tiene guarda de cobertura** (el cron sí): con precios rotos escribe
  un snapshot igual. Acotado — son 8 filas en producción y `browser` es INTRADIA/no-apto.
- ARS (necesita snapshots por broker), Postgres, Fases 3 y 4.
