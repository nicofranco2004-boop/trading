import { describe, it, expect, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AnimatedNumber from './AnimatedNumber'
import { useAlVerse } from '../hooks/useAlVerse'
import ResumenCoincidencias from './profile/ResumenCoincidencias'

// Un número que cuenta "al verse" no puede escribir un número falso mientras
// espera. Medido en Chrome el 2026-10-02: con la tarjeta asomada al pie de la
// pantalla se leía "Tu cartera coincide con tu perfil en 0 de 8", "Win rate 0 %"
// y "+USD 0,00"; con "reducir movimiento", esos ceros quedaban escritos hasta
// que bajabas.
describe('AnimatedNumber — antes de verse', () => {
  it('escondido y con su valor FINAL (lo que dice un lector de pantalla), nunca 0', () => {
    const html = renderToStaticMarkup(<AnimatedNumber value={4} visto={false} format={(n) => `n${Math.round(n)}`} />)
    expect(html).toBe('<span class="por-entrar">n4</span>')
  })
  it('visto: el número a secas, como siempre', () => {
    expect(renderToStaticMarkup(<AnimatedNumber value={4} format={(n) => `n${Math.round(n)}`} />)).toBe('n4')
  })
  it('sin número: "—" aunque no se haya visto (antes salía un 0 inventado)', () => {
    expect(renderToStaticMarkup(<AnimatedNumber value={null} visto={false} format={() => 'NO'} />)).toBe('—')
  })
  it('el resumen del perfil sin verse no dice "0 de 8"', () => {
    const modulos = [{ id: 'a', veredicto: 'coincide' }, { id: 'b', veredicto: 'no_coincide' }]
    const html = renderToStaticMarkup(<ResumenCoincidencias modulos={modulos} visto={false} />)
    expect(html).toContain('<span class="por-entrar">1</span>')
    expect(html).not.toMatch(/>0<\/span>/)
  })
})

describe('useAlVerse — con "reducir movimiento" no hay nada que esperar', () => {
  const antes = { io: globalThis.IntersectionObserver, win: globalThis.window }
  afterEach(() => {
    globalThis.IntersectionObserver = antes.io
    if (antes.win === undefined) delete globalThis.window; else globalThis.window = antes.win
  })
  function Prueba() {
    const [, visto] = useAlVerse()
    return <i>{visto ? 'visto' : 'esperando'}</i>
  }
  const conNavegador = (reducir) => {
    globalThis.IntersectionObserver = class { observe() {} disconnect() {} }
    globalThis.window = { matchMedia: () => ({ matches: reducir }) }
  }
  it('pidió menos movimiento: arranca visto (index.css ya muestra lo que espera)', () => {
    conNavegador(true)
    expect(renderToStaticMarkup(<Prueba />)).toContain('visto')
  })
  it('sin ese pedido: espera a verse, como siempre', () => {
    conNavegador(false)
    expect(renderToStaticMarkup(<Prueba />)).toContain('esperando')
  })
})
