# LA FRASE NO LLEGÓ AL 89 %

Sos el chat IMPLEMENTADOR. La ronda anterior está **commiteada en `971c7522`** (sin pushear) y
**auditada por ejecución**: el diff hace lo que dice y no rompió nada. Esto es el remanente.

Ronda corta: **copy y una clase**. Cero lógica, cero cálculo, cero backend.

---

## 0 · LO QUE YA ESTÁ BIEN — no lo vuelvas a hacer

Todo esto lo verificó el auditor corriendo, no leyendo. Está cerrado:

| Qué | Cómo se midió | Resultado |
|---|---|---|
| USD queda idéntico | `getComputedStyle` + `.disabled` + `.title` sobre los dos botones | `disabled:false`, títulos originales, clases **exactas** de antes |
| ARS dibuja el toggle apagado | ídem, con `rendi_display_currency='ARS'` | 2 botones, `disabled:true`, `cursor-not-allowed`, motivo en el `title` |
| El modo que se pide en ARS | `performance.getEntriesByType('resource')` | `?bench=inflation_ar&modo=certero` ✅ |
| Backend | `python3 -m pytest tests/` | **29 fallas / 3.701 pasan**; conjunto de nombres **idéntico** a `fallas_conocidas.txt` (0 nuevas, 0 desaparecidas) |
| Frontend | `npx vitest run` · `npx vite build` | 50 archivos / **1.351 pasan** · build ✓ en 3,12 s |
| Wrap en mobile (375 px) | viewport emulado + `scrollWidth − clientWidth` | **0 px de overflow**, la frase envuelve dentro de 269 px |

Y dos cosas de la lista "QUÉ NO VERIFIQUÉ" quedan **resueltas, no pendientes**:

- **El tema claro no existe.** `contexts/ThemeContext.jsx` tiene `LIGHT_MODE_LOCKED = true` y el
  provider devuelve `dark: true` fijo. No hay nada que probar ahí.
- **Las capturas fallan por el entorno, no por vos.** El auditor reprodujo lo mismo: el panel
  pinta una vez inmediatamente después de `navigate` y después devuelve negro, y el input muere
  con *"the Browser pane is currently hidden"*. No lo arregles; está anotado abajo.

- **El riesgo de modo pegado no existe.** El control de moneda vive sólo en Dashboard, Config y
  Positions (`grep -rn CurrencyToggle\\\|CurrencyRail`), no en `/analisis`. Cambiar de moneda
  desmonta Insights, así que `modoPerf` vuelve a `'certero'` y el tooltip de pesos —*"lo que
  estás viendo acá es la medición a precio real"*— **dice la verdad**. Verificado en la request.

---

## 1 · 🔴 EL HALLAZGO: en pesos el chip sigue desnudo

La ronda anterior tenía dos mitades. La de ARS llegó. **La del chip no llegó a los usuarios de
ARS — que son justo el 89 %.**

Medido en la app corriendo, con `rendi_display_currency='ARS'`:

```
chips "Medido desde …" en pantalla : 1   → "Medido desde 11/07/2026"
                        …en la tarjeta : "Curva de drawdown"
frase "No perdiste historial…"     : 0   ← NO ESTÁ EN NINGÚN LADO
```

Y en USD, la misma medición:

```
chips  : 2   → "Cartera vs S&P 500 (USD)"  y  "Curva de drawdown"
frases : 1   → sólo en "Cartera vs S&P 500 (USD)"
```

**Por qué pasa** — hay dos call sites de `ChipMedido` y sólo uno lleva `explica`:

| línea | call site | ¿gateado a USD? | ¿lleva la frase? |
|---|---|---|---|
| `Insights.jsx:2922-2923` | tarjeta de Performance | **sí** (`currency === 'USD' &&`) | sí (`explica`) |
| `Insights.jsx:3141` | encabezado de "Curva de drawdown" | **no** | no |

