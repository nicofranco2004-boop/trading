// NotasGrafico — las banderitas de tus notas y de tu tesis en el gráfico técnico.
// ════════════════════════════════════════════════════════════════════════════
// Una NOTA (Nico, 30/10: «compré acá por el balance») es uno de tus dibujos
// (utils/dibujos.js, tipo 'nota'): un texto en un día y un precio, guardado en
// tu cuenta con los demás, que se mueve, se colorea y se deshace como ellos.
//
// Tu TESIS no se copia acá: es la de la ficha (backend/tesis.py, con historia
// por día) y cada versión aparece como una banderita violeta en el día en que
// la escribiste, a la altura del cierre de ese día. Tocarla la muestra y lleva
// a la tesis de la ficha, que es donde se edita: un solo lugar para lo mismo.
//
// Las banderitas no se amontonan: las que en la pantalla se pisarían se juntan
// en UNA con el número de cuántas son (también en el celular, porque se mide
// en píxeles con el ancho real), y tocarla las lista. La elegida va siempre
// sola, para poder leerla y arrastrarla. Lo que dicen se lee en el cartel de
// arriba del gráfico (LecturaTecnica), que usa todo el ancho: un globo pegado a
// la banderita, en un celular de 375 px, se salía de la pantalla.
//
// No van en la imagen de «Compartir» (utils/imagenGrafico.js): son tuyas.

import { useState } from 'react'
import { Lightbulb, Pencil, StickyNote, Trash2 } from 'lucide-react'
import { colorDe } from './CapaDibujos'
import { NOTA_MAXIMA, largoDeNota, limpiarNota, recortarNota } from '../../utils/dibujos'

// El cuadradito de la banderita y el palito que la une a su punto, en px.
export const BANDERITA_PX = 22
const PALITO_PX = 9
export const COLOR_TESIS = 'rgb(var(--data-violet))'

// El id de lo que se elige al tocar una banderita: una nota, su id; una
// versión de tu tesis, «tesis:<id>»; varias juntas, «grupo:<id>,<id>…». Los
// dos puntos no entran en el id de un dibujo (main._Dibujo), así no se pisan.
export const claveDeTesis = (id) => `tesis:${id}`
export const esClaveDeTesis = (id) => typeof id === 'string' && id.startsWith('tesis:')
export const esClaveDeGrupo = (id) => typeof id === 'string' && id.startsWith('grupo:')
export const clavesDelGrupo = (id) => (esClaveDeGrupo(id) ? id.slice(6).split(',').filter(Boolean) : [])

/**
 * Las banderitas en lo que se ve, ya juntadas: [{ id, x, y, arriba, items }].
 * `x` e `y` son el punto (de 0 a 100); `arriba`: la banderita va arriba del
 * punto (abajo si no entra). `items`: [{ clave, tipo: 'nota'|'tesis', color,
 * texto, ... }].
 *  · notas: tus notas, ya ubicadas ({ id, a: { k, precio }, texto, color })
 *  · tesis: las versiones de tu tesis, ya ubicadas ({ id, k, precio, texto, escrita_el })
 *  · provisoria: la nota que se está escribiendo ({ k, precio, color }), sola.
 */
export function banderitasEnVista({ notas = [], tesis = [], provisoria = null, pctX, pctY, ancho, alto, elegido = null }) {
  const lista = [
    ...notas.filter(n => n.a).map(n => ({ clave: n.id, tipo: 'nota', color: colorDe(n), texto: n.texto, x: pctX(n.a.k), y: pctY(n.a.precio), nota: n })),
    ...tesis.map(t => ({ clave: claveDeTesis(t.id), tipo: 'tesis', color: COLOR_TESIS, texto: t.texto, escrita_el: t.escrita_el, x: pctX(t.k), y: pctY(t.precio), tesis: t })),
  ].filter(b => b.x >= 0 && b.x <= 100 && b.y >= 0 && b.y <= 100)
    .sort((a, b) => a.x - b.x || a.y - b.y)
  const alto_ = Math.max(1, alto || 1), ancho_ = Math.max(1, ancho || 1)
  const arribaDe = (y) => (y / 100) * alto_ >= PALITO_PX + BANDERITA_PX + 2
  // Dónde queda el centro del cuadradito, en px.
  const centro = (b) => {
    const arriba = arribaDe(b.y)
    const off = PALITO_PX + BANDERITA_PX / 2
    return { cx: (b.x / 100) * ancho_, cy: (b.y / 100) * alto_ + (arriba ? -off : off), arriba }
  }
  const grupos = []
  for (const b of lista) {
    const c = centro(b)
    const solo = b.clave === elegido
    const g = solo ? null : grupos.find(x => !x.solo && Math.abs(x.cx - c.cx) < BANDERITA_PX + 2 && Math.abs(x.cy - c.cy) < BANDERITA_PX + 2)
    if (g) g.items.push(b)
    else grupos.push({ x: b.x, y: b.y, cx: c.cx, cy: c.cy, arriba: c.arriba, solo, items: [b] })
  }
  const out = grupos.map(g => ({
    id: g.items.length === 1 ? g.items[0].clave : `grupo:${g.items.map(b => b.clave).join(',')}`,
    x: g.x, y: g.y, cx: g.cx, cy: g.cy, arriba: g.arriba, items: g.items,
  }))
  if (provisoria && provisoria.precio != null) {
    const b = { x: pctX(provisoria.k), y: pctY(provisoria.precio) }
    if (b.x >= 0 && b.x <= 100 && b.y >= 0 && b.y <= 100) {
      const c = centro(b)
      out.push({ id: '__nota__', provisoria: true, x: b.x, y: b.y, cx: c.cx, cy: c.cy, arriba: c.arriba,
        items: [{ clave: '__nota__', tipo: 'nota', color: provisoria.color || colorDe(null), texto: '' }] })
    }
  }
  return out
}

