// /guia/novedades — sección 5 del manual

import GuidePage from '../../components/guide/GuidePage'

export default function Novedades() {
  return (
    <GuidePage
      section="5 de 6"
      title="Novedades"
      intro="Eventos del mercado que afectan tus tickers + noticias filtradas por tu cartera + noticias macro generales."
      prev={{ to: '/guia/coach-ia', label: 'Coach IA' }}
      next={{ to: '/guia/cuenta-y-planes', label: 'Cuenta y planes' }}
      metaTitle="Novedades (Eventos + Noticias) — Guía Rendi"
      metaDescription="Cómo funcionan los eventos del mercado y las noticias filtradas por tu cartera en Rendi."
      canonicalPath="/guia/novedades"
    >
      <h2>Cómo llegar</h2>
      <p>
        Sección <strong>Novedades</strong> en el sidebar. Tiene 2 tabs arriba:{' '}
        <strong>Eventos</strong> y <strong>Noticias</strong>. La URL refleja el tab
        activo: <code>/novedades?tab=eventos</code> o <code>/novedades?tab=noticias</code>.
      </p>

      <h2>Eventos</h2>
      <p>
        Eventos del mercado que afectan o pueden afectar tus tickers. Tres tipos:
      </p>
      <ul>
        <li><strong>Earnings</strong>: cuando una empresa reporta resultados trimestrales. Te muestra fecha exacta + estimaciones.</li>
        <li><strong>Dividendos</strong>: cuando una empresa anuncia pago de dividendo. Ex-date, payment date, monto.</li>
        <li><strong>Splits</strong>: cuando una empresa hace stock split (1:2, 1:5, etc.).</li>
      </ul>
      <p>
        Sub-tabs adentro de Eventos:
      </p>
      <ul>
        <li><strong>Mi cartera</strong>: solo eventos de activos que tenés en posiciones.</li>
        <li><strong>Mercado</strong>: eventos de tickers populares (los grandes USA + AR), aunque no los tengas.</li>
      </ul>

      <h2>Noticias</h2>
      <p>
        Feed de noticias financieras tageadas por ticker. Source: Google News RSS +
        feeds de Investing.com. Actualizamos cada 30 minutos para tickers de tu
        cartera y cada 1 hora para mercado general.
      </p>

      <h3>Tab "Para ti"</h3>
      <p>
        Noticias filtradas por los tickers que tenés en posiciones. Buscamos en español
        para tickers AR (GGAL, YPF, etc.) y en inglés para tickers USA (NVDA, AAPL).
      </p>
      <p>
        Cada noticia tiene:
      </p>
      <ul>
        <li>Título + fuente (Bloomberg, Reuters, Cronista, Infobae, etc.).</li>
        <li>Fecha de publicación.</li>
        <li>Ticker al que se refiere (chip clickeable para filtrar).</li>
        <li>Tags automáticos (earnings, M&amp;A, regulatory, dividendo, etc.).</li>
        <li>Click → abre la noticia original en otra pestaña.</li>
      </ul>

      <h3>Tab "Mercado"</h3>
      <p>
        Noticias macro y de índices populares: Fed, inflación AR, dólar blue, Merval,
        BCRA, política monetaria. Las mismas para todos los usuarios — no filtradas
        por cartera.
      </p>

      <h2>Filtros</h2>
      <p>
        En "Para ti" podés filtrar por:
      </p>
      <ul>
        <li><strong>Ticker</strong>: chips con cada ticker de tu cartera. Click → ver solo noticias de ese activo.</li>
        <li><strong>Tag</strong>: earnings, M&amp;A, regulatory, dividend, etc.</li>
      </ul>

      <h2>Cómo se actualizan</h2>
      <p>
        Rendi usa <strong>stale-while-revalidate</strong>: cuando abrís la página, te
        mostramos las noticias en caché al instante y refrescamos en background. La
        próxima vez que abras Novedades, ya tenés data fresca.
      </p>
      <p>
        Si nunca abriste Novedades antes y tu cartera tiene tickers nuevos, la primera
        carga puede tardar 3-5 segundos mientras buscamos noticias frescas.
      </p>

      <h2>Tip: AI Coach + Novedades</h2>
      <p>
        Si una noticia te preocupa, podés pasarla al Coach IA para contexto:
        "vi una noticia que dice X sobre NVDA. ¿cómo me afecta a mí?". El bot tiene
        herramienta <code>get_recent_news_for_assets</code> que busca news frescas
        para responderte con contexto.
      </p>
    </GuidePage>
  )
}
