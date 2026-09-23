// ═══════════════════════════════════════════════════════════════════════════
// /admin/pruebas — una fila por persona que está (o estuvo) probando Rendi
// ═══════════════════════════════════════════════════════════════════════════
// El embudo del panel de admin cuenta cabezas al final del camino. Esta página
// contesta la otra pregunta, la que sólo sirve MIENTRAS la prueba corre:
// ¿ESTA persona está enganchando? Al que no cargó nada en tres días se le
// puede escribir; al que ya se le venció, no.
//
// ⭐ LA REGLA DE ESTE ARCHIVO: las columnas se declaran UNA vez, en `COLUMNAS`,
// y de ahí salen las tres cosas — el encabezado, la celda y el CSV. Con una
// lista para la tabla y otra para el export, el día que se agregue una columna
// el CSV sale incompleto y nadie se entera hasta que alguien lo abre en Excel
// y le falta justo la que importaba.
//
// Cada columna tiene:
//   · `get(p)`  → el valor CRUDO. Ordena la tabla y es lo que va al CSV, así
//                 que las fechas van en ISO y los números como números: Excel
//                 no sabe qué hacer con "hace 5 días".
//   · `celda(p)`→ opcional, cómo se dibuja. Puede ser una etiqueta de color o
//                 una barrita; el dato de abajo sigue siendo el mismo.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, RefreshCw, ChevronLeft, ArrowUp, ArrowDown } from 'lucide-react'
import { api } from '../utils/api'
import { pctTxt, nfmt } from '../utils/format'
import { hoyISO } from '../utils/fecha'
import { PageSkeleton } from '../components/Skeleton'

// ── Vocabulario ────────────────────────────────────────────────────────────
const ESTADO = {
  activa:    { txt: 'Probando',  cls: 'bg-data-violet/14 text-data-violet' },
  pago:      { txt: 'Pagó',      cls: 'bg-rendi-pos/14 text-rendi-pos' },
  terminada: { txt: 'Terminada', cls: 'bg-bg-3 text-ink-2' },
}
const USO = {
  avanzando: { txt: 'Avanzando', cls: 'text-rendi-pos' },
  tibio:     { txt: 'Se enfrió', cls: 'text-rendi-warn' },
  frenado:   { txt: 'Frenado',   cls: 'text-rendi-neg' },
  sin_datos: { txt: 'App vacía', cls: 'text-rendi-neg' },
}

// "hace 5 días" en vez de una fecha: lo que se quiere leer de un vistazo es la
// distancia, no el día. Al CSV va la fecha cruda igual.
function haceCuanto(dia, hoy) {
  if (!dia) return null
  const d = Math.round(
    (new Date(hoy + 'T00:00:00') - new Date(dia + 'T00:00:00')) / 86400000)
  if (d <= 0) return 'hoy'
  if (d === 1) return 'ayer'
  return `hace ${d} días`
}

// dd/mm/aaaa para leer, ISO para el CSV.
function fechaCorta(iso) {
  if (!iso) return ''
  const [a, m, d] = String(iso).split('-')
  return `${d}/${m}/${a}`
}

const Tag = ({ cls, children }) => (
  <span className={`inline-block px-1.5 py-0.5 rounded-sm text-[10.5px] font-medium whitespace-nowrap ${cls}`}>
    {children}
  </span>
)

