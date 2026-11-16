// Lo que Rendi dice sobre impuestos en las páginas públicas, escrito UNA vez.
//
// Por qué existe: la auditoría SEO del 16/11/2026 encontró que las landings
// prometían «FIFO automático para tu declaración AFIP» sobre la venta de CEDEARs
// y acciones. Para una persona humana residente, vender CEDEARs y acciones
// argentinas en BYMA está EXENTO de Ganancias (ley del impuesto, art. 26 inc. u):
// esa ganancia no se paga ni se liquida. Lo que sí puede tributar son los
// dividendos de los CEDEARs y Bienes Personales. Y el organismo se llama ARCA
// desde octubre de 2024: decir sólo «AFIP» suena a página vieja.
//
// El mismo error sigue en otras páginas (Cedears, la FAQ de la portada, la guía
// de Cartera y Operaciones, el artículo de FIFO del blog). Al corregirlas, usar
// estas frases en vez de escribir otra. Binance y /afip-cripto hablan de cripto,
// que sí tributa, pero todavía dicen «AFIP» a secas.

export const VENTA_EXENTA =
  'Para una persona humana, vender CEDEARs y acciones argentinas en BYMA está exento de Ganancias.'

// Un ítem de la lista «Lo que te da Rendi» (formato {title, desc} de KeywordLanding).
export const RENDI_Y_LOS_IMPUESTOS = {
  title: 'Impuestos: qué te muestra Rendi y qué no',
  desc: `${VENTA_EXENTA} Por eso Rendi no te presenta esa ganancia como algo para declarar ante ARCA (la ex AFIP): te la muestra para que sepas cuánto ganaste. Lo que sí puede tributar —los dividendos de tus CEDEARs, o Bienes Personales sobre lo que tenés al 31 de diciembre— conviene revisarlo con tu contador.`,
}
