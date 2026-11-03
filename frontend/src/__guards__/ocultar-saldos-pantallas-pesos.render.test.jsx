// «Ocultar saldos» mirando LO DIBUJADO, pantalla por pantalla (compu en PESOS, 1280 px).
//
// POR QUÉ ESTA PRUEBA
// ───────────────────
// 30/10: con el ojito prendido, el inicio mostraba «Distribución de activos»,
// «Principales posiciones», las tortas por tipo y sector, «Hoy +USD 545» y el
// resumen del mes; la Cartera del celular, TODO. Los guardianes que había leían
// el CÓDIGO (¿el archivo pide usePrivacy?) y daban el inicio por revisado
// porque lo pedía en otra tarjeta. La pregunta de verdad es si en la pantalla
// queda un número tuyo, y eso se contesta mirando la pantalla.
//
// Cómo (detalle en testing/pantallaConOjito.js): la app entera, con la cuenta
// del demo pasando por utils/api.js como en producción, en cada ruta de App.jsx
// (testing/pantallasDeLaApp.js: una página nueva entra sola). Cada pantalla se
// dibuja con la cartera tal cual y multiplicada por 3: lo que cambia depende de
// tu plata y con el ojito prendido no puede aparecer.
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { demoEscalado, revisarPantallas } from '../testing/pantallaConOjito'
import { pantallasDeLaApp } from '../testing/pantallasDeLaApp'
import { handleDemoRequest } from '../utils/demo'

vi.mock('../utils/demo', (io) => demoEscalado(io))
// El muñequito animado de Mervall-E dibuja un SVG que el navegador mínimo no tiene; no muestra datos.
vi.mock('../components/ai/mervalle/motor', async (io) => ({
  ...(await io()), crearMervallE: () => new Proxy({}, { get: () => () => {} }),
}))

revisarPantallas({ describe, it, expect, beforeAll, handleDemoRequest, pantallasDeLaApp, ancho: 1280, conControl: true, moneda: 'ARS' })
