export const meta = {
  name: 'barrido-chequear-y-escribir',
  description: 'Barre el backend buscando chequeos en Python seguidos de escritura (el patron que ningun grep detecta), y verifica cada hallazgo adversarialmente',
  phases: [
    { title: 'Barrido', detail: 'siete lentes distintas sobre el backend, cada una ciega a las demas' },
    { title: 'Verificacion', detail: 'tres escepticos por hallazgo, con la consigna de refutarlo' },
  ],
}

const RAIZ = '/Users/nicolaspussetto/Documents/trading/.claude/worktrees/verif-pg'

const CONTEXTO = `
Repo: Rendi, app de seguimiento de inversiones con ~1.093 usuarios reales y plata real.
Trabajás en la copia ${RAIZ} (backend en ${RAIZ}/backend). Es SOLO LECTURA: no edites ni un archivo.

EL BUG QUE BUSCAMOS, con su mecanismo exacto. Hoy la base es SQLite y se está migrando a
Postgres. Varias reglas de negocio se hacen cumplir así:

    1. el código LEE algo para decidir (un conteo, un saldo, un estado, "¿ya existe?")
    2. decide en Python
    3. unas líneas después ESCRIBE

Entre el paso 1 y el 3 entra otro pedido HTTP simultáneo. Se creía que SQLite tapaba esa
ventana "porque deja escribir a uno por vez". NO LA TAPA: el paso 1 es un SELECT, y un
SELECT en SQLite toma candado COMPARTIDO, no de escritura. Cinco pedidos leen los cinco lo
mismo y después escriben los cinco. MEDIDO HOY: tope de 1 broker para el plan Free, cinco
pedidos simultáneos → quedaron 5 brokers (y 3, 3, 2 en otras corridas). En Postgres es
igual o peor, porque además cada transacción lee una foto del momento en que arrancó.

QUÉ **SÍ** ESTÁ PROTEGIDO — si un sitio cae en alguna de estas, NO es un hallazgo:
  (a) El conteo/chequeo está DENTRO de la misma sentencia que escribe. Ejemplo:
      INSERT ... SELECT ... WHERE (SELECT COUNT(*) ...) < tope
      o  UPDATE ... SET x = x + 1 WHERE (SELECT ...) < tope
      En SQLite eso es atómico. (En Postgres no alcanza solo, pero eso ya está cubierto.)
  (b) Antes del chequeo, la MISMA conexión ya escribió algo en una fila QUE SEGURO EXISTE
      (ej. un UPDATE no-op sobre la fila del usuario). Eso toma el candado de escritura y
      serializa de verdad. Ojo: si la fila puede NO existir todavía, no protege nada.
  (c) Un índice ÚNICO de la base rechaza al segundo. Verificá que el índice exista de
      verdad en backend/schema_pg.sql o en el init_db de backend/main.py, y que cubra
      exactamente las columnas del caso. Si el código captura la excepción y sigue, mirá
      qué hace en el camino de error.
  (d) Es un solo escritor por diseño y está dicho así: un cron, un job nocturno, un script
      de migración, algo que no puede correr dos veces a la vez. Decí por qué estás seguro.
  (e) Lo que se escribe es idempotente de verdad: que entren dos veces deja el mismo
      resultado que una (no "casi", no "un contador queda en 2").

LO QUE YA ESTÁ ENCONTRADO Y ARREGLADO — no lo reportes, sería ruido:
  · ai/quota.py: reserve_chat / reserve_analysis / reserve_listen / reserve_diag_dismiss
    (las cuatro reservas de cuota de IA, ya unificadas en _reservar_un_slot con candado)
  · ai/plan.py check_broker_quota y check_alert_quota + sus INSERT en main.py
    (tope de brokers y de alertas del plan)
  · billing/trial.py: el tope de pruebas gratis del mes
  · main.py _atomic_insert_fact: el tope de datos recordados por usuario
  · efectivo.py tomar_saldo: la caja de efectivo del broker
  · main.py _update_monthly_flow: la fila contable del mes

CÓMO BUSCAR SIN LEER EL REPO ENTERO. backend/main.py tiene ~47.000 líneas: NO lo leas
completo, te quedás sin contexto antes de encontrar nada. Usá grep/rg con patrones, mirá
sólo las ventanas de ±40 líneas alrededor de cada coincidencia, y seguí hacia la escritura.
Archivos que valen la pena barrer además de main.py: backend/billing/*.py, backend/ai/*.py,
backend/efectivo.py, backend/dividendos.py, backend/importers*.py o similar,
backend/snapshots_job.py, backend/alerts_engine.py, y cualquier otro .py del backend.

QUÉ TIENE QUE TRAER CADA HALLAZGO, o no sirve:
  · archivo y número de línea del CHEQUEO, y archivo y línea de la ESCRITURA
  · si las dos están en la MISMA transacción/conexión (decí cómo lo sabés: ¿hay un commit
    en el medio? ¿la conexión es la misma?)
  · el entrelazado concreto de DOS pedidos: "el pedido A lee X, el pedido B lee X, A
    escribe, B escribe, y queda Y" — con nombres y números, no en abstracto
  · qué pasa de malo para el USUARIO o para el negocio (¿plata mal? ¿pared del plan que se
    escapa? ¿un número duplicado? ¿nada visible?)
  · por qué NINGUNA de las protecciones (a)-(e) aplica
Si no podés completar esos puntos, no lo reportes. Un hallazgo a medias cuesta más de
verificar que de encontrar.

Preferí 3 hallazgos sólidos a 15 sospechas. Si tu lente no encuentra nada, devolvé la lista
vacía y decí qué barriste — eso también es información.`

