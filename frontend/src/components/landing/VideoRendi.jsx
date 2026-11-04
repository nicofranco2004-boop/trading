// VideoRendi — «Mirá Rendi en un minuto»: el video de la portada.
// ════════════════════════════════════════════════════════════════════════════
// El video (public/video/) es la app real filmada con una cuenta de prueba
// distinta del demo; sus fuentes y cómo rearmarlo están en
// `rendi 2/rendi-posts-bot/herramientas/videos-dinamicos/portada-1min/LEEME.txt`.
//
// Cómo se comporta:
//   · No se baja hasta que la persona llega acá (`preload="none"`): son 8 MB y
//     la portada es lo primero que se abre desde un anuncio.
//   · Al verse, arranca solo y SIN sonido, en ronda. Es lo único que los
//     navegadores dejan arrancar sin un toque, y desde un anuncio casi todos
//     miran sin sonido: los carteles del video se leen solos.
//   · Al salir de pantalla se pausa; al volver, sigue.
//   · «Activar sonido» lo vuelve a empezar con música y con los controles. Si
//     la persona lo pausó o le dio sonido, se respeta: no se vuelve a pausar ni
//     a arrancar solo.
//   · Con «reducir movimiento» no arranca solo: queda la imagen con el play.

import { useEffect, useRef, useState } from 'react'
import { Volume2 } from 'lucide-react'
import { prefiereSinMovimiento } from '../../utils/movimiento'

const VIDEO = '/video/rendi-en-un-minuto.mp4'
const PORTADA = '/video/rendi-en-un-minuto.jpg'

export default function VideoRendi() {
  const video = useRef(null)
  const marco = useRef(null)
  const elegido = useRef(false)
  const [andando, setAndando] = useState(false)
  const [conSonido, setConSonido] = useState(false)

  const arrancar = () => {
    const v = video.current
    v?.play().then(() => setAndando(true)).catch(() => {})
  }
  const pausar = () => { video.current?.pause(); setAndando(false) }

  useEffect(() => {
    if (prefiereSinMovimiento() || typeof IntersectionObserver === 'undefined') return undefined
    const ojo = new IntersectionObserver(([e]) => {
      const v = video.current
      if (!v) return
      if (e.isIntersecting && !elegido.current) arrancar()
      else if (!e.isIntersecting && !v.paused) pausar()
    }, { threshold: 0.5 })
    ojo.observe(marco.current)
    return () => ojo.disconnect()
  }, [])

  const tocarPlay = () => { elegido.current = true; arrancar() }
  const tocarVideo = () => {
    if (conSonido) return // con los controles a la vista, el navegador maneja el toque
    elegido.current = true
    if (video.current?.paused) arrancar(); else pausar()
  }
  const activarSonido = () => {
    const v = video.current
    if (!v) return
    elegido.current = true
    v.muted = false
    v.currentTime = 0
    setConSonido(true)
    arrancar()
  }

  return (
    <div ref={marco} className="relative w-full max-w-[980px] mx-auto aspect-video rounded-xl overflow-hidden border border-line-2 bg-bg-1 lp-sombra-video">
      <video ref={video} src={VIDEO} poster={PORTADA} muted loop playsInline preload="none"
             controls={conSonido} onClick={tocarVideo}
             onPause={() => setAndando(false)} onPlay={() => setAndando(true)}
             aria-label="Video: Rendi en un minuto, con una cuenta de ejemplo"
             className="absolute inset-0 w-full h-full object-cover" />
      {!andando && (
        <button type="button" onClick={tocarPlay} aria-label="Reproducir el video"
                className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 grid place-items-center w-16 h-16 sm:w-[88px] sm:h-[88px] rounded-full bg-data-violet text-white lp-llama hover:scale-105 transition-transform focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-data-violet">
          <svg viewBox="0 0 24 24" className="w-[42%] h-[42%] ml-[6%] fill-current" aria-hidden="true"><path d="M8 5.5v13l11-6.5z" /></svg>
        </button>
      )}
      {andando && !conSonido && (
        <button type="button" onClick={activarSonido}
                className="absolute left-3.5 bottom-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-white bg-black/60 rounded-full px-3 py-1.5 hover:bg-black/75 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-data-violet">
          <Volume2 size={14} strokeWidth={2} aria-hidden="true" />Activar sonido
        </button>
      )}
      {!andando && (
        <span className="absolute right-3.5 bottom-3 text-[12.5px] font-medium tabular bg-bg-0/80 border border-line-2 rounded-md px-2 py-0.5">1:00</span>
      )}
    </div>
  )
}
