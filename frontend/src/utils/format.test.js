import { describe, it, expect } from 'vitest'
import { labelVentanaMeses, parseNum, numToInput, pctTxt } from './format'
describe('labelVentanaMeses — la card "Acumulado" tiene que decir su período', () => {
  it('12 meses (el default) se lee "1A"', () => {
    expect(labelVentanaMeses(12)).toBe('1A')
  })
  it('los tabs del gráfico', () => {
    expect(labelVentanaMeses(24)).toBe('2A')
    expect(labelVentanaMeses(60)).toBe('5A')
  })
  it('meses sueltos', () => {
    expect(labelVentanaMeses(6)).toBe('6m')
    expect(labelVentanaMeses(1)).toBe('1m')
  })
  it('MAX (null/0) es "histórico", no vacío ni "0m"', () => {
    // El caso que importa: sin rótulo, "Acumulado" se lee como "desde siempre"
    // y compite mentalmente con el "Rendimiento anual" del Dashboard.
    expect(labelVentanaMeses(null)).toBe('histórico')
    expect(labelVentanaMeses(undefined)).toBe('histórico')
    expect(labelVentanaMeses(0)).toBe('histórico')
    expect(labelVentanaMeses(-3)).toBe('histórico')
  })
})

// ─── parseNum / numToInput ───────────────────────────────────────────────────
// El parser es por donde entra TODA la plata que se carga a mano. Un número mal
// leído acá no rompe nada visible: se guarda una compra con el importe cambiado.
// Por eso los casos malos exigen NaN y no "algo parecido".
describe('parseNum — lee lo que la gente escribe', () => {
  it('formato argentino, que es lo que Rendi muestra', () => {
    expect(parseNum('1.037,74')).toBe(1037.74)
    expect(parseNum('1.234.567,89')).toBe(1234567.89)
    expect(parseNum('0,01')).toBe(0.01)
    expect(parseNum('9.000')).toBe(9000)        // nueve mil, no nueve
  })
  it('formato US, que es lo que se pega de un resumen del broker', () => {
    expect(parseNum('1037.74')).toBe(1037.74)
    expect(parseNum('380.5')).toBe(380.5)
  })
  it('tolera lo que rodea al número', () => {
    expect(parseNum('  1.500  ')).toBe(1500)
    expect(parseNum('US$ 1.500,50')).toBe(1500.5)
    expect(parseNum('ARS 7.542.000')).toBe(7542000)
    expect(parseNum('12,5%')).toBe(12.5)
    expect(parseNum('1.500,')).toBe(1500)       // mientras se está tipeando
  })
  it('notación científica: "1e5" son CIEN MIL, no quince', () => {
    // Regresión: un filtro que borraba "todo lo que no es dígito" se comía la
    // "e" y dejaba "15". Cien mil pesos guardados como quince, sin aviso.
    expect(parseNum('1e5')).toBe(100000)
    expect(parseNum('1,5e3')).toBe(1500)
  })
  it('lo ambiguo o mal escrito se RECHAZA, no se adivina', () => {
    expect(parseNum('1.2.3')).toBeNaN()
    expect(parseNum('1,2,3')).toBeNaN()
    expect(parseNum('1.03,74')).toBeNaN()       // los puntos no son miles válidos
    expect(parseNum('--5')).toBeNaN()
    expect(parseNum('abc')).toBeNaN()
    expect(parseNum('')).toBeNaN()
    expect(parseNum(null)).toBeNaN()
  })
  it('números negativos y con signo', () => {
    expect(parseNum('-45,5')).toBe(-45.5)
    expect(parseNum('+1.200')).toBe(1200)
  })
})

describe('numToInput ↔ parseNum — lo que el sistema escribe, se vuelve a leer igual', () => {
  it('ida y vuelta sin pérdida', () => {
    for (const n of [7230825, 4820.55, 1500, 0.00000123, 1424, 980, 1037.74, -250.5]) {
      expect(parseNum(numToInput(n))).toBe(n)
    }
  })
  it('sin número, campo vacío', () => {
    expect(numToInput(null)).toBe('')
    expect(numToInput(NaN)).toBe('')
    expect(numToInput(undefined)).toBe('')
  })
})

describe('pctTxt — el % que ya viene en escala de porcentaje', () => {
  it('escribe el separador, no cambia el número', () => {
    expect(pctTxt(23.4)).toBe('23,4%')
    expect(pctTxt(23)).toBe('23%')
    expect(pctTxt(-5.8)).toBe('-5,8%')
  })
  it('un valor ya armado como texto no se convierte en guión', () => {
    // isNaN("18,0") es true: un chequeo numérico a secas lo borraba de la pantalla
    expect(pctTxt('18,0')).toBe('18,0%')
  })
  it('sin dato, guión', () => {
    expect(pctTxt(null)).toBe('—')
    expect(pctTxt('')).toBe('—')
  })
})