const ESQUEMA_HALLAZGOS = {
  type: 'object',
  properties: {
    que_barri: { type: 'string', description: 'Qué buscaste y dónde, en dos o tres frases. Los patrones de grep que usaste.' },
    hallazgos: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          titulo: { type: 'string' },
          archivo_chequeo: { type: 'string' },
          linea_chequeo: { type: 'integer' },
          archivo_escritura: { type: 'string' },
          linea_escritura: { type: 'integer' },
          misma_transaccion: { type: 'string', description: 'Sí/No + cómo lo sabés' },
          entrelazado: { type: 'string', description: 'El paso a paso de dos pedidos simultáneos, con números' },
          consecuencia: { type: 'string', description: 'Qué pasa de malo para el usuario o el negocio' },
          por_que_no_protegido: { type: 'string', description: 'Por qué no aplica ninguna de (a)-(e)' },
          gravedad: { type: 'string', enum: ['plata', 'paywall', 'datos', 'cosmetico'] },
        },
        required: ['titulo', 'archivo_chequeo', 'linea_chequeo', 'archivo_escritura', 'linea_escritura', 'misma_transaccion', 'entrelazado', 'consecuencia', 'por_que_no_protegido', 'gravedad'],
      },
    },
  },
  required: ['que_barri', 'hallazgos'],
}

const ESQUEMA_VEREDICTO = {
  type: 'object',
  properties: {
    refutado: { type: 'boolean', description: 'true si el hallazgo NO es real o no es alcanzable' },
    motivo: { type: 'string', description: 'Por qué. Si refutás, nombrá la protección concreta con archivo:línea.' },
    que_verifique: { type: 'string', description: 'Qué leíste o corriste para decidir' },
  },
  required: ['refutado', 'motivo', 'que_verifique'],
}

