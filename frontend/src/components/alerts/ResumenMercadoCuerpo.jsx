// ResumenMercadoCuerpo — el cuerpo del resumen del mercado, dibujado UNA vez.
// ═══════════════════════════════════════════════════════════════════════════
// Lo usan dos lugares: el ejemplo de la card de /alertas (MarketBriefPrefs) y la
// pantalla /resumen, que abre la notificación del resumen. Antes el ejemplo
// tenía su propio dibujo; con una segunda pantalla, dos copias del mismo bloque
// se terminan desviando — y el ejemplo dejaría de mostrar lo que de verdad llega.
//
// Recibe la misma forma que devuelve GET /api/market-brief/ultimo
// (`market_brief.ultimo_resumen`): titular, mercado[], tu_cartera[],
// fuera_de_horario {lineas[], nota} y agenda [{ticker, label}]. Los dos bloques
// de abajo los arma el CÓDIGO del servidor, con el mismo armador que el mail; acá
// sólo se maquetan.
//
// `compacto`: la letra chica de la card. Sin él, la de la pantalla, que es para
// LEER cuatro párrafos seguidos, no para escanear.
//
// Sistema visual: generación nueva — rótulos sans sentence-case, sin tipografía
// de ancho fijo.

export default function ResumenMercadoCuerpo({ resumen, compacto = false }) {
  if (!resumen) return null
  const parrafo = compacto
    ? 'text-xs text-ink-1 leading-relaxed'
    : 'text-[15px] text-ink-1 leading-relaxed'
  const rotulo = compacto
    ? 'text-[11px] tracking-label text-ink-3 mt-3'
    : 'text-[13px] font-medium text-data-violet mt-7'
  const mercado = (resumen.mercado || []).filter(p => (p || '').trim())
  const cartera = (resumen.tu_cartera || []).filter(p => (p || '').trim())
  const fdh = resumen.fuera_de_horario
  const lineas = (fdh && fdh.lineas) || []
  const agenda = resumen.agenda || []

  return (
    <div>
      <div className={compacto
        ? 'text-sm font-medium text-ink-0 leading-snug'
        : 'text-xl sm:text-2xl font-semibold text-ink-0 leading-snug tracking-tight'}>
        {resumen.titular}
      </div>
      {mercado.map((p, k) => (
        <p key={k} className={`${parrafo} ${compacto ? 'mt-2' : 'mt-4'}`}>{p}</p>
      ))}

      {cartera.length > 0 && (
        <>
          <div className={rotulo}>Lo tuyo</div>
          {cartera.map((p, k) => (
            <p key={k} className={`${parrafo} ${compacto ? 'mt-1' : 'mt-2'}`}>{p}</p>
          ))}
        </>
      )}

      {lineas.length > 0 && (
        <>
          <div className={rotulo}>Wall Street fuera de la rueda</div>
          {lineas.map((l, k) => (
            <p key={k} className={`${parrafo} ${compacto ? 'mt-1' : 'mt-2'}`}>{l}</p>
          ))}
          {fdh.nota && (
            <p className={`${compacto ? 'text-[11px]' : 'text-xs'} text-ink-3 leading-relaxed mt-1.5`}>
              {fdh.nota}
            </p>
          )}
        </>
      )}

      {agenda.length > 0 && (
        <>
          <div className={rotulo}>En tu agenda de hoy</div>
          {agenda.map((e, k) => (
            <div key={k} className={`${compacto ? 'text-xs mt-0.5' : 'text-sm mt-1.5'} text-ink-1`}>
              <span className="font-medium">{e.ticker}</span>
              <span className="text-ink-2"> — {e.label}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