/** La banderita que está en (x, y) px (dentro del gráfico), con `margen` px de
 *  más alrededor (el dedo necesita más que el mouse). Su id, o null. La
 *  elegida gana aunque otra vecina quede más cerca del toque: se dibuja encima
 *  y es la que se quiere arrastrar. */
export function banderitaEn(grupos, x, y, margen = 4, elegido = null) {
  let mejor = null, dist = Infinity
  for (const g of grupos) {
    if (g.provisoria) continue
    const mitad = BANDERITA_PX / 2 + margen
    const enCuadro = Math.abs(x - g.cx) <= mitad && Math.abs(y - g.cy) <= mitad
    // También el palito y el punto: de donde arranca a donde está el cuadradito.
    const enPalito = Math.abs(x - g.cx) <= margen + 2 && (y - g.cy) * (y - (g.cy + (g.arriba ? 1 : -1) * (PALITO_PX + BANDERITA_PX / 2))) <= 0
    if (!enCuadro && !enPalito) continue
    const d = g.id === elegido ? -1 : Math.hypot(x - g.cx, y - g.cy)
    if (d < dist) { mejor = g.id; dist = d }
  }
  return mejor
}

/** Lo que dice el globito de una banderita con el mouse encima. */
function avance(g) {
  if (g.items.length > 1) {
    const n = g.items.filter(b => b.tipo === 'nota').length, t = g.items.length - n
    const partes = [n && `${n} nota${n === 1 ? '' : 's'}`, t && `${t === 1 ? 'tu tesis' : `${t} versiones de tu tesis`}`].filter(Boolean)
    return `${partes.join(' y ')} acá: tocá para verlas.`
  }
  const b = g.items[0]
  return b.tipo === 'tesis' ? `Tu tesis: «${b.texto}»` : b.texto
}

