// El chrome de los gráficos — grilla, ejes, globo de datos, series.
// ═══════════════════════════════════════════════════════════════════════════
// POR QUÉ EXISTE
// ──────────────
// Los cinco gráficos de Recharts tenían cada uno su copia del mismo bloque:
// la grilla, el color de los números del eje, el fondo del globo de datos, su
// borde, su texto. Cinco copias de una decisión, escritas a mano.
//
// Y ya habían divergido sin que nadie lo notara: `Dashboard`, `Insights` y
// `AdvisorDashboard` usaban los colores del sistema nuevo (#1B2230, #10151F),
// pero `Goals` se quedó con los del sistema anterior (#334155, #1e293b — los
// `slate` de Tailwind). Los dos juegos se parecen sobre fondo oscuro, así que
// la diferencia era invisible. Sobre blanco no lo hubiera sido.
//
// LO QUE CAMBIA ENTRE TEMAS, Y POR QUÉ NO ALCANZA CON ACLARAR
// ───────────────────────────────────────────────────────────
// La grilla es el caso que más engaña. Usaba el mismo valor que los bordes
// (#1B2230): sobre el panel oscuro contrasta 1,18:1 — un susurro, que es
// exactamente lo que una grilla tiene que ser. Ese mismo valor sobre blanco
// contrasta 15,93:1 y se convierte en lo más oscuro del gráfico: la grilla
// pesando más que los datos. Por eso el valor claro es otro, no el mismo
// "un poco más claro".
//
// El globo de datos se da vuelta entero: de un rectángulo casi negro a uno
// blanco con sombra. Y el relleno bajo la línea sube de opacidad, porque la
// misma transparencia se percibe más débil sobre blanco que sobre negro
// (`--chart-area-op`, en index.css).
//
// CÓMO SE USA
// ───────────
// Recharts acepta strings de color, así que estos valores son `rgb(var(--x))`
// y los resuelve el navegador. Consecuencia: al cambiar de tema no hay que
// volver a dibujar nada.
//
//   <CartesianGrid {...chartGrid} />
//   <XAxis tick={chartTick} axisLine={false} tickLine={false} />
//   <Tooltip {...chartTooltip} />
//
// Los objetos se exportan congelados: un `chartGrid.stroke = ...` en un
// componente se los cambiaría a los otros cuatro.

const v = (token) => `rgb(var(--${token}))`

/** La grilla de fondo. Recesiva en los dos temas — nunca compite con los datos. */
export const chartGrid = Object.freeze({
  stroke: v('chart-grid'),
  strokeOpacity: 0.35,
  strokeDasharray: '2 4',
  vertical: false,
})

/** Los números de los ejes. Son texto terciario y toman el token de texto
 *  terciario — antes eran #7C8698, un gris que no pertenecía a la paleta. */
export const chartTick = Object.freeze({ fill: v('ink-2'), fontSize: 12 })

/** Igual, para los gráficos que usan tipografía más chica. */
export const chartTickSm = Object.freeze({ fill: v('ink-2'), fontSize: 11 })

/** Líneas de referencia (metas, promedios, el cero). Más presentes que la
 *  grilla, menos que una serie. */
export const chartReferenceStroke = v('line-3')

/** El globo de datos al pasar el mouse. En oscuro es un panel elevado; en
 *  claro es blanco con sombra, porque en claro no se puede elevar aclarando. */
export const chartTooltip = Object.freeze({
  cursor: { stroke: v('line-3'), strokeWidth: 1, strokeDasharray: '3 3' },
  contentStyle: {
    background: v('bg-1'),
    border: `1px solid ${v('line-2')}`,
    borderRadius: 12,
    fontSize: 12.5,
    padding: '8px 12px',
    boxShadow: 'var(--chart-tooltip-shadow)',
  },
  labelStyle: { color: v('ink-0'), fontSize: 12, fontWeight: 600, marginBottom: 5 },
  itemStyle: { color: v('ink-1'), fontSize: 12.5, padding: '2px 0' },
})

