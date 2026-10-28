// ReporteCartera — el reporte de la cartera en papel (se imprime / guarda como PDF).
// ═══════════════════════════════════════════════════════════════════════════
// Sólo dibuja: los datos llegan ya armados por utils/reporteCartera (que a su
// vez no calcula nada, lee lo que Análisis ya calculó). Si `mostrarMontos` fue
// no, el objeto no trae ninguna cifra de plata y acá no hay nada que ocultar.
//
// Papel claro siempre, con la paleta `P` del informe público (ReportPublic):
// es un documento que se imprime, no una pantalla de la app (R8, excepción 2).
// El violeta de marca y los colores de las porciones sí son variables: se ven
// bien sobre blanco en los dos temas, y así no hay un hex nuevo.
//
// Los gráficos son SVG a mano y no recharts: recharts anima al aparecer y mide
// el contenedor con ResizeObserver, y en la vista de impresión eso sale como
// un gráfico vacío o a medio dibujar.

import { P } from '../../pages/ReportPublic'

const VIOLETA = 'rgb(var(--data-violet))'
const FUENTE = "'Geist', -apple-system, 'Segoe UI', system-ui, sans-serif"
const num = { fontVariantNumeric: 'tabular-nums' }
const pct = (v) => `${Number(v).toFixed(1).replace('.', ',')}%`
const colorDeSigno = (s) => (s > 0 ? P.up : s < 0 ? P.down : P.ink0)

// "Último año" → "En el último año"; "Desde el inicio" queda como está.
export const fraseDelPeriodo = (periodo) => {
  if (!periodo) return 'En el período'
  if (/^desde/i.test(periodo)) return periodo
  return `En el ${periodo.charAt(0).toLowerCase()}${periodo.slice(1)}`
}

