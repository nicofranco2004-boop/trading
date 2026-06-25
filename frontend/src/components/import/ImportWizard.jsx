import { useEffect, useRef, useState } from 'react'
import { X, Upload, AlertTriangle, CheckCircle2, Download, FileText, Loader2, Save, Trash2, RotateCcw, Info } from 'lucide-react'
import InfoTooltip from '../InfoTooltip'
import BrokerInstructions from './BrokerInstructions'
import { api } from '../../utils/api'
import { whatsappUrl } from '../../utils/support'
import { WhatsAppIcon } from '../SupportWhatsAppFab'
import { track } from '../../utils/track'

// Explicaciones por campo Rendi — se muestran en un (?) al lado del label.
const FIELD_HELP = {
  fecha: {
    title: 'Fecha de la operación',
    body: 'Cuándo ocurrió el movimiento. Aceptamos YYYY-MM-DD (2024-03-15), DD/MM/YYYY (15/03/2024) y YYYY/MM/DD.',
  },
  tipo: {
    title: 'Tipo de movimiento',
    body: 'Qué clase de operación es: compra, venta, depósito, retiro, dividendo, conversión de moneda, etc. Reconocemos varios nombres en castellano e inglés (Compra/Buy/Bought, Venta/Sell/Sold, Deposit/Depósito, etc.).',
    examples: 'Si todas las filas de tu archivo son del mismo tipo (ej.: solo compras), podés poner el valor fijo "COMPRA" en vez de mapear una columna.',
  },
  broker: {
    title: 'Broker / cuenta',
    body: 'A qué broker o cuenta corresponde la operación. Tiene que coincidir con un broker que ya tengas creado en Rendi.',
    examples: 'Si tu archivo es de un solo broker (ej.: todo IBKR), elegí "IBKR" como valor fijo y no necesitás columna.',
  },
  activo: {
    title: 'Activo / ticker',
    body: 'El símbolo del activo: ej. AAPL, GGAL, BTC, BABA. Solo aplica a compras, ventas y dividendos. Para depósitos y retiros queda vacío.',
  },
  cantidad: {
    title: 'Cantidad de unidades',
    body: 'Cuántas unidades del activo se compraron o vendieron. Para una compra de 10 acciones de AAPL, va 10.',
    examples: 'Si tu archivo no tiene esta columna pero sí tiene precio y monto total, lo calculamos solos (cantidad = monto ÷ precio).',
  },
  precio: {
    title: 'Precio unitario',
    body: 'Precio por unidad del activo al momento de la operación. Si compraste 10 AAPL a USD 180 cada una, va 180.',
    examples: 'Si tu archivo no tiene esta columna pero sí tiene cantidad y monto total, lo calculamos solos (precio = monto ÷ cantidad).',
  },
  monto: {
    title: 'Monto total',
    body: 'Monto total de la operación en la moneda del broker. Para depósitos, retiros y dividendos representa el monto del cash. Para compras y ventas, si lo dejás vacío lo calculamos como cantidad × precio.',
  },
  monto_usd: {
    title: 'Monto en USD',
    body: 'Solo para conversiones de moneda (ARS ↔ USD): los dólares involucrados en la operación. Si compraste USD 1000 con tus pesos, va 1000.',
    examples: 'Si tu archivo no tiene esta columna pero sí tiene monto (ARS) y tc, lo calculamos solos (USD = ARS ÷ TC).',
  },
  tc: {
    title: 'Tipo de cambio',
    body: 'Solo para conversiones de moneda: el TC efectivo de la operación (ARS por USD). Si compraste USD a 1200, va 1200.',
    examples: 'Si tu archivo no tiene esta columna pero sí tiene monto (ARS) y monto_usd, lo calculamos solos (TC = ARS ÷ USD).',
  },
  comisiones: {
    title: 'Comisiones',
    body: 'Comisiones que cobró el broker por la operación. Reducen tu P&L. Si no tenés el dato dejalo en cero.',
  },
  moneda: {
    title: 'Moneda de la operación',
    body: 'En qué moneda está expresado el precio o el monto. Aceptamos USD, USDT y ARS.',
    examples: 'Si todo tu archivo está en USD, ponelo como valor fijo y no necesitás columna.',
  },
  notas: {
    title: 'Notas / descripción',
    body: 'Cualquier comentario adicional. Lo guardamos junto con la operación para referencia, no afecta los cálculos.',
  },
}

const STEP_INTRO = 'intro'    // Paso 0: ¿propio o de un broker? + config inicial
const STEP_UPLOAD = 'upload'
const STEP_MAP = 'map'
const STEP_PREVIEW = 'preview'
const STEP_SEED = 'seed'
const STEP_DONE = 'done'

// Moneda base por plataforma soportada (rama "de un broker"). Define si
// preguntamos por el sub-broker USD (solo brokers ARS lo necesitan) y con qué
// moneda se auto-crea el broker. Si sumás un broker ARS nuevo (ej. IOL),
// agregalo acá. Plataformas no listadas caen a null → sin pregunta de USD ops.
const PLATFORM_BASE_CURRENCY = {
  cocos: 'ARS',
  binance: 'USDT',
  schwab: 'USD',
  ibkr: 'USD',
  bullmarket: 'ARS',
  iol: 'ARS',
}

// Plataformas cuya importación está temporalmente deshabilitada (parser
// incompleto o todavía inexistente — falta data del CSV). La plataforma
// aparece en el dropdown de "Plataforma" para que el user la encuentre por
// nombre, pero al seleccionarla mostramos un card de contacto por WhatsApp
// en vez del uploader, y se bloquea el botón Continuar. Para reactivar:
// borrá la entrada de acá.
//
// Las que NO tienen parser en el backend se inyectan en el dropdown vía
// withBlockedPlatforms(); las que sí lo tienen (ej: Cocos, Balanz, IOL) ya
// vienen del registry, así que no se duplican.
//
// IOL pasó a tener parser nativo (importing/parsers/iol.py) — ya no está acá.
const BLOCKED_IMPORT_PLATFORMS = {}

// Inyecta en la lista de parserGroups las plataformas bloqueadas que NO tienen
// un parser real en el backend, para que aparezcan en el dropdown y disparen el
// card de contacto. No duplica las que ya vienen del registry (Cocos, Balanz,
// IOL…). Hoy BLOCKED_IMPORT_PLATFORMS está vacío → no inyecta nada.
function withBlockedPlatforms(groups) {
  const list = Array.isArray(groups) ? groups : []
  const present = new Set(list.map(g => g.platform))
  const synthetic = Object.entries(BLOCKED_IMPORT_PLATFORMS)
    .filter(([id]) => !present.has(id))
    .map(([id, info]) => ({
      platform: id,
      platform_label: info.label,
      exports: [{ id, label: info.label, supported: false }],
    }))
  return [...list, ...synthetic]
}

const OP_LABELS = {
  BUY: 'Compra',
  SELL: 'Venta',
  DEPOSIT: 'Depósito',
  WITHDRAW: 'Retiro',
  DIVIDEND: 'Dividendo',
  INTEREST: 'Interés',
  FX_ARS_TO_USD: 'Conversión ARS → USD',
  FX_USD_TO_ARS: 'Conversión USD → ARS',
  FEE: 'Comisión',
  TRANSFER: 'Transferencia',
}

