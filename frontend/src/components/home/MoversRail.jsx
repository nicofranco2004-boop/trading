// MoversRail — "Movers del día": top gainers / top losers (V2).
// Dos columnas con DataRow denso. Eyebrows sans (<Eyebrow>). Sin cards anidadas.
//
// Movimiento (2026-09-29): al entrar en pantalla las filas aparecen de a una y
// los porcentajes cuentan hasta su valor; detrás de cada fila, una barra de
// intensidad (BarraIntensidad); arriba, el estado de la rueda (EnVivo). Se
// refresca solo cada 5 min con la pestaña a la vista, y el número que cambió
// destella verde o rojo (FlashValue). El servidor guarda los movers 30 min,
// así que el destello aparece como mucho cada media hora: es un dato de verdad
// que cambió, no un efecto de adorno.
//
// El título vive ACÁ (antes lo ponía cada página por su lado, con dos estilos
// distintos en Home y HomeMobile) porque el indicador en vivo va a su lado.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '../../utils/api'
import { pctVar, pctVarSign } from '../../utils/format'
import { refrescoSegunRueda } from '../../utils/relojVisible'
import { useUltimoPedido } from '../../hooks/useUltimoPedido'
import { useRelojVisible } from '../../hooks/useRelojVisible'
import { useAlVerse } from '../../hooks/useAlVerse'
import AssetQuickView from './AssetQuickView'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'
import DataRow from '../DataRow'
import EnVivo from '../EnVivo'
import BarraIntensidad from '../BarraIntensidad'
import FlashValue from '../FlashValue'
import AnimatedNumber from '../AnimatedNumber'

// Exportado para los tests de render.
export function MoverList({ items, tone, icon: Icon, label, onSelect, visto }) {
  return (
    <Panel padding="none" className="overflow-hidden">
      <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
        <Icon size={14} className={tone === 'pos' ? 'text-rendi-pos' : 'text-rendi-neg'} strokeWidth={1.75} aria-hidden="true" />
        <Eyebrow tone={tone === 'pos' ? 'signal' : 'red'}>{label}</Eyebrow>
      </div>
      <div className="divide-y divide-line/30">
        {items.map((it, i) => {
          // Del número redondeado, como la flecha de la cinta; sin dato, gris.
          const dir = pctVarSign(it.change_pct)
          const tono = dir > 0 ? 'text-rendi-pos' : dir < 0 ? 'text-rendi-neg' : 'text-ink-3'
          return (
            <DataRow
              key={it.symbol}
              density="compact"
              hoverable
              onClick={() => onSelect(it)}
              className={`relative isolate ${visto ? 'entra' : 'por-entrar'}`}
              style={{ '--i': i }}
            >
              <BarraIntensidad pct={it.change_pct} visto={visto} />
              <DataRow.Cell width={64} mono>
                <span className="text-ink-0 text-[13px]">{it.symbol}</span>
              </DataRow.Cell>
              <DataRow.Cell muted className="text-[12.5px] flex-1">
                {it.name}
              </DataRow.Cell>
              <DataRow.Cell align="right" width={70} tabular>
                <FlashValue value={it.change_pct} className={`font-medium ${tono}`}>
                  <AnimatedNumber value={visto ? it.change_pct : 0} format={pctVar} />
                </FlashValue>
              </DataRow.Cell>
            </DataRow>
          )
        })}
      </div>
    </Panel>
  )
}

export default function MoversRail({ market = "sp500" }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [selected, setSelected] = useState(null)
  const [ref, visto] = useAlVerse()
  const nuevoPedido = useUltimoPedido()

  // Si un refresco falla se quedan los movers que había: el error sólo se
  // muestra cuando no hay nada que mostrar. Y una respuesta que llega tarde
  // (ya hubo otro pedido, o cambió el mercado) se descarta.
  const cargar = useCallback(() => {
    const vigente = nuevoPedido()
    return api.get(`/home/movers?market=${market}`)
      .then(d => { if (vigente()) { setData(d); setErr(null) } })
      .catch(ex => { if (vigente()) setErr(ex.message) })
  }, [market, nuevoPedido])

  useEffect(() => { setData(null); cargar() }, [cargar])
  // Con la rueda cerrada los movers no cambian: el próximo pedido va a la
  // próxima media hora en punto (refrescoSegunRueda). Una vez por respuesta: calculado en cada render, un plazo que depende de
  // la hora reiniciaba el reloj con cualquier cambio de estado.
  const plazo = useMemo(() => refrescoSegunRueda(data), [data])
  useRelojVisible(cargar, plazo)

  return (
    <section ref={ref}>
      <div className="flex items-center justify-between gap-3 mb-2">
        {/* h2: en el celular era un encabezado (se navega por encabezados con
            lector de pantalla); al traer el título acá no se tiene que perder. */}
        <h2><Eyebrow>Movers del día</Eyebrow></h2>
        {data && <EnVivo estado={data} />}
      </div>
      {!data && !err ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="h-48 rounded bg-bg-1 border border-line animate-pulse" />
          <div className="h-48 rounded bg-bg-1 border border-line animate-pulse" />
        </div>
      ) : !data ? (
        <div className="text-xs text-rendi-neg">Sin movers: {err}</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <MoverList
            items={data.gainers || []}
            tone="pos"
            icon={TrendingUp}
            label="Más suben"
            onSelect={setSelected}
            visto={visto}
          />
          <MoverList
            items={data.losers || []}
            tone="neg"
            icon={TrendingDown}
            label="Más bajan"
            onSelect={setSelected}
            visto={visto}
          />
        </div>
      )}
      {selected && (
        <AssetQuickView symbol={selected.symbol} onClose={() => setSelected(null)} />
      )}
    </section>
  )
}