const LENTES = [
  {
    clave: 'saldo',
    titulo: 'suficiencia de plata',
    prompt: `Buscá chequeos de SUFICIENCIA seguidos de un débito: "¿tiene saldo?", "¿alcanza?",
"¿tiene esa cantidad para vender?", "¿el broker tiene esos dólares?" y después un UPDATE que
resta o un INSERT de operación. Es la lente de PLATA: si dos pedidos pasan el mismo chequeo,
el saldo queda en negativo o se vende algo que no estaba.
Mirá especialmente backend/efectivo.py, backend/dividendos.py, los endpoints de venta, retiro,
conversión de monedas y traspaso entre brokers en backend/main.py.
Patrones útiles para grep: "saldo", "insuficiente", "no alcanza", "quantity <", "invested <",
"< cantidad", "disponible".`,
  },
  {
    clave: 'duplicado',
    titulo: 'unicidad decidida en Python',
    prompt: `Buscá el patrón "¿ya existe?" decidido en Python y después un INSERT: un SELECT que
busca una fila, un \`if not fila:\` o \`if fila is None:\`, y adentro un INSERT. Dos pedidos
simultáneos ven los dos que no existe y crean dos.
Para cada uno, verificá si hay un índice ÚNICO que lo rechace — buscá el CREATE UNIQUE INDEX
en backend/schema_pg.sql y en el init_db de backend/main.py — y si lo hay, si cubre
EXACTAMENTE esas columnas. Un índice sobre (user_id, name) no protege un chequeo por
(user_id, name, currency).
Patrones: "if not row", "if row is None", "if not existe", "fetchone()" cerca de un INSERT,
"ya existe", "duplicad".`,
  },
  {
    clave: 'estado',
    titulo: 'transición de estado',
    prompt: `Buscá guardas de ESTADO seguidas de un cambio de estado: "¿está pendiente?",
"¿está activo?", "¿ya se usó?", "¿está pagado?", "¿ya venció?" y después un UPDATE que lo
cambia. Si dos pedidos leen "pendiente", los dos ejecutan la acción: un cobro que se aplica
dos veces, un token de un solo uso que sirve dos veces, un crédito que se otorga dos veces.
Mirá backend/billing/ (cobros, créditos, reembolsos, cambios de plan), los tokens de reseteo
de contraseña y los links de asesor en backend/main.py, y los webhooks de pago.
Patrones: "status ==", "state ==", "if.*pending", "if.*active", "used_at", "ya fue",
"consumido", "redeem", "canjea".`,
  },
  {
    clave: 'idempotencia',
    titulo: 'guardas de "ya lo hice"',
    prompt: `Buscá guardas de idempotencia que se chequean leyendo y después escriben: "¿este lote
ya se importó?", "¿este webhook ya se procesó?", "¿ya le mandé este mail?", "¿ya corrió hoy?".
Dos ejecuciones simultáneas (dos clicks, un reintento del proveedor de pago, dos corridas del
cron que se solapan) ven las dos que no se hizo y lo hacen dos veces.
Mirá los importadores, los webhooks de pago, los envíos de mail y las tareas programadas.
Patrones: "already", "ya se", "ya fue", "ya corrio", "ya corrió", "procesado", "enviado",
"idempot", "event_id", "batch_id", "last_run".`,
  },
  {
    clave: 'primera_fila',
    titulo: 'el que asume "la primera" o "la más vieja"',
    prompt: `Buscá lugares que leen UNA fila asumiendo que hay una sola — \`ORDER BY id LIMIT 1\`,
\`LIMIT 1\`, \`fetchone()\` sobre algo que debería ser único — y después escriben sobre ELLA.
El peligro es doble: (1) si algún camino puede crear una segunda fila, lo que se escriba en
la primera deja la segunda huérfana y nadie la toca más (así desaparecía plata de una caja de
efectivo duplicada); (2) dos pedidos pueden leer la misma fila y escribir pisándose.
Para cada uno, decí QUIÉN crea esas filas y si ese creador puede correr dos veces a la vez.
Patrones: "ORDER BY id LIMIT 1", "LIMIT 1", "fetchone()" seguido de UPDATE sobre su id.`,
  },
  {
    clave: 'acumulador',
    titulo: 'leer-modificar-escribir sobre un número',
    prompt: `Buscá el patrón leer-modificar-escribir sobre un NÚMERO: un SELECT que trae un valor,
aritmética en Python, y un UPDATE que escribe el resultado — en vez de un
\`UPDATE ... SET x = x + ?\` que lo hace en la base. Dos pedidos leen 10, los dos suman 5, los
dos escriben 15: se perdió una suma.
Mirá contadores, acumulados, totales, saldos, cupos consumidos, segundos de dictado, costos
acumulados.
Patrones: un fetchone() cuyo valor termina en un UPDATE del mismo campo; "+= " cerca de SQL;
"total =", "acumulado", "sum(" seguido de UPDATE.`,
  },
  {
    clave: 'borrado',
    titulo: 'leer para borrar o reconstruir',
    prompt: `Buscá lugares que LEEN un conjunto de filas y después BORRAN o REESCRIBEN ese conjunto
(reconstrucciones, recálculos, "borrar y volver a crear", limpiezas). Si otro pedido inserta
una fila en el medio, o se borra lo que el otro acaba de escribir, o queda a medias.
Mirá las reconstrucciones de cartera, los recálculos, el "empezar de cero", los borrados de
snapshots y los revert de importaciones.
Patrones: "DELETE FROM" precedido de un SELECT del mismo conjunto; "rebuild", "reconstru",
"recalc", "revert", "borrar y", "limpi".`,
  },
]