export default function ImportWizard({ onClose, onConfirmed, initialPreview = null, redoBanner = null }) {
  const [step, setStep] = useState(initialPreview ? STEP_PREVIEW : STEP_INTRO)

  // Activación: marca la entrada al flujo de import (antes el wizard no emitía
  // ningún evento → no se podía medir cuántos abren vs completan).
  useEffect(() => { track('import_started', { has_initial: !!initialPreview }) }, [])

  // Paso 0: de dónde viene el archivo. null = todavía no eligió.
  //   'broker'   → export de un broker soportado (parser específico)
  //   'personal' → CSV/Excel propio del usuario (parser genérico)
  const [sourceType, setSourceType] = useState(null)
  // Rama 'personal': moneda declarada de las operaciones del archivo. Define
  // el default al crear el broker inline y si preguntamos por ops en USD.
  const [personalCurrency, setPersonalCurrency] = useState(null)  // 'ARS' | 'USD' | null
  // Parsers agrupados por plataforma — alimentan el grid de brokers del Paso 0.
  const [parserGroups, setParserGroups] = useState([])
  const [platform, setPlatform] = useState('generic')
  const [format, setFormat] = useState('rendi_generic')
  // Multi-file: el wizard ahora acepta N CSVs en un mismo import. El backend
  // los combina (manteniendo el header del primero) y los procesa como un
  // solo batch. Ideal para subir un año por archivo de Cocos/IOL/etc.
  const [files, setFiles] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [inspect, setInspect] = useState(null)        // {headers, sample_rows, rendi_fields, suggested_mapping}
  const [mapping, setMapping] = useState({ columns: {}, defaults: {} })
  const [brokers, setBrokers] = useState([])
  // Templates de mapping guardados — se cargan al montar y se actualizan al guardar.
  const [savedTemplates, setSavedTemplates] = useState([])
  // Modo: 'single' = todas las filas son de un broker (no hace falta columna);
  // 'general' = el archivo mezcla varios brokers (mapeo desde columna).
  const [importMode, setImportMode] = useState('single')
  const [singleBroker, setSingleBroker] = useState('')
  const [preview, setPreview] = useState(initialPreview)
  const [confirmResult, setConfirmResult] = useState(null)
  // Set de row_index que el usuario marcó como "omitir en este confirm"
  const [skippedRowIndices, setSkippedRowIndices] = useState(new Set())
  // Estado inicial sintético — solo se manda al backend si hay seed_suggestions
  // y el usuario lo completa.
  // Forma: { seed_date: 'YYYY-MM-DD', brokers: [{broker, cash: {USDT, ARS}, assets: [{symbol, qty, cost_basis_unit}]}] }
  const [seedState, setSeedState] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    api.get('/imports/parsers/grouped')
      .then(g => setParserGroups(withBlockedPlatforms(g)))
      .catch(() => setParserGroups(withBlockedPlatforms([])))
    api.get('/brokers').then(bs => {
      setBrokers(bs)
      if (!singleBroker && bs.length > 0) setSingleBroker(bs[0].name)
    }).catch(() => setBrokers([]))
    api.get('/imports/mappings').then(setSavedTemplates).catch(() => setSavedTemplates([]))
  }, [])

  // Ruteo por moneda: lo decide el BACKEND solo. Si un broker ARS trae filas
  // en USD (compras dólar-MEP, depósitos USD, etc.), el pipeline las separa a
  // un sub-broker "<Padre> · USD". La moneda de cada fila es inequívoca (la
  // trae el parser), así que ya no le preguntamos al usuario — antes el toggle
  // manual hacía que el cash en pesos cayera en un bucket USD si elegía mal.
  // Caveat aceptado: si comprás el MISMO CEDEAR en ARS y en USD y después lo
  // vendés, la posición queda partida entre el padre y el sibling (raro).

  async function saveTemplate(name) {
    if (!name?.trim()) return
    try {
      const saved = await api.post('/imports/mappings', { name: name.trim(), mapping })
      setSavedTemplates(t => {
        const others = t.filter(x => x.name !== saved.name)
        return [...others, saved].sort((a, b) => a.name.localeCompare(b.name))
      })
      return saved
    } catch (ex) {
      setError(ex.message || 'No se pudo guardar la plantilla.')
    }
  }

  async function deleteTemplate(id) {
    try {
      await api.delete(`/imports/mappings/${id}`)
      setSavedTemplates(t => t.filter(x => x.id !== id))
    } catch (ex) {
      setError(ex.message || 'No se pudo borrar la plantilla.')
    }
  }

  function loadTemplate(template) {
    if (!template) return
    setMapping({
      columns: { ...(template.mapping?.columns || {}) },
      defaults: { ...(template.mapping?.defaults || {}) },
    })
  }

  function reset() {
    setStep(STEP_INTRO)
    setSourceType(null)
    setPersonalCurrency(null)
    setPlatform('generic')
    setFormat('rendi_generic')
    setImportMode('single')
    setFiles([])
    setInspect(null)
    setMapping({ columns: {}, defaults: {} })
    setPreview(null)
    setConfirmResult(null)
    setSkippedRowIndices(new Set())
    setSeedState(null)
    setError(null)
  }

  // Crea un broker desde el Paso 0 (rama propio) sin salir del wizard. Reusa
  // POST /brokers, lo agrega al estado y lo deja seleccionado como destino.
  async function createBrokerInline(name, currency) {
    const clean = (name || '').trim()
    if (!clean) { setError('Poné un nombre para el broker.'); return false }
    setError(null)
    try {
      const created = await api.post('/brokers', { name: clean, currency })
      setBrokers(prev => [...prev, created])
      setSingleBroker(created.name)
      return true
    } catch (ex) {
      setError(ex.message || 'No se pudo crear el broker.')
      return false
    }
  }

  // Rama "de un broker" (Paso 0): elegir un broker soportado. Setea el parser
  // específico (el backend auto-crea el broker, por eso singleBroker queda
  // vacío) para que el upload salte el mapeo y vaya directo a preview.
  function chooseBrokerPlatform(group) {
    setSourceType('broker')
    setImportMode('single')
    setSingleBroker('')
    setPlatform(group.platform)
    const supported = (group.exports || []).find(e => e.supported) || group.exports?.[0]
    if (supported) setFormat(supported.id)
  }

  // Rama "archivo propio" (Paso 0): parser genérico + mapeo manual. Resetea
  // cualquier parser específico que hubiera quedado de una elección previa.
  function choosePersonal() {
    setSourceType('personal')
    setPlatform('generic')
    setFormat('rendi_generic')
    setImportMode('single')
  }

  function toggleSkipRow(rowIndex) {
    setSkippedRowIndices(prev => {
      const next = new Set(prev)
      if (next.has(rowIndex)) next.delete(rowIndex)
      else next.add(rowIndex)
      return next
    })
  }

  // Aplica el broker single al mapping.defaults cuando el modo lo amerita.
  // Sobrescribe cualquier columna mapeada para 'broker' (single-mode manda).
  function applyImportMode(currentMapping) {
    if (importMode === 'single' && singleBroker) {
      const cols = { ...(currentMapping.columns || {}) }
      delete cols.broker
      return {
        columns: cols,
        defaults: { ...(currentMapping.defaults || {}), broker: singleBroker },
      }
    }
    // En modo general no tocamos lo que el auto-detect haya sugerido para broker.
    return currentMapping
  }

  async function downloadTemplate() {
    setError(null)
    try {
      const res = await fetch(`/api/imports/template?format=${format}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `rendi_template_${format}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (ex) {
      setError(`No se pudo descargar el template: ${ex.message}`)
    }
  }

  const singleBrokerObj = brokers.find(b => b.name === singleBroker)
  // Moneda "de contexto": en la rama broker la define la plataforma elegida
  // (Cocos=ARS, Schwab=USD, etc.); en la rama propio la define la elección de
  // moneda del Paso 0 (o, si ya hay broker destino, su moneda).
  const effectiveCurrency = sourceType === 'broker'
    ? (PLATFORM_BASE_CURRENCY[platform] || null)
    : (personalCurrency || singleBrokerObj?.currency || null)
  const isArsContext = effectiveCurrency === 'ARS'
  // El ruteo USD→sub-broker lo decide el backend (auto-detección por moneda de
  // cada fila). Acá solo reflejamos su decisión para los chips/resúmenes del
  // wizard, una vez que el preview volvió.
  const useCurrencyRouting = !!preview?.route_by_currency

  // Parsers específicos (Binance, Cocos, etc.) ya saben qué significa cada
  // columna del archivo del broker — no hace falta que el usuario mapee.
  const isSpecificParser = format && format !== 'rendi_generic'

  // Plataforma con importación bloqueada (ver BLOCKED_IMPORT_PLATFORMS).
  const isBlockedPlatform = !!BLOCKED_IMPORT_PLATFORMS[platform]

  async function uploadAndInspect() {
    if (!files || files.length === 0) {
      setError('Seleccioná al menos un archivo CSV.')
      return
    }
    // Cuando usás un parser específico (Binance/Balanz), el broker viene
    // hardcoded del parser — no exigimos picarlo en el wizard.
    if (importMode === 'single' && !singleBroker && !isSpecificParser) {
      setError('Elegí el broker al que pertenece este archivo.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      // Para parsers específicos saltamos el Map step y vamos directo al Preview.
      if (isSpecificParser) {
        const fd = new FormData()
        files.forEach(f => fd.append('files', f))
        fd.append('format', format)
        if (importMode === 'single' && singleBroker) {
          fd.append('broker', singleBroker)
        }
        // route_by_currency lo decide el backend solo (auto-detección por moneda).
        const data = await api.upload('/imports/preview', fd)
        setPreview(data)
        setStep(STEP_PREVIEW)
        return
      }
      // Genérico: inspect → map → preview. Inspect lee solo el primer archivo
      // (los demás deben tener el mismo header — se valida al subirlos juntos).
      const fd = new FormData()
      fd.append('file', files[0])
      const data = await api.upload('/imports/inspect', fd)
      setInspect(data)
      const initial = {
        columns: { ...(data.suggested_mapping?.columns || {}) },
        defaults: { ...(data.suggested_mapping?.defaults || {}) },
      }
      setMapping(applyImportMode(initial))
      setStep(STEP_MAP)
    } catch (ex) {
      setError(ex.message || 'Error al leer el archivo.')
    } finally {
      setBusy(false)
    }
  }

  async function confirmMapping() {
    // Validar required fields
    const missing = (inspect?.rendi_fields || []).filter(f => {
      if (!f.required) return false
      const hasCol = !!mapping.columns?.[f.id]
      const hasDef = !!mapping.defaults?.[f.id]
      return !hasCol && !hasDef
    })
    if (missing.length > 0) {
      setError(`Falta mapear: ${missing.map(f => f.label).join(', ')}`)
      return
    }
    setError(null)
    setBusy(true)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))
      fd.append('format', 'rendi_generic')
      fd.append('mapping', JSON.stringify(mapping))
      // route_by_currency lo decide el backend solo (auto-detección por moneda).
      const data = await api.upload('/imports/preview', fd)
      setPreview(data)
      setStep(STEP_PREVIEW)
    } catch (ex) {
      setError(ex.message || 'Error al previsualizar el archivo.')
    } finally {
      setBusy(false)
    }
  }

  // Inicializa el seedState con valores en cero a partir de las seed_suggestions
  // del backend. Lo llamamos cuando el usuario entra al step SEED.
  function initSeedStateFromSuggestions() {
    const sug = preview?.seed_suggestions
    if (!sug) return null
    const brokers = (sug.brokers || []).map(b => ({
      broker: b.broker,
      broker_currency: b.broker_currency,
      cash_overdraft: b.cash_overdraft || {},
      // Saldo que da el CSV por moneda (puede ser negativo). El campo `cash` ahora
      // guarda el SALDO ACTUAL que tipea el user; el depósito inicial se back-calcula
      // en buildSeedPayload como (saldo_actual − final_balance).
      final_balance: b.final_balance || {},
      cash: Object.fromEntries(
        Object.keys(b.cash_overdraft || {}).map(c => [c, ''])
      ),
      assets: (b.assets || []).map(a => ({
        symbol: a.symbol,
        qty: String(a.min_qty || ''),
        cost_basis_unit: '',
        min_qty: a.min_qty,
        // exact_qty: la cantidad es conocida y fija (posición transferida) — el
        // user solo completa el precio. Sin esto (sell sin compra previa) la qty
        // es un mínimo editable.
        exact_qty: !!a.exact_qty,
        reason: a.reason || '',
      })),
    }))
    return {
      seed_date: sug.seed_date,
      earliest_csv_date: sug.earliest_csv_date,
      brokers,
    }
  }

  function buildSeedPayload() {
    if (!seedState) return null
    const brokers = (seedState.brokers || [])
      .map(b => ({
        broker: b.broker,
        // Moneda del broker — el backend la usa como moneda de las compras
        // sintéticas cuando no hay cash declarado (posiciones transferidas).
        broker_currency: b.broker_currency,
        // El user tipea su SALDO ACTUAL; el depósito inicial que necesita el
        // backend = saldo_actual − saldo_que_da_el_CSV (final_balance, puede ser
        // negativo). Solo mandamos si el depósito da > 0.
        cash: Object.fromEntries(
          Object.entries(b.cash || {})
            .filter(([_, v]) => v !== '')
            .map(([cur, v]) => {
              const F = Number(b.final_balance?.[cur] || 0)
              return [cur, Number(v) - F]   // ajuste = saldo_real − estimado (+ o −)
            })
            // Mandamos el ajuste sea POSITIVO (faltaba plata previa) o NEGATIVO
            // (el cash estimado por los trades quedó más alto que el real — típico
            // en imports cross-currency/MEP). El backend lo aplica como depósito o
            // retiro sintético. Antes el filtro `>0` descartaba el caso negativo,
            // así que la corrección del usuario "hacia abajo" se ignoraba.
            .filter(([_, adj]) => Math.abs(adj) > 0.005)
        ),
        assets: (b.assets || [])
          // Las de cantidad exacta (posiciones transferidas) SIEMPRE se incluyen,
          // aunque el user no haya puesto precio: se crean con costo 0 (editable
          // luego) para no volver a perderlas. Las de qty mínima (sell sin compra
          // previa) siguen siendo opcionales — solo si el user cargó el precio.
          .filter(a => a.symbol && Number(a.qty) > 0 && (a.cost_basis_unit !== '' || a.exact_qty))
          .map(a => ({
            symbol: a.symbol.trim().toUpperCase(),
            qty: Number(a.qty),
            cost_basis_unit: a.cost_basis_unit === '' ? 0 : Number(a.cost_basis_unit),
          })),
      }))
      .filter(b => Object.keys(b.cash).length > 0 || b.assets.length > 0)
    if (brokers.length === 0) return null
    return { seed_date: seedState.seed_date, brokers }
  }

  // Llamar a confirm con o sin seed_state (según haya o no datos cargados)
  async function confirm({ withSeed = false } = {}) {
    if (!preview?.session_id) return
    setBusy(true)
    setError(null)
    try {
      const seedPayload = withSeed ? buildSeedPayload() : null
      const data = await api.post('/imports/confirm', {
        session_id: preview.session_id,
        skip_row_indices: Array.from(skippedRowIndices),
        seed_state: seedPayload,
      })
      setConfirmResult(data)
      setStep(STEP_DONE)
      // Activación: el import completado es el camino principal a "cargué mi
      // cartera". Antes el wizard no emitía NINGÚN evento → embudo invisible.
      track('import_completed', { broker: format, rows: data?.imported ?? data?.rows ?? null })
      onConfirmed?.(data)
    } catch (ex) {
      track('import_failed', { stage: 'confirm', error: ex?.message || 'unknown' })
      setError(ex.message || 'Error al confirmar el import.')
    } finally {
      setBusy(false)
    }
  }

  // Acción del botón que lleva al paso de cash/precios (seed) desde el preview
  function goToSeedStep() {
    if (!seedState) {
      const initial = initSeedStateFromSuggestions()
      if (initial) setSeedState(initial)
    }
    setStep(STEP_SEED)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto">
      <div className="bg-white dark:bg-bg-2 border border-line rounded-t-2xl sm:rounded-xl w-full max-w-3xl shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line flex-shrink-0">
          <h2 className="font-semibold text-ink-0 text-sm sm:text-base">
            Importar CSV
          </h2>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-2 dark:hover:text-ink-0">
            <X size={18} />
          </button>
        </div>

        <Stepper
          step={step}
          skipMap={isSpecificParser}
          hasSeed={!!preview?.seed_suggestions?.needed}
          hasSeedAssets={(preview?.seed_suggestions?.brokers || []).some(b => (b.assets || []).length > 0)}
        />

        <div className="p-5 overflow-y-auto flex-1">
          {error && (
            <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm">
              <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {step === STEP_INTRO && (
            <IntroStep
              parserGroups={parserGroups}
              sourceType={sourceType} setSourceType={setSourceType}
              platform={platform}
              onChooseBroker={chooseBrokerPlatform}
              onChoosePersonal={choosePersonal}
              personalCurrency={personalCurrency} setPersonalCurrency={setPersonalCurrency}
              importMode={importMode} setImportMode={setImportMode}
              brokers={brokers}
              singleBroker={singleBroker} setSingleBroker={setSingleBroker}
              onCreateBroker={createBrokerInline}
              effectiveCurrency={effectiveCurrency}
              isArsContext={isArsContext}
            />
          )}

          {step === STEP_UPLOAD && (
            <UploadStep
              sourceType={sourceType}
              platform={platform}
              format={format}
              parserGroups={parserGroups}
              files={files} setFiles={setFiles}
              downloadTemplate={downloadTemplate}
              inputRef={inputRef}
              importMode={importMode}
              singleBroker={singleBroker}
              effectiveCurrency={effectiveCurrency}
              isArsContext={isArsContext}
              useCurrencyRouting={useCurrencyRouting}
              onBack={() => setStep(STEP_INTRO)}
            />
          )}

          {step === STEP_MAP && inspect && (
            <MapStep
              inspect={inspect}
              mapping={mapping}
              setMapping={setMapping}
              brokers={brokers}
              importMode={importMode}
              singleBroker={singleBroker}
              useCurrencyRouting={useCurrencyRouting}
              savedTemplates={savedTemplates}
              onSaveTemplate={saveTemplate}
              onDeleteTemplate={deleteTemplate}
              onLoadTemplate={loadTemplate}
            />
          )}

          {step === STEP_PREVIEW && preview && (
            <PreviewStep
              preview={preview}
              importMode={importMode}
              singleBroker={singleBroker}
              useCurrencyRouting={useCurrencyRouting}
              skippedRowIndices={skippedRowIndices}
              onToggleSkipRow={toggleSkipRow}
              onSeedClick={goToSeedStep}
              redoBanner={redoBanner}
            />
          )}

          {step === STEP_SEED && preview?.seed_suggestions && (
            <SeedStep
              suggestions={preview.seed_suggestions}
              seedState={seedState}
              setSeedState={setSeedState}
            />
          )}

          {step === STEP_DONE && confirmResult && (
            <DoneStep result={confirmResult} />
          )}
        </div>

        <div className="flex justify-between gap-2 px-5 py-3 border-t border-line flex-shrink-0">
          <div>
            {step === STEP_UPLOAD && (
              <button
                onClick={() => setStep(STEP_INTRO)}
                className="px-3 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
              >
                ← Volver
              </button>
            )}
            {step === STEP_MAP && (
              <button
                onClick={() => setStep(STEP_UPLOAD)}
                className="px-3 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
              >
                ← Volver
              </button>
            )}
            {step === STEP_PREVIEW && (
              <button
                onClick={() => setStep(isSpecificParser ? STEP_UPLOAD : STEP_MAP)}
                className="px-3 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
              >
                {isSpecificParser ? '← Volver' : '← Ajustar mapeo'}
              </button>
            )}
            {step === STEP_SEED && (
              <button
                onClick={() => setStep(STEP_PREVIEW)}
                className="px-3 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
              >
                ← Volver a vista previa
              </button>
            )}
          </div>
          <div className="flex gap-2">
            {step !== STEP_DONE && (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
              >
                Cancelar
              </button>
            )}
            {step === STEP_INTRO && (() => {
              // Habilitar "Continuar" solo cuando el Paso 0 está completo:
              //  • broker: eligió un broker soportado (parser específico seteado)
              //  • personal: eligió moneda y (mezcla, o un broker destino)
              const canContinue = sourceType === 'broker'
                ? isSpecificParser
                : sourceType === 'personal'
                  ? !!personalCurrency && (importMode === 'general' || !!singleBroker)
                  : false
              return (
                <button
                  onClick={() => { setError(null); setStep(STEP_UPLOAD) }}
                  disabled={!canContinue}
                  className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  Continuar
                </button>
              )
            })()}
            {step === STEP_UPLOAD && !isBlockedPlatform && (
              <button
                onClick={uploadAndInspect}
                disabled={busy || files.length === 0}
                className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                {isSpecificParser ? 'Generar vista previa' : 'Continuar'}
              </button>
            )}
            {step === STEP_MAP && (
              <button
                onClick={confirmMapping}
                disabled={busy}
                className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                Generar vista previa
              </button>
            )}
            {step === STEP_PREVIEW && (() => {
              const valid = preview?.summary?.valid_rows || 0
              const invalid = preview?.summary?.invalid_rows || 0
              const skipped = skippedRowIndices.size
              const toImport = Math.max(0, valid - skipped)
              const totalSkip = invalid + skipped
              const hasSeedSug = !!preview?.seed_suggestions?.needed
              const seedHasAssets = (preview?.seed_suggestions?.brokers || []).some(b => (b.assets || []).length > 0)
              // Si falta el saldo inicial, NO dejamos confirmar acá: el único
              // camino hacia adelante es ir a resolverlo (paso siguiente). Así
              // nadie importa con la caja en negativo sin querer.
              if (hasSeedSug) {
                return (
                  <button
                    onClick={goToSeedStep}
                    className="px-4 py-2 text-sm rounded-md font-semibold transition bg-rendi-accent hover:bg-rendi-accent/90 text-white flex items-center gap-2"
                  >
                    {seedHasAssets ? 'Completar mis datos →' : 'Confirmar mi cash →'}
                  </button>
                )
              }
              const label = totalSkip > 0
                ? `Importar ${toImport} filas (omitir ${totalSkip})`
                : 'Confirmar e importar'
              return (
                <button
                  onClick={() => confirm({ withSeed: false })}
                  disabled={busy || toImport === 0}
                  className="px-4 py-2 text-sm rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 bg-rendi-accent hover:bg-rendi-accent/90 text-white"
                >
                  {busy && <Loader2 size={14} className="animate-spin" />}
                  {label}
                </button>
              )
            })()}
            {step === STEP_SEED && (() => {
              // No dejamos cerrar hasta que cada cuenta con saldo negativo tenga
              // su monto confirmado (con el tick "es el mismo monto" o tipeando
              // el real). El cash queda "resuelto" cuando el input no está vacío.
              // OBLIGATORIO: hay que confirmar el saldo de HOY de TODAS las
              // monedas que se muestran — no solo las que dieron negativo. Un
              // import sin depósitos (ej. Balanz) deja el cash mal; si el user
              // saltea este paso, la cartera queda con saldos fantasma. Cada
              // moneda mostrada debe tener un valor (tipeado o vía "es el mismo").
              const cashComplete = (seedState?.brokers || []).every(b => {
                const currencies = new Set([
                  ...Object.keys(b.cash_overdraft || {}),
                  ...Object.keys(b.cash || {}),
                ])
                if (b.broker_currency) currencies.add(b.broker_currency)
                return Array.from(currencies).every(cur => {
                  const v = b.cash?.[cur]
                  return v !== '' && v != null
                })
              })
              // Las posiciones de cantidad EXACTA (transferidas / compras sin
              // precio) deben tener un precio cargado — o el user tocó "No sé el
              // precio" (que setea 0). Las de qty mínima (ventas sin compra) son
              // opcionales. Sin esto, alguien podía pasar de largo y dejarlas mal.
              const assetsComplete = (seedState?.brokers || []).every(b =>
                (b.assets || []).every(a =>
                  !a.exact_qty || (a.cost_basis_unit !== '' && a.cost_basis_unit != null)
                )
              )
              const seedComplete = cashComplete && assetsComplete
              return (
                <div className="flex flex-col items-end gap-1">
                  <button
                    onClick={() => confirm({ withSeed: true })}
                    disabled={busy || !seedComplete}
                    className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    {busy && <Loader2 size={14} className="animate-spin" />}
                    Confirmar e importar
                  </button>
                  {!seedComplete && (
                    <span className="text-[11px] text-ink-3">
                      {!cashComplete
                        ? 'Confirmá el cash de cada cuenta para seguir.'
                        : 'Completá el precio de cada posición (o tocá "No sé el precio").'}
                    </span>
                  )}
                </div>
              )
            })()}
            {step === STEP_DONE && (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition"
              >
                Cerrar
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}


function Stepper({ step, skipMap, hasSeed, hasSeedAssets }) {
  const baseSteps = skipMap
    ? [
        { id: STEP_INTRO, label: 'Inicio' },
        { id: STEP_UPLOAD, label: 'Archivo' },
        { id: STEP_PREVIEW, label: 'Previsualización' },
      ]
    : [
        { id: STEP_INTRO, label: 'Inicio' },
        { id: STEP_UPLOAD, label: 'Archivo' },
        { id: STEP_MAP, label: 'Mapear columnas' },
        { id: STEP_PREVIEW, label: 'Previsualización' },
      ]
  const seedSteps = hasSeed ? [{ id: STEP_SEED, label: hasSeedAssets ? 'Cash y precios' : 'Tu cash' }] : []
  const steps = [...baseSteps, ...seedSteps, { id: STEP_DONE, label: 'Listo' }]
  // Si el step actual es SEED pero hasSeed=false (caso transitorio), igual lo
  // resaltamos comparando por id.
  const idx = steps.findIndex(s => s.id === step)
  return (
    <div className="flex items-center gap-2 px-5 py-3 border-b border-line bg-bg-2 dark:bg-bg-1/40 text-xs text-ink-3">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center gap-2">
          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-semibold
            ${i <= idx ? 'bg-rendi-accent text-white' : 'bg-bg-2 dark:bg-bg-2 text-ink-3'}`}>
            {i + 1}
          </span>
          <span className={i === idx ? 'text-ink-0 font-medium' : ''}>{s.label}</span>
          {i < steps.length - 1 && <span className="mx-1 text-ink-3">›</span>}
        </div>
      ))}
    </div>
  )
}


// ─── Paso 0 — IntroStep ──────────────────────────────────────────────────────
// Dos preguntas antes de subir nada:
//   1. ¿El archivo es de un broker o es propio?
//      • broker  → grid de brokers soportados (parser específico, auto-crea el
//        broker). "No encuentro mi broker" → CTA WhatsApp (acá entra cualquier
//        broker sin parser dedicado).
//      • propio  → moneda + broker destino (elegir o crear inline) + mezcla.
//   2. Moneda: en la rama broker la define la plataforma; en la propia, la elige
//      el user. Si es ARS, se pregunta por operaciones en USD (sub-broker).
function IntroStep({ parserGroups, sourceType, setSourceType, platform,
                     onChooseBroker, onChoosePersonal, personalCurrency, setPersonalCurrency,
                     importMode, setImportMode, brokers, singleBroker, setSingleBroker,
                     onCreateBroker, isArsContext }) {
  // Brokers soportados para la rama "de un broker": del registry, excluyendo el
  // genérico y cualquier plataforma bloqueada (BLOCKED_IMPORT_PLATFORMS).
  const supportedBrokers = (parserGroups || []).filter(g =>
    g.platform !== 'generic' &&
    !BLOCKED_IMPORT_PLATFORMS[g.platform] &&
    (g.exports || []).some(e => e.supported)
  )
  const brokerLabel = supportedBrokers.find(g => g.platform === platform)?.platform_label

  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  async function handleCreate() {
    setCreating(true)
    const ok = await onCreateBroker(newName, personalCurrency === 'ARS' ? 'ARS' : 'USD')
    setCreating(false)
    if (ok) { setShowCreate(false); setNewName('') }
  }

  const bigCard = (active) =>
    `text-left px-4 py-3.5 rounded-lg border transition ${
      active ? 'border-rendi-accent bg-rendi-accent/10' : 'border-line hover:border-line-2'
    }`

  return (
    <div className="space-y-5">
      {/* ── P1: origen del archivo ───────────────────────────────────── */}
      <div>
        <label className="block text-sm font-medium text-ink-0 mb-2">¿De dónde viene este archivo?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button type="button" onClick={() => setSourceType('broker')} className={bigCard(sourceType === 'broker')}>
            <div className="text-sm font-medium text-ink-0">El export de mi broker</div>
            <div className="text-xs text-ink-3 mt-0.5">Lo descargaste de Cocos, Binance, Schwab, etc.</div>
          </button>
          <button type="button" onClick={onChoosePersonal} className={bigCard(sourceType === 'personal')}>
            <div className="text-sm font-medium text-ink-0">Un archivo propio</div>
            <div className="text-xs text-ink-3 mt-0.5">Un CSV o Excel que armaste vos.</div>
          </button>
        </div>
      </div>

      {/* ── Rama: de un broker ───────────────────────────────────────── */}
      {sourceType === 'broker' && (
        <div className="space-y-3">
          <label className="block text-xs text-ink-3">Elegí tu broker</label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {supportedBrokers.map(g => {
              const active = platform === g.platform
              const cur = PLATFORM_BASE_CURRENCY[g.platform]
              return (
                <button
                  key={g.platform}
                  type="button"
                  onClick={() => onChooseBroker(g)}
                  className={`flex items-center justify-between gap-2 px-3 py-2.5 rounded-md border text-left transition ${
                    active ? 'border-rendi-accent bg-rendi-accent/10' : 'border-line hover:border-line-2'
                  }`}
                >
                  <span className="text-sm font-medium text-ink-0 truncate">{g.platform_label}</span>
                  {cur && <span className="text-[10px] font-mono text-ink-3 flex-shrink-0">{cur}</span>}
                </button>
              )
            })}
          </div>

          {/* No encuentro mi broker → WhatsApp (brokers sin parser dedicado) */}
          <a
            href={whatsappUrl('Hola, quiero importar a Rendi operaciones de un broker que todavía no está en la lista. Mi broker es: ')}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-xs text-ink-2 hover:text-ink-0 transition-colors"
          >
            <WhatsAppIcon size={14} />
            <span>No encuentro mi broker — <span className="underline underline-offset-2">escribinos y lo agregamos</span></span>
          </a>

          {/* Cómo descargar el CSV del broker elegido */}
          {platform && platform !== 'generic' && (
            <BrokerInstructions lockBrokerId={platform} />
          )}
        </div>
      )}

      {/* ── Rama: archivo propio ─────────────────────────────────────── */}
      {sourceType === 'personal' && (
        <div className="space-y-4">
          {/* P2: moneda */}
          <div>
            <label className="block text-xs text-ink-3 mb-2">¿En qué moneda están las operaciones?</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setPersonalCurrency('ARS')}
                className={`text-sm px-3 py-2 rounded-md border transition ${
                  personalCurrency === 'ARS' ? 'border-rendi-accent bg-rendi-accent/10 text-ink-0 font-medium'
                                             : 'border-line text-ink-2 hover:border-line-2'
                }`}
              >
                Pesos (ARS)
              </button>
              <button
                type="button"
                onClick={() => setPersonalCurrency('USD')}
                className={`text-sm px-3 py-2 rounded-md border transition ${
                  personalCurrency === 'USD' ? 'border-rendi-accent bg-rendi-accent/10 text-ink-0 font-medium'
                                             : 'border-line text-ink-2 hover:border-line-2'
                }`}
              >
                Dólares (USD)
              </button>
            </div>
          </div>

          {/* Broker destino (solo si no es mezcla) */}
          {personalCurrency && importMode !== 'general' && (
            <div>
              <label className="block text-xs text-ink-3 mb-1">¿A qué broker se importan estas operaciones?</label>
              {brokers.length > 0 && !showCreate && (
                <select
                  value={singleBroker}
                  onChange={e => setSingleBroker(e.target.value)}
                  className="w-full bg-bg-2 dark:bg-bg-2 border border-line-2 rounded-md px-3 py-2 text-sm text-ink-0"
                >
                  <option value="">Elegí un broker…</option>
                  {brokers.map(b => <option key={b.id} value={b.name}>{b.name} ({b.currency})</option>)}
                </select>
              )}
              {!showCreate ? (
                <button
                  type="button"
                  onClick={() => setShowCreate(true)}
                  className="mt-2 text-xs text-rendi-accent hover:underline"
                >
                  + Crear un broker nuevo
                </button>
              ) : (
                <div className="mt-2 p-3 rounded-md border border-line bg-bg-2/40 space-y-2">
                  <input
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    autoFocus
                    placeholder="Nombre del broker (ej.: Mi cuenta IOL)"
                    className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
                  />
                  <div className="text-[11px] text-ink-3">
                    Se crea en {personalCurrency === 'ARS' ? 'pesos (ARS)' : 'dólares (USD)'} — la moneda que elegiste arriba.
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={handleCreate}
                      disabled={creating || !newName.trim()}
                      className="text-xs bg-rendi-accent text-white rounded-md px-3 py-1.5 font-medium disabled:opacity-50"
                    >
                      {creating ? 'Creando…' : 'Crear broker'}
                    </button>
                    <button
                      type="button"
                      onClick={() => { setShowCreate(false); setNewName('') }}
                      className="text-xs text-ink-3 hover:text-ink-0 px-2"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Avanzado: mezcla de brokers */}
          {personalCurrency && (
            <button
              type="button"
              onClick={() => setImportMode(importMode === 'general' ? 'single' : 'general')}
              className="text-xs text-ink-3 hover:text-ink-1 transition-colors underline underline-offset-2"
            >
              {importMode === 'general'
                ? '← Mi archivo es de un solo broker'
                : 'Mi archivo mezcla varios brokers (tiene una columna que lo indica)'}
            </button>
          )}
          {importMode === 'general' && (
            <p className="text-xs text-ink-3 px-3 py-2 rounded-md bg-bg-2/60 border border-line">
              En el paso de mapeo vas a indicar qué columna del archivo dice a qué broker pertenece cada fila. Los brokers que no existan se crean automáticamente.
            </p>
          )}
        </div>
      )}
    </div>
  )
}


// ─── UploadStep ──────────────────────────────────────────────────────────────
// Después del Paso 0 ya sabemos origen + broker + moneda. Acá solo: resumen de
// lo elegido (con "Cambiar"), instrucciones de descarga (rama broker) o template
// (rama propia), y el dropzone de archivos.
function UploadStep({ sourceType, platform, format, parserGroups = [], files, setFiles,
                      downloadTemplate, inputRef, importMode, singleBroker,
                      effectiveCurrency, isArsContext, useCurrencyRouting, onBack }) {
  const [fileError, setFileError] = useState(null)
  const isSpecific = sourceType === 'broker' && format && format !== 'rendi_generic'
  const brokerLabel = (parserGroups || []).find(g => g.platform === platform)?.platform_label || platform

  // Acumula files (no reemplaza). Dedup por (name, size). Sin auto-detección:
  // el broker/parser ya se eligió explícitamente en el Paso 0.
  function pickFiles(newFiles) {
    if (!newFiles || newFiles.length === 0) return
    const incoming = Array.from(newFiles)
    const errors = []
    const valid = []
    for (const f of incoming) {
      const name = (f.name || '').toLowerCase()
      if (!(name.endsWith('.csv') || name.endsWith('.txt') || name.endsWith('.xlsx') || name.endsWith('.xls'))) {
        errors.push(`"${f.name}" no es un CSV ni Excel.`)
        continue
      }
      valid.push(f)
    }
    let dupCount = 0
    setFiles(prev => {
      const seen = new Set(prev.map(f => `${f.name}::${f.size}`))
      const merged = [...prev]
      for (const f of valid) {
        const key = `${f.name}::${f.size}`
        if (seen.has(key)) dupCount++
        else { merged.push(f); seen.add(key) }
      }
      return merged
    })
    if (errors.length > 0) {
      const hasPdf = errors.some(e => /\.pdf/i.test(e))
      const hasXlsx = errors.some(e => /\.xlsx?/i.test(e))
      let helpText = ' Aceptamos CSV, Excel (.xls, .xlsx) y TXT. '
      if (hasPdf) helpText += 'Si tu broker exportó un PDF, buscá la opción "Exportar a CSV" o "Descargar movimientos en CSV".'
      else if (hasXlsx) helpText += 'Abrí el Excel y guardalo como CSV (Archivo → Guardar como → Tipo: CSV UTF-8).'
      else helpText += 'Si tu broker no exporta CSV, podés pegar los datos en Google Sheets y descargar como CSV.'
      setFileError(errors.join(' ') + helpText)
    } else if (dupCount > 0) {
      setFileError(`${dupCount} ${dupCount === 1 ? 'archivo ya estaba' : 'archivos ya estaban'} en la lista — lo ignoramos.`)
    } else {
      setFileError(null)
    }
  }

  function removeFile(name, size) {
    setFiles(prev => prev.filter(f => !(f.name === name && f.size === size)))
  }

  const curWord = effectiveCurrency === 'ARS' ? 'pesos' : effectiveCurrency === 'USD' ? 'dólares' : effectiveCurrency

  return (
    <div className="space-y-4">
      {/* Resumen de lo elegido en el Paso 0 + cambiar */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-md bg-rendi-accent/[0.07] border border-rendi-accent/25">
        <div className="text-sm text-ink-1 min-w-0">
          {sourceType === 'broker' ? (
            <>Importando un export de <span className="font-semibold text-ink-0">{brokerLabel}</span>
              {effectiveCurrency ? ` · ${effectiveCurrency}` : ''}{useCurrencyRouting ? ' (+ sub-broker USD)' : ''}</>
          ) : (
            <>Archivo propio{curWord ? ` en ${curWord}` : ''}
              {importMode === 'general'
                ? ' · mezcla de brokers'
                : (singleBroker ? <> → <span className="font-semibold text-ink-0">{singleBroker}</span></> : '')}
              {useCurrencyRouting ? ' (+ sub-broker USD)' : ''}</>
          )}
        </div>
        <button type="button" onClick={onBack} className="text-xs text-rendi-accent hover:underline flex-shrink-0">
          Cambiar
        </button>
      </div>

      {/* Instrucciones de descarga del broker (rama broker) */}
      {isSpecific && platform !== 'generic' && (
        <BrokerInstructions lockBrokerId={platform} />
      )}

      {/* Template genérico (rama propia) */}
      {!isSpecific && (
        <>
          <p className="text-xs text-ink-3">
            El template genérico funciona con cualquier CSV — en el próximo paso vas a mapear tus columnas a las de Rendi.
          </p>
          <button
            onClick={downloadTemplate}
            className="inline-flex items-center gap-1.5 text-sm text-rendi-accent hover:underline"
          >
            <Download size={14} /> Descargar template de ejemplo
          </button>
        </>
      )}

      {/* Dropzone */}
      <div>
        <label className="block text-xs text-ink-3 mb-1">Archivo CSV / Excel</label>
        {fileError && (
          <div className="mb-2 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-warn/[0.08] border border-rendi-warn/25 text-rendi-warn text-xs">
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
            <span>{fileError}</span>
          </div>
        )}
        <div
          role="button"
          tabIndex={0}
          aria-label="Seleccionar archivos CSV o Excel — arrastrá o hacé clic"
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              inputRef.current?.click()
            }
          }}
          onDragOver={e => { e.preventDefault() }}
          onDrop={e => { e.preventDefault(); pickFiles(e.dataTransfer?.files) }}
          className="border-2 border-dashed border-line-2 rounded-lg p-6 text-center cursor-pointer hover:border-rendi-accent/50 focus:border-rendi-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-rendi-accent/40 transition"
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv,text/plain,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xls,application/vnd.ms-excel"
            multiple
            className="hidden"
            onChange={e => pickFiles(e.target.files)}
          />
          {files.length === 0 ? (
            <div className="text-sm text-ink-3">
              <Upload size={20} className="mx-auto mb-2 opacity-60" />
              Soltá tu CSV o Excel, o hacé clic para seleccionarlo
              <div className="mt-1 text-[11px] text-ink-3">
                Tip: para importar varios años, seleccioná los CSVs juntos
              </div>
            </div>
          ) : (
            <div className="text-sm text-ink-1">
              <div className="text-xs text-ink-3 mb-2">
                {files.length} {files.length === 1 ? 'archivo seleccionado' : 'archivos seleccionados'} · hacé clic para agregar más
              </div>
              <ul className="space-y-1 text-left max-w-md mx-auto">
                {files.map(f => (
                  <li
                    key={`${f.name}::${f.size}`}
                    className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-bg-2 dark:bg-bg-2"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileText size={14} className="flex-shrink-0 text-ink-3" />
                      <span className="font-medium truncate">{f.name}</span>
                      <span className="text-ink-3 text-xs flex-shrink-0">({(f.size / 1024).toFixed(1)} KB)</span>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); removeFile(f.name, f.size) }}
                      className="text-ink-3 hover:text-red-500 transition p-0.5"
                      title="Quitar archivo"
                      aria-label={`Quitar ${f.name}`}
                    >
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
              {!isSpecific && files.length > 1 && (
                <div className="mt-2 text-[11px] text-ink-3 max-w-md mx-auto">
                  Nota: vamos a mapear las columnas del primer archivo. Los demás deben tener el mismo header.
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="text-xs text-ink-3 space-y-1">
        <p>Antes de importar, generamos una vista previa: vas a poder revisar fila por fila lo que Rendi entendió antes de guardar nada.</p>
        <p>Si tu archivo tiene errores, las filas válidas se importan igual y te mostramos cuáles fallaron.</p>
      </div>
    </div>
  )
}


function MapStep({ inspect, mapping, setMapping, brokers, importMode, singleBroker, useCurrencyRouting,
                    savedTemplates = [], onSaveTemplate, onDeleteTemplate, onLoadTemplate }) {
  const headers = inspect.headers || []
  const allFields = inspect.rendi_fields || []
  const sampleRows = inspect.sample_rows || []
  // En modo single-broker el campo broker queda fijo y no se muestra en el mapeo.
  const fields = importMode === 'single'
    ? allFields.filter(f => f.id !== 'broker')
    : allFields
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [templateName, setTemplateName] = useState('')

  function setColumn(fieldId, header) {
    setMapping(m => {
      const cols = { ...(m.columns || {}) }
      if (header) cols[fieldId] = header
      else delete cols[fieldId]
      return { ...m, columns: cols }
    })
  }
  function setDefault(fieldId, value) {
    setMapping(m => {
      const defs = { ...(m.defaults || {}) }
      if (value) defs[fieldId] = value
      else delete defs[fieldId]
      return { ...m, defaults: defs }
    })
  }

  return (
    <div className="space-y-4">
      {importMode === 'single' && singleBroker && (
        <div className="flex flex-col gap-1 px-3 py-2 rounded-md bg-rendi-accent/10 border border-rendi-accent/30 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-ink-1">Importando todo a:</span>
            <span className="font-semibold text-ink-0">{singleBroker}</span>
          </div>
          {useCurrencyRouting && (
            <div className="text-xs text-ink-2">
              Filas en USD → al sub-broker <span className="font-medium">{singleBroker} · USD</span> (auto-creado).
            </div>
          )}
        </div>
      )}

      {/* Templates de mapping guardados */}
      <div className="flex items-center gap-2 flex-wrap">
        {savedTemplates.length > 0 && (
          <div className="inline-flex items-center gap-1.5 text-xs">
            <span className="text-ink-3">Plantilla:</span>
            <select
              onChange={e => {
                const t = savedTemplates.find(x => String(x.id) === e.target.value)
                if (t) onLoadTemplate?.(t)
                e.target.value = ''
              }}
              defaultValue=""
              className="bg-bg-2 dark:bg-bg-1/40 border border-line rounded-md px-2 py-1 text-xs text-ink-0"
            >
              <option value="" disabled>— cargar guardada —</option>
              {savedTemplates.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        )}
        <button
          type="button"
          onClick={() => { setTemplateName(''); setShowSaveDialog(true) }}
          className="inline-flex items-center gap-1 text-xs text-ink-2 hover:text-ink-0 dark:hover:text-ink-1 px-2 py-1 rounded border border-line hover:border-line dark:hover:border-line-2 transition"
        >
          <Save size={11} /> Guardar mapeo actual
        </button>
        {showSaveDialog && (
          <div className="inline-flex items-center gap-1.5">
            <input
              type="text"
              value={templateName}
              onChange={e => setTemplateName(e.target.value)}
              onKeyDown={async e => {
                if (e.key === 'Enter' && templateName.trim()) {
                  await onSaveTemplate?.(templateName)
                  setShowSaveDialog(false)
                } else if (e.key === 'Escape') {
                  setShowSaveDialog(false)
                }
              }}
              placeholder="Nombre (ej: IBKR template)"
              autoFocus
              className="bg-bg-2 dark:bg-bg-1/40 border border-line-2 rounded-md px-2 py-1 text-xs text-ink-0 placeholder-ink-3"
            />
            <button
              type="button"
              onClick={async () => { await onSaveTemplate?.(templateName); setShowSaveDialog(false) }}
              disabled={!templateName.trim()}
              className="text-xs px-2 py-1 rounded bg-rendi-accent text-white hover:bg-rendi-accent/90 disabled:opacity-50 font-medium"
            >Guardar</button>
            <button
              type="button"
              onClick={() => setShowSaveDialog(false)}
              className="text-xs text-ink-3 hover:text-ink-1"
            >Cancelar</button>
          </div>
        )}
        {savedTemplates.length > 0 && (
          <details className="text-xs ml-auto">
            <summary className="cursor-pointer text-ink-3 hover:text-ink-1 dark:hover:text-ink-0">
              Administrar
            </summary>
            <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
              {savedTemplates.map(t => (
                <div key={t.id} className="flex items-center justify-between gap-2 px-2 py-1 rounded border border-line">
                  <span className="text-xs text-ink-1">{t.name}</span>
                  <button
                    type="button"
                    onClick={() => onDeleteTemplate?.(t.id)}
                    className="text-ink-3 hover:text-red-500"
                    title="Borrar plantilla"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      <div className="text-xs text-ink-2">
        <p className="mb-1">
          Decile a Rendi qué columna de tu archivo corresponde a cada dato. Auto-detectamos las que pudimos por el nombre, ajustá lo que haga falta.
        </p>
        <p className="text-ink-3">
          {importMode === 'single'
            ? 'Si tu archivo no tiene una columna (ej.: moneda), podés definir un valor fijo para todas las filas.'
            : 'Si tu archivo no tiene una columna (ej.: broker o moneda), podés definir un valor fijo para todas las filas.'}
        </p>
      </div>

      <div className="px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-1/40 border border-line">
        <div className="text-[10px] uppercase tracking-wider text-ink-3 mb-1">
          Columnas detectadas en tu archivo
        </div>
        <div className="flex flex-wrap gap-1.5">
          {headers.map(h => (
            <span key={h} className="text-xs bg-white dark:bg-bg-2 border border-line rounded px-2 py-0.5 font-mono">
              {h}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {fields.map(f => {
          const colVal = mapping.columns?.[f.id] || ''
          const defVal = mapping.defaults?.[f.id] || ''
          const help = FIELD_HELP[f.id]
          return (
            <div key={f.id} className="grid grid-cols-1 sm:grid-cols-[160px_1fr_1fr] gap-2 items-center">
              <label className="text-xs text-ink-1 inline-flex items-center gap-1">
                <span>{f.label}{f.required && <span className="text-red-500 ml-0.5">*</span>}</span>
                {help && (
                  <InfoTooltip size={11} align="left" label={`Qué es ${f.label}`}>
                    <p className="font-semibold text-ink-0">{help.title}</p>
                    <p>{help.body}</p>
                    {help.examples && (
                      <p className="text-ink-3 italic">{help.examples}</p>
                    )}
                  </InfoTooltip>
                )}
              </label>
              <select
                value={colVal}
                onChange={e => setColumn(f.id, e.target.value)}
                className="w-full bg-bg-2 dark:bg-bg-1/40 border border-line rounded-md px-2 py-1.5 text-xs text-ink-0"
              >
                <option value="">— sin columna —</option>
                {headers.map(h => <option key={h} value={h}>{h}</option>)}
              </select>
              {f.allow_default ? (
                f.id === 'broker' && brokers.length > 0 ? (
                  <select
                    value={defVal}
                    onChange={e => setDefault(f.id, e.target.value)}
                    className="w-full bg-bg-2 dark:bg-bg-1/40 border border-line rounded-md px-2 py-1.5 text-xs text-ink-0"
                  >
                    <option value="">— valor fijo (opcional) —</option>
                    {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={defVal}
                    onChange={e => setDefault(f.id, e.target.value)}
                    placeholder="— valor fijo (opcional) —"
                    className="w-full bg-bg-2 dark:bg-bg-1/40 border border-line rounded-md px-2 py-1.5 text-xs text-ink-0 placeholder-ink-3"
                  />
                )
              ) : <div />}
            </div>
          )
        })}
      </div>

      {sampleRows.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-ink-3 mb-1">
            Vista previa de tu archivo (primeras filas)
          </div>
          <div className="overflow-x-auto border border-line rounded-md">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-bg-2 dark:bg-bg-1/40">
                  {headers.map(h => (
                    <th key={h} className="px-2 py-1 text-left font-mono text-ink-2 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleRows.map((r, i) => (
                  <tr key={i} className="border-t border-line/50 dark:border-line/40">
                    {headers.map(h => (
                      <td key={h} className="px-2 py-1 text-ink-1 whitespace-nowrap">
                        {r[h] || ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}


function PreviewStep({ preview, importMode, singleBroker, useCurrencyRouting,
                        skippedRowIndices = new Set(), onToggleSkipRow, onSeedClick,
                        redoBanner = null }) {
  const s = preview.summary || {}
  const dup = preview.duplicate_of_batch_id
  const routing = preview.routing_summary
  const breakdown = preview.routing_breakdown || []
  const isMulti = preview.is_multi_broker
  const seedSug = preview.seed_suggestions
  const seedHasAssets = (seedSug?.brokers || []).some(b => (b.assets || []).length > 0)

  return (
    <div className="space-y-4">
      {redoBanner && (
        <div className="px-3 py-2 rounded-md bg-emerald-500/10 border border-emerald-500/30 text-sm">
          <div className="flex items-start gap-2">
            <RotateCcw size={14} className="mt-0.5 flex-shrink-0 text-emerald-600 dark:text-emerald-400" />
            <div>
              <div className="font-medium text-ink-0 mb-0.5">
                Editar y rehacer
              </div>
              <p className="text-xs text-ink-2">
                Revertimos el import original y reprocesamos los mismos datos. Ajustá lo que haga falta (omitir filas, confirmar tu cash, etc.) y confirmá para crear un import nuevo.
              </p>
            </div>
          </div>
        </div>
      )}
      {(preview.brokers_already_imported || []).length > 0 && !redoBanner && (
        <div className="px-3 py-2.5 rounded-md bg-amber-500/10 border border-amber-500/50 text-sm">
          <div className="flex items-start gap-2">
            <AlertTriangle size={15} className="mt-0.5 flex-shrink-0 text-amber-500" />
            <div className="flex flex-col gap-1">
              <div className="font-semibold text-ink-0">
                Ojo: ya tenés posiciones de {preview.brokers_already_imported.join(', ')} importadas
              </div>
              <p className="text-xs text-ink-2">
                Si estás subiendo los <span className="font-medium text-ink-1">mismos datos de nuevo</span> (ej. otro
                export del mismo broker), confirmar va a <span className="font-medium text-ink-1">duplicar</span> tus
                posiciones. Si es eso, primero <span className="font-medium text-ink-1">revertí el import anterior</span> desde
                "Importar CSV". Si son movimientos NUEVOS, seguí tranquilo.
              </p>
            </div>
          </div>
        </div>
      )}
      {seedSug?.needed && (
        <div className="px-3 py-3 rounded-md bg-blue-500/10 border border-blue-500/40 text-sm">
          <div className="flex items-start gap-2 mb-2">
            <Info size={16} className="mt-0.5 flex-shrink-0 text-blue-500" />
            <div>
              <div className="font-semibold text-ink-0 mb-0.5">
                {seedHasAssets
                  ? 'Te faltan un par de datos — tranqui, no es un error'
                  : 'Falta confirmar tu cash — tranqui, no es un error'}
              </div>
              <p className="text-xs text-ink-2">
                Tu archivo arranca con la cuenta ya en uso. Para que las cuentas cierren, en el paso
                siguiente te pedimos cuánto <span className="font-medium text-ink-1">efectivo</span> tenés <span className="font-medium text-ink-1">hoy</span> en
                el broker (la plata sin invertir, no el total) y, si hace falta, el <span className="font-medium text-ink-1">precio de compra</span> de
                algunas posiciones. Es rápido, casi siempre un solo clic.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onSeedClick}
            className="text-xs font-semibold px-3 py-1.5 rounded-md bg-rendi-accent hover:bg-rendi-accent/90 text-white transition"
          >
            {seedHasAssets ? 'Completar mis datos →' : 'Confirmar mi cash →'}
          </button>
        </div>
      )}
      {importMode === 'single' && singleBroker && (
        <div className="flex flex-col gap-1 px-3 py-2 rounded-md bg-rendi-accent/10 border border-rendi-accent/30 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-ink-1">Importando todo a:</span>
            <span className="font-semibold text-ink-0">{singleBroker}</span>
          </div>
          {useCurrencyRouting && routing && (
            <div className="text-xs text-ink-2">
              <span className="tabular">{routing.ars_rows_to_parent}</span> filas ARS → {singleBroker}{' · '}
              <span className="tabular">{routing.usd_rows_to_sibling}</span> filas USD → {singleBroker} · USD <span className="text-ink-3">(sub-broker)</span>
            </div>
          )}
        </div>
      )}

      {(preview.new_brokers_created || []).length > 0 && (
        <div className="px-3 py-2 rounded-md bg-blue-500/10 border border-blue-500/30 text-sm">
          <div className="text-ink-1 mb-1 font-medium">
            Brokers nuevos creados
          </div>
          <p className="text-xs text-ink-2 mb-1.5">
            Detectamos brokers en el archivo que no estaban en tu cuenta. Los creamos automáticamente con la moneda inferida (podés cambiarla después en Posiciones).
          </p>
          <ul className="text-xs space-y-0.5">
            {preview.new_brokers_created.map(b => (
              <li key={b.name} className="flex items-center gap-2">
                <span className="font-semibold text-ink-0">{b.name}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-ink-1">
                  {b.currency}
                </span>
                <span className="text-ink-3">· {b.rows} {b.rows === 1 ? 'fila' : 'filas'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isMulti && breakdown.length > 0 && (
        <div className="px-3 py-2 rounded-md bg-rendi-accent/10 border border-rendi-accent/30 text-sm">
          <div className="text-ink-1 mb-1.5 font-medium">
            Distribución por broker
          </div>
          <ul className="text-xs space-y-1">
            {breakdown.map(b => (
              <li key={b.broker} className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold text-ink-0">{b.broker}</span>
                <span className="text-ink-3">({b.broker_currency})</span>
                <span className="text-ink-2">
                  · <span className="tabular">{b.ars_rows}</span> ARS{' '}
                  · <span className="tabular">{b.usd_rows}</span> USD
                </span>
                {b.creates_sibling && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-rendi-accent/20 text-ink-1">
                    USD → {b.sibling_name} (auto-creado)
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dup && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
          <span>Ya importaste este archivo antes (mismo contenido). Si confirmás vas a duplicar las operaciones.</span>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <SummaryBox label="Filas totales" value={s.total_rows} />
        <SummaryBox label="Válidas" value={s.valid_rows} positive />
        <SummaryBox label="Con errores" value={s.invalid_rows} negative={s.invalid_rows > 0} />
        <SummaryBox label="Brokers" value={(s.detected_brokers || []).join(', ') || '—'} />
      </div>

      <Section title="Se va a crear">
        <ul className="text-sm text-ink-1 space-y-1">
          {(s.by_operation_type || []).map(it => (
            <li key={it.type} className="flex justify-between">
              <span>{it.label}</span>
              <span className="tabular font-medium">{it.count}</span>
            </li>
          ))}
        </ul>
        <div className="mt-3 pt-3 border-t border-line text-xs text-ink-3 space-y-0.5">
          <div>{s.estimated_impact?.positions_to_create || 0} posiciones nuevas en <em>Posiciones</em></div>
          <div>{s.estimated_impact?.operations_to_create || 0} operaciones cerradas en <em>Operaciones</em></div>
          <div>{s.estimated_impact?.cash_movements || 0} movimientos de cash</div>
          <div>{s.estimated_impact?.fx_conversions || 0} conversiones de moneda</div>
        </div>
      </Section>

      {s.date_range && (
        <div className="text-xs text-ink-3">
          Período: <span className="text-ink-1 tabular">{s.date_range.from}</span> → <span className="text-ink-1 tabular">{s.date_range.to}</span>
        </div>
      )}

      {(preview.by_asset || []).length > 0 && (
        <Section title="Por activo">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-ink-3">
                <th className="py-1">Activo</th><th className="py-1">Compras</th><th className="py-1">Ventas</th><th className="py-1 text-right">Neto</th>
              </tr>
            </thead>
            <tbody>
              {preview.by_asset.map(a => (
                <tr key={a.asset} className="border-t border-line/50 dark:border-line/40">
                  <td className="py-1 font-medium">{a.asset}</td>
                  <td className="py-1 tabular">{a.buys} ({a.buy_qty})</td>
                  <td className="py-1 tabular">{a.sells} ({a.sell_qty})</td>
                  <td className={`py-1 tabular text-right ${a.net_qty > 0 ? 'text-emerald-600 dark:text-emerald-400' : a.net_qty < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>
                    {a.net_qty > 0 ? '+' : ''}{a.net_qty}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {(preview.duplicate_row_indices || []).length > 0 && (
        <div className="px-3 py-2 rounded-md bg-blue-500/10 border border-blue-500/30 text-xs">
          <div className="font-medium text-ink-1 mb-1">
            {preview.duplicate_row_indices.length} {preview.duplicate_row_indices.length === 1 ? 'fila ya fue importada antes' : 'filas ya fueron importadas antes'}
          </div>
          <p className="text-ink-2">
            Detectamos que estas filas coinciden con operaciones de imports anteriores (misma fecha + broker + tipo + activo + cantidad + precio).
            Si confirmás, se van a duplicar en la cartera. Filas: {' '}
            <span className="font-mono text-ink-1">
              {preview.duplicate_row_indices.slice(0, 30).join(', ')}
              {preview.duplicate_row_indices.length > 30 && '…'}
            </span>
          </p>
        </div>
      )}

      {/* Cuando hay seed sugerido, el banner azul de arriba ya explica el saldo
          negativo de forma tranquila y lleva al fix → no repetimos este aviso
          ámbar (alarmista). Solo lo mostramos si NO hay seed que resolver. */}
      {(preview.cash_warnings || []).length > 0 && !seedSug?.needed && (
        <div className="px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-xs">
          <div className="font-medium text-amber-700 dark:text-amber-400 mb-1">
            Atención: {preview.cash_warnings.length} {preview.cash_warnings.length === 1 ? 'fila deja' : 'filas dejan'} el cash en negativo
          </div>
          <p className="text-amber-700/80 dark:text-amber-400/80 mb-2">
            El sistema permite saldos negativos en imports (overdraft), pero suele indicar que faltan aportes anteriores en el archivo o que la cronología no es realista. Las filas se importan igual; revisalo si querés que el saldo cuadre.
          </p>
          <ul className="text-amber-700 dark:text-amber-400 space-y-1 max-h-40 overflow-y-auto">
            {preview.cash_warnings.map((w, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="font-mono text-[10px] bg-amber-500/10 px-1 py-0.5 rounded flex-shrink-0">Fila {w.row_index}</span>
                <span>
                  {w.message} · saldo {w.broker}: <span className="tabular font-medium">{w.currency} {w.new_balance.toLocaleString('es-AR', { maximumFractionDigits: 2 })}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(preview.errors || []).length > 0 && (
        <Section title={`Errores (${preview.errors.length})`} variant="error">
          <p className="text-xs text-red-700/80 dark:text-red-400/80 mb-2">
            Estas filas no se importan. Las {preview.summary?.valid_rows ?? 0} filas válidas siguen entrando normalmente al confirmar.
          </p>
          <ul className="text-xs text-red-700 dark:text-red-400 space-y-1 max-h-40 overflow-y-auto">
            {preview.errors.map((e, i) => (
              <li key={i}>
                <span className="font-mono text-[10px] bg-red-500/10 px-1 py-0.5 rounded mr-2">Fila {e.row_index}</span>
                {e.message}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {(preview.rows_preview || []).length > 0 && (
        <Section title={`Filas a importar (${preview.rows_preview.length - skippedRowIndices.size}${skippedRowIndices.size > 0 ? ` · ${skippedRowIndices.size} omitidas` : ''})`}>
          <p className="text-xs text-ink-3 mb-2">
            Tildá filas para excluirlas de este import. La data del archivo no se modifica.
          </p>
          <div className="max-h-60 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white dark:bg-bg-2">
                <tr className="text-left text-ink-3">
                  <th className="py-1 w-6"></th>
                  <th className="py-1">#</th>
                  <th className="py-1">Fecha</th>
                  <th className="py-1">Tipo</th>
                  <th className="py-1">Activo</th>
                  <th className="py-1 text-right">Cant.</th>
                  <th className="py-1 text-right">Precio</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows_preview.map(r => {
                  const isSkipped = skippedRowIndices.has(r.row_index)
                  return (
                    <tr key={r.row_index} className={`border-t border-line/50 dark:border-line/40 ${isSkipped ? 'opacity-40 line-through' : ''}`}>
                      <td className="py-1">
                        <input
                          type="checkbox"
                          checked={!isSkipped}
                          onChange={() => onToggleSkipRow?.(r.row_index)}
                          className="cursor-pointer"
                          title={isSkipped ? 'Restaurar fila' : 'Omitir fila'}
                        />
                      </td>
                      <td className="py-1 tabular text-ink-3">{r.row_index}</td>
                      <td className="py-1 tabular">{r.date}</td>
                      <td className="py-1">{OP_LABELS[r.operation_type] || r.operation_type}</td>
                      <td className="py-1 font-medium">{r.asset_symbol || '—'}</td>
                      <td className="py-1 tabular text-right">{r.quantity ?? '—'}</td>
                      <td className="py-1 tabular text-right">{r.unit_price ?? r.gross_amount ?? '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  )
}


// En los sub-brokers AR "<Padre> · USD" el dólar es REAL, no la stablecoin USDT
// (el modelo usa USDT como bucket interno, pero el usuario tiene dólares). Para
// mostrar, lo etiquetamos "USD". Crypto-nativos (Binance, etc.) siguen "USDT".
function displayCur(cur, brokerName) {
  if (cur === 'USDT' && /\bUSD$/.test(brokerName || '')) return 'USD'
  return cur
}

function SeedStep({ suggestions, seedState, setSeedState }) {
  const brokers = seedState?.brokers || []
  const hasAssets = brokers.some(b => (b.assets || []).length > 0)

  function setCash(idx, currency, value) {
    setSeedState(s => {
      const next = { ...s, brokers: [...(s.brokers || [])] }
      const b = { ...next.brokers[idx], cash: { ...(next.brokers[idx].cash || {}) } }
      b.cash[currency] = value
      next.brokers[idx] = b
      return next
    })
  }

  function setAsset(idx, assetIdx, field, value) {
    setSeedState(s => {
      const next = { ...s, brokers: [...(s.brokers || [])] }
      const b = { ...next.brokers[idx], assets: [...(next.brokers[idx].assets || [])] }
      b.assets[assetIdx] = { ...b.assets[assetIdx], [field]: value }
      next.brokers[idx] = b
      return next
    })
  }

  return (
    <div className="space-y-4">
      <div className="px-3 py-2.5 rounded-md bg-rendi-accent/10 border border-rendi-accent/30 text-sm">
        <div className="flex items-start gap-2">
          <Info size={15} className="mt-0.5 flex-shrink-0 text-rendi-accent" />
          <div className="flex flex-col gap-1">
            <div className="text-ink-0 font-semibold">
              {hasAssets
                ? 'Completá tu cash y el precio de tus posiciones — es el último paso'
                : 'Confirmá cuánto cash tenés hoy — es el último paso'}
            </div>
            <p className="text-xs text-ink-2">
              ¿El número de arriba te parece raro (negativo o muy alto)? <span className="font-medium text-ink-1">Tranqui, es normal.</span> El
              archivo de tu broker no siempre trae todos los movimientos de plata (depósitos, transferencias
              o conversiones a dólar), así que ese cash estimado puede quedar desfasado.{' '}
              <span className="font-medium text-ink-1">Tus operaciones se tomaron bien igual</span> — solo poné el efectivo
              (la plata sin invertir) que tenés hoy en tu broker y nosotros ajustamos lo anterior solos.
            </p>
          </div>
        </div>
      </div>

      {brokers.length === 0 && (
        <div className="text-sm text-ink-3 text-center py-6">
          Tu cartera ya cierra — no hay cash para confirmar.
        </div>
      )}

      {brokers.map((b, bi) => {
        const overdraftEntries = Object.entries(b.cash_overdraft || {})
        const cashCurrencies = new Set([
          ...overdraftEntries.map(([c]) => c),
          ...Object.keys(b.cash || {}),
        ])
        // Aseguramos siempre la moneda del broker como mínimo
        if (b.broker_currency) cashCurrencies.add(b.broker_currency)
        return (
          <div key={bi} className="border border-line rounded-md">
            <div className="px-3 py-2 bg-bg-2 dark:bg-bg-1/40 border-b border-line flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-ink-0 text-sm">{b.broker}</span>
                {b.broker_currency && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-2 dark:bg-bg-2 text-ink-1 uppercase">
                    {displayCur(b.broker_currency, b.broker)}
                  </span>
                )}
              </div>
            </div>
            <div className="p-3 space-y-3">
              {/* Cash */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-ink-3 mb-1">
                  ¿Cuánto efectivo (cash) tenés hoy en {b.broker}?
                </div>
                <p className="text-[11px] text-ink-3 mb-1.5">
                  Solo la plata <span className="font-medium text-ink-1">disponible sin invertir</span> — <span className="font-medium text-ink-1">no</span> el total de la cuenta (ese incluye tus acciones, bonos y fondos).
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {Array.from(cashCurrencies).map(cur => {
                    const curLabel = displayCur(cur, b.broker)  // "USDT"→"USD" en sub-brokers AR
                    const F = b.final_balance?.[cur]          // saldo que da el CSV (puede ser <0)
                    const hasF = F != null
                    const current = b.cash?.[cur] ?? ''       // saldo de HOY que pone el user
                    const isSame = hasF && F >= 0 && current !== '' &&
                      Math.abs(Number(current) - F) < 0.01
                    return (
                      <div key={cur} className="block">
                        <div className="mb-2 flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-ink-0 text-sm">{curLabel}</span>
                          {hasF && (
                            <span className="inline-flex items-baseline gap-1.5 px-2.5 py-1 rounded-md bg-rendi-accent/12 border border-rendi-accent/40">
                              <span className="text-[9px] uppercase tracking-wider text-rendi-accent/90 font-bold">según tu CSV</span>
                              <span className="text-base font-bold text-rendi-accent tabular leading-none">
                                {F.toLocaleString('es-AR', { maximumFractionDigits: 2 })} {curLabel}
                              </span>
                              {F < 0 && (
                                <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium"> · negativo, falta plata previa</span>
                              )}
                            </span>
                          )}
                        </div>
                        {hasF && (
                          <div className="text-[11px] text-ink-3 mb-1.5 -mt-1">
                            Revisá que coincida con el cash {curLabel} real de tu broker — si no, corregilo abajo.
                          </div>
                        )}
                        {hasF && F >= 0 && (
                          <button
                            type="button"
                            onClick={() => setCash(bi, cur, String(F))}
                            className={`w-full mb-1.5 flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-xs font-medium transition ${
                              isSame
                                ? 'border-rendi-pos/40 bg-rendi-pos/10 text-rendi-pos'
                                : 'border-line hover:border-rendi-accent text-ink-1 hover:bg-bg-2'
                            }`}
                          >
                            <CheckCircle2 size={13} className={isSame ? 'text-rendi-pos' : 'text-ink-3'} />
                            Es el mismo que calculó Rendi
                          </button>
                        )}
                        <input
                          type="number"
                          step="any"
                          min="0"
                          value={current}
                          onChange={e => setCash(bi, cur, e.target.value)}
                          placeholder={`¿Cuánto ${curLabel} tenés hoy?`}
                          className={`w-full bg-bg-2 dark:bg-bg-1/40 border rounded-md px-2 py-1.5 text-xs text-ink-0 ${
                            (current === '' || current == null)
                              ? 'border-amber-500/60'
                              : 'border-line'
                          }`}
                        />
                        {(current === '' || current == null) ? (
                          <div className="mt-1 flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400 font-semibold">
                            <AlertTriangle size={12} /> Falta confirmar tu cash de hoy
                          </div>
                        ) : (
                          <div className="mt-1 flex items-center gap-1 text-[11px] text-rendi-pos font-medium">
                            <CheckCircle2 size={12} /> Cash confirmado
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Precio de compra — posiciones transferidas / compras sin precio / ventas sin compra previa */}
              {(b.assets || []).length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-ink-3 mb-1">
                    Precio de compra de tus posiciones en {b.broker}
                  </div>
                  <p className="text-[11px] text-ink-3 mb-2">
                    Estas posiciones no traen precio en el archivo (entraron por transferencia, o el
                    archivo no incluía la compra original). Poné el{' '}
                    <span className="font-medium text-ink-1">precio promedio al que las compraste</span> para que el P&L salga bien.
                  </p>
                  <div className="space-y-2">
                    {(b.assets || []).map((a, ai) => {
                      const curLabel = displayCur(b.broker_currency, b.broker)
                      const empty = a.cost_basis_unit === '' || a.cost_basis_unit == null
                      const isZero = !empty && Number(a.cost_basis_unit) === 0
                      // exact_qty = posición que SÍ se va a crear (transferida o
                      // compra sin precio) → el precio es requerido (o "no sé" → 0).
                      // min_qty = venta sin compra previa → opcional (el motor
                      // auto-sintetiza al precio de venta si se deja vacío).
                      const needsPrice = a.exact_qty && empty
                      return (
                        <div key={ai} className="flex items-center gap-2 flex-wrap rounded-md border border-line px-2 py-1.5">
                          <span className="font-mono font-semibold text-ink-0 text-sm w-14">{a.symbol}</span>
                          <span className="text-[11px] text-ink-3">
                            {a.exact_qty ? '' : 'mín. '}{Number(a.qty).toLocaleString('es-AR', { maximumFractionDigits: 8 })} nominales
                          </span>
                          {needsPrice && (
                            <button
                              type="button"
                              onClick={() => setAsset(bi, ai, 'cost_basis_unit', '0')}
                              className="text-[10px] text-ink-3 hover:text-ink-1 underline decoration-dotted"
                            >
                              No sé el precio
                            </button>
                          )}
                          <div className="flex items-center gap-1.5 ml-auto">
                            <span className="text-[10px] text-ink-3 uppercase">{curLabel}</span>
                            <input
                              type="number"
                              step="any"
                              min="0"
                              value={a.cost_basis_unit}
                              onChange={e => setAsset(bi, ai, 'cost_basis_unit', e.target.value)}
                              placeholder={a.exact_qty ? 'precio prom.' : 'precio (opcional)'}
                              className={`w-32 bg-bg-2 dark:bg-bg-1/40 border rounded-md px-2 py-1.5 text-xs text-ink-0 ${
                                needsPrice ? 'border-amber-500/60' : 'border-line'
                              }`}
                            />
                          </div>
                          {needsPrice && (
                            <div className="w-full flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
                              <AlertTriangle size={12} /> Falta el precio — o tocá "No sé el precio" para crearla con costo 0
                            </div>
                          )}
                          {a.exact_qty && isZero && (
                            <div className="w-full flex items-center gap-1 text-[11px] text-ink-3">
                              <Info size={12} /> Se crea con costo 0 — la editás después en Posiciones
                            </div>
                          )}
                          {!a.exact_qty && (
                            <div className="w-full text-[11px] text-ink-3">
                              Opcional — si lo dejás vacío, usamos el precio de la venta como referencia.
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )
      })}

      <div className="text-xs text-ink-3">
        Lo guardamos como un aporte inicial sintético dentro del mismo lote — si revertís el import, también se borra.
      </div>
    </div>
  )
}


// ────────────────────────────────────────────────────────────────────────────
// Card de reconciliación de cash por broker — el corazón de la UX post-import.
// Muestra:
//   • Lo que Rendi calculó del CSV (referencia).
//   • Input grande para que el user escriba lo que dice el broker hoy.
//   • Diff en vivo mientras escribe (verde si suma, ámbar si resta).
//   • Estado "✓ Confirmado" después de aplicar.
// ────────────────────────────────────────────────────────────────────────────
function CashReconcileCard({ c, onApplied }) {
  const [value, setValue] = useState('')           // string para no perder edits parciales
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [applied, setApplied] = useState(null)     // { previous, target, diff } cuando ya se aplicó

  const currencySymbol = c.currency === 'ARS' ? '$' : 'US$'
  const computedFmt = formatMoney(c.balance, c.currency)

  // Diff preview en vivo mientras el user escribe
  const target = value === '' ? null : Number(value)
  const validTarget = target !== null && Number.isFinite(target)
  const diff = validTarget ? target - c.balance : null
  const diffAbs = diff !== null ? Math.abs(diff) : 0
  const diffSig = diff !== null && Math.abs(diff) >= 0.01

  async function apply() {
    if (!validTarget) { setErr('Tipeá el cash en números'); return }
    setBusy(true); setErr(null)
    try {
      await api.post('/brokers/reconcile-cash', {
        broker_name: c.broker, target_cash: target,
      })
      setApplied({ previous: c.balance, target, diff })
      onApplied?.(target)
    } catch (ex) {
      setErr(ex.message || 'Error al reconciliar')
    } finally {
      setBusy(false)
    }
  }

  // Estado: ya fue aplicado → mostrar resumen verde
  if (applied) {
    return (
      <div className="rounded-lg border border-rendi-pos/30 bg-rendi-pos/5 p-3 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-rendi-pos">
            <CheckCircle2 size={14} />
            <span className="text-xs font-semibold">{c.broker}</span>
          </div>
          <span className="text-sm font-mono text-ink-0">
            {formatMoney(applied.target, c.currency)}
          </span>
        </div>
        <p className="text-[11px] text-ink-3 pl-6">
          Ajustado. Diferencia de {formatMoney(applied.diff, c.currency, true)} registrada como
          {' '}{applied.diff < 0 ? 'retiro' : 'aporte'} pre-CSV.
        </p>
      </div>
    )
  }

  // Heurística para color del balance computado: negativo claramente "raro"
  const isNegative = c.balance < -0.01
  return (
    <div className={`rounded-lg border p-3 space-y-2.5 ${
      isNegative
        ? 'border-rendi-warn/40 bg-rendi-warn/5'
        : 'border-line bg-bg-2/50 dark:bg-bg-1/30'
    }`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-ink-0">{c.broker}</span>
          {isNegative && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-rendi-warn/15 text-rendi-warn border border-rendi-warn/30">
              negativo
            </span>
          )}
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wide text-ink-3">Calculado del CSV</div>
          <div className={`text-sm font-mono ${isNegative ? 'text-rendi-warn' : 'text-ink-1'}`}>
            {computedFmt}
          </div>
        </div>
      </div>

      <div className="flex items-stretch gap-2">
        <div className="flex-1">
          <label className="block text-[10px] uppercase tracking-wide text-ink-3 mb-1">
            ¿Qué cash muestra tu app de {c.broker}?
          </label>
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-ink-3 pointer-events-none">
              {currencySymbol}
            </span>
            <input
              type="number" step="0.01" value={value}
              onChange={e => { setValue(e.target.value); setErr(null) }}
              onKeyDown={e => { if (e.key === 'Enter' && validTarget) apply() }}
              disabled={busy}
              placeholder="0.00"
              className="w-full pl-9 pr-2 py-2 text-sm bg-white dark:bg-bg-2 border border-line-2 rounded-md tabular text-ink-0 focus:outline-none focus:border-rendi-accent disabled:opacity-50"
            />
          </div>
        </div>
        <button
          onClick={apply}
          disabled={busy || !validTarget || !diffSig}
          className="px-4 mt-[18px] text-sm font-semibold rounded-md bg-rendi-accent text-white hover:bg-rendi-accent/90 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
        >
          {busy && <Loader2 size={14} className="animate-spin" />}
          Confirmar
        </button>
      </div>

      {/* Diff preview live */}
      {validTarget && diffSig && (
        <div className={`text-[11px] leading-relaxed px-2 py-1.5 rounded border ${
          diff < 0
            ? 'bg-amber-500/5 border-amber-500/20 text-amber-700 dark:text-amber-400'
            : 'bg-emerald-500/5 border-emerald-500/20 text-emerald-700 dark:text-emerald-400'
        }`}>
          {diff < 0 ? '↓' : '↑'} Diferencia de <strong>{formatMoney(diffAbs, c.currency)}</strong>.
          Se registra como {diff < 0 ? 'retiro' : 'aporte'} pre-CSV en el primer mes del broker
          (representa {diff < 0 ? 'salidas que el CSV no capturó' : 'cash que ya estaba antes de que arranque el archivo'}).
        </div>
      )}
      {validTarget && !diffSig && (
        <div className="text-[11px] text-ink-3 px-2">
          Ya coincide — no hay ajuste necesario.
        </div>
      )}
      {err && <p className="text-[11px] text-rendi-neg px-2">{err}</p>}
    </div>
  )
}

// Helper: formatea montos con prefijo de moneda. signed=true muestra ± explícito.
function formatMoney(amount, currency, signed = false) {
  const abs = Math.abs(amount)
  const num = abs.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const sym = currency === 'ARS' ? '$' : 'US$'
  const sign = signed ? (amount < 0 ? '−' : '+') : (amount < 0 ? '−' : '')
  return `${sign}${sym}${num}`
}

function DoneStep({ result }) {
  const skipped = result.skipped_rows || []
  const initialCashHealth = result.cash_health || []
  const [cashHealth, setCashHealth] = useState(initialCashHealth)
  const negativeCash = cashHealth.filter(c => (c.balance || 0) < -0.01)
  const hasIssues = skipped.length > 0 || negativeCash.length > 0
  const needsReconcile = cashHealth.length > 0

  return (
    <div className="py-2 space-y-5">
      {/* Hero: success header */}
      <div className="text-center space-y-2">
        <CheckCircle2 size={36} className={`mx-auto ${hasIssues ? 'text-rendi-warn' : 'text-rendi-pos'}`} />
        <h3 className="font-semibold text-ink-0">
          {hasIssues ? 'Importación completada con observaciones' : 'Importación completada'}
        </h3>
        <div className="flex justify-center gap-3 text-xs text-ink-3 flex-wrap">
          {(result.positions_created || 0) > 0 && (
            <span><strong className="text-ink-1 tabular">{result.positions_created}</strong> posiciones</span>
          )}
          {(result.operations_created || 0) > 0 && (
            <span><strong className="text-ink-1 tabular">{result.operations_created}</strong> operaciones</span>
          )}
          {(result.cash_movements || 0) > 0 && (
            <span><strong className="text-ink-1 tabular">{result.cash_movements}</strong> movs. cash</span>
          )}
          {(result.conversions || 0) > 0 && (
            <span><strong className="text-ink-1 tabular">{result.conversions}</strong> conversiones</span>
          )}
        </div>
      </div>

      {/* Cash reconcile — main UX */}
      {needsReconcile && (
        <div className="space-y-3">
          <div className="flex items-start gap-2 px-1">
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-ink-0">
                Confirmá el cash con tu broker
              </h4>
              <p className="text-xs text-ink-3 mt-0.5 leading-relaxed">
                Abrí la app de cada broker y comparalo. Si no coincide,
                {' '}<strong>tipeá el efectivo real</strong> (la plata sin invertir, no el total) y la diferencia
                se registra como aporte/retiro pre-CSV. Si ya coincide, podés saltarlo.
              </p>
            </div>
          </div>
          <div className="space-y-2">
            {cashHealth.map((c, i) => (
              <CashReconcileCard
                key={`${c.broker}-${c.asset}`}
                c={c}
                onApplied={(newBalance) => {
                  setCashHealth(prev => prev.map((x, j) => j === i ? { ...x, balance: newBalance } : x))
                }}
              />
            ))}
          </div>
        </div>
      )}

      {skipped.length > 0 && (
        <div className="px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-xs">
          <div className="font-medium text-amber-700 dark:text-amber-400 mb-1">
            {skipped.length} {skipped.length === 1 ? 'fila no se importó' : 'filas no se importaron'}
          </div>
          <p className="text-amber-700/80 dark:text-amber-400/80 mb-2">
            Aparecieron al persistir y se saltearon automáticamente — el resto del lote entró igual:
          </p>
          <ul className="text-amber-700 dark:text-amber-400 space-y-1 max-h-32 overflow-y-auto">
            {skipped.map((s, i) => (
              <li key={i}>
                <span className="font-mono text-[10px] bg-amber-500/10 px-1 py-0.5 rounded mr-2">Fila {s.row_index}</span>
                {s.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="text-center text-xs text-ink-3 pt-2">
        <a href="/imports" className="text-rendi-accent hover:underline">
          Ver historial de importaciones
        </a>
        <span className="mx-1">·</span>
        <span>desde ahí podés revertir un lote si te equivocaste</span>
      </div>
    </div>
  )
}


function SummaryBox({ label, value, positive, negative }) {
  return (
    <div className={`px-3 py-2 rounded-md border
      ${positive ? 'border-emerald-500/30 bg-emerald-500/5' :
        negative ? 'border-red-500/30 bg-red-500/5' :
        'border-line bg-bg-2 dark:bg-bg-1/40'}`}>
      <div className="text-[10px] uppercase tracking-wider text-ink-3">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 tabular
        ${positive ? 'text-emerald-700 dark:text-emerald-400' :
          negative ? 'text-red-700 dark:text-red-400' :
          'text-ink-0'}`}>{value}</div>
    </div>
  )
}


function Section({ title, children, variant }) {
  return (
    <div>
      <div className={`text-xs font-medium mb-2
        ${variant === 'error' ? 'text-red-700 dark:text-red-400' : 'text-ink-1'}`}>
        {title}
      </div>
      <div className={`px-3 py-2 rounded-md border
        ${variant === 'error' ? 'border-red-500/30 bg-red-500/5' :
          'border-line bg-bg-2 dark:bg-bg-1/40'}`}>
        {children}
      </div>
    </div>
  )
}
