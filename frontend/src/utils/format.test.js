import { describe, it, expect } from 'vitest'
import { labelVentanaMeses, parseNum, numToInput, pctTxt, pctVar, pctVarSign, pctColor, fmtIndexPrice } from './format'
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

describe('pctTxt con decimales — un porcentaje que no es variación', () => {
  it('decimales fijos, coma, y sin "+"', () => {
    expect(pctTxt(35, 1)).toBe('35,0%')
    expect(pctTxt(0.4, 2)).toBe('0,40%')
    expect(pctTxt(62.46, 0)).toBe('62%')
  })
  it('negativo con el menos tipográfico; lo que redondea a cero, sin signo', () => {
    expect(pctTxt(-12.34, 1)).toBe('−12,3%')
    expect(pctTxt(-0.04, 1)).toBe('0,0%')
  })
  it('no multiplica por 100', () => {
    expect(pctTxt(12.5, 1)).toBe('12,5%')
  })
  it('sin dato, guión — también NaN y texto sin número', () => {
    expect(pctTxt(null, 1)).toBe('—')
    expect(pctTxt(NaN, 1)).toBe('—')
    expect(pctTxt('abc', 1)).toBe('—')
  })
  it('sin `decimals` sigue igual que antes: no redondea', () => {
    expect(pctTxt(23.4)).toBe('23,4%')
    expect(pctTxt(35)).toBe('35%')
  })
})

describe('redondeo de los porcentajes — el mismo que el servidor', () => {
  // Valores donde toFixed y toLocaleString discrepan en la última cifra. Lo que
  // se espera es lo que escribe el backend: Python `fmt_num(19.95, 1)` → "19,9"
  // (medido 2026-10-01). Con el redondeo de nfmt, el insight decía "+19,9%" en
  // el texto del servidor y "+20,0%" en la evidencia de la pantalla.
  it('pctVar redondea como el backend', () => {
    expect(pctVar(19.95, 1)).toBe('+19,9%')
    expect(pctVar(2.15, 1)).toBe('+2,1%')
    expect(pctVar(-1.45, 1)).toBe('\u22121,4%')
  })
  it('pctTxt con decimales, igual', () => {
    expect(pctTxt(19.95, 1)).toBe('19,9%')
    expect(pctTxt(2.15, 1)).toBe('2,1%')
  })
  it('lo que ya viene con los decimales que se muestran no se toca', () => {
    expect(pctVar(3.25, 2)).toBe('+3,25%')
    expect(pctVar(-0.85)).toBe('\u22120,85%')
  })
  it('infinito no es un porcentaje que se pueda mostrar', () => {
    expect(pctVar(Infinity)).toBe('—')
    expect(pctVarSign(-Infinity)).toBe(0)
  })
})

describe('pctColor — el color es el del número que se ve', () => {
  it('positivo verde, negativo rojo', () => {
    expect(pctColor(1.2, 1)).toBe('text-rendi-pos')
    expect(pctColor(-1.2, 1)).toBe('text-rendi-neg')
  })
  it('lo que se escribe "0,0%" va neutro aunque el crudo sea negativo', () => {
    // Una acción comprada hoy: −0,02 % se escribe "0,0%". Roja, el texto dice
    // "no se movió" y el color "perdiste".
    expect(pctVar(-0.02, 1)).toBe('0,0%')
    expect(pctColor(-0.02, 1)).toBe('text-ink-2')
    expect(pctColor(0)).toBe('text-ink-2')
  })
  it('usa los MISMOS decimales que el texto', () => {
    expect(pctColor(-0.02, 2)).toBe('text-rendi-neg')   // "−0,02%"
  })
  it('sin dato, neutro', () => {
    expect(pctColor(null)).toBe('text-ink-2')
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

describe('pctVar — la variación del día, con signo y a la argentina', () => {
  it('signo explícito y coma decimal', () => {
    expect(pctVar(0.42)).toBe('+0,42%')
    expect(pctVar(2.7)).toBe('+2,70%')
    expect(pctVar(1.28, 1)).toBe('+1,3%')
  })
  it('el menos es el tipográfico (−), no el guion — el mismo de la barra del celular', () => {
    // Las tarjetas del inicio escribían "-0,85%" y la barra "−0,85%": la misma
    // caída con dos signos distintos según dónde se mirara.
    expect(pctVar(-0.85)).toBe('\u22120,85%')
    expect(pctVar(-0.85)).not.toContain('-')
  })
  it('lo que redondea a cero no tiene signo ni dirección', () => {
    expect(pctVar(-0.001)).toBe('0,00%')
    expect(pctVar(0)).toBe('0,00%')
    expect(pctVarSign(-0.001)).toBe(0)
    expect(pctVarSign(-0.005)).toBe(-1)
    expect(pctVarSign(0.004)).toBe(0)
  })
  it('no multiplica por 100 — ya viene en porcentaje', () => {
    expect(pctVar(12.5)).toBe('+12,50%')
  })
  it('sin dato, guión', () => {
    expect(pctVar(null)).toBe('—')
    expect(pctVar(undefined)).toBe('—')
    expect(pctVar(NaN)).toBe('—')
    expect(pctVarSign(null)).toBe(0)
  })
})

describe('fmtIndexPrice — el precio de la cinta y de las tarjetas del inicio', () => {
  it('índices con dos decimales, siempre dos', () => {
    expect(fmtIndexPrice(5840.5, 'index')).toBe('5.840,50')
    expect(fmtIndexPrice(2748.2, 'commodity')).toBe('2.748,20')
  })
  it('cripto y seis cifras sin decimales', () => {
    expect(fmtIndexPrice(81595.37, 'crypto')).toBe('81.595')
    expect(fmtIndexPrice(3320.4, 'crypto')).toBe('3.320')
    expect(fmtIndexPrice(2150420.75, 'index')).toBe('2.150.421')
  })
  it('sin precio, guión', () => {
    expect(fmtIndexPrice(null, 'index')).toBe('—')
  })
})

import { pctVarFino, decimalesFinos } from './format'

describe('pctVarFino — el número al lado de un veredicto no dice "0,0%"', () => {
  it('lo que redondea a cero se escribe con un decimal más (con su signo)', () => {
    expect(pctVarFino(-0.04, 1)).toBe('−0,04%')
    expect(decimalesFinos(-0.04, 1)).toBe(2)
  })
  it('lo demás, igual que pctVar', () => {
    expect(pctVarFino(-1.84, 1)).toBe('−1,8%')
    expect(pctVarFino(0, 1)).toBe('0,0%')
    expect(pctVarFino(null, 1)).toBe('—')
  })
})

import { ppVarFino } from './format'

describe('decimalesFinos / ppVarFino — hasta dos decimales más, con signo', () => {
  it('−0,004 ya no se escribe "0,00%"', () => {
    expect(pctVarFino(-0.004, 1)).toBe('−0,004%')
  })
  it('en puntos porcentuales', () => {
    expect(ppVarFino(1.24, 1)).toBe('+1,2 pp')
    expect(ppVarFino(-0.04, 1)).toBe('−0,04 pp')
    expect(ppVarFino(null, 1)).toBe('—')
  })
})
