// Los artículos del blog: título, descripción, fechas. Lo leen el índice
// (pages/Blog.jsx) y cada artículo (components/blog/BlogPost.jsx, por el slug).
//
// Por qué un solo lugar: hasta el 16/11/2026 el título y la descripción estaban
// escritos dos veces —en el índice y en el artículo— y ya se habían separado
// (el índice decía «Por qué AFIP exige FIFO» y el artículo «AFIP / ARCA»).
//
// `updatedAt`: la fecha de la última revisión de CONTENIDO (no de un cambio de
// diseño). Se muestra arriba del artículo y es el `dateModified` que lee Google.
// Si corregís lo que dice una nota, actualizala acá.
export const POSTS = [
  {
    slug: 'fifo-cedears-argentina',
    title: '¿Los CEDEARs pagan Ganancias? Y para qué sirve el FIFO',
    description: 'Si vivís en Argentina y vendés CEDEARs en BYMA, no pagás Ganancias por esa venta. Qué sí pagás (dividendos, Bienes Personales) y para qué sirve el FIFO.',
    category: 'Impuestos',
    publishedAt: '2026-05-24',
    // 16/11: reescrita entera; decía que vender CEDEARs paga 15 % (está exento).
    updatedAt: '2026-11-16',
    readTime: '7 min',
  },
  {
    slug: 'pnl-real-usd-blue-argentina',
    title: 'P&L real en USD blue: por qué tus pesos te engañan',
    description: "La diferencia entre 'ganaste 50% en pesos' y 'ganaste 5% en dólares'. Cómo medir tu rendimiento real cuando operás en un país con inflación alta.",
    category: 'P&L y rendimiento',
    publishedAt: '2026-05-24',
    updatedAt: null,
    readTime: '6 min',
  },
  {
    slug: 'comparativa-brokers-argentina',
    title: 'Cocos vs IOL vs Balanz vs Bull: qué broker AR conviene en 2026',
    description: 'Comparativa honesta de los 4 brokers más populares en Argentina: comisiones, catálogo, app, soporte. Cuál elegir según tu perfil de inversor.',
    category: 'Brokers AR',
    publishedAt: '2026-05-24',
    updatedAt: null,
    readTime: '10 min',
  },
]

export const POST_POR_SLUG = Object.fromEntries(POSTS.map((p) => [p.slug, p]))