// ── Las columnas, una sola vez ─────────────────────────────────────────────
export function columnas(hoy, totalDias, diasAviso) {
  const nunca = (v, txt) => v
    ? <span className="tabular">{txt}</span>
    : <span className="text-ink-3">nunca importó</span>

  return [
    {
      key: 'usuario', label: 'Usuario', get: p => p.name || '',
      celda: p => <span className="text-ink-0 font-medium">{p.name || '—'}</span>,
    },
    {
      key: 'mail', label: 'Mail', get: p => p.email,
      celda: p => <span className="text-ink-2">{p.email}</span>,
    },
    {
      key: 'estado', label: 'Estado', get: p => ESTADO[p.estado]?.txt || p.estado,
      // El `||` no es decorativo: si el backend agrega un estado nuevo, la
      // celda muestra el código en vez de quedar en blanco.
      celda: p => <Tag cls={ESTADO[p.estado]?.cls || 'bg-bg-3 text-ink-2'}>
        {ESTADO[p.estado]?.txt || p.estado}
      </Tag>,
    },
    {
      key: 'plan', label: 'Plan',
      // Sólo la que está probando tiene etapa: el que pagó ya tiene su plan y
      // a la terminada no le queda ninguna.
      get: p => (p.stage ? (p.stage === 'plus' ? 'Plus' : 'Pro') : ''),
      celda: p => p.stage
        ? <Tag cls={p.stage === 'plus' ? 'bg-bg-3 text-ink-2' : 'bg-data-cyan/12 text-data-cyan'}>
            {p.stage === 'plus' ? 'Plus' : 'Pro'}
          </Tag>
        : <span className="text-ink-3">—</span>,
    },
    {
      key: 'inicio', label: 'Arrancó', get: p => p.inicio,
      celda: p => <span className="text-ink-3 tabular">{fechaCorta(p.inicio)}</span>,
    },
    {
      key: 'dia', label: 'Día', num: true, get: p => p.dia,
      celda: p => (
        <span className="tabular whitespace-nowrap">
          <span className="relative inline-block align-middle w-[52px] h-1 rounded-full bg-bg-3 mr-2">
            <span
              className={`absolute left-0 top-0 bottom-0 rounded-full ${p.estado === 'activa' ? 'bg-data-violet' : 'bg-ink-3'}`}
              style={{ width: `${Math.min(100, Math.round(p.dia / totalDias * 100))}%` }}
            />
          </span>
          <span className={p.estado === 'activa' ? 'text-ink-0 font-medium' : 'text-ink-3'}>{p.dia}</span>
          <span className="text-ink-3">/{totalDias}</span>
        </span>
      ),
    },
    {
      key: 'quedan', label: 'Le queda', num: true,
      get: p => (p.estado === 'activa' ? p.days_left : null),
      celda: p => p.estado !== 'activa'
        ? <span className="text-ink-3">—</span>
        // Se pone ámbar con el MISMO corte con el que sale el mail de aviso.
        : <span className={`tabular ${p.days_left <= diasAviso ? 'text-rendi-warn font-semibold' : 'text-ink-0 font-medium'}`}>
            {p.days_left}
          </span>,
    },
    { key: 'brokers', label: 'Brokers', num: true, get: p => p.tiene.brokers },
    {
      key: 'posiciones', label: 'Posiciones', num: true, get: p => p.tiene.posiciones,
      celda: p => (
        <span className="tabular">
          {nfmt(p.tiene.posiciones, 0)}
          {/* El punto ciego, marcado donde se ve: esas filas no guardan de qué
              día son, así que no aparecen en «Cargó 7d». Sin esta marca, quien
              carga todo a mano se lee igual que quien no hizo nada. */}
          {p.tiene.a_mano > 0 && (
            <span className="text-data-cyan text-[10.5px] ml-1">
              {p.tiene.a_mano >= p.tiene.posiciones + p.tiene.operaciones
                ? 'todas a mano'
                : `${p.tiene.a_mano} a mano`}
            </span>
          )}
        </span>
      ),
    },
    { key: 'operaciones', label: 'Operac.', num: true, get: p => p.tiene.operaciones },
    {
      key: 'carga7', label: 'Cargó 7d', num: true,
      get: p => p.ventanas?.['7']?.filas ?? 0,
      celda: p => {
        const n = p.ventanas?.['7']?.filas ?? 0
        return n
          ? <span className="tabular text-rendi-pos font-semibold">+{nfmt(n, 0)}</span>
          : <span className="text-ink-3">—</span>
      },
    },
    {
      key: 'frecuencia', label: 'Frecuencia', num: true,
      get: p => p.ventanas?.['7']?.dias_entro ?? 0,
      celda: p => (
        <span className="tabular text-ink-1">
          {p.ventanas?.['7']?.dias_entro ?? 0}<span className="text-ink-3">/7 días</span>
        </span>
      ),
    },
    {
      key: 'login', label: 'Último login', get: p => p.ultimo_login,
      celda: p => p.ultimo_login
        ? <span className="tabular">{haceCuanto(p.ultimo_login, hoy)}</span>
        : <span className="text-ink-3">nunca entró</span>,
    },
    {
      key: 'carga', label: 'Última carga', get: p => p.ultima_importacion,
      celda: p => nunca(p.ultima_importacion, haceCuanto(p.ultima_importacion, hoy)),
    },
    {
      key: 'senal', label: 'Señal', get: p => USO[p.estado_uso]?.txt || p.estado_uso,
      celda: p => <span className={USO[p.estado_uso]?.cls || 'text-ink-2'}>
        {USO[p.estado_uso]?.txt || p.estado_uso || '—'}
      </span>,
    },
  ]
}

