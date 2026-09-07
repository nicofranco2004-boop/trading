# EL CONSEJO QUE NO SE PUEDE SEGUIR

Sos el chat IMPLEMENTADOR. La ronda anterior está **commiteada en `c1fe78f0`** (sin pushear) y
**auditada por ejecución**: los cuatro cambios hacen lo que dicen y no rompieron nada.

Esta ronda es **una condición**. Cero lógica, cero cálculo, cero backend. Es corta de verdad.

---

## 0 · LO QUE YA ESTÁ VERIFICADO — no lo vuelvas a hacer

El auditor reprodujo tus mediciones con su propio instrumento, sobre la app corriendo:

| Qué | Resultado |
|---|---|
| ARS · chips / frases | 1 / **1** (era 1 / 0) ✅ |
| USD · chips / frases | 2 / **1** — sin duplicar ✅ |
| ARS · contraste del apagado | **3,16:1** (era 1,67) ✅ |
| USD · toggle | clases **byte-idénticas**, `disabled:false`, títulos originales, 5,17 / 3,16 ✅ |
| ARS · modo que se pide | `?bench=inflation_ar&modo=certero` ✅ |
| Backend | 29 fallas / 3.701 pasan · conjunto **idéntico** (0 nuevas, 0 desaparecidas) ✅ |
| Frontend | 50 archivos / 1.351 pasan · `vite build` ✓ ✅ |

Y **tres de tus seis "no verifiqué" quedan cerrados**, medidos o demostrados:

- **El wrap en 375 px con la frase en su nueva casa: no desborda.** A/B en el mismo viewport
  (USD = fila sin frase, ARS = con frase, mismo código): overflow de página **0 px**, de la fila
  **0 px**, la frase no se sale de la tarjeta. Lo único que pasa es que el encabezado crece de
  **53 px a 119 px** de alto. Y el `<h2>` ya envolvía **antes** del cambio (91 px vs 79 px de
  ancho, 48 px de alto en los dos), así que eso no lo causaste vos.
- **La rama `contable` es INALCANZABLE en pesos.** `twr.py:1275` y `:1708`:
  `base_del_twr = 'contable' if modo == MODO_ESTIMADO else 'mercado'`. En ARS el modo es siempre
  certero, así que esa rama no se puede dar. No la cubras.
- **"Exactamente una frase" no es una coincidencia, es estructural.** Los dos call sites leen
  `chipPerfVisible` —la misma variable, en el mismo render—: `{chipPerfVisible && …}` en uno y
  `explica={!chipPerfVisible}` en el otro. No hay estado intermedio posible donde aparezca dos
  veces. Tu punto 6 está cerrado por construcción.

**Lo que sigue abierto de tu lista**: nadie vio nada con los ojos, y tu tercera rama de
`ChipMedido` —la que sí es alcanzable en pesos— resultó tener un problema. Es esta ronda.

---

## 1 · 🔴 EL HALLAZGO: la pantalla aconseja algo que ella misma prohíbe

`ChipMedido` tiene tres ramas de retorno. Vos lo dijiste: la frase vive sólo en la última. La del
medio —`Insights.jsx:1027`, `if (!perf.medido_desde)`— dibuja **"Sin mediciones todavía"**, y su
tooltip dice, en `Insights.jsx:1036-1038`:

```jsx
{modoPerf === 'certero' && (
  <p className="text-ink-3">Probá el modo <strong>Estimado</strong>: incluye
     tu historia contable, que es aproximada pero te deja ver la forma.</p>
)}
```

**En pesos `modoPerf` es SIEMPRE `'certero'`** —está medido arriba, la request sale con
`modo=certero`, y el toggle está deshabilitado así que no se puede cambiar—. O sea que esa
condición es **siempre verdadera en ARS**, y el usuario lee *"Probá el modo Estimado"* con el
botón **Estimado gris y `cursor-not-allowed` a diez píxeles de distancia**.

### 1.1 · A cuántos les pasa

```sql
-- sobre pico.db (copia de producción estampada), sqlite3 en modo lectura
SELECT COUNT(DISTINCT b.user_id) FROM brokers b
WHERE COALESCE(b.currency,'ARS')='ARS'
  AND NOT EXISTS (SELECT 1 FROM snapshots s WHERE s.user_id=b.user_id AND s.apto=1);
```

```
usuarios con broker             854
   … con broker en pesos        758   (el 89% que ya conocíamos)
   … sin NINGUNA fila apta      449   → `medido_desde` sale None (twr.py:1226)
   ── INTERSECCIÓN ──           184   ← les pasa a éstos, siempre
```

**184 usuarios.** No es un borde: es uno de cada cinco.

### 1.2 · Y lo creó esta ronda — que es la parte interesante

Antes, en pesos el toggle **no se dibujaba**. El consejo apuntaba a un control que no existía:
inútil, pero invisible. Ahora el control está en pantalla, apagado y legible a 3,16:1 —
justamente porque la ronda anterior lo hizo visible a propósito.

**Hacer visible un control volvió visible una contradicción que ya estaba escrita.** No es una
regresión: es la misma clase de hallazgo que las trece rondas anteriores —el texto y el estado
no se hablaban— y esta vez el que lo destapó fue tu propio arreglo.

⚠️ **Esto NO se arregla habilitando el toggle en pesos.** El gate es correcto y está justificado:
en ARS el estimado no se puede construir hoy y arreglarlo necesita snapshots por broker, que es
un cambio de modelo de datos. Lo que sobra es el consejo, no el gate.

