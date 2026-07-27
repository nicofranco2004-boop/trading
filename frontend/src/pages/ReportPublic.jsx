// ReportPublic — el informe del período que abre el CLIENTE (/i/:token).
// ═══════════════════════════════════════════════════════════════════════════
// Público, sin login: el link viaja por WhatsApp/email. El contenido viene
// CONGELADO del backend (lo que el asesor mandó no cambia después). La marca
// es la del ASESOR — Rendi aparece solo en el pie. Papel claro a propósito:
// es un documento que se lee/imprime (mockup aprobado por Nico), no una
// pantalla de la app. "Descargar PDF" = window.print() con print CSS.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import PageMeta from '../components/PageMeta'

const P = {
  paper: '#FDFDFB', paper2: '#F4F4F1', ink0: '#191D26', ink2: '#5C6474',
  ink3: '#8B92A3', line: '#E6E6E0', brand: '#1E1840',
  up: '#0FA968', down: '#E04250',
}

const fmtUsd = (n) => (n == null ? '—' : `US$ ${Math.round(n).toLocaleString('es-AR')}`)
const signed = (n) => (n == null ? '—' : `${n >= 0 ? '+' : '−'}US$ ${Math.abs(Math.round(n)).toLocaleString('es-AR')}`)

export default function ReportPublic() {
  const { token } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/reports/public/${encodeURIComponent(token || '')}`)
      .then(async (res) => {
        const d = await res.json()
        if (cancelled) return
        if (!res.ok) { setError(typeof d.detail === 'string' ? d.detail : 'Informe no encontrado'); return }
        setData(d.report)
      })
      .catch(() => { if (!cancelled) setError('No pudimos cargar el informe. Probá de nuevo.') })
    return () => { cancelled = true }
  }, [token])

  if (error) {
    return (
      <div style={{ minHeight: '100vh', background: '#07090C', display: 'grid', placeItems: 'center', padding: 20 }}>
        <div style={{ color: '#9CA3B5', fontSize: 14, textAlign: 'center' }}>
          <p style={{ color: '#E6EAF2', fontSize: 18, fontWeight: 600, marginBottom: 6 }}>Informe no disponible</p>
          {error}
        </div>
      </div>
    )
  }
  if (!data) {
    return (
      <div style={{ minHeight: '100vh', background: '#07090C', display: 'grid', placeItems: 'center' }}>
        <p style={{ color: '#5A6478', fontSize: 14 }}>Cargando el informe…</p>
      </div>
    )
  }

  const r = data
  const initials = (r.branding?.name || 'A').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
  const holdingsMax = Math.max(...(r.holdings || []).map(h => h.weight_pct || 0), 1)

  return (
    <div className="report-shell" style={{ minHeight: '100vh', background: '#07090C', padding: '28px 14px 60px' }}>
      <PageMeta title={`Informe de cartera — ${r.client_label}`} noindex={true} />
      <style>{`
        @media print {
          .report-shell { background: #fff !important; padding: 0 !important; }
          .no-print { display: none !important; }
          .report-paper { box-shadow: none !important; border-radius: 0 !important; }
          /* Sin esto los navegadores omiten los backgrounds: el monograma y
             las barras de tenencias salían invisibles en el PDF (audit). */
          .report-paper, .report-paper * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        }
      `}</style>

      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <div className="no-print" style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 10 }}>
          <button
            type="button"
            onClick={() => window.print()}
            style={{ background: '#8B7DFF', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          >
            Descargar PDF
          </button>
        </div>

        <div className="report-paper" style={{ background: P.paper, color: P.ink0, borderRadius: 14, padding: '30px 32px', boxShadow: '0 24px 60px -24px rgba(0,0,0,.7)', fontFamily: "'Geist', -apple-system, 'Segoe UI', system-ui, sans-serif" }}>

          {/* Cabecera con la marca del asesor */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, borderBottom: `2px solid ${P.ink0}`, paddingBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, background: P.brand, color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 15 }}>{initials}</div>
              <div>
                <div style={{ fontSize: 15.5, fontWeight: 700 }}>{r.branding?.name || 'Tu asesor'}</div>
                {r.branding?.matricula && (
                  <div style={{ fontSize: 10.5, color: P.ink2 }}>Idóneo registrado CNV · Mat. N° {r.branding.matricula}</div>
                )}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700 }}>Informe de cartera</div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{r.period?.start} → {r.period?.end}</div>
              <div style={{ fontSize: 12, color: P.ink2, marginTop: 2 }}>{r.client_label}</div>
            </div>
          </div>

          {/* Números principales */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 14, margin: '18px 0 4px' }}>
            <div>
              <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, marginBottom: 4 }}>Valor de la cartera</div>
              <div style={{ fontSize: 24, fontWeight: 750 }}>{fmtUsd(r.value_end_usd)}</div>
              <div style={{ fontSize: 11, color: P.ink2, marginTop: 3 }}>al {r.value_as_of || r.period?.end} · dólar MEP {r.tc_mep ? Math.round(r.tc_mep).toLocaleString('es-AR') : '—'}</div>
            </div>
            <div>
              <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, marginBottom: 4 }}>Resultado del período</div>
              <div style={{ fontSize: 24, fontWeight: 750, color: (r.market_usd ?? 0) >= 0 ? P.up : P.down }}>
                {r.ret_pct != null ? `${r.ret_pct >= 0 ? '+' : ''}${r.ret_pct}%` : '—'}
              </div>
              <div style={{ fontSize: 11, color: P.ink2, marginTop: 3 }}>{signed(r.market_usd)} · neto de comisiones</div>
            </div>
            <div>
              <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, marginBottom: 4 }}>¿De dónde vino?</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.6 }}>
                Mercado <b style={{ color: (r.market_usd ?? 0) >= 0 ? P.up : P.down }}>{signed(r.market_usd)}</b><br />
                Aportes netos <b>{signed(r.flows_usd)}</b>
              </div>
            </div>
          </div>

          {/* Nota del asesor */}
          {r.note && (
            <div style={{ background: P.paper2, borderLeft: `3px solid ${P.brand}`, borderRadius: '0 8px 8px 0', padding: '10px 14px', margin: '14px 0', fontSize: 13 }}>
              <div style={{ fontSize: 10.5, letterSpacing: '.08em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, marginBottom: 3 }}>Nota de tu asesor</div>
              {r.note}
            </div>
          )}

          {/* Benchmark MEP */}
          {r.mep_var_pct != null && r.ret_pct != null && (
            <div style={{ display: 'flex', border: `1px solid ${P.line}`, borderRadius: 10, overflow: 'hidden', margin: '16px 0', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 150, padding: '10px 14px', borderRight: `1px solid ${P.line}`, background: r.ret_pct >= 0 ? '#F2FBF6' : 'transparent' }}>
                <div style={{ fontSize: 10.5, color: P.ink2 }}>Tu cartera (en dólares)</div>
                <div style={{ fontSize: 16, fontWeight: 750, color: r.ret_pct >= 0 ? P.up : P.down }}>{r.ret_pct >= 0 ? '+' : ''}{r.ret_pct}%</div>
              </div>
              <div style={{ flex: 1, minWidth: 150, padding: '10px 14px' }}>
                <div style={{ fontSize: 10.5, color: P.ink2 }}>Dólar MEP en el mismo lapso</div>
                <div style={{ fontSize: 16, fontWeight: 750 }}>{r.mep_var_pct >= 0 ? '+' : ''}{r.mep_var_pct}% <span style={{ fontSize: 10, fontWeight: 400, color: P.ink3 }}>(en pesos)</span></div>
              </div>
            </div>
          )}

          {/* Evolución */}
          {r.series?.length >= 2 && <EvolutionSvg series={r.series} />}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 20, marginTop: 16 }}>
            {/* Movimientos */}
            <div>
              <div style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, margin: '6px 0 8px' }}>Movimientos del período</div>
              {r.movements?.length ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                  <tbody>
                    {r.movements.map((m, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #F0F0EA' }}>
                        <td style={{ padding: '7px 6px', color: P.ink2, whiteSpace: 'nowrap' }}>{m.date}</td>
                        <td style={{ padding: '7px 6px' }}>{m.type || 'Operación'} {m.asset}{m.quantity ? ` · ${m.quantity}` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p style={{ fontSize: 12.5, color: P.ink3, margin: 0 }}>Sin movimientos registrados en el período.</p>
              )}
              {r.movements_total > (r.movements?.length || 0) && (
                <p style={{ fontSize: 11, color: P.ink3, marginTop: 6 }}>Se muestran los {r.movements.length} más recientes de {r.movements_total}.</p>
              )}
            </div>
            {/* Tenencias */}
            <div>
              <div style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, margin: '6px 0 8px' }}>Principales tenencias</div>
              {(r.holdings || []).map((h, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, padding: '4px 0' }}>
                  <b style={{ width: 64, flexShrink: 0 }}>{h.asset}</b>
                  {h.weight_pct != null ? (
                    <>
                      <div style={{ flex: 1, height: 8, background: P.paper2, borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.max(4, (h.weight_pct / holdingsMax) * 100)}%`, height: '100%', background: P.brand, borderRadius: 4 }} />
                      </div>
                      <span style={{ fontWeight: 700, width: 38, textAlign: 'right' }}>{h.weight_pct}%</span>
                    </>
                  ) : (
                    <span style={{ marginLeft: 'auto', fontWeight: 700 }}>{fmtUsd(h.value_usd)}</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Invitación si el cliente todavía no reclamó su cuenta */}
          {r.claimed === false && (
            <div className="no-print" style={{ marginTop: 18, padding: '10px 14px', background: '#F5F3FF', border: '1px solid #E3DEFB', borderRadius: 10, fontSize: 12.5, color: P.ink2 }}>
              ¿Querés seguir tu cartera al día, desde tu celular? Pedile a {r.branding?.name || 'tu asesor'} que te invite a tu cuenta de Rendi.
            </div>
          )}

          {/* Pie */}
          <div style={{ marginTop: 22, paddingTop: 12, borderTop: `1px solid ${P.line}`, fontSize: 9.5, color: P.ink3, lineHeight: 1.6 }}>
            Informe preparado por {r.branding?.name || 'tu asesor'}{r.branding?.matricula ? ` (Mat. CNV N° ${r.branding.matricula})` : ''} y
            generado con Rendi el {r.generated_at} · Valores en dólares al tipo de cambio MEP · Retornos netos de comisiones ·
            Este informe es de carácter informativo: no constituye oferta ni recomendación de inversión · Rendi registra y reporta — no opera ni custodia fondos.
          </div>
        </div>
      </div>
    </div>
  )
}