// ── CSV ────────────────────────────────────────────────────────────────────
// Sale de las MISMAS columnas que la tabla, en el mismo orden, con los valores
// crudos. Separador `;` y BOM porque el Excel en español abre así sin pedir
// nada: con coma mete todo en la columna A y el archivo parece roto.
export function aCSV(cols, filas) {
  const esc = v => {
    if (v == null) return ''
    const s = String(v)
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lineas = [cols.map(c => esc(c.label)).join(';')]
  for (const p of filas) lineas.push(cols.map(c => esc(c.get(p))).join(';'))
  return '﻿' + lineas.join('\r\n')
}

function bajarCSV(texto, nombre) {
  const url = URL.createObjectURL(new Blob([texto], { type: 'text/csv;charset=utf-8;' }))
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── Orden ──────────────────────────────────────────────────────────────────
export function ordenarFilas(filas, col, dir) {
  if (!col) return filas
  const signo = dir === 'asc' ? 1 : -1
  return [...filas].sort((a, b) => {
    const x = col.get(a), y = col.get(b)
    // ⭐ Los vacíos van SIEMPRE al final, ordene como ordene. Si viajaran con
    // el orden, pedir "los que menos tiempo les queda" pondría arriba a los
    // que ya terminaron (que no tienen tiempo) y escondería abajo justo a los
    // que hay que mirar.
    if (x == null && y == null) return 0
    if (x == null) return 1
    if (y == null) return -1
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * signo
    return String(x).localeCompare(String(y), 'es') * signo
  })
}


// ── Resumen ────────────────────────────────────────────────────────────────
// Cada tasa dice de qué está hecha. Sin eso, en dos semanas nadie se acuerda
// qué medía cada número y el panel deja de usarse.
function Tasa({ label, valor, de, def, tono = '', destacada = false }) {
  return (
    <div className={`rounded-lg border p-4 ${destacada
      ? 'border-data-violet/25 bg-gradient-to-b from-data-violet/[0.07] to-transparent'
      : 'border-line bg-bg-1'}`}>
      <div className="text-[11px] uppercase tracking-wider text-ink-3 mb-2">{label}</div>
      <div className={`text-4xl font-semibold tabular leading-none ${tono}`}>
        {valor == null ? <span className="text-ink-3 text-2xl">sin datos</span> : pctTxt(valor)}
      </div>
      <div className="text-xs text-ink-2 mt-2">{de}</div>
      <div className="text-[11px] text-ink-3 mt-2 leading-relaxed">{def}</div>
    </div>
  )
}

function Celda({ n, k, h, alerta = false, tono = '' }) {
  return (
    <div className={`rounded-lg border p-3.5 ${alerta
      ? 'border-rendi-neg/30 bg-gradient-to-b from-rendi-neg/[0.05] to-transparent'
      : 'border-line bg-bg-1'}`}>
      <div className={`text-2xl font-semibold tabular leading-none ${tono}`}>{n}</div>
      <div className="text-[11.5px] text-ink-2 mt-1.5">{k}</div>
      {h && <div className="text-[10.5px] text-ink-3 mt-1">{h}</div>}
    </div>
  )
}

function Resumen({ r, personas, days }) {
  // Sin resumen: el backend no lo manda (deploy viejo). Con resumen en cero:
  // no hay pruebas, y de eso ya avisa la tabla — tres tarjetas diciendo "sin
  // datos" no agregan nada.
  if (!r || !r.total) return null
  const total = r.total || 0
  const tramos = [
    { n: r.en_pro, txt: `${r.en_pro} en Pro`, cls: 'bg-data-violet/85 text-bg-0',
      leg: 'Probando, en los días de Pro' },
    { n: r.en_plus, txt: `${r.en_plus} en Plus`, cls: 'bg-data-violet/45 text-bg-0',
      leg: 'Probando, en los días de Plus' },
    { n: r.pagaron, txt: `${r.pagaron}`, cls: 'bg-rendi-pos-fill text-bg-0', leg: 'Pagaron' },
    // Por resta, no por su propia cuenta: así los cuatro tramos suman el total
    // exacto y la barra no puede quedar corta.
    { n: r.terminadas_sin_pagar, txt: `${r.terminadas_sin_pagar} terminadas`,
      cls: 'bg-bg-3 text-ink-2', leg: 'Se les terminó sin pagar' },
  ].filter(t => t.n > 0)

  // A quién le falta menos, con nombre: un contador sin nombres no se puede
  // accionar, y es justo el que pide acción.
  const porVencer = personas
    .filter(p => p.estado === 'activa' && p.days_left <= r.dias_aviso)
    .sort((a, b) => a.days_left - b.days_left)
    .map(p => `${(p.name || p.email).split(/[ @]/)[0]} (${p.days_left})`)
    .join(' · ')

  return (
    <section className="mt-7">
      <h2 className="text-base font-semibold text-ink-0">Resumen de la tanda</h2>
      <p className="text-xs text-ink-3 mt-0.5 mb-4">
        Las {total} {total === 1 ? 'prueba' : 'pruebas'} de los últimos {days} días.
        Cada número dice abajo de qué está hecho.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 mb-3.5">
        <Tasa
          destacada label="Tasa de uso" valor={r.tasa_uso}
          de={`${r.con_datos} de ${total} llegaron a cargar datos`}
          def={r.sin_datos > 0
            ? `Cuántos llegaron a tener la cartera adentro. Los otros ${r.sin_datos} están probando una app vacía: ahí el problema es el arranque, no el precio.`
            : 'Cuántos llegaron a tener la cartera adentro. No hay ninguno probando una app vacía.'}
        />
        <Tasa
          label="Tasa de abandono" valor={r.tasa_abandono} tono="text-rendi-neg"
          de={`${r.frenados} de ${r.con_datos} cargaron y desaparecieron`}
          def="De los que sí cargaron datos, los que hace más de 7 días que no entran. Es la lista de a quién escribirle."
        />
        <Tasa
          label="Conversión" valor={r.tasa_conversion} tono="text-rendi-pos"
          de={`${r.convirtieron} de ${r.terminadas} que ya terminaron`}
          def="Sobre las pruebas TERMINADAS, no sobre todas: los que siguen probando todavía no tuvieron su chance de decidir."
        />
      </div>

      {total > 0 && (
        <div className="rounded-lg border border-line bg-bg-1 p-4 mb-3.5">
          <div className="text-[11px] uppercase tracking-wider text-ink-3 mb-2.5">
            Dónde está cada una de las {total}
          </div>
          <div className="flex h-6 rounded overflow-hidden gap-0.5">
            {tramos.map(t => (
              <div key={t.leg} className={`flex items-center justify-center text-[11px] font-semibold ${t.cls}`}
                   style={{ width: `${t.n / total * 100}%` }} title={t.leg}>
                {t.n / total > 0.06 ? t.txt : ''}
              </div>
            ))}
          </div>
          <div className="flex gap-4 flex-wrap mt-2.5 text-[11.5px] text-ink-2">
            {tramos.map(t => (
              <span key={t.leg} className="flex items-center gap-1.5">
                <span className={`w-2.5 h-2.5 rounded-xs inline-block ${t.cls}`} />{t.leg}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
        <Celda n={r.en_curso} k="Pruebas en curso" h="activas ahora mismo" />
        <Celda n={r.por_terminar} k={`Se terminan en ≤ ${r.dias_aviso} días`}
               h={porVencer || 'ninguna por ahora'}
               alerta={r.por_terminar > 0} tono={r.por_terminar > 0 ? 'text-rendi-warn' : ''} />
        <Celda n={r.en_pro} k="En los días de Pro" h="día 1 al 10" />
        <Celda n={r.en_plus} k="En los días de Plus" h="día 11 al 20" />
        {/* Éste es el denominador de la conversión —las que ya se vencieron—
            y por eso el pie habla de los que pagaron, no de los que no: es la
            misma frase que la tarjeta de Conversión. El tramo gris de la barra
            cuenta otra cosa y por eso se llama distinto. */}
        <Celda n={r.terminadas} k="Ya se vencieron"
               h={`${r.convirtieron} pagaron`} />
      </div>

      <p className="text-[11px] text-ink-3 mt-4 leading-relaxed">
        <span className="px-1.5 py-0.5 rounded-xs bg-bg-2 text-ink-2 text-[10.5px]">Cómo se cuenta</span>{' '}
        «Cargó 7d» y las fechas de carga salen de las importaciones, que es lo único que queda
        fechado. Lo cargado a mano se ve en la columna de posiciones marcado{' '}
        <span className="text-data-cyan">a mano</span>, pero no en «Cargó 7d»: esas filas no
        guardan de qué día son. «Frecuencia» son los días distintos que entró en la última
        semana. Los días se cuentan en UTC.
      </p>
    </section>
  )
}

// ── La página ──────────────────────────────────────────────────────────────
const FILTROS = [
  { id: 'todas', txt: 'Todas', mira: () => true },
  { id: 'activa', txt: 'Probando', mira: p => p.estado === 'activa' },
  { id: 'terminada', txt: 'Terminadas', mira: p => p.estado === 'terminada' },
  { id: 'pago', txt: 'Pagaron', mira: p => p.estado === 'pago' },
]

export default function AdminPruebas() {
  const [data, setData] = useState(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [days, setDays] = useState(30)
  const [q, setQ] = useState('')
  const [filtro, setFiltro] = useState('todas')
  const [orden, setOrden] = useState({ key: 'carga7', dir: 'desc' })
  // Guard anti-carrera, el mismo patrón que el buscador de /admin: cambiar la
  // ventana dos veces seguidas larga dos pedidos, y el de 30 días puede llegar
  // DESPUÉS del de 180. Sin esto, la pantalla queda mostrando la respuesta
  // vieja con el selector diciendo otra cosa — y no hay ningún error.
  const pedido = useRef(0)

  useEffect(() => { cargar() }, [days])

  async function cargar() {
    const mio = ++pedido.current
    setCargando(true); setError('')
    try {
      const r = await api.get(`/admin/billing/trial-progress?days=${days}`)
      if (mio === pedido.current) setData(r)
    } catch (e) {
      if (mio !== pedido.current) return
      // El 403 es el caso esperable —alguien que no es admin abrió el link— y
      // "HTTP 403" no le dice nada a nadie.
      setError(e?.status === 403
        ? 'Esta página es sólo para administradores.'
        : `No pudimos traer las pruebas: ${e?.message || 'error desconocido'}`)
    } finally {
      if (mio === pedido.current) setCargando(false)
    }
  }

  const personas = data?.personas || []
  const cols = useMemo(
    () => columnas(data?.hoy, data?.total_dias || 20, data?.resumen?.dias_aviso ?? 3),
    [data?.hoy, data?.total_dias, data?.resumen?.dias_aviso])

  const visibles = useMemo(() => {
    const t = q.trim().toLowerCase()
    const f = FILTROS.find(x => x.id === filtro) || FILTROS[0]
    const col = cols.find(c => c.key === orden.key)
    const filas = personas.filter(p => f.mira(p) && (
      !t || (p.email || '').toLowerCase().includes(t) || (p.name || '').toLowerCase().includes(t)))
    return ordenarFilas(filas, col, orden.dir)
  }, [personas, q, filtro, orden, cols])

  function ordenarPor(key) {
    setOrden(o => o.key === key
      ? { key, dir: o.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: cols.find(c => c.key === key)?.num ? 'desc' : 'asc' })
  }

  if (cargando && !data) return <PageSkeleton />

  const r = data?.resumen
  const cuentas = Object.fromEntries(
    FILTROS.map(f => [f.id, personas.filter(f.mira).length]))

  return (
    <div className="max-w-[1560px] mx-auto px-5 sm:px-7 py-6 pb-16">
      <div className="text-xs text-ink-3 mb-2.5">
        <Link to="/admin" className="hover:text-ink-1 inline-flex items-center gap-1">
          <ChevronLeft size={13} /> Admin
        </Link>
        <span className="mx-2">›</span>Pruebas
      </div>

      <div className="flex items-end justify-between gap-4 flex-wrap mb-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink-0 tracking-tight">Pruebas</h1>
          <p className="text-[13px] text-ink-2 mt-1">
            Una fila por persona. {personas.length} en la ventana
            {r?.en_curso > 0 && <> · <span className="text-data-violet">{r.en_curso} probando ahora</span></>}
            {r?.por_terminar > 0 && <> · <span className="text-rendi-warn">
              {r.por_terminar} {r.por_terminar === 1 ? 'se termina' : 'se terminan'} en ≤{r.dias_aviso} días
            </span></>}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={cargar} disabled={cargando}
                  className="inline-flex items-center gap-1.5 px-3 py-2 rounded border border-line-2 bg-bg-2 text-[13px] font-medium text-ink-1 hover:text-ink-0 disabled:opacity-50">
            <RefreshCw size={13} className={cargando ? 'animate-spin' : ''} /> Actualizar
          </button>
          <button
            onClick={() => bajarCSV(aCSV(cols, visibles), `rendi_pruebas_${hoyISO()}.csv`)}
            disabled={!visibles.length}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded border border-data-violet/35 bg-data-violet/12 text-[13px] font-medium text-data-violet disabled:opacity-40">
            <Download size={13} /> Exportar CSV
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap mb-3.5">
        <input
          value={q} onChange={e => setQ(e.target.value)}
          placeholder="Buscar por nombre o mail…" aria-label="Buscar por nombre o mail"
          className="flex-1 min-w-[200px] max-w-[330px] px-3 py-2 rounded border border-line bg-bg-1 text-[13px] text-ink-1 placeholder:text-ink-3 focus:outline-none focus:border-line-3"
        />
        {FILTROS.map(f => (
          <button key={f.id} onClick={() => setFiltro(f.id)}
                  className={`px-3 py-1.5 rounded-full text-[12.5px] border ${
                    filtro === f.id
                      ? 'bg-data-violet/13 border-data-violet/40 text-data-violet'
                      : 'border-line text-ink-2 hover:text-ink-1'}`}>
            {f.txt} · {cuentas[f.id]}
          </button>
        ))}
        <select value={days} onChange={e => setDays(Number(e.target.value))}
                className="ml-auto px-3 py-1.5 rounded border border-line bg-bg-1 text-[12.5px] text-ink-2">
          <option value={30}>Últimos 30 días</option>
          <option value={60}>60 días</option>
          <option value={90}>90 días</option>
          <option value={180}>180 días</option>
        </select>
      </div>

      {/* Si la tanda no entró entera, el resumen de abajo se calculó sobre lo
          que se ve. Decirlo importa: el "total" es justamente el número con el
          que se toman decisiones. */}
      {data?.truncado && (
        <div className="rounded-lg border border-rendi-warn/30 bg-rendi-warn/5 p-3 text-[12px] text-rendi-warn mb-3.5">
          Hay {data.total_en_ventana} pruebas en esta ventana y la tabla muestra las{' '}
          {personas.length} más recientes. El resumen de abajo cuenta sólo esas: para verlas
          todas, achicá la ventana de días.
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rendi-neg/30 bg-rendi-neg/5 p-4 text-[13px] text-rendi-neg mb-4">
          {error}
        </div>
      )}

      <div className="rounded-lg border border-line bg-bg-1 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1380px] border-separate border-spacing-0">
            <thead>
              <tr>
                {cols.map(c => (
                  <th key={c.key} onClick={() => ordenarPor(c.key)}
                      aria-sort={orden.key === c.key
                        ? (orden.dir === 'asc' ? 'ascending' : 'descending')
                        : 'none'}
                      className={`sticky top-0 z-[2] bg-bg-2 px-2.5 py-2.5 text-[10.5px] font-semibold uppercase tracking-wider text-ink-3 whitespace-nowrap border-b border-line-2 cursor-pointer select-none hover:text-ink-2 ${c.num ? 'text-right' : 'text-left'}`}>
                    {c.label}
                    {orden.key === c.key && (
                      orden.dir === 'asc'
                        ? <ArrowUp size={11} className="inline ml-1 text-data-violet" />
                        : <ArrowDown size={11} className="inline ml-1 text-data-violet" />
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibles.map(p => (
                <tr key={p.id} className="hover:bg-bg-2/60">
                  {cols.map(c => (
                    <td key={c.key}
                        className={`px-2.5 py-2.5 border-b border-line/75 text-[12.5px] text-ink-1 whitespace-nowrap ${c.num ? 'text-right' : ''}`}>
                      {/* Los enteros pasan por `nfmt`: en Rendi el punto es el
                          separador de miles en TODA la app, y "12500" en una
                          tabla que al lado dice "12.500" se lee como otro
                          número. Al CSV va el crudo — eso lo da `get`. */}
                      {c.celda
                        ? c.celda(p)
                        : <span className={c.num ? 'tabular' : ''}>
                            {c.num ? nfmt(c.get(p), 0) : (c.get(p) || '—')}
                          </span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!visibles.length && (
          <p className="text-[12.5px] text-ink-3 px-4 py-6 text-center">
            {personas.length
              ? 'Ninguna prueba coincide con el filtro.'
              : `No hay pruebas activas ni terminadas en los últimos ${days} días. La tabla se llena sola cuando alguien verifica su mail: ahí le arranca la prueba.`}
          </p>
        )}
      </div>

      <Resumen r={r} personas={personas} days={days} />
    </div>
  )
}