phase('Barrido')
log(`${LENTES.length} lentes sobre el backend, cada una ciega a las demás`)

const porLente = await pipeline(
  LENTES,
  (lente) => agent(
    `${CONTEXTO}\n\n── TU LENTE: ${lente.titulo} ──\n${lente.prompt}\n\n` +
    `Ésta es TU lente y sólo tu lente. Otros agentes están barriendo las otras en paralelo; ` +
    `no te desvíes a buscar lo de ellos aunque lo cruces, porque entonces nadie cubre lo tuyo a fondo.`,
    { label: `barrido:${lente.clave}`, phase: 'Barrido', schema: ESQUEMA_HALLAZGOS },
  ),
  (res, lente) => {
    if (!res) return []
    log(`${lente.clave}: ${res.hallazgos.length} hallazgo(s)`)
    return res.hallazgos.map((h) => ({ ...h, lente: lente.clave }))
  },
)

const crudos = porLente.filter(Boolean).flat()

// Dedup por (archivo de escritura + línea de escritura): dos lentes distintas pueden
// llegar al MISMO sitio por caminos distintos, y verificarlo dos veces es pagar doble.
const vistos = new Set()
const unicos = []
for (const h of crudos) {
  const clave = `${h.archivo_escritura}:${h.linea_escritura}`
  if (vistos.has(clave)) continue
  vistos.add(clave)
  unicos.push(h)
}

log(`${crudos.length} hallazgos crudos → ${unicos.length} distintos`)

// Los de plata y paywall primero: si hay que recortar, se recorta lo cosmético.
const PESO = { plata: 0, paywall: 1, datos: 2, cosmetico: 3 }
const ordenados = unicos.sort((a, b) => (PESO[a.gravedad] ?? 9) - (PESO[b.gravedad] ?? 9))
const TOPE_VERIFICAR = 16
const aVerificar = ordenados.slice(0, TOPE_VERIFICAR)
const dejados = ordenados.slice(TOPE_VERIFICAR)
if (dejados.length) {
  log(`⚠️ SIN VERIFICAR por el tope de ${TOPE_VERIFICAR}: ${dejados.map((h) => h.titulo).join(' · ')}`)
}

phase('Verificacion')
if (!aVerificar.length) {
  log('Las siete lentes no encontraron nada nuevo. No hay nada que verificar.')
  return { confirmados: [], refutados: [], sin_verificar: dejados, barridos: LENTES.length }
}
log(`${aVerificar.length} hallazgo(s) × 3 escépticos cada uno`)

const LENTES_DE_DUDA = [
  {
    clave: 'proteccion',
    prompt: `Tu trabajo es encontrar la PROTECCIÓN que el que reportó no vio. Repasá una por una:
(a) ¿el chequeo está dentro de la misma sentencia que escribe? (b) ¿la misma conexión ya
escribió antes en una fila que seguro existe? (c) ¿hay un índice único que lo rechace —
buscalo en schema_pg.sql Y en el init_db de main.py, y comprobá que cubra exactamente esas
columnas? (d) ¿es un escritor único por diseño (cron, job, script)? (e) ¿es idempotente de
verdad? Si encontrás cualquiera, el hallazgo está refutado y nombrala con archivo:línea.`,
  },
  {
    clave: 'alcanzable',
    prompt: `Tu trabajo es decidir si esto es ALCANZABLE con dos pedidos HTTP simultáneos de verdad.
Buscá el endpoint que llega hasta ahí y seguí el camino completo. ¿Hay un \`Depends\` que
serialice? ¿Un lock de proceso? ¿Es código que sólo corre desde un cron o un script suelto y
no desde la web? ¿Requiere que el mismo usuario mande dos pedidos a la vez, o le sirve a
usuarios distintos? ¿Hay algo antes en el camino que ya haya escrito y por lo tanto tomado el
candado? Si el camino no existe o está serializado antes, está refutado.`,
  },
  {
    clave: 'consecuencia',
    prompt: `Tu trabajo es verificar que la CONSECUENCIA sea real y no cosmética. Suponé que la
carrera se da y que entran los dos. ¿Qué queda escrito exactamente? ¿Alguien lee después ese
dato, y lee mal? Seguí el dato hasta la pantalla o hasta el cálculo que lo usa. Si el
resultado final es el mismo que sin la carrera, o si un recálculo posterior lo corrige, o si
nadie lee nunca esa fila, el hallazgo está refutado. Si en cambio hay plata mal o una pared
del plan que se escapa, decí el número concreto.`,
  },
]

