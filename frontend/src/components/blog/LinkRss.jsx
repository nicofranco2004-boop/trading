// El link al RSS del blog en el <head> del índice (/blog) y de cada nota. Es
// lo que buscan los lectores de RSS y los buscadores para encontrar el feed.
// El archivo lo escribe el prerender en dist/rss.xml (scripts/paginasEscritas.mjs).
import { Helmet } from 'react-helmet-async'
import { RSS_URL, RSS_TITULO } from '../../data/rss'

export default function LinkRss() {
  return (
    <Helmet>
      <link rel="alternate" type="application/rss+xml" title={RSS_TITULO} href={RSS_URL} />
    </Helmet>
  )
}