export default function ReporteCartera({ datos }) {
  const d = datos
  return (
    <div
      className="reporte-papel"
      style={{ background: P.paper, color: P.ink0, fontFamily: FUENTE, padding: '32px 34px', maxWidth: 800, margin: '0 auto', borderRadius: 12 }}
    >
      {/* ── Encabezado ─────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, borderBottom: `2px solid ${P.ink0}`, paddingBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="/brand/rendi-mark-violet.png" alt="" style={{ height: 34 }} />
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, lineHeight: 1 }}>Rendi</div>
            <div style={{ fontSize: 11.5, color: P.ink2, marginTop: 3 }}>rendi.finance</div>
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 18, fontWeight: 700 }}>Reporte de cartera</div>
          <div style={{ fontSize: 12.5, color: P.ink2, marginTop: 3 }}>
            {d.fecha} · valores {d.enMoneda}
          </div>
        </div>
      </div>

      {/* ── Resumen ────────────────────────────────────────────────────── */}
      {(d.patrimonio || d.rendimiento || d.noRealizado || d.drawdown) && (
      <Seccion titulo="Resumen">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 14 }}>
          {d.patrimonio && <Dato rotulo="Valor de la cartera" valor={d.patrimonio} />}
          {d.rendimiento && (
            <Dato
              rotulo={`Rendimiento · ${d.periodo || 'período'}`}
              sub={d.rendimiento.nota ? d.rendimiento.nota.charAt(0).toUpperCase() + d.rendimiento.nota.slice(1) : null}
              valor={d.rendimiento.cartera}
              color={colorDeSigno(d.rendimiento.signoCartera)}
            />
          )}
          {d.rendimiento?.bench && (
            <Dato rotulo={`${d.rendimiento.benchLabel} · mismo período`} valor={d.rendimiento.bench} />
          )}
          {d.rendimiento?.diferencia && (
            <Dato
              rotulo="Diferencia"
              valor={d.rendimiento.diferencia}
              color={colorDeSigno(d.rendimiento.contraBench)}
            />
          )}
          {d.noRealizado && (
            <Dato
              rotulo="P/L no realizado"
              valor={d.noRealizado.monto || d.noRealizado.pct}
              color={colorDeSigno(d.noRealizado.signo)}
              sub={d.noRealizado.monto ? `${d.noRealizado.pct} sobre lo invertido` : 'sobre lo invertido'}
            />
          )}
          {d.drawdown && (
            <Dato
              rotulo="Caída desde el máximo"
              valor={d.drawdown.actual}
              sub={d.drawdown.maximo ? `Peor caída: ${d.drawdown.maximo}` : null}
            />
          )}
        </div>
      </Seccion>
      )}

      {/* ── Aportes vs mercado ─────────────────────────────────────────── */}
      {d.plata && (
        <Seccion titulo="Lo que pusiste y lo que puso el mercado">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 14, alignItems: 'stretch' }}>
            <Dato rotulo="Aportado (neto de retiros)" valor={d.plata.aportado} />
            <Dato
              rotulo={d.plata.mercadoPositivo ? 'Ganado en el mercado' : 'Perdido en el mercado'}
              valor={d.plata.mercado}
              color={d.plata.mercadoPositivo ? P.up : P.down}
            />
            {d.plata.valorHoy && <Dato rotulo="Lo que vale hoy" valor={d.plata.valorHoy} />}
          </div>
          <p style={{ fontSize: 11.5, color: P.ink3, margin: '8px 0 0', lineHeight: 1.5 }}>
            Lo que vale hoy tu cartera = lo que aportaste (depósitos menos retiros) + lo que
            {d.plata.mercadoPositivo ? ' ganó' : ' perdió'} el mercado. Incluye lo realizado y lo no realizado.
          </p>
        </Seccion>
      )}

      {/* ── Rendimiento vs benchmark ───────────────────────────────────── */}
      {d.rendimiento && (
        <Seccion titulo={d.rendimiento.bench ? `Tu cartera vs ${d.rendimiento.benchLabel}` : 'Evolución de tu cartera'}>
          {d.rendimiento.bench && (
            <p style={{ fontSize: 13, color: P.ink2, margin: '0 0 10px', lineHeight: 1.5 }}>
              {fraseDelPeriodo(d.periodo)}, tu cartera rindió{' '}
              <strong style={{ color: P.ink0, ...num }}>{d.rendimiento.cartera}</strong> y el{' '}
              {d.rendimiento.benchLabel} <strong style={{ color: P.ink0, ...num }}>{d.rendimiento.bench}</strong>
              {' '}con tus mismos depósitos y retiros.{' '}
              {d.rendimiento.contraBench > 0
                ? `Le ganaste por ${d.rendimiento.diferencia.replace(/^[+−]/, '')}.`
                : d.rendimiento.contraBench < 0
                  ? `Quedaste ${d.rendimiento.diferencia.replace(/^[+−]/, '')} abajo.`
                  : 'Quedaste igual.'}
            </p>
          )}
          <CurvaRendimiento serie={d.rendimiento.serie} />
          <div style={{ display: 'flex', gap: 18, fontSize: 11.5, color: P.ink2, marginTop: 6 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 18, height: 3, background: VIOLETA, display: 'inline-block' }} /> Mi cartera
            </span>
            {d.rendimiento.bench && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 18, borderTop: `2px dashed ${P.ink3}`, display: 'inline-block' }} /> {d.rendimiento.benchLabel}
              </span>
            )}
          </div>
        </Seccion>
      )}

      {/* ── Distribuciones ─────────────────────────────────────────────── */}
      {d.distribuciones.map(dist => (
        <Seccion key={dist.titulo} titulo={dist.titulo}>
          <div style={{ display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
            <Torta porciones={dist.porciones} />
            <table style={{ flex: 1, minWidth: 260, borderCollapse: 'collapse', fontSize: 12.5 }}>
              <tbody>
                {dist.porciones.map((p, i) => (
                  <tr key={`${i}-${p.label}`} style={{ borderBottom: `1px solid ${P.line2}` }}>
                    <td style={{ padding: '5px 0', width: 16 }}>
                      <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, background: p.color }} />
                    </td>
                    <td style={{ padding: '5px 8px 5px 0' }}>{p.label}</td>
                    {d.mostrarMontos && (
                      <td style={{ padding: '5px 10px', textAlign: 'right', color: P.ink2, ...num }}>{p.monto}</td>
                    )}
                    <td style={{ padding: '5px 0', textAlign: 'right', fontWeight: 600, width: 60, ...num }}>{pct(p.pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Seccion>
      ))}

      {/* ── Qué explica tu resultado ───────────────────────────────────── */}
      {(d.ganadores.length > 0 || d.perdedores.length > 0) && (
        <Seccion titulo="Qué explica tu resultado">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 18 }}>
            <ListaActivos titulo="Los que más sumaron" filas={d.ganadores} color={P.up} vacio="Ningún activo en positivo." />
            <ListaActivos titulo="Los que más restaron" filas={d.perdedores} color={P.down} vacio="Ningún activo en negativo." />
          </div>
        </Seccion>
      )}

      {/* ── Aviso ──────────────────────────────────────────────────────── */}
      <div style={{ marginTop: 26, paddingTop: 12, borderTop: `1px solid ${P.line}`, fontSize: 10.5, color: P.ink3, lineHeight: 1.55 }}>
        Reporte generado con Rendi el {d.fecha}. Es informativo y no constituye una
        recomendación de inversión. Los valores surgen de las operaciones y tenencias
        cargadas en Rendi y de las cotizaciones disponibles a esa fecha; el rendimiento
        del {d.rendimiento?.benchLabel || 'índice de referencia'} se simula con tus mismos
        depósitos y retiros.
        {!d.mostrarMontos && ' Este reporte se generó sin montos: sólo muestra porcentajes.'}
      </div>
    </div>
  )
}

function Seccion({ titulo, children }) {
  return (
    <section style={{ marginTop: 22, breakInside: 'avoid', pageBreakInside: 'avoid' }}>
      <h2 style={{ fontSize: 14.5, fontWeight: 700, margin: '0 0 10px', color: P.ink0 }}>{titulo}</h2>
      {children}
    </section>
  )
}

function Dato({ rotulo, valor, color, sub }) {
  return (
    <div style={{ background: P.paper2, borderRadius: 10, padding: '10px 12px' }}>
      <div style={{ fontSize: 11, color: P.ink2, marginBottom: 4 }}>{rotulo}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || P.ink0, ...num }}>{valor}</div>
      {sub && <div style={{ fontSize: 11, color: P.ink2, marginTop: 3, ...num }}>{sub}</div>}
    </div>
  )
}