### 1.3 · Qué hacer

Que el consejo aparezca **sólo cuando el modo Estimado se puede usar**. La condición hoy es
`modoPerf === 'certero'`; le falta la otra mitad — que el toggle no esté deshabilitado.

Y decidí qué le decís al usuario de pesos **en su lugar**, porque hoy se queda sin ninguna
salida: no hay curva, no hay explicación de qué hacer, y el único camino que el texto le ofrecía
está cerrado. Un renglón alcanza. Lo que **no** puede pasar es que se quede con el cartel
"Sin mediciones todavía" y nada más — sería el vacío sin explicación de siempre, otra vez.

⚠️ **No inventes fechas ni plazos** (regla de las dos rondas anteriores, sigue vigente).

## 2 · 🔴 LO QUE NO SE PUEDE ROMPER

**En USD el consejo tiene que seguir apareciendo tal cual.** Ahí el toggle está habilitado y
"Probá el modo Estimado" es exactamente el consejo correcto. Medilo en las dos monedas.

**Nada de lógica.** Si te encontrás editando `twr.py`, `performance.py`, `insightsModel.js`,
`evolution.js` o cualquier cálculo, **parate**.

**Y lo deployado + lo de las dos rondas anteriores**: certero bit-idéntico · estimado ⊇ certero ·
el clamp 95→71 · el eje temporal · una frase por pantalla en las dos monedas · el toggle de USD
byte-idéntico · la suite en **29 fallas conocidas**.

## 3 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD c1fe78f0, árbol limpio)
origin/main sigue en e3ab0b0f — nada de esto está deployado.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (`file:…?mode=ro`).
- La suite: `python3 -m pytest tests/` (≈54 s). Frontend: `npx vitest run` + `npx vite build`.

### Cómo pararte en el caso de los 184

`medido_desde` es `aptos[0]["date"] if aptos else None` (`twr.py:1226`). Para reproducir la rama
necesitás una cuenta **sin una sola fila con `apto=1`**. La demo no sirve tal cual: tiene
mediciones. Armate el caso (una copia de la demo con las filas aptas fuera, o un usuario de
`pico.db`) y **decí cuál usaste**. Si no podés reproducirlo en pantalla, decilo — pero entonces
la condición se verifica leyendo el render, no suponiendo.

### Instrumento — trece trampas que ya cobraron

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. Compará **CONJUNTOS de nombres**, nunca conteos.
5. Y extraé el conjunto con **`^FAILED ` anclado**: el log tiene líneas propias que empiezan con
   `ERROR ` y el auditor contó 43 donde había 29.
6. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.**
7. **Verificá ANTES de commitear**, no después.
8. **El panel del browser no se puede usar para capturas.** Confirmado tres veces, en los dos
   chats: pinta una vez después de `navigate` y después el input muere con *"the Browser pane is
   currently hidden"*. `javascript_tool` para leer el DOM **sí** funciona siempre. Medí por DOM.
9. Midiendo el gráfico por DOM los dos chats se equivocaron **siete** veces (selector que mezcla
   dos `.recharts-wrapper`, sesión expirada tomada por bug, contar `M`/`L` con curvas `C`,
   contar `dots`, un solo path, adivinar claves). Leé `chartData` del fiber.
10. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.
11. **Un número sin su consulta no es reproducible.** Si pasás una medición, pasá la query.
12. `which` no es el inventario: hay PostgreSQL real vía el paquete pip `pgserver`.
13. 🆕 **Una A/B vale más que un "antes" recordado.** El wrap en mobile se pudo cerrar porque USD
    y ARS son, en la misma pantalla y el mismo código, el estado sin frase y el estado con frase.
    Antes de reconstruir un "antes", fijate si ya lo tenés al lado.

**Datos**: `pico.db` en el scratchpad. App local: `http://localhost:5199`,
`demo.metricas@rendi.test` / `demo1234`. Para pararte en pesos:
`localStorage.setItem('rendi_display_currency','ARS')` y recargar — en `/analisis` no hay
selector de moneda.

## 4 · CRITERIO DE SALIDA

1. En pesos, la pantalla **no aconseja** un modo que no se puede usar.
2. En pesos, el usuario sin mediciones **igual se lleva una explicación** — no un cartel mudo.
3. En USD el consejo sigue **igual**, medido.
4. Una frase por pantalla en las dos monedas — la propiedad de la ronda anterior, sin moverse.
5. Sin fallas nuevas; `fallas_conocidas.txt` no crece. `vite build` limpio.

## 5 · QUÉ ENTREGAR

1. Los cambios, con `file:line`.
2. Cómo reprodujiste el caso de los 184 (o por qué no pudiste).
3. La medición en las dos monedas.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"**. Las dos últimas fueron buenas: de los seis puntos de la anterior,
   tres se pudieron cerrar **porque los dejaste escritos**. Seguí haciéndolo.

## 6 · FUERA DE ALCANCE

- 🔴 **La ruta de cobro sin tests** — `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:~25939`). **Es lo que debería venir
  después de esta ronda**: es plata, no tiene cobertura desde que migraron de proveedor, y sólo
  se supo porque se recuperó la suite.
- `test_bond_conduit.py` — 640 donde se espera 720.
- El POST del browser sin guarda de cobertura (el cron sí la tiene).
- **Snapshots por broker** — lo que habilitaría el estimado en ARS de verdad. Proyecto, no ronda.
- Postgres, Fases 3 y 4.
