# Contrato del sistema visual de Rendi

Este documento gobierna el frontend. Lo lee cualquier agente que trabaje sobre `frontend/`
y lo verifica `src/__design__/design-contract.test.js` en cada `npm test`.

## De dónde sale

Rendi tuvo dos generaciones de sistema visual:

- **La vieja** ("base de datos" / terminal): JetBrains Mono para números y rótulos, labels en
  MAYÚSCULA con tracking espaciado, `rounded-sm` (4px) como radio de contenedor, tablas densas.
- **La nueva** ("web de análisis", clean pass de julio 2026): Geist con `tabular` para números,
  rótulos sans sentence-case, cards `rounded-xl`, el átomo `Panel` como superficie.

El clean pass migró la mayor parte del producto pero **no llegó parejo**. La referencia viva de
la generación nueva son las páginas del Plan Asesor — `pages/Advisor*.jsx` y
`components/advisor/` — que tienen 0 usos de `font-mono` en sus 2.297 líneas de página.
Cuando dudes de cómo se ve algo nuevo, mirá ahí.

Lo que quedó atrás son las **tres pantallas bifurcadas por viewport** (Cartera, Movimientos,
Home): tienen un archivo `*Mobile.jsx` aparte que los rediseños estructurales no tocaron. El
commit que rediseñó Posiciones lo dice en su propio mensaje: `Mobile (PositionsMobile) no se toca.`
Ese es el problema que este contrato existe para no repetir.

---

## Las 7 reglas

### R1 — Los números van en Geist con `tabular`. Nunca en `font-mono`.

Aplica a montos, precios, porcentajes, variaciones, cantidades, contadores y cuotas, en
cualquier moneda y en cualquier superficie del producto.

**Trampa al migrar:** `index.css` aplica `font-variant-numeric: tabular-nums` a `.tabular`
**y a `.font-mono`** por igual. O sea: sobre un nodo `font-mono`, la clase `tabular` es hoy un
no-op, y en los nodos numéricos que *no* la llevan la alineación la está dando el propio mono.
**Sacar `font-mono` a secas hace que los dígitos empiecen a saltar.** Hay que agregar `tabular`
en el mismo movimiento. Son 24 de las 25 líneas de `Positions.jsx` y 13 de 13 de `ImportWizard.jsx`.

### R2 — Rótulos en sans sentence-case. Prohibido el par `font-mono` + `uppercase`.

Labels, eyebrows, badges, chips y headers de tabla.

**La MAYÚSCULA sola no está prohibida.** La generación nueva soltó el mono, no la mayúscula: el
Plan Asesor usa `uppercase` + `tracking` en al menos 6 lugares. Un guard que prohibiera
`uppercase` arrancaría en rojo sobre su propia referencia.

**Vía de escape que el guard no ve:** sacar la clase `uppercase` y escribir el texto a mano en
caps (`eyebrow="ANALYTICS"`) pasa el test sin cambiar un pixel. Se mira en el code review.

### R3 — El mono queda para meta técnica literal. La lista es cerrada.

1. Bloques de código: `<code>`, `<pre>`, `.blog-prose code/pre`
2. Atajos de teclado
3. Glifos de estructura que necesitan ancho fijo (el `└` que marca un lote)
4. IDs opacos y ordinales de fila del importador ("Fila 42")
5. El input de ticker mientras se tipea
6. Códigos de activo y de moneda (tickers)

Cualquier otro uso es deuda.

Los **tickers entran por decisión explícita**, no por descuido: la generación de referencia los
pone en mono en tres componentes compartidos que las propias páginas del asesor montan
(`CompositionDonut` la leyenda de todos los donuts, `AssetLogo` las iniciales de fallback,
`BookComposition`). Declararlos violación pondría al guard en contra del material que se usa
como norte. Si algún día se decide pasarlos a sans, se migran esos tres componentes
compartidos primero — no las hojas.

### R4 — La familia también se cambia por atributo, por estilo inline y por canvas.

`fontFamily`, `style.fontFamily` y `ctx.font` con un valor mono cuentan igual que la clase.
Son 22 usos que `grep font-mono` no ve: `ReturnsDiagram.jsx` (16, vía la constante `MONO`),
`utils/shareCard.js` (5 `ctx.font`) y `Heatmap.jsx` (1 `fontFamily="monospace"` sobre un
porcentaje).

**Acoplamiento a mirar a mano:** `shareCard.js` precarga los specs `12px "JetBrains Mono"`,
`13px` y `14px` con `document.fonts.load()`. Cambiar `FONT_MONO` sin tocar esos tres literales
exporta el PNG social en fallback, sin ningún error.

### R5 — La escala de radios es la que está declarada en `tailwind.config.js`.

```
xs 2  ·  sm 4  ·  DEFAULT 6  ·  md 6 (alias deprecado)  ·  lg 8
xl 12 ★  ·  2xl 16  ·  3xl 24  ·  full 9999
```

