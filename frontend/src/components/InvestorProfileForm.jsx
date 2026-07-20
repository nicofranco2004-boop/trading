// InvestorProfileForm — test de 7 preguntas para alimentar el Coach IA.
// ═══════════════════════════════════════════════════════════════════════════
// Vive en /config dentro de Panel "Perfil de inversor". Las respuestas se
// guardan en users.investor_profile (JSON) y se inyectan en el system prompt
// del Coach IA para que tenga contexto del horizonte, tolerancia, objetivo
// y experiencia del user.
//
// UX: pills clickeables, no dropdowns. Una pregunta por bloque, con eyebrow
// uppercase pequeño + opciones en flex-wrap. Guardado optimista — si falla
// el POST mostramos error inline.

import { useEffect, useState } from 'react'
import { api } from '../utils/api'
import { Sparkles, Check } from 'lucide-react'

const QUESTIONS = [
  {
    id: 'horizon',
    label: 'Horizonte',
    hint: '¿En cuánto tiempo esperás necesitar el grueso de esta plata?',
    options: [
      { id: 'short',  label: 'Corto plazo',    sub: 'Días a semanas' },
      { id: 'medium', label: 'Mediano plazo',  sub: 'Meses' },
      { id: 'long',   label: 'Largo plazo',    sub: 'Años' },
    ],
  },
  {
    id: 'drawdown',
    label: 'Si tu cartera cae 30% en un mes, ¿qué hacés?',
    options: [
      { id: 'sell_all',  label: 'Vendo todo',         sub: 'Corto la sangría' },
      { id: 'sell_some', label: 'Vendo una parte',    sub: 'Reduzco exposición' },
      { id: 'hold',      label: 'Mantengo',           sub: 'Espero recuperación' },
      { id: 'buy_more',  label: 'Compro más',         sub: 'Promedio abajo' },
    ],
  },
  {
    id: 'goal',
    label: 'Objetivo principal',
    options: [
      { id: 'retirement',         label: 'Jubilación' },
      { id: 'freedom',            label: 'Libertad financiera' },
      { id: 'learn',              label: 'Aprender a invertir' },
      { id: 'hobby',              label: 'Hobby / pasatiempo' },
      { id: 'specific_purchase',  label: 'Compra puntual',    sub: 'Casa, auto, viaje' },
    ],
  },
  {
    id: 'style',
    label: 'Estilo',
    options: [
      { id: 'passive', label: 'Pasivo',  sub: 'Buy & hold' },
      { id: 'active',  label: 'Activo',  sub: 'Trading frecuente' },
      { id: 'mixed',   label: 'Mixto',   sub: 'Combino los dos' },
    ],
  },
  {
    id: 'net_worth',
    label: '¿Qué porcentaje de tu patrimonio total tenés invertido acá?',
    options: [
      { id: 'under_10',  label: '< 10%' },
      { id: '10_to_30',  label: '10 – 30%' },
      { id: '30_to_60',  label: '30 – 60%' },
      { id: 'over_60',   label: '+60%' },
    ],
  },
  {
    id: 'liquidity',
    label: '¿Necesitás parte de esta plata en los próximos 12-24 meses?',
    options: [
      { id: 'yes',     label: 'Sí',         sub: 'La necesito en menos de 2 años' },
      { id: 'partial', label: 'Parcial',    sub: 'Quizás una porción' },
      { id: 'no',      label: 'No',         sub: 'Es plata de largo plazo' },
    ],
  },
  {
    id: 'experience',
    label: 'Experiencia invirtiendo',
    options: [
      { id: 'first_time', label: 'Primera vez' },
      { id: 'under_2',    label: '< 2 años' },
      { id: '2_to_5',     label: '2 – 5 años' },
      { id: 'over_5',     label: '+5 años' },
    ],
  },
  {
    id: 'return_expectation',
    label: '¿Qué esperás que rinda esta plata?',
    hint: 'En términos reales — contra la inflación.',
    options: [
      { id: 'preserve',       label: 'Preservar capital',      sub: 'Que no me la coma la inflación' },
      { id: 'beat_inflation', label: 'Ganarle a la inflación', sub: 'Algunos puntos por encima' },
      { id: 'grow',           label: 'Crecer fuerte',          sub: 'Inflación + ~10 puntos' },
      { id: 'aggressive',     label: 'Maximizar retorno',      sub: 'Banco la volatilidad por más upside' },
    ],
  },
]

