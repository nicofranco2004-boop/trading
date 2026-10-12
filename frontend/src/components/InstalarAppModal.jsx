// InstalarAppModal — «Descargar app»: el paso a paso para poner Rendi en la
// pantalla de inicio del celular.
// ════════════════════════════════════════════════════════════════════════════
// Rendi no está en App Store ni en Play Store. Lo que sí hay es una web que ya
// está preparada para instalarse (ícono, nombre, pantalla completa): faltaba
// decirle al usuario cómo. Este cartel se lo dice, con el celular que tiene.
//
//   • iPhone: capturas reales de Safari con el botón marcado. Apple no deja
//     que una página instale sola, así que acá siempre son pasos a mano.
//   • Android: Chrome sí deja → botón «Instalar ahora» cuando el navegador lo
//     ofrece (utils/instalarApp.js), y los pasos a mano como plan B.
//   • Computadora: los pasos se hacen en el celular, y el cartel lo avisa
//     arriba de todo.
//
// Las capturas son recortes de 1206 px de ancho (iPhone, modo oscuro). El
// recuadro violeta NO está pintado en la foto: se dibuja encima con `marco`,
// en porcentajes del recorte, para poder cambiar una foto sin editar imágenes.
// Si Apple mueve un botón: nueva captura → nuevo recorte → nuevo `marco`.
//
// Trigger: «Descargar app» en el pie del Sidebar + tarjeta en /mas.

import { useEffect, useRef, useState } from 'react'
import { Download, MoreVertical, Smartphone, SquarePlus, Globe } from 'lucide-react'
import Modal from './Modal'
import { track } from '../utils/track'
import { plataformaDe, instalarAhora, useHayInstalador } from '../utils/instalarApp'
import iphone1 from '../assets/instalar/iphone-1.jpg'
import iphone2 from '../assets/instalar/iphone-2.jpg'
import iphone3 from '../assets/instalar/iphone-3.jpg'
import iphone4 from '../assets/instalar/iphone-4.jpg'

export const PASOS_IPHONE = [
  {
    foto: iphone1, ancho: 804, alto: 293,
    marco: { left: '4.15%', top: '14.09%', width: '91.63%', height: '29.55%' },
    alt: 'Safari con rendi.finance escrito en la barra de direcciones',
    texto: <>Abrí <b className="font-semibold text-ink-0">rendi.finance</b> en Safari</>,
  },
  {
    foto: iphone2, ancho: 804, alto: 296,
    marco: { left: '43.12%', top: '50%', width: '10.78%', height: '28.38%' },
    alt: 'La barra de abajo de Safari, con el botón Compartir marcado',
    texto: <>Tocá el botón <b className="font-semibold text-ink-0">Compartir</b>, abajo al medio</>,
    nota: '¿No lo ves? En algunos iPhone está adentro de los tres puntitos «···».',
  },
  {
    foto: iphone3, ancho: 804, alto: 219,
    marco: { left: '5.8%', top: '51.22%', width: '88.39%', height: '41.46%' },
    alt: 'El menú de Compartir, con la opción Agregar a inicio marcada',
    texto: <>Bajá en el menú y elegí <b className="font-semibold text-ink-0">Agregar a inicio</b></>,
    nota: 'Si tu iPhone está en inglés dice «Add to Home Screen», como en la foto.',
  },
  {
    foto: iphone4, ancho: 804, alto: 375,
    marco: { left: '79.19%', top: '8.72%', width: '17%', height: '24.2%' },
    alt: 'La pantalla Agregar a inicio, con el botón Agregar marcado arriba a la derecha',
    texto: <>Tocá <b className="font-semibold text-ink-0">Agregar</b>, arriba a la derecha</>,
  },
]

// Android todavía va con dibujos: faltan capturas de un Android de verdad.
export const PASOS_ANDROID = [
  { icono: Globe,        texto: <>Abrí <b className="font-semibold text-ink-0">rendi.finance</b> en Chrome</> },
  { icono: MoreVertical, texto: <>Tocá los <b className="font-semibold text-ink-0">tres puntitos</b>, arriba a la derecha</> },
  { icono: SquarePlus,   texto: <>Elegí <b className="font-semibold text-ink-0">Agregar a pantalla principal</b> (en algunos celulares dice «Instalar app»)</> },
  { icono: Download,     texto: <>Tocá <b className="font-semibold text-ink-0">Instalar</b></> },
]

const PESTANAS = [
  { id: 'iphone',  label: 'iPhone' },
  { id: 'android', label: 'Android' },
]

// Las fotos se piden ANTES de que se abra el cartel: cuando el mouse llega al
// botón del menú, o al entrar a /mas. Pesan 59 KB entre las cuatro y el
// servidor las entrega en 0,2 s, así que para cuando el cartel aparece ya
// están en la memoria del navegador.
//
// Sin esto se veían los cuatro recuadros vacíos un buen rato. La causa no era
// el peso ni el servidor: las imágenes llevaban `loading="lazy"` («pedila
// recién cuando esté por verse»), y Safari, adentro de un cartel con scroll
// propio, se toma su tiempo para decidir que ya se ven. NO volver a ponerlo:
// acá no ahorra nada, porque el <img> sólo existe con el cartel abierto.
let fotosPedidas = false
export function precargarFotosDeInstalar() {
  if (fotosPedidas || typeof Image === 'undefined') return
  fotosPedidas = true
  for (const p of PASOS_IPHONE) {
    const img = new Image()
    img.src = p.foto
  }
}