`xl` (12px) es **el radio de superficie de la generación nueva** — lo usa el átomo `Panel` y
todas las cards del asesor. Radios arbitrarios `rounded-[Npx]` prohibidos: si falta un paso, se
agrega a la escala.

Hasta la Fase 0 el config declaraba 3 pasos y afirmaba "Solo 3 pasos. Nada de 12/20/24px",
pero el bloque vive bajo `extend`, que **no** reemplaza la escala default de Tailwind: `md`,
`xl`, `2xl`, `3xl` y `full` seguían alcanzables y el código los usaba en 478 lugares,
empezando por el propio `Panel`. Se declaró la escala real. Los valores son los defaults de
tailwindcss 3.4.19 convertidos a px con root 16px, así que el cambio visual fue cero —
verificado clave por clave con `resolveConfig`. La única diferencia de comportamiento: los
radios ya no escalan con el font-size del navegador. Los tres pasos que ya estaban declarados
tampoco lo hacían, así que esto los vuelve consistentes.

`md` (6px) es **pixel-idéntico** a `DEFAULT`. Los 307 usos son deuda invisible: se migran a
`rounded` cuando se toque el archivo por otra razón, nunca en un barrido propio.

#### El borde de `Panel` no se pisa desde `className`. Hace falta `!`.

`Panel` emite siempre `bg-bg-1 border border-line rounded-xl` y **después** concatena tu
`className`. Eso engaña: uno escribe `<Panel className="border-data-violet/30">` y da por hecho
que gana el violeta porque va último en el atributo. **No gana.** Las dos son utilidades de
`border-color` con la MISMA especificidad (una clase), así que no decide el orden en el atributo
— decide **cuál aparece después en la hoja compilada**. Y Tailwind las emite en **orden
alfabético del nombre del color**:

```
.!border-data-violet/30   ← el `!` la saca del orden y le pone !important
.border-amber-500/30      ← pierde contra line
.border-data-violet/30    ← pierde contra line
.border-line              ← el default de Panel
.border-rendi-neg/30      ← gana, pero por casualidad alfabética
```

O sea: **todo color alfabéticamente anterior a `line` sale gris y nadie se entera.** No lo ve
ningún test, y el código "se lee" correcto.

El fix es el modificador important de Tailwind: `!border-data-violet/30`. Es el primer y único
`!` del repo a propósito — no es un idioma para usar en cualquier lado, es la salida para
*pisar un default que emite un átomo*. Único uso hoy: `More.jsx:98`.

**`Config.jsx:500` tiene HOY este bug sin arreglar**: pide `border-amber-500/30` y renderiza
gris. `Config.jsx:554` (`border-rendi-neg/30`) zafa sólo porque `rendi-neg` va después de
`line` en el alfabeto. Queda anotado, no arreglado.

Para re-verificarlo: `npm run build` y buscar en `dist/assets/*.css` el offset de cada
`.border-*` — el que aparece más adelante es el que pinta.

### R6 — No se bifurca por viewport.

Cero forks nuevos de `Página` → `PáginaMobile`. Lo responsive se resuelve con las variantes de
Tailwind (`sm:` / `md:`) o con un shell compartido que cambie sólo el contenedor — el patrón
de `Modal.jsx` y `AnalysisDrawer.jsx`, que existen justamente para evitar el fork.

**Si una tabla no entra en 375px, se rediseña la fila. No se escribe un segundo archivo.**

El modelo a copiar cuando mobile y desktop necesitan estructuras genuinamente distintas es
`Config.jsx`: `isMobile && !activeSection` muestra la lista, `isMobile && activeSection` muestra
el detalle, todo en un archivo, con una sola fuente de datos.

Por qué importa más que las otras seis: cada fork **duplica el costo de todas las demás reglas**.
Y no duplica sólo la vista — `PositionsMobile.jsx` no llama nunca a `computeBrokerValue()`,
reimplementa unas 110 líneas de valuación a mano. El fork por viewport se convirtió en un fork
del motor de números.

### R7 — El comentario de cabecera de un átomo es parte del contrato.

Si un componente cambia de tipografía, de radio o de tratamiento de label, su comentario se
actualiza **en el mismo commit**. Un comentario que describe el sistema anterior es un bug: el
próximo que lo lea para copiar el patrón va a reintroducir la generación vieja creyendo que
hace lo correcto.

Fósiles corregidos en la Fase 0: `StatCard` prometía "Instrument Serif italic" (una fuente que
ya no existe en el repo) y "labels en mono uppercase"; `Panel` decía "Radius default = 6px"
mientras renderiza `rounded-xl`; `PageHeader` prometía un eyebrow "uppercase mono" mientras
renderiza sans violeta; `Pill` y `MoversRail` igual.

