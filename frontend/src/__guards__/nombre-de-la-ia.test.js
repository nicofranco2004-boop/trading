// La IA de Rendi se llama Mervall-E AI. "Coach IA" y "Rendi AI" son los nombres
// viejos y no vuelven ("Rendi AI" se sumó el 2026-10-03, cuando la IA pasó a
// llamarse Mervall-E AI y a tener cara: components/ai/MervallE.jsx).
//
// POR QUÉ ESTE TEST
// ─────────────────
// El nombre cambió en el catálogo, la FAQ y la guía, y el viejo siguió vivo en
// unos 60 textos más: el <title> de la home, Términos (donde era una
// DEFINICIÓN), Privacidad, las landings de SEO, el blog, la app y el manual de
// marca publicado. Un nombre viejo no rompe nada ni tira ningún error: sale en
// Google y calla. Los textos que arma el servidor los vigila
// `backend/tests/test_nombre_de_la_ia.py`.
//
// Recorre el ÁRBOL, no una lista (ver `scripts/texto-visible.mjs`): una página
// o un componente nuevo entra solo. Los comentarios SÍ pueden nombrarlo (cuentan
// la historia); lo que se muestra, no.
//
// LO QUE APRENDIÓ AUDITÁNDOSE (2026-09-26, mismo día)
// ───────────────────────────────────────────────────
// La primera versión pasaba en verde con el nombre de vuelta en tres casos:
//   • adentro de WallbitConnect.jsx: la regex que sacaba comentarios se comía
//     94 renglones reales (ahora los decide un parser);
//   • partido por una etiqueta o un `{' '}`: "Coach <strong>IA</strong>";
//   • como "AI Coach" (fue el título de una sección de la guía hasta julio).
// El caso de abajo "el patrón caza…" deja esos tres congelados.
//
// Un falso rojo posible, a sabiendas: "el coach" como sustantivo común ("Rendi
// no es el coach que te dice qué comprar") también lo marca. Si hace falta
// escribir eso, que se escriba de otra forma: en esta app "el Coach" fue el
// nombre de la IA.
import { describe, it, expect } from 'vitest'
import {
  ENTRE, archivosConTexto, esPublica, hallazgos, relativa, sinComentarios,
} from '../../scripts/texto-visible.mjs'

const NOMBRE_VIEJO = [
  new RegExp(String.raw`coach${ENTRE}(de${ENTRE})?ia\b`, 'gi'),  // "Coach IA", "Coach de IA", "Coach <b>IA</b>"
  new RegExp(String.raw`\b(el|al|del)${ENTRE}coach\b`, 'gi'),      // "El Coach lee tu test", "Memoria del Coach"
  new RegExp(String.raw`\bai${ENTRE}coach\b`, 'gi'),               // "Tip: AI Coach" (la guía, de mayo a julio)
  new RegExp(String.raw`\brendi(?:${ENTRE}|[-‐‑_·])(?:ai|ia)\b`, 'gi'), // "Rendi AI" (de septiembre al 2026-10-03), "Rendi IA", "Rendi-AI"
  // La IA llamada "Rendi" a secas: el personaje habla, lee y escucha; la app,
  // no. Son las frases que adb57b29 encontró mirando la app abierta y que el
  // servidor todavía tenía ("La voz de Rendi no está disponible").
  new RegExp(String.raw`\bpregunt[\wáéíóúñ]*${ENTRE}a${ENTRE}rendi\b`, 'gi'),        // "Preguntale a Rendi"
  new RegExp(String.raw`\b(?:habl|escrib)[\wáéíóúñ]*le${ENTRE}a${ENTRE}rendi\b`, 'gi'), // "Hablarle a Rendi", "Escribile a Rendi"
  new RegExp(String.raw`\brendi${ENTRE}(?:está|te)${ENTRE}(?:habl|lee|leé|escuch|contest)`, 'gi'), // "Rendi está hablando", "Rendi te lee"
  new RegExp(String.raw`\bla${ENTRE}voz${ENTRE}de${ENTRE}rendi\b`, 'gi'),             // "La voz de Rendi"
]

const TODOS = archivosConTexto()
const vistos = (ruta, texto) =>
  NOMBRE_VIEJO.flatMap((p) => [...sinComentarios(ruta, texto).matchAll(p)].map((m) => m[0]))