function ListaActivos({ titulo, filas, color, vacio }) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color, marginBottom: 6 }}>{titulo}</div>
      {filas.length === 0 ? (
        <div style={{ fontSize: 12, color: P.ink3 }}>{vacio}</div>
      ) : filas.map((f, i) => (
        <div key={`${i}-${f.label}`} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '5px 0', borderBottom: `1px solid ${P.line2}` }}>
          <span style={{ fontWeight: 600 }}>{f.label}</span>
          {f.resultado && <span style={{ color, fontWeight: 600, ...num }}>{f.resultado}</span>}
        </div>
      ))}
    </div>
  )
}

// La torta: anillo de SVG con las mismas porciones (y colores) que la tabla.
function Torta({ porciones, tam = 170 }) {
  const c = tam / 2
  const R = c - 2
  const r = R * 0.6
  const suma = porciones.reduce((s, p) => s + p.pct, 0) || 1
  const hueco = porciones.length > 1 ? 0.02 : 0
  let a = -Math.PI / 2
  const punto = (rad, ang) => `${(c + rad * Math.cos(ang)).toFixed(2)} ${(c + rad * Math.sin(ang)).toFixed(2)}`
  return (
    <svg width={tam} height={tam} viewBox={`0 0 ${tam} ${tam}`} style={{ flexShrink: 0 }} aria-hidden="true">
      {porciones.length === 1 ? (
        <circle cx={c} cy={c} r={(R + r) / 2} fill="none" stroke={porciones[0].color} strokeWidth={R - r} />
      ) : porciones.map((p, i) => {
        const barrido = (p.pct / suma) * Math.PI * 2
        const desde = a + hueco / 2
        const hasta = a + barrido - hueco / 2
        a += barrido
        if (!(hasta > desde)) return null
        const grande = hasta - desde > Math.PI ? 1 : 0
        const dPath = `M ${punto(R, desde)} A ${R} ${R} 0 ${grande} 1 ${punto(R, hasta)} L ${punto(r, hasta)} A ${r} ${r} 0 ${grande} 0 ${punto(r, desde)} Z`
        return <path key={i} d={dPath} fill={p.color} />
      })}
    </svg>
  )
}