const verificados = await pipeline(
  aVerificar,
  (h) => parallel(
    LENTES_DE_DUDA.map((duda) => () => agent(
      `${CONTEXTO}\n\n── HALLAZGO A REFUTAR ──\n` +
      `Título: ${h.titulo}\n` +
      `Chequeo: ${h.archivo_chequeo}:${h.linea_chequeo}\n` +
      `Escritura: ${h.archivo_escritura}:${h.linea_escritura}\n` +
      `¿Misma transacción?: ${h.misma_transaccion}\n` +
      `Entrelazado que afirma: ${h.entrelazado}\n` +
      `Consecuencia que afirma: ${h.consecuencia}\n` +
      `Por qué dice que no está protegido: ${h.por_que_no_protegido}\n` +
      `Gravedad que afirma: ${h.gravedad}\n\n` +
      `── TU CONSIGNA: REFUTARLO ──\n${duda.prompt}\n\n` +
      `No confirmes por cortesía ni por parecer riguroso. Ante la duda, refutado=true: ` +
      `un hallazgo falso que llega al informe cuesta una sesión entera de otra persona. ` +
      `Leé el código de verdad, no razones desde el resumen de arriba — ese resumen puede estar mal.`,
      { label: `duda:${duda.clave}:${h.lente}`, phase: 'Verificacion', schema: ESQUEMA_VEREDICTO },
    )),
  ).then((votos) => {
    const vivos = votos.filter(Boolean)
    const refutaron = vivos.filter((v) => v.refutado)
    // Mayoría: con 3 escépticos, 2 refutaciones lo matan. Si uno murió, con 1 de 2 alcanza.
    const sobrevive = vivos.length > 0 && refutaron.length < Math.ceil(vivos.length / 2)
    return { hallazgo: h, sobrevive, votos: vivos, refutaron: refutaron.length, de: vivos.length }
  }),
)

const vivos = verificados.filter(Boolean)
const confirmados = vivos.filter((v) => v.sobrevive)
const refutados = vivos.filter((v) => !v.sobrevive)

log(`CONFIRMADOS: ${confirmados.length} · refutados: ${refutados.length}`)
for (const c of confirmados) {
  log(`  ✅ [${c.hallazgo.gravedad}] ${c.hallazgo.titulo} (${c.hallazgo.archivo_escritura}:${c.hallazgo.linea_escritura}) — refutaron ${c.refutaron} de ${c.de}`)
}

return {
  confirmados: confirmados.map((c) => ({
    ...c.hallazgo,
    votos_a_favor: c.de - c.refutaron,
    votos_en_contra: c.refutaron,
    motivos_de_duda: c.votos.map((v) => `${v.refutado ? 'REFUTA' : 'confirma'}: ${v.motivo}`),
  })),
  refutados: refutados.map((r) => ({
    titulo: r.hallazgo.titulo,
    sitio: `${r.hallazgo.archivo_escritura}:${r.hallazgo.linea_escritura}`,
    por_que: r.votos.filter((v) => v.refutado).map((v) => v.motivo),
  })),
  sin_verificar: dejados.map((h) => ({ titulo: h.titulo, sitio: `${h.archivo_escritura}:${h.linea_escritura}`, gravedad: h.gravedad })),
  que_se_barrio: LENTES.map((l) => l.titulo),
}