// Línea de evolución con la punteada de aportado — misma semántica que el
// gráfico del libro (la brecha entre las dos es la ganancia).
function EvolutionSvg({ series }) {
  const W = 640, H = 110, PAD = 6
  const vals = series.flatMap(p => [p.v, p.nd])
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const span = (mx - mn) || 1
  const x = (i) => (i / (series.length - 1)) * (W - PAD * 2) + PAD
  const y = (v) => H - PAD - ((v - mn) / span) * (H - PAD * 2 - 14)
  const path = (key) => series.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ')
  return (
    <div>
      <div style={{ fontSize: 11, letterSpacing: '.1em', textTransform: 'uppercase', color: P.ink2, fontWeight: 700, margin: '14px 0 6px' }}>Evolución del período</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        <line x1="0" y1={H - PAD} x2={W} y2={H - PAD} stroke={P.line} strokeWidth="1" />
        <path d={`${path('v')} L${x(series.length - 1)},${H - PAD} L${PAD},${H - PAD} Z`} fill="rgba(30,24,64,.06)" />
        <path d={path('v')} fill="none" stroke={P.brand} strokeWidth="2.2" />
        <path d={path('nd')} fill="none" stroke={P.ink3} strokeWidth="1.4" strokeDasharray="4 4" />
        <text x={PAD} y="11" fontSize="10" fill={P.ink3}>— tu cartera &nbsp; - - plata aportada (la brecha es la ganancia)</text>
      </svg>
    </div>
  )
}
