import { useEffect, useState } from 'react'
import { Save, Info } from 'lucide-react'

export default function Config() {
  const [cfg, setCfg] = useState({ tc_mep: '', tc_blue: '' })
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(d => setCfg({ tc_mep: d.tc_mep, tc_blue: d.tc_blue }))
  }, [])

  async function save(e) {
    e.preventDefault()
    await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tc_mep: +cfg.tc_mep, tc_blue: +cfg.tc_blue }),
    })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="pt-20 px-6 pb-10 max-w-lg mx-auto">
      <h1 className="text-xl font-bold text-slate-100 mb-6">Configuración</h1>

      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6">
        <h2 className="font-semibold text-slate-200 mb-4">Tipos de cambio</h2>
        <form onSubmit={save} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-300 mb-1 font-medium">TC MEP (ARS/USD)</label>
            <input
              type="number" step="any"
              value={cfg.tc_mep}
              onChange={e => setCfg(c => ({ ...c, tc_mep: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-slate-200"
            />
            <p className="text-xs text-slate-500 mt-1">Usado para convertir precios USD → ARS en posiciones de Cocos</p>
          </div>
          <div>
            <label className="block text-sm text-slate-300 mb-1 font-medium">TC Blue (ARS/USD)</label>
            <input
              type="number" step="any"
              value={cfg.tc_blue}
              onChange={e => setCfg(c => ({ ...c, tc_blue: e.target.value }))}
              className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-slate-200"
            />
            <p className="text-xs text-slate-500 mt-1">Usado para convertir P&L ARS → USD en posiciones de Cocos</p>
          </div>
          <button
            type="submit"
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-md text-sm font-medium transition-colors"
          >
            <Save size={14} />
            {saved ? '✓ Guardado' : 'Guardar'}
          </button>
        </form>
      </div>

      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 mt-4">
        <div className="flex items-center gap-2 mb-3">
          <Info size={14} className="text-slate-400" />
          <h2 className="font-semibold text-slate-300 text-sm">Cómo funcionan los precios</h2>
        </div>
        <ul className="text-xs text-slate-400 space-y-2">
          <li><span className="text-blue-400 font-medium">Binance:</span> Precios en USD via Yahoo Finance (crypto via CoinGecko)</li>
          <li><span className="text-violet-400 font-medium">Cocos:</span> Precios USD del mercado NYSE/NASDAQ, convertidos a ARS usando TC MEP (precio_ars = precio_usd × TC_MEP)</li>
          <li><span className="text-amber-400 font-medium">Override manual:</span> Podés setear un precio manual por posición (campo "Precio override") para reemplazar el automático</li>
          <li><span className="text-slate-300 font-medium">CEDEARs:</span> Si el precio automático no coincide por ratio de CEDEAR, usá el override manual</li>
        </ul>
      </div>
    </div>
  )
}
