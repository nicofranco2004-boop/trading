export const meta = {
  name: 'tomar-turno-24-sitios',
  description: 'Los 24 usos de _tomar_turno: cual protege de verdad en Postgres y cual confia en una proteccion que solo existe en SQLite',
  phases: [
    { title: 'Mapeo', detail: 'ocho familias de sitios, cada agente con el mismo molde de preguntas' },
    { title: 'Refutacion', detail: 'tres esccepticos por sitio marcado como desprotegido' },
  ],
}

const RAIZ = '/Users/nicolaspussetto/Documents/trading/.claude/worktrees/verif-pg'

const CONTEXTO = `
Repo: Rendi, app de seguimiento de inversiones, ~1.093 usuarios reales y plata real.
Copia: ${RAIZ} (backend en ${RAIZ}/backend). **SOLO LECTURA: no edites ni un archivo.**

══ EL MECANISMO, y es todo lo que hay que entender ══

\`main._tomar_turno(conn, uid)\` (definida en \`main.py\`, buscala con grep) hace UNA cosa:

    conn.execute("UPDATE users SET tier=tier WHERE id=?", (uid,))

Es un UPDATE que no cambia nada. Su propósito es «poné en fila esta operación
contra las otras del mismo usuario». La usan **24 lugares de producción**, casi
todos operaciones destructivas: borrados en cascada, deshacer, cobros de bonos,
dividendos, la contabilidad mensual.

🔴 **PROTEGE MUCHO MENOS DE LO QUE PARECE, y de forma distinta en cada motor:**

  · En SQLite ese UPDATE toma **la base ENTERA** hasta el commit. Entonces
    cualquier otro pedido que quiera ESCRIBIR cualquier cosa espera. Protección
    total, gratis, sin que nadie la pidiera.
  · En Postgres toma **solamente la fila de ese usuario en la tabla \`users\`**.
    Entonces únicamente espera quien también escriba ESA fila. Todo lo demás
    pasa por al lado.

👉 **LA PREGUNTA DE ESTE TRABAJO, por cada sitio:**
   ¿Quién puede meterse en el medio **sin escribir la fila de \`users\`**?
   · Si los únicos que podrían hacer daño son otras operaciones que TAMBIÉN
     llaman a \`_tomar_turno\`, el sitio está PROTEGIDO también en Postgres
     (se serializan entre ellas por la fila de \`users\`).
   · Si hay un camino que toca las mismas filas y NO llama a \`_tomar_turno\`,
     el sitio NO está protegido en Postgres.

══ EL CASO YA RESUELTO, úsenlo para calibrar ══

\`_delete_one_movement\` (borrar un depósito cargado a mano) resultó un bug REAL
de plata, y así se descubrió:
  1. Pide \`_tomar_turno\` al entrar.
  2. Lee el saldo de efectivo con un SELECT para decidir si puede borrar.
  3. Corre \`_foto_contable\`, que el propio código mide en **0,8 a 1,65 segundos**.
  4. Debita, permitiendo que el saldo quede NEGATIVO.
  El competidor era \`POST /api/cash/flow\` (un retiro), que **nunca escribe la
  fila de \`users\`** → no esperaba a nadie. Resultado: efectivo en −$1.000.000
  con la compra viva. Ya está arreglado (ahora leer la caja pide un candado de
  verdad), pero es el molde: **el competidor no era otra operación destructiva,
  era un endpoint común.**

══ CÓMO BUSCAR SIN QUEDARTE SIN CONTEXTO ══

\`backend/main.py\` tiene ~50.000 líneas: **NO lo leas completo**, te quedás sin
contexto antes de llegar a ninguna conclusión. Usá grep/rg y leé ventanas de
±60 líneas. Para encontrar competidores, buscá quién más escribe la MISMA TABLA:
\`grep -n "UPDATE <tabla>\\|INSERT INTO <tabla>\\|DELETE FROM <tabla>" main.py\`
y después mirá si esa función llama a \`_tomar_turno\` (\`grep -n "_tomar_turno" \`
y ver en qué función cae cada línea).

Archivos que también escriben: \`backend/importing/persister.py\`,
\`backend/efectivo.py\`, \`backend/dividendos.py\`, \`backend/snapshots_job.py\`.

══ LO QUE TIENE QUE TRAER CADA SITIO, o no sirve ══

· \`que_protege\`: el par concreto «lee X para decidir → escribe Y», con líneas.
  Si el sitio NO lee nada para decidir (sólo escribe), decilo: entonces el turno
  puede ser innecesario, y eso también es un hallazgo.
· \`tablas\`: qué tablas lee-para-decidir y qué tablas escribe.
· \`competidores_sin_turno\`: funciones CONCRETAS con archivo:línea que escriben
  esas tablas y NO llaman a \`_tomar_turno\`. Si no encontrás ninguno, decí a qué
  tablas buscaste competidor y cuántos candidatos revisaste.
· \`protegido_en_postgres\`: true/false, y en \`por_que\` el razonamiento.
· \`consecuencia\`: qué pasa de malo si se cruzan, concreto. ¿Plata mal? ¿Un
  borrado a medias? ¿Datos de otro usuario? ¿Nada visible?
· \`gravedad\`: plata | datos | paywall | cosmetico | ninguna

Preferí 1 sitio bien analizado a 4 por arriba. Si no podés cerrar un sitio,
marcalo \`protegido_en_postgres: false\` con \`gravedad: "ninguna"\` y explicá en
\`por_que\` qué te faltó — un «no sé» honesto vale más que un veredicto inventado.`