// La curva: cartera (violeta, con área) y benchmark (gris punteado). Un null
// corta la línea, igual que en la pantalla (serie partida).
function CurvaRendimiento({ serie, ancho = 730, alto = 230 }) {
  const valores = serie.flatMap(p => [p.cartera, p.bench]).filter(Number.isFinite)
  if (serie.length < 2 || valores.length < 2) return null
  const pad = { l: 44, r: 8, t: 8, b: 8 }
  const t0 = serie[0].ts
  const t1 = serie[serie.length - 1].ts
  let vMin = Math.min(0, ...valores)
  let vMax = Math.max(0, ...valores)
  const m = (vMax - vMin) * 0.08 || 1
  vMin -= m
  vMax += m
  const X = (t) => pad.l + ((t - t0) / ((t1 - t0) || 1)) * (ancho - pad.l - pad.r)
  const Y = (v) => pad.t + (1 - (v - vMin) / (vMax - vMin)) * (alto - pad.t - pad.b)

  const tramos = (clave) => {
    const out = []
    let act = []
    for (const p of serie) {
      if (Number.isFinite(p[clave])) act.push(p)
      else if (act.length) { out.push(act); act = [] }
    }
    if (act.length) out.push(act)
    return out
  }
  const linea = (tramo, clave) => tramo.map((p, i) => `${i ? 'L' : 'M'} ${X(p.ts).toFixed(1)} ${Y(p[clave]).toFixed(1)}`).join(' ')

  // Sólo el cero. La curva es la FORMA (encadena las fotos del día) y sus
  // extremos pueden no coincidir con el número del KPI, que es el publicado:
  // rotularlos ponía al lado del "+6,6%" un eje que llegaba a otro número.
  const marcas = [0]

  return (
    <svg width="100%" viewBox={`0 0 ${ancho} ${alto}`} style={{ display: 'block' }} aria-hidden="true">
      {marcas.map(v => (
        <g key={v}>
          <line x1={pad.l} x2={ancho - pad.r} y1={Y(v)} y2={Y(v)} stroke={P.line} strokeDasharray={v === 0 ? '0' : '3 4'} />
          <text x={pad.l - 6} y={Y(v) + 4} textAnchor="end" fontSize="10.5" fill={P.ink3} style={num}>
            {`${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v)}%`}
          </text>
        </g>
      ))}
      {tramos('bench').map((tr, i) => (
        <path key={`b${i}`} d={linea(tr, 'bench')} fill="none" stroke={P.ink3} strokeWidth="1.75" strokeDasharray="5 5" />
      ))}
      {tramos('cartera').map((tr, i) => (
        <g key={`c${i}`}>
          {tr.length > 1 && (
            <path
              d={`${linea(tr, 'cartera')} L ${X(tr[tr.length - 1].ts).toFixed(1)} ${Y(vMin).toFixed(1)} L ${X(tr[0].ts).toFixed(1)} ${Y(vMin).toFixed(1)} Z`}
              fill={VIOLETA}
              fillOpacity="0.1"
            />
          )}
          <path d={linea(tr, 'cartera')} fill="none" stroke={VIOLETA} strokeWidth="2.5" strokeLinejoin="round" />
        </g>
      ))}
    </svg>
  )
}
