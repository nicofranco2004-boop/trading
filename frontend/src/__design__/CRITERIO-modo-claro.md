# Modo claro — el criterio de qué NO tocar

Escrito antes de rehacer el trabajo sobre `origin/main` (fb9c7b96), el 2026-09-15.
El barrido de tokens se re-aplica corriendo los mismos pasos. Esto no: es lo que se
decidió **dejar quieto**, y por qué. Sin esta lista, el rehacer toca de más.

---

## La regla que gobierna todo

**El modo oscuro es lo que ven todos los usuarios hoy. Cambio visual CERO en oscuro,
salvo lo declarado abajo.** Cada vez que una migración "obvia" cambiaba un pixel del
oscuro, se descartó.

---

## NO TOCAR — 1. Los `dark:` que son ajustes de opacidad, no deuda

De los 257 `dark:` sobre tokens del sistema, **147 tienen un par claro con distinta
opacidad**:

    bg-bg-2 dark:bg-bg-2/40        border-line/80 dark:border-line/50
    bg-bg-2 dark:bg-bg-1/40        divide-line/50 dark:divide-line/40

Eso NO es deuda: es el mismo color, más translúcido en oscuro que en claro, a
propósito. **Sacarles el prefijo cambia el oscuro.** Se dejan.

Los tres patrones que SÍ se tocaron, y sólo esos:

| patrón | cuántos | por qué es seguro |
|---|---|---|
| `X dark:X` idéntico | 29 | el mismo valor en los dos temas: ruido puro |
| `bg-white dark:bg-bg-1` | 30 | `bg-1` claro **es** `#FFFFFF`: idéntico en ambos |
| `bg-white dark:bg-bg-2` | 47 | oscuro idéntico; en claro pasa a gris de superficie |

## NO TOCAR — 2. Los `dark:` sobre colores legacy que tienen par completo

141 casos tipo `text-amber-600 dark:text-amber-400`, `text-emerald-600 dark:text-emerald-400`.
Son del sistema anterior pero **funcionan bien en los dos temas**. Migrarlos a tokens
cambiaría colores en oscuro sin ganar nada. Se dejan.

## NO TOCAR — 3. Los `bg-white` que son blanco de verdad

Quedan 8 y los 8 son deliberados. No son tema, son objetos blancos:

- `AssetLogo.jsx`, `PfFormModal.jsx`, `AdvisorDashboard.jsx` → el fondo blanco **detrás
  del logo de una empresa** (los logos vienen con fondo transparente).
- `BriefPrefs.jsx`, `MarketBriefPrefs.jsx` → **la perilla de un interruptor**, blanca
  en los dos temas.
- `InsightChip.jsx` → `hover:bg-black/5 dark:hover:bg-white/5`, el par correcto.

## NO TOCAR — 4. `text-ink-0 dark:text-white` (17 casos)

En oscuro rinde blanco puro; el token rinde `#E6EAF2`. Sacarlo es un cambio visual
para todos. En claro **ya usa `text-ink-0`, que es lo correcto**, así que no es el bug.

## NO TOCAR — 5. El verde de WhatsApp `#25D366`

Marca de terceros: no es un token y no se reemplaza por uno. ⚠️ Pero sobre blanco da
**2,2:1** — el botón "Escribirle" se va a leer mal en claro. Necesita **una variante
oscura propia para claro**, no el token de la app. Pendiente, anotado.

## NO TOCAR — 6. `utils/shareCard.js`

Es `<canvas>`: no resuelve `var()`. Decisión de producto: **la imagen que se comparte
en redes queda oscura siempre**, para que la marca se vea igual en el feed de todos.
Si algún día hay que pintarla, existe `resolvePolarity()`.

## NO TOCAR — 7. `Landing.jsx`

Deuda congelada por el contrato del repo (`frontend/CLAUDE.md`): su look terminal es
deliberado y es la única superficie que ve un visitante sin sesión.

## NO TOCAR — 8. Las escalas de 9 pasos del config (`green-50..800`, `red-50..800`)

Siguen siendo hex fijos **a propósito**. Son rampas de heatmap, y una rampa no se
arregla cambiándole valores: hay que recorrerla al revés. Eso lo resuelve
`polarityScale.js`, no el config.