const ESQUEMA_SITIOS = {
  type: 'object',
  properties: {
    como_busque: { type: 'string', description: 'Qué grep usaste para encontrar competidores y cuántos candidatos revisaste' },
    sitios: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          funcion: { type: 'string' },
          linea: { type: 'integer' },
          que_protege: { type: 'string' },
          tablas: { type: 'string' },
          competidores_sin_turno: { type: 'string' },
          protegido_en_postgres: { type: 'boolean' },
          por_que: { type: 'string' },
          consecuencia: { type: 'string' },
          gravedad: { type: 'string', enum: ['plata', 'datos', 'paywall', 'cosmetico', 'ninguna'] },
        },
        required: ['funcion', 'linea', 'que_protege', 'tablas', 'competidores_sin_turno',
                   'protegido_en_postgres', 'por_que', 'consecuencia', 'gravedad'],
      },
    },
  },
  required: ['como_busque', 'sitios'],
}

const ESQUEMA_VEREDICTO = {
  type: 'object',
  properties: {
    refutado: { type: 'boolean', description: 'true si el sitio NO está en riesgo o el riesgo no es alcanzable' },
    motivo: { type: 'string', description: 'Por qué. Si refutás, nombrá la protección concreta con archivo:línea.' },
    que_verifique: { type: 'string', description: 'Qué leíste para decidir' },
  },
  required: ['refutado', 'motivo', 'que_verifique'],
}

// Las 24 llamadas, agrupadas en familias de sitios que comparten tablas.
const FAMILIAS = [
  { clave: 'ops', titulo: 'borrados en cascada de OPERACIONES',
    sitios: '_delete_manual_operation_cascade (21428), _delete_operation_cascade (22123), undo_delete_operation (22483)' },
  { clave: 'posiciones', titulo: 'borrados en cascada de POSICIONES',
    sitios: '_delete_manual_position_cascade (21672), _delete_position_cascade (22339), _undo_manual_delete (21843)' },
  { clave: 'historial', titulo: 'historial de activos',
    sitios: '_delete_asset_history_cascade (22578), undo_delete_asset_history (22793)' },
  { clave: 'mensual', titulo: 'contabilidad mensual a mano',
    sitios: 'create_monthly (16988), update_monthly (17020), delete_monthly (17060)' },
  { clave: 'bonos', titulo: 'bonos y dividendos',
    sitios: 'bond_cashflow (14785), bond_pago (14884), dividendos_cobro (15586)' },
  { clave: 'brokers', titulo: 'brokers',
    sitios: '_borrar_datos_de_brokers (6126), update_broker (6331), _exigir_broker_existente (11851), _ensure_usd_sibling (15621)' },
  { clave: 'foto', titulo: 'movimientos, la foto contable y futuros',
    sitios: '_delete_one_movement (19846), _foto_contable (18677), close_futuro (17376)' },
  { clave: 'secciones', titulo: 'secciones y mapeos del importador',
    sitios: 'import_mappings_save (45071), sections_archive (45250), sections_restore (45283)' },
]