En USD el razonamiento que escribiste es correcto y está medido: dos chips, una frase, la
segunda sería ruido. **En ARS el de Performance no se dibuja, así que el del drawdown es el
ÚNICO chip de la pantalla — y es el que no explica nada.**

O sea: la fecha pelada que hizo pensar al dueño que había perdido su historia sigue en pantalla,
sola, para 758 de 854 usuarios. La condición "sería duplicada" es falsa exactamente donde más
falta hace.

### 1.1 · Qué hacer

Que `explica` deje de depender del call site y pase a depender de **si es el único chip de la
pantalla** — o, dicho al revés y más simple: que la frase acompañe al chip cuando el de
Performance no se está dibujando.

⚠️ **No dupliques la frase en USD.** El criterio sigue siendo: **exactamente una** en pantalla.
Demostralo con la misma medición de arriba, en las dos monedas.

⚠️ **No saques el gate de `:2922`.** No es el que sobra: el chip de Performance describe la
serie de Performance, que en ARS no existe. Lo que hay que mover es la frase, no el chip.

## 2 · 🟡 EL CONTROL APAGADO SE DIBUJA A 1,67:1

Medido en la página, componiendo los fondos reales hasta el primer opaco y aplicando la fórmula
de contraste de WCAG:

```
ARS · deshabilitado   rgb(52,59,72)  sobre rgb(14,18,24)   1,67:1   ← 11 px
USD · no seleccionado                                       3,16:1
USD · seleccionado    blanco sobre bg-blue-600              5,17:1
```

La clase es `text-ink-3/50`: media opacidad sobre un token que ya arranca bajo.

**No es un bug de cumplimiento** — WCAG exime a los controles deshabilitados. Pero el objetivo
declarado de la ronda era *"que el usuario se entere de que el modo existe"*, y ese control se
está dibujando a **la mitad del contraste del estado habilitado más tenue, en 11 px**. Un
control que nadie ve es el vacío de antes con más HTML.

Y hay una ironía que vale citar: `ThemeContext.jsx` mantiene el tema claro bloqueado hasta
*"validar contraste WCAG AA para cada par bg/text"*. El par nuevo entró sin esa validación.

**Qué hacer**: subilo hasta que se lea. `text-ink-3` pelado (3,16:1) ya sería el doble y sigue
leyéndose como apagado, porque quien comunica el estado es el `cursor-not-allowed` + la ausencia
de la píldora azul, no la opacidad. **Medilo y dejá el número escrito**, como el resto del repo.

**Y una decisión que es del dueño, no tuya** (anotala, no la ejecutes): con el toggle apagado,
**ninguno** de los dos botones se ve seleccionado, porque la rama deshabilitada del ternario
pisa el `bg-blue-600`. El usuario en pesos ve dos grises iguales y no sabe cuál rige. Hoy lo
salva el tooltip, que dice cuál. Si querés proponer algo, proponelo — pero no lo cambies solo.

## 3 · 🔴 LO QUE NO SE PUEDE ROMPER

**Nada de lógica.** Esta ronda toca una condición de render y una clase de color. Si te
encontrás editando `twr.py`, `performance.py`, `insightsModel.js`, `evolution.js` o cualquier
cálculo, **parate**: estás arreglando el lugar equivocado.

**El toggle en USD sigue byte-idéntico.** Está medido arriba con su método; reproducilo después
de tu cambio. Si una clase de USD se mueve, no es aceptable "se ve igual".

**Y lo deployado**: certero bit-idéntico · estimado ⊇ certero · el clamp 95→71 · el eje temporal
· la suite en **29 fallas conocidas** (`tests/fallas_conocidas.txt`).