// El recuadro violeta aparece recién cuando la foto llegó: un recuadro marcando
// un botón sobre una caja vacía parece un cartel roto.
function Foto({ paso }) {
  const ref = useRef(null)
  const [lista, setLista] = useState(false)
  // Si la foto ya estaba en memoria, el navegador puede no avisar con `onLoad`.
  useEffect(() => {
    if (ref.current?.complete && ref.current.naturalWidth > 0) setLista(true)
  }, [])
  return (
    <div className="relative rounded-xl overflow-hidden border border-line-2 bg-bg-0">
      <img ref={ref} src={paso.foto} alt={paso.alt} width={paso.ancho} height={paso.alto}
        decoding="async" onLoad={() => setLista(true)} className="block w-full h-auto" />
      {lista && (
        <span aria-hidden="true" style={paso.marco}
          className="absolute rounded-xl border-2 border-data-violet ring-4 ring-data-violet/30" />
      )}
    </div>
  )
}

function Numero({ n }) {
  return (
    <span className="flex-shrink-0 w-[22px] h-[22px] rounded-full bg-data-violet/15 text-data-violet text-xs font-semibold tabular flex items-center justify-center">
      {n}
    </span>
  )
}

export default function InstalarAppModal({ open, onClose, origen = 'menu' }) {
  // Dónde está parado el usuario. En la compu ('otro') arranca en iPhone.
  const plataforma = typeof navigator === 'undefined' ? 'otro' : plataformaDe(navigator)
  const [pestana, setPestana] = useState(plataforma === 'android' ? 'android' : 'iphone')
  const hayInstalador = useHayInstalador()

  // Cuánta gente lo abre y desde dónde (panel «Uso de Rendi» de /admin).
  useEffect(() => {
    if (open) track('instalar_app_abierto', { origen, plataforma })
  }, [open, origen, plataforma])

  if (!open) return null

  async function instalar() {
    const resultado = await instalarAhora()
    track('instalar_app_un_toque', { resultado, origen })
    if (resultado === 'accepted') onClose()
  }

  return (
    <Modal title="Rendi en tu celular" onClose={onClose} wide>
      <p className="text-[13px] text-ink-2 leading-relaxed mb-4">
        No hace falta App Store ni Play Store: Rendi se instala desde el navegador
        y queda con su ícono en tu pantalla de inicio, como cualquier app.
      </p>

      {plataforma === 'otro' && (
        <p className="text-[13px] text-ink-2 leading-relaxed bg-bg-1 border border-line rounded-xl px-3 py-2.5 mb-4">
          <b className="font-semibold text-ink-0">Estos pasos se hacen en el celular.</b>{' '}
          Abrí <b className="font-semibold text-ink-0">rendi.finance</b> en el navegador del teléfono y seguilos ahí.
        </p>
      )}

      <div role="tablist" aria-label="Tipo de celular" className="flex gap-1 bg-bg-1 border border-line rounded-lg p-[3px] mb-4">
        {PESTANAS.map(p => {
          const activa = pestana === p.id
          return (
            <button key={p.id} type="button" role="tab" aria-selected={activa}
              onClick={() => setPestana(p.id)}
              className={`flex-1 py-2 rounded text-[13px] transition-colors ${
                activa ? 'bg-bg-3 text-ink-0 font-medium' : 'text-ink-2 hover:text-ink-0'
              }`}>
              {p.label}
            </button>
          )
        })}
      </div>

      {pestana === 'iphone' ? (
        <ol className="grid gap-4 md:grid-cols-2">
          {PASOS_IPHONE.map((p, i) => (
            <li key={p.alt}>
              <div className="flex items-start gap-2 mb-2 md:min-h-[40px]">
                <Numero n={i + 1} />
                <p className="text-[13.5px] text-ink-1 leading-snug">{p.texto}</p>
              </div>
              <Foto paso={p} />
              {p.nota && <p className="text-xs text-ink-3 leading-relaxed mt-1.5">{p.nota}</p>}
            </li>
          ))}
        </ol>
      ) : (
        <>
          {hayInstalador && (
            <div className="bg-data-violet/[0.06] border border-data-violet/30 rounded-xl p-3 mb-4">
              <button type="button" onClick={instalar}
                className="w-full inline-flex items-center justify-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-4 py-2.5 transition-colors">
                <Download size={15} strokeWidth={2} aria-hidden="true" />
                Instalar ahora
              </button>
              <p className="text-xs text-ink-3 leading-relaxed mt-2 text-center">
                Tu navegador lo hace en un toque. Si preferís, abajo están los pasos a mano.
              </p>
            </div>
          )}
          <ol className="bg-bg-1 border border-line rounded-xl overflow-hidden">
            {PASOS_ANDROID.map(({ icono: Icono, texto }, i) => (
              <li key={i} className={`flex items-center gap-3 px-3 py-3 ${i > 0 ? 'border-t border-line/60' : ''}`}>
                <Numero n={i + 1} />
                <p className="flex-1 text-[13.5px] text-ink-1 leading-snug">{texto}</p>
                <span className="flex-shrink-0 w-9 h-9 rounded-lg border border-data-violet/40 bg-data-violet/10 text-data-violet flex items-center justify-center">
                  <Icono size={17} strokeWidth={1.75} aria-hidden="true" />
                </span>
              </li>
            ))}
          </ol>
          <p className="text-xs text-ink-3 leading-relaxed mt-2">
            En otros navegadores el botón se llama parecido: buscá «Agregar a pantalla de inicio» en el menú.
          </p>
        </>
      )}

      <p className="flex items-start gap-2 text-xs text-ink-3 leading-relaxed border-t border-line mt-4 pt-3">
        <Smartphone size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" aria-hidden="true" />
        <span>
          Listo: el ícono de Rendi queda en tu pantalla de inicio y abre a pantalla completa.
          {pestana === 'iphone' && ' En iPhone, las notificaciones de Rendi sólo llegan con la app instalada.'}
        </span>
      </p>
    </Modal>
  )
}