phase('Mapeo')
log(`${FAMILIAS.length} familias que cubren las 24 llamadas, cada una con el mismo molde`)

const porFamilia = await pipeline(
  FAMILIAS,
  (fam) => agent(
    `${CONTEXTO}\n\n══ TU FAMILIA: ${fam.titulo} ══\n\n` +
    `Analizá ESTOS sitios y sólo éstos, uno por uno:\n    ${fam.sitios}\n\n` +
    `(Los números de línea son de referencia y pueden haberse corrido unas líneas: ` +
    `ubicá cada función por su nombre con grep y usá la línea real.)\n\n` +
    `Son de la misma familia porque comparten tablas, así que el competidor que ` +
    `encuentres para uno probablemente aplique a los otros — pero verificá cada ` +
    `uno, no lo asumas. Otros agentes están analizando las otras familias en ` +
    `paralelo; no te desvíes a las de ellos aunque las cruces.`,
    { label: `mapeo:${fam.clave}`, phase: 'Mapeo', schema: ESQUEMA_SITIOS },
  ),
  (res, fam) => {
    if (!res) return []
    const enRiesgo = res.sitios.filter((s) => !s.protegido_en_postgres && s.gravedad !== 'ninguna')
    log(`${fam.clave}: ${res.sitios.length} sitios · ${enRiesgo.length} en riesgo`)
    return res.sitios.map((s) => ({ ...s, familia: fam.clave }))
  },
)

const todos = porFamilia.filter(Boolean).flat()
const enRiesgo = todos.filter((s) => !s.protegido_en_postgres && s.gravedad !== 'ninguna')
const protegidos = todos.filter((s) => s.protegido_en_postgres)
const sinCerrar = todos.filter((s) => !s.protegido_en_postgres && s.gravedad === 'ninguna')

log(`MAPEO: ${todos.length} sitios analizados · ${enRiesgo.length} en riesgo · ${protegidos.length} protegidos · ${sinCerrar.length} sin cerrar`)

phase('Refutacion')
if (!enRiesgo.length) {
  log('Ningún sitio quedó marcado en riesgo. Nada que refutar.')
  return { en_riesgo: [], protegidos, sin_cerrar: sinCerrar, analizados: todos.length }
}

const PESO = { plata: 0, paywall: 1, datos: 2, cosmetico: 3 }
const ordenados = enRiesgo.sort((a, b) => (PESO[a.gravedad] ?? 9) - (PESO[b.gravedad] ?? 9))
log(`${ordenados.length} sitio(s) en riesgo × 3 escépticos cada uno`)

const LENTES = [
  { clave: 'proteccion', prompt:
    `Tu trabajo es encontrar la PROTECCIÓN que el que reportó no vio. Repasá: ¿el competidor ` +
    `que nombra realmente NO llama a \`_tomar_turno\` (seguí su cadena de llamadas hacia arriba, ` +
    `puede llamarlo un wrapper)? ¿Hay un índice único, un CHECK o una clave foránea que lo ` +
    `rechace (buscalo en \`schema_pg.sql\` Y en el \`init_db\` de \`main.py\`, y comprobá que cubra ` +
    `EXACTAMENTE esas columnas)? ¿Hay otro candado en el medio (\`efectivo.tomar_saldo\`, ` +
    `\`pgsesion.turno_exclusivo\`)? ¿El camino escribe algo ANTES de leer, en una fila que seguro ` +
    `existe? Si encontrás cualquiera, está refutado: nombrala con archivo:línea.` },
  { clave: 'alcanzable', prompt:
    `Tu trabajo es decidir si esto es ALCANZABLE de verdad. Seguí el camino desde el endpoint ` +
    `HTTP hasta el sitio. ¿Existe ese endpoint? ¿Lo puede disparar un usuario, o es un cron, un ` +
    `script o código de administración? ¿Hace falta que el MISMO usuario mande dos pedidos a la ` +
    `vez, o le sirve a dos usuarios distintos? ¿Cuánto dura la ventana entre el leer y el ` +
    `escribir — son dos líneas o hay algo lento en el medio? Una ventana de microsegundos entre ` +
    `dos sentencias seguidas es muy distinta de una que espera a la red. Si el camino no existe ` +
    `o está serializado antes, está refutado.` },
  { clave: 'consecuencia', prompt:
    `Tu trabajo es verificar que la CONSECUENCIA sea real y no cosmética. Suponé que se cruzan. ` +
    `¿Qué queda escrito exactamente? Seguí ese dato hasta la pantalla o hasta el cálculo que lo ` +
    `usa. ⚠️ **OJO CON LOS RECÁLCULOS**: en este repo hay un \`_recalc_pnl_realized_from_ops\` y ` +
    `un \`_repair_monthly_chain\` que rearman la contabilidad desde fuentes autoritativas y pueden ` +
    `estar tapando el daño — si uno de ellos corre después y lo corrige, la consecuencia es menor ` +
    `de lo que parece y hay que decirlo (pero NO es refutado: es «tapado por un recálculo», que es ` +
    `otra cosa, porque el día que alguien agregue una puerta sin recálculo se destapa). ` +
    `Si nadie lee nunca ese dato, o el resultado final es el mismo, está refutado.` },
]

