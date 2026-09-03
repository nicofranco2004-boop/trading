/**
 * ModoRendimiento — el toggle Certero / Estimado, compartido.
 *
 * ⚠️ POR QUÉ EXISTE COMO COMPONENTE Y NO COPIADO EN CADA PANTALLA. El toggle nació
 * en la tarjeta de Performance de Métricas y ahí se quedó: el resto de la app
 * publicaba rendimiento SIN él, con motores propios, así que el mismo usuario
 * leía "Anual +16.841 %" en Metas y "+54 % en 44 días" en Métricas. Un control
 * duplicado a mano se desincroniza igual que se desincronizaron los motores.
 *
 * Los dos modos, en una línea:
 *   · CERTERO  — sólo lo valuado a precio real. Menos historia, número exacto.
 *   · ESTIMADO — además la contabilidad reconstruida. Más historia, aproximada,
 *                y no cuenta lo que todavía no vendiste.
 */
export default function ModoRendimiento({ valor, onChange, deshabilitado, motivo, className = '' }) {
  const OPCIONES = [
    { k: 'certero', t: 'Certero',
      h: 'Menos historial, número exacto: sólo lo valuado a precio real.' },
    { k: 'estimado', t: 'Estimado',
      h: 'Más historial, aproximado: reconstruido de tu contabilidad. Sólo se mueve cuando vendés.' },
  ]
  return (
    <div className={`flex gap-1 bg-bg-2 dark:bg-bg-1/60 rounded-lg p-0.5 ${className}`}>
      {OPCIONES.map(({ k, t, h }) => (
        <button
          key={k}
          type="button"
          title={deshabilitado ? (motivo || '') : h}
          disabled={deshabilitado}
          onClick={() => onChange(k)}
          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
            deshabilitado
              ? 'text-ink-3 cursor-not-allowed'
              : valor === k
                ? 'bg-blue-600 text-white'
                : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  )
}