export default function Banderitas({ grupos, elegido = null, resaltado = null, ancho = 1000 }) {
  if (!grupos.length) return null
  // La elegida, última: queda encima de las vecinas.
  const enOrden = [...grupos.filter(g => g.id !== elegido), ...grupos.filter(g => g.id === elegido)]
  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden="true">
      {enOrden.map(g => {
        const varias = g.items.length > 1
        const tesis = !varias && g.items[0].tipo === 'tesis'
        const color = varias ? 'rgb(var(--ink-2))' : g.items[0].color
        const marcada = g.id === elegido || g.id === resaltado
        return (
          <div key={g.id} data-banderita={g.id} data-tipo={varias ? 'grupo' : g.items[0].tipo} className="absolute" style={{ left: `${g.x}%`, top: `${g.y}%` }}>
            <span className="absolute w-1.5 h-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ background: color }} />
            <span className="absolute w-px -translate-x-1/2" style={{ height: PALITO_PX, top: g.arriba ? -PALITO_PX : 0, background: color }} />
            <span className={`absolute -translate-x-1/2 inline-flex items-center justify-center rounded border-2 shadow-sm ${g.provisoria ? 'opacity-70 border-dashed' : ''} ${marcada ? 'ring-2 ring-ink-0/40' : ''}`}
              style={{ width: BANDERITA_PX, height: BANDERITA_PX, top: g.arriba ? -(PALITO_PX + BANDERITA_PX) : PALITO_PX,
                borderColor: color, background: tesis ? color : 'rgb(var(--bg-1))' }}>
              {varias ? <span className="text-[11px] font-semibold leading-none tabular text-ink-0">{g.items.length}</span>
                : tesis ? <Lightbulb size={13} strokeWidth={2.4} color="rgb(var(--bg-0))" />
                  : <StickyNote size={13} strokeWidth={2.4} color={color} />}
            </span>
            {/* Con el mouse encima, un adelanto (corto). Entero, en el cartel. */}
            {g.id === resaltado && g.id !== elegido && !g.provisoria && (
              <span data-adelanto="" className="absolute z-10 w-max rounded border border-line-2 bg-bg-raised/95 px-2 py-1 text-[11.5px] leading-snug text-ink-0 shadow-sm line-clamp-3 whitespace-pre-line break-words"
                style={{ top: g.arriba ? -(PALITO_PX + BANDERITA_PX + 4) : PALITO_PX + BANDERITA_PX + 4,
                  // Que no se salga del gráfico: a lo sumo 14rem y lo que haya de lugar de ese lado.
                  maxWidth: Math.max(96, Math.min(224, g.x > 60 ? g.cx : g.x < 40 ? ancho - g.cx : 2 * Math.min(g.cx, ancho - g.cx))),
                  transform: `translateX(${g.x > 60 ? '-100%' : g.x < 40 ? '0' : '-50%'})${g.arriba ? ' translateY(-100%)' : ''}` }}>
                {avance(g)}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

const BOTON = 'inline-flex items-center gap-1.5 min-h-10 sm:min-h-8 px-3 rounded-lg border'
const BOTON_LISTO = `${BOTON} border-line-2 text-ink-1 hover:text-ink-0`

/** Dónde está una nota: «el 12/03/26, a US$ 180,25» (o días después del último día que había). */
function dondeEsta(n, precio, fecha) {
  const dia = n.a.mas > 0 ? `${n.a.mas} día${n.a.mas === 1 ? '' : 's'} de mercado después del ${fecha(n.a.d)}` : `el ${fecha(n.a.d)}`
  return `${dia}, a ${precio(n.a.precio)}`
}

// El campo donde se escribe una nota (la nueva o la que se corrige). En el
// celular la letra va a 16 px: más chica, el iPhone acerca la página al tocarlo.
function CampoNota({ id, texto, setTexto, onGuardar, onCancelar, guardar = 'Guardar' }) {
  const vacia = !limpiarNota(texto)
  const largo = largoDeNota(texto)
  return (
    <div className="flex flex-col gap-1.5">
      <textarea id={id} autoFocus rows={2} value={texto} maxLength={NOTA_MAXIMA * 2}
        onChange={e => setTexto(recortarNota(e.target.value))}
        onKeyDown={e => {
          // Cmd/Ctrl+Enter guarda; Esc cancela (sólo esto: no achica la pantalla completa).
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !vacia) { e.preventDefault(); onGuardar() }
          if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancelar() }
        }}
        placeholder="Por ejemplo: «compré acá por el balance»."
        className="w-full resize-y bg-bg-1 border border-line rounded px-2.5 py-1.5 text-base sm:text-[13px] leading-snug text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`text-[11.5px] tabular ${largo >= NOTA_MAXIMA ? 'text-rendi-warn' : 'text-ink-2'}`}>
          {largo} de {NOTA_MAXIMA} letras · Sólo la ves vos: no va en la imagen de «Compartir».
        </span>
        <span className="flex gap-2">
          <button type="button" onClick={onCancelar} className={BOTON_LISTO}>Cancelar</button>
          <button type="button" onClick={onGuardar} disabled={vacia}
            title={vacia ? 'Sin texto no se guarda' : undefined}
            className={`${BOTON} border-data-cyan/60 bg-data-cyan/15 text-ink-0 font-medium disabled:opacity-40`}>{guardar}</button>
        </span>
      </div>
    </div>
  )
}

/**
 * El cartel de arriba del gráfico para tus notas y tu tesis (LecturaTecnica):
 *  · modo 'escribir': la nota nueva, con su punto ya tocado;
 *  · modo 'elegido': la nota elegida (leerla entera, corregirla, cambiarle el
 *    color, borrarla), una versión de tu tesis (leerla e ir a editarla a la
 *    ficha) o un grupo de banderitas juntas (elegir cuál).
 */
export function CartelDeNotas({ modo, elegido, notas, tesis = [], texto, setTexto, onGuardar, onCancelar,
  editando, setEditando, onCorregir, onBorrar, onElegir, onListo, onVerTesis = null, precio, fecha, colores }) {
  const [borrador, setBorrador] = useState('')
  if (modo === 'escribir') {
    return (
      <>
        <label htmlFor="nota-nueva" className="block mb-1">
          <b className="font-semibold text-ink-0">Tu nota.</b> Tocá otro punto del gráfico si querés cambiarla de lugar. Sin texto no se guarda.
        </label>
        <CampoNota id="nota-nueva" texto={texto} setTexto={setTexto} onGuardar={onGuardar} onCancelar={onCancelar} />
      </>
    )
  }
  const versiones = [...tesis].sort((a, b) => (a.escrita_el < b.escrita_el ? -1 : a.escrita_el > b.escrita_el ? 1 : a.id - b.id))
  const deTesis = (clave) => versiones.find(t => claveDeTesis(t.id) === clave)
  if (esClaveDeGrupo(elegido)) {
    const items = clavesDelGrupo(elegido).map(c => (esClaveDeTesis(c) ? { c, t: deTesis(c) } : { c, n: notas.find(n => n.id === c) }))
      .filter(x => x.t || x.n)
    return (
      <div className="flex flex-col gap-1.5">
        <span>Acá hay {items.length} banderitas juntas: tocá una para leerla. Si acercás el gráfico, se separan.</span>
        <ul className="flex flex-col gap-1">
          {items.map(({ c, t, n }) => (
            <li key={c}>
              <button type="button" data-elegir={c} onClick={() => onElegir(c)}
                className="w-full flex items-start gap-2 min-h-10 rounded-lg border border-line-2 bg-bg-1 px-2.5 py-1.5 text-left hover:border-ink-3">
                {t ? <Lightbulb size={14} className="mt-0.5 shrink-0" color={COLOR_TESIS} aria-hidden="true" />
                  : <StickyNote size={14} className="mt-0.5 shrink-0" color={colorDe(n)} aria-hidden="true" />}
                <span className="min-w-0 flex-1">
                  <span className="text-ink-2">{t ? `Tu tesis, el ${fecha(t.escrita_el)}` : `Nota, ${dondeEsta(n, precio, fecha)}`}: </span>
                  <span className="text-ink-0 line-clamp-2 break-words">{t ? t.texto : n.texto}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <span><button type="button" onClick={onListo} className={BOTON_LISTO}>Listo</button></span>
      </div>
    )
  }
  if (esClaveDeTesis(elegido)) {
    const t = deTesis(elegido)
    const vigente = versiones[versiones.length - 1]
    return (
      <div className="flex flex-col gap-1.5">
        {t ? (
          <>
            <span className="inline-flex items-center gap-1.5">
              <Lightbulb size={14} color={COLOR_TESIS} aria-hidden="true" />
              <b className="font-semibold text-ink-0">Tu tesis, escrita el {fecha(t.escrita_el)}</b>
              {t !== vigente && <span className="text-ink-2">(después la cambiaste)</span>}
            </span>
            <p className="text-[13.5px] text-ink-0 whitespace-pre-line break-words">«{t.texto}»</p>
            <span className="text-ink-2">Está en el día en que la escribiste. Se edita en «Tu tesis», en la ficha.</span>
          </>
        ) : <span>Esa versión de tu tesis ya no está.</span>}
        <span className="flex flex-wrap gap-2">
          {t && onVerTesis && (
            <button type="button" onClick={onVerTesis} className={`${BOTON} border-data-violet/50 bg-data-violet/10 text-ink-0 font-medium`}>
              Ver o editar tu tesis
            </button>
          )}
          <button type="button" onClick={onListo} className={BOTON_LISTO}>Listo</button>
        </span>
      </div>
    )
  }
  const n = notas.find(x => x.id === elegido)
  if (!n) return null
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-ink-2">
        <b className="font-semibold text-ink-0">Tu nota</b>, {dondeEsta(n, precio, fecha)}.{!editando && ' Arrastrala para moverla.'}
      </span>
      {editando ? (
        <CampoNota id="nota-elegida" texto={borrador} setTexto={setBorrador} guardar="Guardar cambios"
          onGuardar={() => onCorregir(n.id, borrador)} onCancelar={() => setEditando(false)} />
      ) : (
        <>
          <p data-texto-nota="" className="text-[13.5px] text-ink-0 whitespace-pre-line break-words">{n.texto}</p>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <button type="button" onClick={() => { setBorrador(n.texto); setEditando(true) }} className={`${BOTON} border-line-2 bg-bg-1 text-ink-0`}>
              <Pencil size={14} aria-hidden="true" />Editar
            </button>
            <button type="button" onClick={() => onBorrar(n.id)} className={`${BOTON} border-rendi-neg/50 bg-rendi-neg/10 text-ink-0 font-medium`}>
              <Trash2 size={14} aria-hidden="true" />Borrar esta nota
            </button>
            {colores(n)}
            <button type="button" onClick={onListo} className={BOTON_LISTO}>Listo</button>
          </span>
        </>
      )}
    </div>
  )
}
