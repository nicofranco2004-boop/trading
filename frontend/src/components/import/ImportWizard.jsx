import { useEffect, useRef, useState } from 'react'
import { X, Upload, AlertTriangle, CheckCircle2, Download, FileText, Loader2 } from 'lucide-react'
import InfoTooltip from '../InfoTooltip'
import { api } from '../../utils/api'

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

const STEP_UPLOAD = 'upload'
const STEP_MAP = 'map'
const STEP_PREVIEW = 'preview'
const STEP_DONE = 'done'

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

export default function ImportWizard({ onClose, onConfirmed }) {
  const [step, setStep] = useState(STEP_UPLOAD)
  const [parsers, setParsers] = useState([])
  const [format, setFormat] = useState('rendi_generic')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [inspect, setInspect] = useState(null)        // {headers, sample_rows, rendi_fields, suggested_mapping}
  const [mapping, setMapping] = useState({ columns: {}, defaults: {} })
  const [brokers, setBrokers] = useState([])
  // Modo: 'single' = todas las filas son de un broker (no hace falta columna);
  // 'general' = el archivo mezcla varios brokers (mapeo desde columna).
  const [importMode, setImportMode] = useState('single')
  const [singleBroker, setSingleBroker] = useState('')
  // Cuando el broker single es ARS, el usuario indica si el archivo además
  // tiene operaciones en USD. Si sí, las ruteamos al sub-broker USD.
  const [hasUsdOps, setHasUsdOps] = useState(false)
  const [preview, setPreview] = useState(null)
  const [confirmResult, setConfirmResult] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    api.get('/imports/parsers').then(setParsers).catch(() => setParsers([]))
    api.get('/brokers').then(bs => {
      setBrokers(bs)
      if (!singleBroker && bs.length > 0) setSingleBroker(bs[0].name)
    }).catch(() => setBrokers([]))
  }, [])

  function reset() {
    setStep(STEP_UPLOAD)
    setFile(null)
    setInspect(null)
    setMapping({ columns: {}, defaults: {} })
    setPreview(null)
    setConfirmResult(null)
    setError(null)
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
      const token = localStorage.getItem('rendi_token')
      const res = await fetch(`/api/imports/template?format=${format}`, {
        headers: { Authorization: `Bearer ${token}` },
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

  // ¿El broker seleccionado en modo single es ARS?
  const singleBrokerObj = brokers.find(b => b.name === singleBroker)
  const isArsBroker = importMode === 'single' && singleBrokerObj?.currency === 'ARS'
  // El ruteo USD→sub-broker solo aplica cuando el broker padre es ARS y el
  // usuario marcó que el archivo tiene operaciones en USD.
  const useCurrencyRouting = isArsBroker && hasUsdOps

  async function uploadAndInspect() {
    if (!file) {
      setError('Seleccioná un archivo CSV.')
      return
    }
    if (importMode === 'single' && !singleBroker) {
      setError('Elegí el broker al que pertenece este archivo.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
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
      fd.append('file', file)
      fd.append('format', 'rendi_generic')
      fd.append('mapping', JSON.stringify(mapping))
      if (useCurrencyRouting) fd.append('route_by_currency', '1')
      const data = await api.upload('/imports/preview', fd)
      setPreview(data)
      setStep(STEP_PREVIEW)
    } catch (ex) {
      setError(ex.message || 'Error al previsualizar el archivo.')
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!preview?.session_id) return
    setBusy(true)
    setError(null)
    try {
      const data = await api.post('/imports/confirm', { session_id: preview.session_id })
      setConfirmResult(data)
      setStep(STEP_DONE)
      onConfirmed?.(data)
    } catch (ex) {
      setError(ex.message || 'Error al confirmar el import.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto">
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-t-2xl sm:rounded-xl w-full max-w-3xl shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
          <h2 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base">
            Importar CSV
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
            <X size={18} />
          </button>
        </div>

        <Stepper step={step} />

        <div className="p-5 overflow-y-auto flex-1">
          {error && (
            <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-sm">
              <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {step === STEP_UPLOAD && (
            <UploadStep
              parsers={parsers}
              format={format} setFormat={setFormat}
              file={file} setFile={setFile}
              downloadTemplate={downloadTemplate}
              inputRef={inputRef}
              importMode={importMode} setImportMode={setImportMode}
              singleBroker={singleBroker} setSingleBroker={setSingleBroker}
              brokers={brokers}
              isArsBroker={isArsBroker}
              hasUsdOps={hasUsdOps} setHasUsdOps={setHasUsdOps}
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
            />
          )}

          {step === STEP_PREVIEW && preview && (
            <PreviewStep
              preview={preview}
              importMode={importMode}
              singleBroker={singleBroker}
              useCurrencyRouting={useCurrencyRouting}
            />
          )}

          {step === STEP_DONE && confirmResult && (
            <DoneStep result={confirmResult} />
          )}
        </div>

        <div className="flex justify-between gap-2 px-5 py-3 border-t border-slate-200 dark:border-slate-700 flex-shrink-0">
          <div>
            {step === STEP_MAP && (
              <button
                onClick={() => setStep(STEP_UPLOAD)}
                className="px-3 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                ← Volver
              </button>
            )}
            {step === STEP_PREVIEW && (
              <button
                onClick={() => setStep(STEP_MAP)}
                className="px-3 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                ← Ajustar mapeo
              </button>
            )}
          </div>
          <div className="flex gap-2">
            {step !== STEP_DONE && (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              >
                Cancelar
              </button>
            )}
            {step === STEP_UPLOAD && (
              <button
                onClick={uploadAndInspect}
                disabled={busy || !file}
                className="px-4 py-2 text-sm bg-rendi-green hover:bg-rendi-green-dark text-rendi-bg rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                Continuar
              </button>
            )}
            {step === STEP_MAP && (
              <button
                onClick={confirmMapping}
                disabled={busy}
                className="px-4 py-2 text-sm bg-rendi-green hover:bg-rendi-green-dark text-rendi-bg rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                Generar vista previa
              </button>
            )}
            {step === STEP_PREVIEW && (
              <button
                onClick={confirm}
                disabled={busy || preview?.summary?.valid_rows === 0}
                className="px-4 py-2 text-sm bg-rendi-green hover:bg-rendi-green-dark text-rendi-bg rounded-md font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                Confirmar e importar
              </button>
            )}
            {step === STEP_DONE && (
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm bg-rendi-green hover:bg-rendi-green-dark text-rendi-bg rounded-md font-semibold transition"
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


function Stepper({ step }) {
  const steps = [
    { id: STEP_UPLOAD, label: 'Archivo' },
    { id: STEP_MAP, label: 'Mapear columnas' },
    { id: STEP_PREVIEW, label: 'Previsualización' },
    { id: STEP_DONE, label: 'Listo' },
  ]
  const idx = steps.findIndex(s => s.id === step)
  return (
    <div className="flex items-center gap-2 px-5 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 text-xs text-slate-500 dark:text-slate-400">
      {steps.map((s, i) => (
        <div key={s.id} className="flex items-center gap-2">
          <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-semibold
            ${i <= idx ? 'bg-rendi-green text-rendi-bg' : 'bg-slate-200 dark:bg-slate-700 text-slate-500'}`}>
            {i + 1}
          </span>
          <span className={i === idx ? 'text-slate-900 dark:text-slate-100 font-medium' : ''}>{s.label}</span>
          {i < steps.length - 1 && <span className="mx-1 text-slate-400">›</span>}
        </div>
      ))}
    </div>
  )
}


function UploadStep({ parsers, format, setFormat, file, setFile, downloadTemplate, inputRef,
                      importMode, setImportMode, singleBroker, setSingleBroker, brokers,
                      isArsBroker, hasUsdOps, setHasUsdOps }) {
  return (
    <div className="space-y-4">
      {/* ¿Qué clase de archivo es? */}
      <div>
        <label className="block text-xs text-slate-500 dark:text-slate-400 mb-2">¿De qué tipo es este archivo?</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setImportMode('single')}
            className={`text-left px-3 py-2.5 rounded-md border transition ${
              importMode === 'single'
                ? 'border-rendi-green bg-rendi-green/10'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            }`}
          >
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Un solo broker</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Es un export de IBKR, Cocos, Binance, etc. Todas las filas pertenecen al mismo broker.
            </div>
          </button>
          <button
            type="button"
            onClick={() => setImportMode('general')}
            className={`text-left px-3 py-2.5 rounded-md border transition ${
              importMode === 'general'
                ? 'border-rendi-green bg-rendi-green/10'
                : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
            }`}
          >
            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">Mezcla de brokers</div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Tu archivo tiene una columna que indica a qué broker pertenece cada fila.
            </div>
          </button>
        </div>
      </div>

      {importMode === 'single' && (
        <div>
          <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Broker del archivo</label>
          {brokers.length > 0 ? (
            <select
              value={singleBroker}
              onChange={e => setSingleBroker(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200"
            >
              {brokers.map(b => <option key={b.id} value={b.name}>{b.name} ({b.currency})</option>)}
            </select>
          ) : (
            <div className="text-xs text-amber-600 dark:text-amber-400 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/20">
              Todavía no tenés brokers cargados. Creá uno en Configuración antes de importar.
            </div>
          )}
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Todas las filas del archivo se van a importar a este broker. No necesitás una columna de broker en el CSV.
          </p>
        </div>
      )}

      {isArsBroker && (
        <div className="px-3 py-3 rounded-md border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40">
          <div className="text-xs text-slate-700 dark:text-slate-200 mb-2 font-medium">
            ¿Este archivo tiene operaciones en dólares?
          </div>
          <div className="flex gap-2 mb-2">
            <button
              type="button"
              onClick={() => setHasUsdOps(true)}
              className={`flex-1 text-sm px-3 py-1.5 rounded-md border transition ${
                hasUsdOps ? 'border-rendi-green bg-rendi-green/10 text-slate-900 dark:text-slate-100 font-medium'
                          : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-slate-300'
              }`}
            >
              Sí, hay operaciones en USD
            </button>
            <button
              type="button"
              onClick={() => setHasUsdOps(false)}
              className={`flex-1 text-sm px-3 py-1.5 rounded-md border transition ${
                !hasUsdOps ? 'border-rendi-green bg-rendi-green/10 text-slate-900 dark:text-slate-100 font-medium'
                           : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:border-slate-300'
              }`}
            >
              No, todo es en ARS
            </button>
          </div>
          {hasUsdOps && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Vamos a crear automáticamente un sub-broker USD asociado a {singleBroker} y rutear cada fila según la moneda: las ARS al broker padre, las USD al sub-broker.
            </p>
          )}
          {!hasUsdOps && (
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Todas las filas se van a importar al broker en ARS. Si después aparecen filas con moneda USD, se van a registrar igual al broker padre.
            </p>
          )}
        </div>
      )}

      <div>
        <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Formato del archivo</label>
        <select
          value={format}
          onChange={e => setFormat(e.target.value)}
          className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200"
        >
          {parsers.map(p => (
            <option key={p.id} value={p.id} disabled={!p.supported}>
              {p.label}{!p.supported ? ' (próximamente)' : ''}
            </option>
          ))}
        </select>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          El template genérico funciona con cualquier CSV — vas a poder mapear las columnas en el siguiente paso.
        </p>
      </div>

      <button
        onClick={downloadTemplate}
        className="inline-flex items-center gap-1.5 text-sm text-rendi-green hover:underline"
      >
        <Download size={14} /> Descargar template de ejemplo
      </button>

      <div>
        <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Archivo CSV</label>
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={e => { e.preventDefault() }}
          onDrop={e => {
            e.preventDefault()
            const f = e.dataTransfer.files?.[0]
            if (f) setFile(f)
          }}
          className="border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-lg p-6 text-center cursor-pointer hover:border-rendi-green/50 transition"
        >
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={e => setFile(e.target.files?.[0] || null)}
          />
          {file ? (
            <div className="flex items-center justify-center gap-2 text-sm text-slate-700 dark:text-slate-200">
              <FileText size={16} />
              <span className="font-medium">{file.name}</span>
              <span className="text-slate-500">({(file.size / 1024).toFixed(1)} KB)</span>
            </div>
          ) : (
            <div className="text-sm text-slate-500 dark:text-slate-400">
              <Upload size={20} className="mx-auto mb-2 opacity-60" />
              Soltá un archivo CSV o hacé clic para seleccionarlo
            </div>
          )}
        </div>
      </div>

      <div className="text-xs text-slate-500 dark:text-slate-400 space-y-1">
        <p>Antes de importar, generamos una vista previa: vas a poder revisar fila por fila lo que Rendi entendió antes de guardar nada.</p>
        <p>Si tu archivo tiene errores, las filas válidas se importan igual y te mostramos cuáles fallaron.</p>
      </div>
    </div>
  )
}


function MapStep({ inspect, mapping, setMapping, brokers, importMode, singleBroker, useCurrencyRouting }) {
  const headers = inspect.headers || []
  const allFields = inspect.rendi_fields || []
  const sampleRows = inspect.sample_rows || []
  // En modo single-broker el campo broker queda fijo y no se muestra en el mapeo.
  const fields = importMode === 'single'
    ? allFields.filter(f => f.id !== 'broker')
    : allFields

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
        <div className="flex flex-col gap-1 px-3 py-2 rounded-md bg-rendi-green/10 border border-rendi-green/30 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-slate-700 dark:text-slate-200">Importando todo a:</span>
            <span className="font-semibold text-slate-900 dark:text-slate-100">{singleBroker}</span>
          </div>
          {useCurrencyRouting && (
            <div className="text-xs text-slate-600 dark:text-slate-300">
              Filas en USD → al sub-broker <span className="font-medium">{singleBroker} · USD</span> (auto-creado).
            </div>
          )}
        </div>
      )}

      <div className="text-xs text-slate-600 dark:text-slate-300">
        <p className="mb-1">
          Decile a Rendi qué columna de tu archivo corresponde a cada dato. Auto-detectamos las que pudimos por el nombre, ajustá lo que haga falta.
        </p>
        <p className="text-slate-500 dark:text-slate-400">
          {importMode === 'single'
            ? 'Si tu archivo no tiene una columna (ej.: moneda), podés definir un valor fijo para todas las filas.'
            : 'Si tu archivo no tiene una columna (ej.: broker o moneda), podés definir un valor fijo para todas las filas.'}
        </p>
      </div>

      <div className="px-3 py-2 rounded-md bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
          Columnas detectadas en tu archivo
        </div>
        <div className="flex flex-wrap gap-1.5">
          {headers.map(h => (
            <span key={h} className="text-xs bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded px-2 py-0.5 font-mono">
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
              <label className="text-xs text-slate-700 dark:text-slate-200 inline-flex items-center gap-1">
                <span>{f.label}{f.required && <span className="text-red-500 ml-0.5">*</span>}</span>
                {help && (
                  <InfoTooltip size={11} align="left" label={`Qué es ${f.label}`}>
                    <p className="font-semibold text-slate-800 dark:text-slate-100">{help.title}</p>
                    <p>{help.body}</p>
                    {help.examples && (
                      <p className="text-slate-500 dark:text-slate-400 italic">{help.examples}</p>
                    )}
                  </InfoTooltip>
                )}
              </label>
              <select
                value={colVal}
                onChange={e => setColumn(f.id, e.target.value)}
                className="w-full bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-900 dark:text-slate-200"
              >
                <option value="">— sin columna —</option>
                {headers.map(h => <option key={h} value={h}>{h}</option>)}
              </select>
              {f.allow_default ? (
                f.id === 'broker' && brokers.length > 0 ? (
                  <select
                    value={defVal}
                    onChange={e => setDefault(f.id, e.target.value)}
                    className="w-full bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-900 dark:text-slate-200"
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
                    className="w-full bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-900 dark:text-slate-200 placeholder-slate-400"
                  />
                )
              ) : <div />}
            </div>
          )
        })}
      </div>

      {sampleRows.length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
            Vista previa de tu archivo (primeras filas)
          </div>
          <div className="overflow-x-auto border border-slate-200 dark:border-slate-700 rounded-md">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-900/40">
                  {headers.map(h => (
                    <th key={h} className="px-2 py-1 text-left font-mono text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sampleRows.map((r, i) => (
                  <tr key={i} className="border-t border-slate-100 dark:border-slate-700/40">
                    {headers.map(h => (
                      <td key={h} className="px-2 py-1 text-slate-700 dark:text-slate-200 whitespace-nowrap">
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


function PreviewStep({ preview, importMode, singleBroker, useCurrencyRouting }) {
  const s = preview.summary || {}
  const dup = preview.duplicate_of_batch_id
  const routing = preview.routing_summary

  return (
    <div className="space-y-4">
      {importMode === 'single' && singleBroker && (
        <div className="flex flex-col gap-1 px-3 py-2 rounded-md bg-rendi-green/10 border border-rendi-green/30 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-slate-700 dark:text-slate-200">Importando todo a:</span>
            <span className="font-semibold text-slate-900 dark:text-slate-100">{singleBroker}</span>
          </div>
          {useCurrencyRouting && routing && (
            <div className="text-xs text-slate-600 dark:text-slate-300">
              <span className="tabular">{routing.ars_rows_to_parent}</span> filas ARS → {singleBroker}{' · '}
              <span className="tabular">{routing.usd_rows_to_sibling}</span> filas USD → {singleBroker} · USD <span className="text-slate-500 dark:text-slate-400">(sub-broker)</span>
            </div>
          )}
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
        <ul className="text-sm text-slate-700 dark:text-slate-300 space-y-1">
          {(s.by_operation_type || []).map(it => (
            <li key={it.type} className="flex justify-between">
              <span>{it.label}</span>
              <span className="tabular font-medium">{it.count}</span>
            </li>
          ))}
        </ul>
        <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-500 dark:text-slate-400 space-y-0.5">
          <div>{s.estimated_impact?.positions_to_create || 0} posiciones nuevas en <em>Posiciones</em></div>
          <div>{s.estimated_impact?.operations_to_create || 0} operaciones cerradas en <em>Operaciones</em></div>
          <div>{s.estimated_impact?.cash_movements || 0} movimientos de cash</div>
          <div>{s.estimated_impact?.fx_conversions || 0} conversiones de moneda</div>
        </div>
      </Section>

      {s.date_range && (
        <div className="text-xs text-slate-500 dark:text-slate-400">
          Período: <span className="text-slate-700 dark:text-slate-300 tabular">{s.date_range.from}</span> → <span className="text-slate-700 dark:text-slate-300 tabular">{s.date_range.to}</span>
        </div>
      )}

      {(preview.by_asset || []).length > 0 && (
        <Section title="Por activo">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 dark:text-slate-400">
                <th className="py-1">Activo</th><th className="py-1">Compras</th><th className="py-1">Ventas</th><th className="py-1 text-right">Neto</th>
              </tr>
            </thead>
            <tbody>
              {preview.by_asset.map(a => (
                <tr key={a.asset} className="border-t border-slate-100 dark:border-slate-700/40">
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

      {(preview.errors || []).length > 0 && (
        <Section title={`Errores (${preview.errors.length})`} variant="error">
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
        <Section title={`Filas a importar (${preview.rows_preview.length})`}>
          <div className="max-h-60 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white dark:bg-slate-800">
                <tr className="text-left text-slate-500 dark:text-slate-400">
                  <th className="py-1">#</th>
                  <th className="py-1">Fecha</th>
                  <th className="py-1">Tipo</th>
                  <th className="py-1">Activo</th>
                  <th className="py-1 text-right">Cant.</th>
                  <th className="py-1 text-right">Precio</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows_preview.map(r => (
                  <tr key={r.row_index} className="border-t border-slate-100 dark:border-slate-700/40">
                    <td className="py-1 tabular text-slate-400">{r.row_index}</td>
                    <td className="py-1 tabular">{r.date}</td>
                    <td className="py-1">{OP_LABELS[r.operation_type] || r.operation_type}</td>
                    <td className="py-1 font-medium">{r.asset_symbol || '—'}</td>
                    <td className="py-1 tabular text-right">{r.quantity ?? '—'}</td>
                    <td className="py-1 tabular text-right">{r.unit_price ?? r.gross_amount ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  )
}


function DoneStep({ result }) {
  return (
    <div className="text-center py-6 space-y-3">
      <CheckCircle2 size={36} className="mx-auto text-rendi-green" />
      <h3 className="font-semibold text-slate-900 dark:text-slate-100">Importación completada</h3>
      <div className="text-sm text-slate-600 dark:text-slate-300 space-y-1">
        <p>{result.positions_created || 0} posiciones nuevas</p>
        <p>{result.operations_created || 0} operaciones cerradas</p>
        <p>{result.cash_movements || 0} movimientos de cash</p>
        <p>{result.conversions || 0} conversiones de moneda</p>
      </div>
    </div>
  )
}


function SummaryBox({ label, value, positive, negative }) {
  return (
    <div className={`px-3 py-2 rounded-md border
      ${positive ? 'border-emerald-500/30 bg-emerald-500/5' :
        negative ? 'border-red-500/30 bg-red-500/5' :
        'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40'}`}>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 tabular
        ${positive ? 'text-emerald-700 dark:text-emerald-400' :
          negative ? 'text-red-700 dark:text-red-400' :
          'text-slate-900 dark:text-slate-100'}`}>{value}</div>
    </div>
  )
}


function Section({ title, children, variant }) {
  return (
    <div>
      <div className={`text-xs font-medium mb-2
        ${variant === 'error' ? 'text-red-700 dark:text-red-400' : 'text-slate-700 dark:text-slate-300'}`}>
        {title}
      </div>
      <div className={`px-3 py-2 rounded-md border
        ${variant === 'error' ? 'border-red-500/30 bg-red-500/5' :
          'border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40'}`}>
        {children}
      </div>
    </div>
  )
}
