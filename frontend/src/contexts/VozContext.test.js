import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

// El proveedor es el dueño de la conversación y del audio. No se puede montar
// acá (el frontend corre sus tests sin navegador), así que estos son guards de
// fuente sobre decisiones que ya se rompieron una vez.
const fuente = readFileSync(new URL('./VozContext.jsx', import.meta.url), 'utf8')

// El cuerpo de onReset, hasta donde de verdad termina. Antes esto recortaba
// 900 caracteres a ojo y el test se puso rojo al agregar tres líneas ARRIBA:
// el código estaba bien, el recorte no llegaba. Un guard que se rompe cuando
// te movés al lado enseña a ignorarlo.
const bloqueOnReset = () => {
  const i = fuente.indexOf('const onReset = () => {')
  const fin = fuente.indexOf('const res = await api.chatStream', i)
  return fuente.slice(i, fin > i ? fin : i + 1200)
}

describe('cuando el turno se reinicia, el audio también', () => {
  it('el reset calla lo que se haya empezado a decir', () => {
    // Un turno que usa una herramienta escribe primero un preámbulo ("dejame
    // ver los precios") que después se borra de la pantalla. Si ese preámbulo
    // traía su resumen hablado, Rendi ya estaba diciéndolo en voz alta.
    expect(bloqueOnReset()).toMatch(/stop\(\)/)
  })

  it('y vuelve a permitir que suene la respuesta de verdad', () => {
    // Éste era el daño grande: `yaSono` quedaba en true, así que la respuesta
    // real no arrancaba NUNCA. El usuario escuchaba el preámbulo, se quedaba
    // esperando el resto, y la escucha ya estaba gastada.
    expect(bloqueOnReset()).toMatch(/yaSono = false/)
  })

  it('la traba de "ya sonó" se declara ANTES del reset', () => {
    // Si se declarara después, el reset no la vería y el arreglo sería mudo.
    expect(fuente.indexOf('let yaSono = false'))
      .toBeLessThan(fuente.indexOf('const onReset = () => {'))
  })
})