describe('el nombre viejo de la IA no vuelve', () => {
  it('el recorrido lee la app entera, no sólo lo que alguien listó', () => {
    // Contra el falso verde: si el recorrido se rompe y no lee nada, el test
    // de abajo pasa sin mirar un solo archivo.
    const leidos = TODOS.map(relativa)
    expect(leidos.length).toBeGreaterThan(300)
    for (const r of ['index.html', 'public/site.webmanifest', 'public/brand-kit/manual.html',
      'src/pages/Landing.jsx', 'src/pages/Terminos.jsx', 'src/pages/Privacidad.jsx',
      'src/pages/More.jsx', 'src/components/import/WallbitConnect.jsx']) {
      expect(leidos, r).toContain(r)
    }
  })

  it('el patrón caza el texto, aunque venga partido, y deja pasar los comentarios', () => {
    // Las tres formas de comentar, y el nombre afuera de ellas.
    const jsx = "// el Coach IA\n{/* el Coach IA */}\n<p>Preguntale al Coach IA</p>\nx // Coach IA"
    expect(vistos('a.jsx', jsx)).toEqual(['Coach IA', 'al Coach'])
    // El caso de WallbitConnect.jsx: un `/*` adentro de un comentario de una
    // línea no abre nada. Con la regex vieja esto daba [].
    const wallbit = '// todo contra /api/wallbit/*.\nconst X = () => <p>Preguntale al Coach IA</p>\n{/* nota */}\n'
    expect(vistos('a.jsx', wallbit)).toEqual(['Coach IA', 'al Coach'])
    // Partido por una etiqueta, por el `{' '}` del formateador o por un
    // espacio duro: en pantalla se lee igual.
    for (const partido of ['<p>Coach <strong>IA</strong></p>', "<p>Coach{' '}\n  IA</p>",
      '<p>Coach&nbsp;IA</p>', "{'Coach\\u00a0IA'}", '<h2>Tip: AI Coach + Novedades</h2>',
      '<p>Preguntale a Rendi AI</p>', '<b>Rendi</b> AI', "'rendi AI'", "'Rendi IA'", "'Rendi-AI'",
      "'Preguntale a Rendi'", "'Hablarle a Rendi'", "'Rendi está hablando'", "'Rendi te lee la respuesta'",
      "'La voz de Rendi no está'"]) {
      expect(vistos('a.jsx', partido), partido).not.toEqual([])
    }
    // HTML: su comentario no cuenta, el del JS de un <script> tampoco.
    const html = '<!-- Coach IA --><script>// el Coach IA\nvar a = 1</script><title>Rendi, con Coach IA</title>'
    expect(vistos('index.html', html)).toEqual(['Coach IA'])
    // Y no confunde la URL de la guía, que se queda como está: cambiarla
    // rompería los links que ya indexó Google (no hay redirección). Tampoco
    // el nombre del componente de la página, que no se muestra.
    expect(vistos('a.jsx', "to: '/guia/coach-ia'")).toEqual([])
    expect(vistos('a.jsx', "import RendiAI from './pages/RendiAI'")).toEqual([])
    // Y "Rendi" como la APP sigue permitido: no es el personaje.
    for (const app of ["'Bienvenido a Rendi'", "'Decile a Rendi qué columna'", "'Pasate a Rendi Pro'",
      "'Entrar a Rendi'", "'Qué analiza Rendi'", "'te invitó a Rendi'"]) {
      expect(vistos('a.jsx', app), app).toEqual([])
    }
  })

  it('ningún texto de la app, la home, el blog, la guía ni los legales dice "Coach IA" ni "Rendi AI"', () => {
    const encontrados = TODOS.flatMap((r) => hallazgos(r, NOMBRE_VIEJO))
    expect(encontrados, 'la IA se llama Mervall-E AI').toEqual([])
  })
})

// ── Las páginas públicas no nombran el modelo ───────────────────────────────
// La FAQ, la guía y el HTML de la home decían "Claude Haiku 4.5" cuando el chat
// ya usaba Sonnet 5 (desde el 2026-09-12, `chat_model` en main.py). Una versión
// escrita a mano en una página pública es un dato que se vence solo. Nombrar al
// proveedor (Claude, de Anthropic) sí: eso lo exigen Términos y Privacidad.
describe('las páginas públicas no atan el texto a una versión del modelo', () => {
  const publicas = TODOS.filter(esPublica)

  it('el filtro encuentra las páginas públicas', () => {
    const rel = publicas.map(relativa)
    expect(rel.length).toBeGreaterThan(30)
    for (const r of ['src/pages/guia/CoachIA.jsx', 'src/components/landing/FAQ.jsx',
      'src/pages/Blog.jsx', 'src/data/planCatalog.js']) {
      expect(rel, r).toContain(r)
    }
  })

  it('ninguna dice Haiku, Sonnet ni Opus', () => {
    const encontrados = publicas.flatMap((r) => hallazgos(r, [/\b(haiku|sonnet|opus)\b/gi]))
    expect(encontrados).toEqual([])
  })
})
