// La rampa de polaridad — UNA sola, para todo lo que pinta "subió / bajó".
// ═══════════════════════════════════════════════════════════════════════════
// POR QUÉ EXISTE ESTE ARCHIVO
// ──────────────────────────
// Hasta F2, cada gráfico tenía su propia copia de la escala verde/roja escrita
// a mano adentro. `Heatmap.jsx` tenía dos arrays de 9 hex; `PerformanceCalendar`
// tenía seis ramas de `if` con el fondo Y el color del texto escritos en cada
// una. Dos copias de la misma decisión, que ya habían empezado a divergir.
//
// Eso además hacía imposible el modo claro, y de la peor manera: las dos copias
// estaban construidas para fondo oscuro, donde "intenso" quiere decir BRILLANTE.
// Sobre blanco esa escala se lee al revés — un activo que se movió 0,4 % se
// pintaba casi negro y uno que subió 1 % se pintaba pálido.
//
// CÓMO SE ARREGLA (y por qué no alcanza con cambiar los valores)
// ─────────────────────────────────────────────────────────────
// Una rampa no se adapta cambiándole los hex: hay que RECORRERLA AL REVÉS.
//   oscuro → arranca profunda y sube al verde señal (intenso = brillante)
//   claro  → arranca casi blanca y baja al verde profundo (intenso = oscuro)
// Los valores de los dos recorridos viven en `src/index.css` como variables
// (`--pol-up-N`, `--pol-down-N`, y su tinta `-ink`). Este archivo no los
// conoce: devuelve `rgb(var(--pol-up-2))` y deja que el tema resuelva.
//
// Consecuencia útil: al cambiar de tema NO hay que volver a dibujar nada. El
// navegador repinta solo. Por eso acá no hay hooks ni lectura del DOM.
//
// ⚠️ SÓLO SIRVE EN SVG Y EN CSS. Un `<canvas>` (utils/shareCard.js) no resuelve
// `var()`: necesita un valor concreto. Para ese caso está `resolvePolarity()`.
//
// LOS CORTES NO SON PARTE DE LA RAMPA
// ───────────────────────────────────
// "Cuánto es mucho" depende de qué se mide, y unificarlo sería el bug opuesto:
// un día que se movió 2 % es un día fuerte; un mes que rindió 2 % es un mes
// tibio. Por eso la rampa es una sola y los cortes son varios, declarados abajo
// con el nombre de lo que miden.

/** Cuántos pasos tiene la rampa por lado. La define index.css; acá se declara
 *  para que `stepFor` no pueda devolver un paso que no existe. */
export const POLARITY_STEPS = 3

// ── Los cortes, por lo que mide cada uno ───────────────────────────────────
// Son los umbrales de |%| que separan un paso del siguiente (con 3 pasos hacen
// falta 2). Cada caso declara TODOS sus umbrales juntos, incluido a partir de
// cuánto deja de considerarse plano. `plano` no es un detalle compartible: un día que se
// movió 0,3 % se movió, un mes que rindió 0,3 % no rindió nada.

/** Movimiento de UNA RUEDA (mapa de calor del mercado).
 *  Casi cualquier movimiento cuenta; 0,5 % ya se nota y 1 % es un día fuerte. */
export const CORTES_DIA = { plano: 0.05, pasos: [0.5, 1] }

/** Rendimiento de UN MES (calendario de Reportes).
 *  Bajo medio punto es un mes plano; 2 % es normal y 5 % es un mes grande. */
export const CORTES_MES = { plano: 0.5, pasos: [2, 5] }

/**
 * Qué paso de la rampa le toca a una variación.
 *
 * "Plano" devuelve sign 0, y plano no es un color: es ausencia. Se pinta con
 * `--pol-flat`, que tiende al fondo del tema — en claro al blanco del panel,
 * en oscuro al fondo oscuro. Un gris fijo para los dos es lo que producía los
 * cuadrados negros sobre fondo claro.
 *
 * @param {number} pct  la variación, en porcentaje (2.4 = +2,4 %)
 * @param {{plano: number, pasos: number[]}} cortes  CORTES_DIA | CORTES_MES
 * @returns {{ sign: -1|0|1, step: 1|2|3 }}  sign 0 = plano (step se ignora)
 */