// ─── Vaciar el chat mientras Rendi escribe ───────────────────────────────────
// Nada cancela el pedido en vuelo, y es a propósito: cancelar al desmontar era
// el bug que se arregló (preguntabas en /ai, te ibas al panel y perdías la
// respuesta con la ficha ya cobrada). Pero quedó el caso de al lado: tocar
// "Nueva conversación" mientras escribe. El hilo se vacía, la respuesta sigue
// viajando, y al llegar se dibujaba igual — sola, en el chat vacío,
// contestando una pregunta que ya no se ve.
describe('lo que llega tarde de una conversación borrada se descarta', () => {
  it('el turno tiene número y vaciar lo cambia', () => {
    expect(fuente).toMatch(/turnoRef\.current \+= 1/)
    const limpiar = fuente.slice(fuente.indexOf('const limpiar = useCallback'))
    expect(limpiar.slice(0, 400)).toMatch(/turnoRef\.current \+= 1/)
  })

  it('todo lo que toca la pantalla pregunta si sigue vigente', () => {
    // Si una sola de éstas se olvida, el síntoma vuelve por ahí: la burbuja a
    // medio escribir, la respuesta final, el audio o el cartel de error.
    const ask = fuente.slice(fuente.indexOf('const ask = useCallback'))
    const cuantas = (ask.match(/vigente\(\)/g) || []).length
    expect(cuantas).toBeGreaterThanOrEqual(6)
  })

  it('el audio de una conversación borrada no arranca', () => {
    const ask = fuente.slice(fuente.indexOf('const ask = useCallback'))
    expect(ask).toMatch(/if \(yaSono \|\| !v \|\| !vigente\(\)\) return/)
  })

  it('vaciar libera la pantalla en el momento', () => {
    // Sin esto el chat recién vaciado se queda diciendo "pensando…" por la
    // respuesta vieja y no deja preguntar hasta veinte segundos después.
    const limpiar = fuente.slice(fuente.indexOf('const limpiar = useCallback'))
    expect(limpiar.slice(0, 700)).toMatch(/sendingRef\.current = false/)
  })

  it('y el turno viejo no le saca el lugar al nuevo al terminar', () => {
    expect(fuente).toMatch(/if \(vigente\(\)\) \{\s*\n\s*sendingRef\.current = false/)
  })
})

// ─── Pedir permiso para sonar antes de tener qué decir ───────────────────────
// Rendi pide reproducir ~15 SEGUNDOS después del toque del usuario: manda la
// pregunta, el modelo escribe, y recién ahí hay audio. Para ese momento el
// navegador ya no ve ningún gesto y lo rechaza — al usuario le aparece un play
// sin explicación. Reportado por Nico en las DOS pantallas, celular y
// escritorio (en escritorio también: la política no es sólo del celular).
describe('el sonido se habilita en el toque, no cuando llega el audio', () => {
  it('se desbloquea con un clip mudo', () => {
    expect(fuente).toMatch(/const SILENCIO = 'data:audio\/wav;base64,/)
    expect(fuente).toMatch(/const desbloquearElSonido = useCallback/)
  })

  it('se llama LO PRIMERO de ask, antes de cualquier espera', () => {
    // Una sola línea de `await` antes y el gesto ya no cuenta: el navegador
    // sólo concede el permiso mientras el toque está vigente.
    const ask = fuente.slice(fuente.indexOf('const ask = useCallback'))
    const hasta = ask.slice(0, ask.indexOf('sendingRef.current = true'))
    expect(hasta).toMatch(/desbloquearElSonido\(\)/)
    // Mirando CÓDIGO, no comentarios: el de arriba dice "SIN `await` ANTES" al
    // explicar por qué, y eso hacía fallar al guard contra sí mismo. Es la
    // segunda vez que pasa — un guard que se lee a sí mismo no guarda nada.
    const codigo = hasta.split('\n').filter(l => !l.trim().startsWith('//')).join('\n')
    expect(codigo).not.toMatch(/await/)
  })

  it('no se hace si el usuario tiene a Rendi callada', () => {
    expect(fuente).toMatch(/if \(enabled\) desbloquearElSonido\(\)/)
  })

  it('el clip mudo no ensucia el estado del reproductor', () => {
    // Pasa por los mismos avisos que un audio de verdad: sin la guarda,
    // mandar una pregunta mostraba "Rendi está hablando" por un parpadeo.
    expect(fuente).toMatch(/const mudo = \(\) => desbloqueandoRef\.current/)
    for (const aviso of ['onTime', 'onEnd', 'onErr', 'onPlay', 'onPause']) {
      const i = fuente.indexOf('const ' + aviso + ' =')
      expect(fuente.slice(i, i + 160), aviso).toMatch(/mudo\(\)/)
    }
  })

  it('una sola vez por carga: alcanza para toda la sesión', () => {
    expect(fuente).toMatch(/if \(!a \|\| desbloqueadoRef\.current\) return/)
  })
})

// ─── Decir POR QUÉ no arrancó sola ──────────────────────────────────────────
// Los cinco motivos por los que Rendi puede no ponerse a hablar se veían
// exactamente igual: un botón de play, sin una palabra. Eso costó dos arreglos
// a ciegas —uno para el celular, otro para el permiso del navegador— con el
// problema intacto después de los dos. La salida no era una tercera
// corazonada: era que el programa dijera qué estaba pasando.
describe('cuando no habla, dice por qué', () => {
  it('cubre los cinco motivos', () => {
    for (const motivo of [
      'La tenés silenciada',                 // el usuario la calló
      'Tu plan tiene un audio por semana',   // Free, cupo propio
      'sin consultas por esta semana',       // se acabó la cuota
      'Tu navegador no la deja arrancar',    // política de autoplay
      'no trajo resumen para escuchar',      // el modelo no escribió voz
    ]) {
      expect(fuente).toContain(motivo)
    }
  })

  it('se limpia al empezar un turno nuevo', () => {
    // Si no, el motivo de la respuesta anterior queda colgado abajo de la nueva.
    const ask = fuente.slice(fuente.indexOf('const ask = useCallback'))
    expect(ask.slice(0, 1400)).toMatch(/setMotivoSinVoz\(null\)/)
  })

  it('viaja a las dos pantallas', () => {
    expect(fuente).toMatch(/motivoSinVoz,/)
  })
})