export default function InvestorProfileForm() {
  const [profile, setProfile] = useState({})
  const [loading, setLoading] = useState(true)
  const [saveState, setSaveState] = useState({ saving: false, error: '', justSaved: false })

  useEffect(() => {
    let alive = true
    api.get('/auth/investor-profile')
      .then(data => { if (alive) setProfile(data || {}) })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  async function setAnswer(qid, value) {
    const next = { ...profile, [qid]: value }
    setProfile(next)
    setSaveState({ saving: true, error: '', justSaved: false })
    try {
      await api.post('/auth/investor-profile', next)
      setSaveState({ saving: false, error: '', justSaved: true })
      setTimeout(() => setSaveState(s => ({ ...s, justSaved: false })), 1500)
    } catch (ex) {
      setSaveState({ saving: false, error: ex?.message || 'No pudimos guardar', justSaved: false })
    }
  }

  const answered = QUESTIONS.filter(q => profile[q.id]).length

  return (
    <div className="px-4 py-4 space-y-5">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <p className="text-xs text-ink-3 leading-relaxed max-w-2xl">
          {QUESTIONS.length} preguntas rápidas para que el Coach IA te conozca mejor — todas opcionales,
          y cuantas más respondas, más insights de perfil desbloqueás. Se guarda automáticamente.
          Las respuestas no se comparten — solo viajan al prompt de la IA cuando le hablás.
        </p>
        <span className="text-[12.5px] text-ink-2 whitespace-nowrap font-medium">
          {answered}/{QUESTIONS.length} respondidas
          {saveState.justSaved && (
            <span className="ml-2 inline-flex items-center gap-1 text-rendi-pos">
              <Check size={10} strokeWidth={2} /> guardado
            </span>
          )}
        </span>
      </div>

      {loading ? (
        <p className="text-xs text-ink-3">Cargando…</p>
      ) : (
        <div className="space-y-4">
          {QUESTIONS.map(q => (
            <fieldset key={q.id} className="border-t border-line/30 pt-3 first:border-t-0 first:pt-0">
              <legend className="text-[12.5px] text-ink-2 mb-1 font-medium">
                {q.label}
              </legend>
              {q.hint && (
                <p className="text-[11px] text-ink-3 mb-2 leading-snug">{q.hint}</p>
              )}
              <div className="flex flex-wrap gap-2">
                {q.options.map(opt => {
                  const selected = profile[q.id] === opt.id
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => setAnswer(q.id, opt.id)}
                      className={`text-left rounded-sm px-3 py-2 border transition-colors ${
                        selected
                          ? 'bg-data-violet/15 border-data-violet text-ink-0'
                          : 'bg-bg-1 hover:bg-bg-2 border-line/50 text-ink-1'
                      }`}
                    >
                      <div className="text-sm font-medium leading-tight">{opt.label}</div>
                      {opt.sub && (
                        <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{opt.sub}</div>
                      )}
                    </button>
                  )
                })}
              </div>
            </fieldset>
          ))}
        </div>
      )}

      {saveState.error && (
        <p className="text-xs text-rendi-neg">{saveState.error}</p>
      )}

      <div className="pt-2 border-t border-line/30 flex items-start gap-2">
        <Sparkles size={12} strokeWidth={1.75} className="text-data-violet flex-shrink-0 mt-0.5" />
        <p className="text-[11px] text-ink-3 leading-snug">
          Cuanto más contestás, más útil es el Coach IA. Vas a poder volver y editar cuando quieras.
        </p>
      </div>
    </div>
  )
}