/** El color de una línea o área según vaya ganando o perdiendo.
 *  Usa los tokens de RELLENO, no los de texto: una línea es un trazo, no un
 *  número. En claro el verde de texto es más oscuro para poder leerse; el de
 *  relleno se queda vivo. */
export const trendStroke = (isUp) => v(isUp ? 'rendi-pos-fill' : 'rendi-neg-fill')

/**
 * El color del relleno bajo una línea de área, con su transparencia.
 *
 * La opacidad sale de `--chart-area-op` (0,18 en oscuro, 0,22 en claro): la
 * misma transparencia se percibe más débil sobre blanco. Va adentro del color
 * y no en el atributo `stopOpacity`, que no entiende `var()`.
 *
 * Se usa en el `<stop>` de arriba del degradado; el de abajo va con
 * `stopOpacity={0}` como siempre.
 */
export const trendArea = (isUp) =>
  `rgb(var(--${isUp ? 'rendi-pos-fill' : 'rendi-neg-fill'}) / var(--chart-area-op))`

/** Lo mismo para un color arbitrario ya en forma `rgb(var(--x))`. */
export const areaFill = (color) => color.replace(/\)$/, ' / var(--chart-area-op))')

/**
 * El mismo color, con transparencia.
 *
 * Existe porque el atajo de antes era pegarle dos dígitos hex al final
 * (`` `${color}80` ``), y eso sólo funciona si el color ES un hex. Desde que
 * los colores son `rgb(var(--x))`, esa concatenación produce CSS inválido
 * —`rgb(var(--x))80`— que el navegador descarta sin decir nada: el borde o el
 * fondo simplemente desaparece. Si ves un `${...}` seguido de dos hex sobre un
 * color, es este bug.
 *
 * @param {string} color  un `rgb(var(--x))`
 * @param {number} alpha  0 a 1
 */
export const withAlpha = (color, alpha) => color.replace(/\)$/, ` / ${alpha})`)

/**
 * La paleta de series, en orden fijo.
 *
 * Se asigna por posición y NUNCA se cicla: una novena serie no recibe un color
 * inventado, se pliega en "Otros". El orden es el que ya tenían las tortas de
 * Dashboard e Insights — acá sólo se unificó en un lugar, no se cambió, para
 * que ninguna torta existente cambie de colores.
 *
 * ⚠️ Anotado y NO resuelto: el violeta y el azul de esta lista están
 * demasiado cerca para alguien con visión de color normal (ΔE 9,3 medido; el
 * piso es 15). Eso pasa ya, en oscuro, y es anterior al modo claro. Cambiarlo
 * repinta tortas que la gente ya conoce, así que es su propia decisión.
 */
export const SERIES_COLORS = Object.freeze([
  v('rendi-pos'), v('data-cyan'), v('rendi-accent'),
  v('data-amber'), v('data-violet'), v('rendi-neg'),
])

/** El color de la serie número `i`. Se pliega al último en vez de ciclar:
 *  ciclar hace que dos series distintas compartan color. */
export const seriesColor = (i) => SERIES_COLORS[Math.min(i, SERIES_COLORS.length - 1)]

/**
 * Rampa monocroma violeta, para proporciones de un mismo todo (la composición
 * del libro del asesor). Es otra cosa que `SERIES_COLORS`: ahí el color dice
 * QUIÉN es cada serie; acá dice CUÁNTO pesa cada parte, y por eso es un solo
 * tono en pasos. Se recorre al revés entre temas, igual que la rampa de
 * polaridad — en claro arranca clara y termina profunda.
 */
export const MONO_VIOLET = Object.freeze([
  v('mono-violet-1'), v('mono-violet-2'), v('mono-violet-3'),
  v('mono-violet-4'), v('mono-violet-5'),
])