## 4 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark   (HEAD 971c7522, árbol limpio)
origin/main sigue en e3ab0b0f — lo tuyo NO está deployado.
```

- ❌ **NO pushees.** ✅ Podés commitear encima.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala).
- La suite: `python3 -m pytest tests/` (≈53 s). Frontend: `npx vitest run` + `npx vite build`.

### Instrumento — doce trampas que ya cobraron en este proyecto

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — falla y devuelve exit 0 sin correr nada.
3. `git diff --stat` mide contra HEAD, no contra el estado previo a tu ronda.
4. Compará **CONJUNTOS de nombres**, nunca conteos.
5. 🆕 **Y extraé el conjunto con `^FAILED `, anclado.** El auditor usó
   `grep -E "^(FAILED|ERROR) "` y le dieron **43 fallas donde había 29**: el log de la corrida
   tiene líneas propias que empiezan con `ERROR ` (`ERROR billing.subscriptions:…`). Un
   comparador de conjuntos con un extractor sucio miente igual que un conteo.
6. **Nunca copies archivos de un sandbox al worktree para "aplicar" un merge.** El auditor lo
   hizo: pisó `main.py`, se llevó funciones de producción y commiteó marcas de conflicto.
   Resolvé SIEMPRE en el lugar.
7. **Verificá ANTES de commitear**, no después.
8. 🆕 **El panel del browser**: la única secuencia que pinta es `navigate` → `wait` → `screenshot`
   **en un solo batch**. Un `scrollIntoView` por `javascript_tool` en el medio lo deja en negro,
   y a partir de ahí el input muere con *"the Browser pane is currently hidden"*. Lo que **sí**
   sigue funcionando siempre es `javascript_tool` para leer el DOM. Medí por DOM y no pelees con
   los píxeles.
9. Midiendo el gráfico por DOM los dos chats se equivocaron **siete** veces: selector que mezcla
   dos `.recharts-wrapper`, sesión expirada tomada por bug, contar `M`/`L` cuando Recharts usa
   `C`, contar `dots`, contar un solo path, adivinar nombres de claves. Lo que funciona: leer
   `chartData` del fiber, o los ticks **acotados al primer wrapper**.
10. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.
11. **Un número sin su consulta no es reproducible.** El auditor pasó «21 alertas» sin decir cómo
    lo medía; el implementador midió 24 y no pudo reconciliar. Las dos eran correctas.
12. `which` no es el inventario del entorno: hay PostgreSQL real vía el paquete pip `pgserver`.

**Datos**: copia de producción estampada en `.../scratchpad/pico.db`. App local:
`http://localhost:5199`, `demo.metricas@rendi.test` / `demo1234`. Para pararte en pesos:
`localStorage.setItem('rendi_display_currency','ARS')` y recargar — en `/analisis` no hay
selector de moneda.

## 5 · CRITERIO DE SALIDA

1. En **ARS**, el chip que está en pantalla lleva la explicación. Medido: `frases ≥ 1`.
2. En **USD**, sigue habiendo **exactamente una** frase. Medido, no leído.
3. El contraste del control apagado, medido y escrito, con el número al lado.
4. USD byte-idéntico en el toggle — reproducí la medición del §0.
5. Sin fallas nuevas; `fallas_conocidas.txt` no crece. `vite build` limpio.

## 6 · QUÉ ENTREGAR

1. Los cambios, con `file:line`.
2. Las dos mediciones de chips/frases (ARS y USD), con el script que usaste.
3. El contraste, antes y después.
4. Los conjuntos de tests, antes y después.
5. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito. (El de la ronda pasada estuvo bien hecho: dos
   de sus cuatro puntos se pudieron cerrar justamente porque los dejaste escritos.)

## 7 · FUERA DE ALCANCE

- 🔴 **La ruta de cobro sin tests** — `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:~25939`). Migraron de proveedor y los
  tests no siguieron. **Sigue siendo el mayor riesgo no medido del repo.**
- `test_bond_conduit.py` — 640 donde se espera 720.
- El POST del browser sin guarda de cobertura (el cron sí la tiene).
- **Snapshots por broker** — lo que habilitaría el estimado en ARS de verdad. Proyecto, no ronda.
- Postgres, Fases 3 y 4.