En el mismo movimiento se renombró la clase de label de KPI de `index.css`. Se llamaba
**`.label-mono`** y desde el clean pass emitía sans: el nombre hacía que toda búsqueda de restos
del sistema viejo devolviera 19 falsos positivos apuntando justo a lo ya migrado. Ahora es
**`.kpi-label`**. No se eligió `.label` a secas porque `\blabel\b` matchea dentro de
`tracking-label` (token real del config), `aria-label` (129 usos) y `<label>` (134): habría
cambiado un señuelo por uno peor.

---

## El guard

```bash
npm test                                    # lo corre junto con el resto de la suite
node scripts/gen-design-baseline.mjs        # dry-run: muestra los totales y el delta
node scripts/gen-design-baseline.mjs --write # reescribe el baseline
```

- **Contrato:** este archivo.
- **Patrones y walker:** `scripts/design-patterns.mjs` (vive fuera de `src/` a propósito: si
  estuviera adentro, el walker contaría sus propios literales).
- **Baseline:** `src/__design__/design-baseline.json`.
- **Test:** `src/__design__/design-contract.test.js`.

Falla si un conteo **sube** (violación nueva) y también si **baja** (una mejora tiene que
quedar registrada, no gastarse como presupuesto silencioso para violaciones futuras). Bajar es
bienvenido: se corre el generador con `--write` en el mismo commit que hizo la mejora.

Un archivo que no está en el mapa cuenta como 0, y el test **itera el árbol**, no el mapa: un
archivo nuevo con 40 `font-mono` falla aunque nadie lo haya agregado al JSON.

### Los dos huecos, declarados

1. **Compensación intra-archivo.** El conteo es por archivo: borrar un `font-mono` y agregar
   otro en el mismo archivo pasa. Es el precio de no romperse cada vez que se mueven líneas.
   El guard existe para frenar la expansión a archivos nuevos, no para auditar cada línea.

2. **Los átomos propagan mono por prop.** `DataRow` tiene `const fontClass = mono ? 'font-mono' : ''`
   y 6 call-sites lo activan sin escribir la string. Lo mismo `AssetTypeBadge`, `AssetLogo`,
   `StatCard`. Esos llamadores puntúan 0 y renderizan mono. No es resoluble por grep.

---

## Estado de la deuda (Fase 0, 2026-08-28)

| categoría | regla | total | qué es |
|---|---|---|---|
| `mono_clase` | R1/R3 | 341 | todos los `font-mono`. Landing 58, Positions 25, InsightEvidence 21 |
| `mono_uppercase` | R2 | 71 | el par prohibido. Landing 45, Wrapped 11 |
| `mono_inline` | R4 | 22 | el canal ciego (SVG + canvas) |
| `mono_css` | R1/R3 | 3 | los `@apply` de index.css (2 legítimos, 1 violación) |
| `rounded_md` | R5 | 307 | deuda pixel-invisible |
| `rounded_2xl_3xl` | R5 | 19 | curvas grandes, mayormente sheets mobile |
| `rounded_arbitrario` | R5 | 9 | los `rounded-[2px]`, migrables a `rounded-xs` |
| `upper_inline` | R2 | 10 | los de `ReportPublic.jsx`, contenidos a propósito |
| `fork_viewport` | R6 | 3 | Home · Operations · Positions |
| `paginas_mobile` | R6 | 4 | los 3 gemelos + `PositionDetailMobile` (ruta propia) |
| `clase_renombrada` | R7 | 0 | congelada: el nombre viejo no vuelve |
| `comentarios_fosiles` | R7 | 0 | congelada: los 7 fósiles conocidos, muertos |
| `fork_ternario` | R6 | 0 | congelada: la variante que todavía no existe |

**`Landing.jsx` no se migra.** Es la única superficie que ve un visitante sin sesión, el look
terminal ahí es deliberado (chrome de ventana simulada, marquee de brokers, tabla demo con
`grid-cols` fijas donde cambiar de familia trunca fechas y tickers), y al menos 5 de sus 58
usos ni siquiera son violación bajo R3. Entra al baseline como deuda congelada, **no como
allowlist por archivo**: si se allowlisteara, se podrían agregar violaciones nuevas justo donde
más deuda hay.

## Antes de un barrido de migración

Dos cosas que no rompen ningún test y por eso fallan en silencio:

- **La alineación.** Ver la trampa de R1: sacar `font-mono` sin agregar `tabular` desalinea.
- **Los anchos fijos calibrados al avance uniforme del mono.** Hay al menos 10 sitios con riesgo
  real de clipping: `Wrapped.jsx` (`w-12`, `w-16`), `PerformanceCalendar.jsx`
  (`min-w-[52px]`, `min-w-[80px]`), `AllocationBars` y `CompositionByAsset` (`w-9`),
  `WeekCard` (`min-w-[80px]`), `ImportWizard` (`w-14`), `TickerSearch` (`max-w-[8rem] truncate`)
  y la tabla demo de `Landing.jsx` (`grid-cols-[80px_60px_1fr_80px]`).

Ningún test referencia `font-mono`, `tabular` ni `rounded`. El daño de un find-replace sería
silencioso.
