// Lo que Rendi dice sobre impuestos, en un solo lugar. Lo toman las landings,
// las preguntas frecuentes de la portada, la guía y el blog.
//
// POR QUÉ EXISTE. Hasta el 16/11/2026, 14 archivos decían cada uno lo suyo, y
// estaba mal: que vender CEDEARs paga Ganancias («alícuota 15 %… te pueden
// ajustar + multa»), que «AFIP exige FIFO» para todo, que Rendi entrega el
// «P&L declarable» y que la declaración vence en abril. Un arreglo en un archivo
// dejaba el error vivo en los otros trece. Ahora la frase es una.
//
// QUÉ ES CIERTO (persona humana que vive en Argentina, revisado el 16/11/2026
// contra el texto de la ley en InfoLEG, ARCA y el CPCECABA):
//   · Vender CEDEARs y acciones argentinas en BYMA: EXENTO de Ganancias
//     (Ley de Ganancias t.o. 2019, art. 26 inc. u; Ley 27.430, desde 2018).
//     Requisitos: oferta pública autorizada por la CNV o venta en un mercado
//     autorizado (BYMA, segmento con prioridad precio-tiempo), y no operar como
//     empresa ni comisionista (art. 53). Los CEDEARs de ETF entran por el último
//     párrafo del inciso: lectura habitual, sin pronunciamiento oficial.
//     En nov-2026 el Gobierno propuso gravarlo y lo retiró el 4/11 sin votarse.
//   · Sí pagan: dividendos (los de CEDEARs, escala del 5 al 35 %; los de
//     acciones argentinas, 7 % retenido), cripto vendida con ganancia (5 % o
//     15 %), acciones/ETF vendidos en un broker del exterior (15 %). Los CEDEARs
//     cuentan para Bienes Personales.
//   · La ley no dice «PEPS» ni «FIFO»: dice «las adquisiciones más antiguas»
//     (art. 98, pauta ii), y lo dice EXPRESO sólo para ventas gravadas de
//     acciones. Para cripto y exterior no hay texto expreso para una persona:
//     se llega sólo por remisión al capítulo de empresas (art. 101 → 67;
//     art. 149 → 65 y 67). Es lo prudente y lo habitual. No escribir «la ley
//     exige FIFO» para cripto, ni tampoco «la ley no lo exige».
//   · El CSV de Rendi está en dólares al MEP (y en pesos). La declaración se
//     hace en pesos con el tipo de cambio que fija la ley, y la cripto operada
//     en pesos se mide en pesos: el CSV es la BASE para el contador, no la
//     declaración hecha.
//   · La declaración anual vence a mitad de año (junio según el CUIT) y ARCA
//     suele prorrogarla. Nunca «abril».
//   · AFIP se llama ARCA desde el Decreto 953/2024 (25/10/2024).
// Lo vigila `__guards__/impuestos-bien-dichos.test.jsx`, que arma las páginas
// públicas igual que la publicación y falla si vuelve una frase equivocada.
//
// Si cambia la ley, se cambia ACÁ y se actualiza `REVISADO_EL`.

export const REVISADO_EL = '2026-11-16'

// CEDEARs y acciones argentinas vendidos en BYMA.
export const VENTA_EXENTA =
  'Si vivís en Argentina y vendés CEDEARs o acciones argentinas en la bolsa argentina (BYMA) a través de tu broker, la ganancia de esa venta no paga Ganancias: la ley la declara exenta.'

// Lo que sí paga. Corto, para cerrar un párrafo.
export const LO_QUE_SI_PAGA =
  'Lo que sí paga: los dividendos y lo que ganás al vender cripto, o acciones y ETF en un broker del exterior. Y los CEDEARs cuentan para Bienes Personales.'

// Cripto.
export const CRIPTO_PAGA =
  'Vender cripto con ganancia sí paga Ganancias; mientras no vendas, la suba no paga.'

// Para qué sirve el FIFO: medir, no declarar.
export const FIFO_PARA_QUE =
  'Si compraste lo mismo en varias veces, Rendi descuenta cada venta de la compra más vieja primero (FIFO, o PEPS en castellano) y te dice cuánto ganaste de verdad con cada una, en pesos y en dólares.'

// Lo que entrega Rendi. NO arma la declaración: la «Ayuda para impuestos» de
// /planes está «En construcción» (planCatalog.js, roadmap). Exportar es de Plus
// y Pro (backend/ai/plan.py, «export.csv»). El archivo es el de Operaciones
// (/api/export/operations.csv): una fila por compra que consumió cada venta.
export const CSV_CONTADOR =
  'Con Plus y Pro exportás un CSV con la ganancia de cada venta, compra por compra: la base para que tu contador arme tu declaración.'

export const NO_ES_ASESORAMIENTO =
  'Esto es información general, no asesoramiento impositivo: lo que te toca a vos lo define tu contador.'