export function stepFor(pct, cortes = CORTES_DIA) {
  if (pct == null || !Number.isFinite(pct)) return { sign: 0, step: 1 }
  const abs = Math.abs(pct)
  if (abs < cortes.plano) return { sign: 0, step: 1 }
  // Cuántos cortes superó + 1. Con [0.5, 1]: 0,3→paso 1 · 0,8→paso 2 · 4→paso 3.
  const step = Math.min(cortes.pasos.filter(c => abs >= c).length + 1, POLARITY_STEPS)
  return { sign: pct > 0 ? 1 : -1, step }
}

/**
 * El color de fondo y el de la tinta que va encima, para una variación.
 *
 * Los dos salen juntos a propósito: el fondo cambia de luminancia entre temas,
 * así que el texto de encima también tiene que cambiar. Pedir uno sin el otro
 * es cómo se llega a texto oscuro sobre fondo oscuro.
 *
 * @param {number} pct  la variación, en porcentaje
 * @param {{plano: number, pasos: number[]}} cortes  CORTES_DIA | CORTES_MES
 * @returns {{ bg: string, ink: string, sign: -1|0|1, step: number }}
 *          colores como strings CSS listos para `fill=` o `style.background`
 */
export function polarityColor(pct, cortes = CORTES_DIA) {
  const { sign, step } = stepFor(pct, cortes)
  if (sign === 0) {
    return { bg: 'rgb(var(--pol-flat))', ink: 'rgb(var(--pol-flat-ink))', sign, step }
  }
  const lado = sign > 0 ? 'up' : 'down'
  return {
    bg:  `rgb(var(--pol-${lado}-${step}))`,
    ink: `rgb(var(--pol-${lado}-${step}-ink))`,
    sign,
    step,
  }
}

/**
 * La misma respuesta, pero resuelta a un color concreto.
 *
 * Para `<canvas>`, que no entiende `var()`. Lee el valor que el tema tiene
 * puesto AHORA, así que hay que llamarla en el momento de dibujar y no
 * guardarse el resultado: si el usuario cambia de tema, el valor guardado
 * queda del tema anterior.
 *
 * @returns {{ bg: string, ink: string }} en formato `rgb(r, g, b)`
 */
export function resolvePolarity(pct, cortes = CORTES_DIA) {
  const { bg, ink } = polarityColor(pct, cortes)
  const cs = getComputedStyle(document.documentElement)
  const resolver = (v) => {
    const nombre = v.match(/var\((--[\w-]+)\)/)?.[1]
    if (!nombre) return v
    const canales = cs.getPropertyValue(nombre).trim()
    // Si la variable no está definida, devolver `rgb()` vacío pinta negro sin
    // avisar. Mejor `transparent`: se ve que falta algo en vez de mentir.
    return canales ? `rgb(${canales.split(/\s+/).join(', ')})` : 'transparent'
  }
  return { bg: resolver(bg), ink: resolver(ink) }
}

/**
 * Los pasos de la rampa en orden, de la caída más fuerte a la suba más fuerte,
 * con el plano en el medio. Es lo que dibuja una leyenda.
 *
 * Existe para que la leyenda no sea una lista de colores copiada al lado de la
 * escala: si un día la rampa cambia de pasos, la leyenda cambia con ella.
 */
export function polarityLegend() {
  const paso = (lado, n) => ({ bg: `rgb(var(--pol-${lado}-${n}))`, key: `${lado}-${n}` })
  const bajan = []
  for (let n = POLARITY_STEPS; n >= 1; n--) bajan.push(paso('down', n))
  const suben = []
  for (let n = 1; n <= POLARITY_STEPS; n++) suben.push(paso('up', n))
  return [...bajan, { bg: 'rgb(var(--pol-flat))', key: 'flat' }, ...suben]
}