## NO TOCAR — 9. `value-pulse` en `index.css`

Usa `green-200` (#5FE19D), un paso de la escala de 9. Mismo caso que arriba. Además
lo usa el mock de la Landing, que es oscura siempre.

---

## LOS CORTES DE LA RAMPA NO SE UNIFICAN

`CORTES_DIA = {plano: 0.05, pasos: [0.5, 1]}` y `CORTES_MES = {plano: 0.5, pasos: [2, 5]}`.

Unificarlos parece limpieza y es **el bug opuesto**: un día que se movió 2 % es un día
fuerte; un mes que rindió 2 % es un mes tibio. La rampa es una; los cortes son varios,
y cada uno lleva su propio umbral de "plano".

---

## LO QUE SÍ CAMBIÓ EN OSCURO — los tres, declarados

Si al rehacer alguno de estos "no hace falta", es que se perdió el motivo:

1. **`--pol-up-2-ink`: `#E6EAF2` → `#06160E`.** Sobre `#14A560` daba **2,65:1**, por
   debajo del mínimo legible de 4,5. Los meses de +2 % a +5 % del calendario venían con
   el texto mal contrastado en oscuro desde siempre. Con la tinta oscura da 5,83.
   El guard `theme-tokens.test.js` lo congela.

2. **Los `::marker` del blog y de `.advisor-note` en `index.css`.** Tenían un comentario
   que nombraba un token y un valor que no era ese token (`rgb(125 133 144)` rotulado
   "ink-3", que es `90 100 120`; `157 140 255` rotulado "data-violet", que es
   `139 125 255`). El segundo importaba: sobre blanco daba **2,9:1** en un link.

3. **Los números de los ejes de los gráficos: `#7C8698` → `ink-2`.** `#7C8698` no
   pertenecía a la paleta. `ink-2` mejora el contraste en oscuro (7,44 contra 5,5).

---

## TRAMPAS TÉCNICAS QUE HAY QUE VOLVER A RESPETAR

1. 🔴 **Las variables CSS van en CANALES (`7 9 12`), nunca en hex.** 1.937 usos con
   opacidad (`bg-bg-2/40`) dependen de eso. Con un hex adentro, Tailwind compone CSS
   inválido y **el navegador descarta la declaración entera sin ningún error**.

2. **El lock del modo claro vive en DOS archivos** y se cambian juntos:
   `LIGHT_MODE_LOCKED` en `ThemeContext.jsx` y en el script de `index.html`. Si se saca
   de uno solo: o la app parpadea en cada carga, o las cuentas con `rendi_theme=light`
   guardado de la época vieja arrancan del color equivocado.

3. **El verde y el rojo se parten en dos tokens**: `-pos`/`-neg` para TEXTO (legibles)
   y `-pos-fill`/`-neg-fill` para RELLENO. En oscuro valen lo mismo; en claro el verde
   vivo como texto da 2,03:1.

4. **Los parsers de estos guards leen texto crudo, comentarios incluidos.** Un comentario
   que cita `var(--x)` hace que el test salga a buscar una variable llamada `--x`.

---

## AVISO DE LA OTRA SESIÓN (separadores es-AR) — dónde se cruza con esto

Tres lugares donde un cambio cosmético rompe sin dar error:

1. **Coordenadas SVG** en `Sparkline.jsx`, `MiniSparkline.jsx`, `AssetMiniChart.jsx` y
   `ReportPublic.jsx`: ahí la coma separa coordenadas del dibujo.
   → El barrido de color **no toca** los tres primeros. `ReportPublic.jsx` sí está en
   la lista de F2 pendiente: **mirar a mano**, no barrer.
2. **Valores CSS interpolados** (`` style={{ width: `${pct}%` }} ``): el punto decimal es
   obligatorio.
3. **Código que parsea un string que otro formateó.** Acá aplica a `resolvePolarity()`,
   que lee el valor de una variable CSS (`"27 34 48"`) y lo convierte a `rgb(...)`. Si
   alguien cambia el formato de las variables, se rompe. El guard vigila el formato.