const verificados = await pipeline(
  ordenados,
  (s) => parallel(
    LENTES.map((lente) => () => agent(
      `${CONTEXTO}\n\n══ SITIO A REFUTAR ══\n` +
      `Función: ${s.funcion} (línea ~${s.linea}, familia ${s.familia})\n` +
      `Qué protege: ${s.que_protege}\n` +
      `Tablas: ${s.tablas}\n` +
      `Competidores que afirma: ${s.competidores_sin_turno}\n` +
      `Por qué dice que NO está protegido: ${s.por_que}\n` +
      `Consecuencia que afirma: ${s.consecuencia}\n` +
      `Gravedad que afirma: ${s.gravedad}\n\n` +
      `══ TU CONSIGNA: REFUTARLO ══\n${lente.prompt}\n\n` +
      `No confirmes por cortesía ni por parecer riguroso. Ante la duda, refutado=true: ` +
      `un hallazgo falso que llega al informe cuesta una sesión entera de otra persona. ` +
      `Leé el código de verdad — el resumen de arriba puede estar mal, y tu trabajo es ` +
      `justamente ver si lo está.`,
      { label: `duda:${lente.clave}:${s.funcion}`, phase: 'Refutacion', schema: ESQUEMA_VEREDICTO },
    )),
  ).then((votos) => {
    const vivos = votos.filter(Boolean)
    const refutaron = vivos.filter((v) => v.refutado)
    const sobrevive = vivos.length > 0 && refutaron.length < Math.ceil(vivos.length / 2)
    return { sitio: s, sobrevive, votos: vivos, refutaron: refutaron.length, de: vivos.length }
  }),
)

const vivos = verificados.filter(Boolean)
const confirmados = vivos.filter((v) => v.sobrevive)
const refutados = vivos.filter((v) => !v.sobrevive)

log(`CONFIRMADOS: ${confirmados.length} · refutados: ${refutados.length}`)
for (const c of confirmados) {
  log(`  🔴 [${c.sitio.gravedad}] ${c.sitio.funcion} — refutaron ${c.refutaron} de ${c.de}`)
}

return {
  confirmados: confirmados.map((c) => ({
    ...c.sitio,
    votos_a_favor: c.de - c.refutaron,
    votos_en_contra: c.refutaron,
    motivos: c.votos.map((v) => `${v.refutado ? 'REFUTA' : 'confirma'}: ${v.motivo}`),
  })),
  refutados: refutados.map((r) => ({
    funcion: r.sitio.funcion,
    gravedad_que_afirmaba: r.sitio.gravedad,
    por_que_se_cae: r.votos.filter((v) => v.refutado).map((v) => v.motivo),
  })),
  protegidos: protegidos.map((s) => ({ funcion: s.funcion, por_que: s.por_que })),
  sin_cerrar: sinCerrar.map((s) => ({ funcion: s.funcion, que_falto: s.por_que })),
  analizados: todos.length,
}
