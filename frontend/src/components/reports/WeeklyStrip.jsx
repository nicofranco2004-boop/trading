// WeeklyStrip — la tira "Semana a semana" de Reportes.
// ═══════════════════════════════════════════════════════════════════════════
// Una barra por semana. La barra se parte en dos: lo que se movieron las
// POSICIONES ABIERTAS (mark-to-market) y lo que dejaron las VENTAS Y DIVIDENDOS.
// El interruptor de arriba deja ver sólo el primero, que es el pedido original
// del usuario: "cómo rindió mi cartera, no mis operaciones cerradas".
//
// Sistema visual (contrato en frontend/CLAUDE.md):
//   • Tipografía: Geist. Todo número lleva `tabular`; nada de la familia de
//     ancho fijo, que en este repo está reservada a meta técnica literal (R1/R3).
//   • Radios: la tarjeta la da Panel (12px). Barras y cuadraditos, de la escala
//     declarada — `rounded-sm` y `rounded-xs`, nunca un valor a medida (R5).
//   • Un solo archivo, responsive por variantes. Sin gemelo para el teléfono (R6).
//   • EL COLOR SIGNIFICA SIGNO, NO CATEGORÍA. Verde es ganancia y rojo es
//     pérdida, siempre — así lo declara tailwind.config.js y así lo lee todo el
//     producto. Los dos pedazos de la barra se distinguen por OPACIDAD (lleno =
//     posiciones abiertas, apagado = ventas). Si el verde significara "abiertas",
//     una venta con pérdida se leería como ganancia.
//
// Las cuentas —qué semana entra, cuánto mide cada pedazo, dónde cae la línea del
// cero— viven en utils/semanas.js, que sí tiene tests. Acá sólo se dibuja.

import { useMemo, useState } from 'react'
import Panel from '../Panel'
import { useCurrency, useMoneyFormat } from '../../contexts/CurrencyContext'
import { colorClass } from '../../utils/format'
import { hoyISO } from '../../utils/fecha'
import {
  MAX_SEMANAS, aplanarSemanas, ultimasSemanas, medirSemana, pedazosDe,
  escalaDeSerie, fraccionArriba, altoPorcentual, rangoSemana, diaCorto, valorDe,
} from '../../utils/semanas'

const ALTO_GRAFICO = 'h-[200px] sm:h-[224px]'

/** Verde o rojo por el SIGNO del pedazo; lleno o apagado por su tipo. */
function claseDePedazo(pedazo) {
  const positivo = pedazo.valor > 0
  if (pedazo.tipo === 'abiertas') return positivo ? 'bg-rendi-pos' : 'bg-rendi-neg'
  return positivo ? 'bg-rendi-pos/60' : 'bg-rendi-neg/60'
}

export default function WeeklyStrip({ yearGroups, broker = 'global', modo: modoElegido = 'todo', onModo }) {
  const { currency } = useCurrency()
  const { fmtMoney } = useMoneyFormat()
  const [elegida, setElegida] = useState(null)

  // Con un broker elegido el motor no puede separar las abiertas (la foto de la
  // cartera es global): el interruptor no tendría nada que filtrar.
  const porBroker = broker !== 'global'
  const modo = porBroker ? 'todo' : modoElegido

  const medidas = useMemo(
    () => ultimasSemanas(aplanarSemanas(yearGroups, hoyISO()), MAX_SEMANAS)
      .map(s => medirSemana(s, { porBroker })),
    [yearGroups, porBroker],
  )
  const escala = useMemo(() => escalaDeSerie(medidas, modo), [medidas, modo])

  const fmtPlata = (v) => fmtMoney(v, { signed: true })
  const frac = fraccionArriba(escala)
  const topCero = `${(frac * 100).toFixed(2).replace('.', ',')}%`
  const altoAbajo = `${((1 - frac) * 100).toFixed(2).replace('.', ',')}%`
  // La marca de "sin medición" va CENTRADA en la línea del cero, pero la línea
  // puede quedar pegada a un borde (una serie toda positiva la manda al 100%) y
  // entonces la marca se salía de la caja y caía encima de las fechas. Se acota
  // su posición sin tocar la línea: lo que se corrige es el adorno, no la escala.
  const topMarca = `${Math.min(86, Math.max(0, frac * 100 - 7)).toFixed(2).replace('.', ',')}%`

  // La elegida por defecto es la última: la semana más reciente es la que el
  // usuario viene a mirar. El recorte por índice cubre el caso de que cambien
  // los datos (otro broker, otra moneda) y la elegida ya no exista.
  const indice = elegida != null && elegida < medidas.length ? elegida : medidas.length - 1
  const foco = medidas[indice]

  // ⚠️ EL VACÍO DE VERDAD NO ES "NO LLEGARON SEMANAS", ES "NINGUNA SE PUDO
  // MEDIR". El backend arma las semanas de todos los meses SIEMPRE
  // (timeline.py:218), así que una lista vacía casi no existe: el caso real de
  // una cuenta nueva es que lleguen doce y no se pueda medir ninguna. Sin este
  // chequeo, esa cuenta veía doce cajas punteadas vacías abajo de un título que
  // le prometía datos, y leía "esto no funciona". Nos pasó con el primer usuario
  // que lo pidió.
  const medibles = medidas.filter(m => m.estado !== 'sin-medicion').length

  if (medidas.length === 0 || medibles === 0) {
    return (
      <Panel padding="lg" className="mb-4">
        <Cabecera modo={modo} porBroker={porBroker} onModo={onModo} cantidad={0} />
        <p className="text-xs text-ink-2 leading-relaxed max-w-lg">
          Todavía no podemos medir ninguna semana. Para saber cuánto rindió una
          semana hacen falta dos fotos del valor de tu cartera: la que la abre y la
          que la cierra. Se guardan solas, una por día, y en cuanto haya dos aparece
          la primera barra.{' '}
          <span className="text-ink-3">
            Si esto sigue vacío dentro de unos días, el problema es nuestro y no tuyo:
            escribinos y lo miramos.
          </span>
        </p>
      </Panel>
    )
  }

  return (
    <Panel padding="lg" className="mb-4">
      <Cabecera modo={modo} porBroker={porBroker} onModo={onModo} cantidad={medidas.length} />

      {porBroker && (
        <div className="border border-line-2 bg-bg-2/60 rounded px-3 py-2 mb-4 text-[11px] text-ink-2 leading-relaxed">
          Estás viendo un broker solo, y la foto diaria de tu cartera es del conjunto:
          por eso acá no se puede separar cuánto se movieron tus posiciones abiertas.
          Estas barras muestran únicamente las operaciones cerradas de este broker.
          Para ver el movimiento de lo que tenés, elegí todos los brokers.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_232px] items-start">
        <div>
          <div className={`relative ${ALTO_GRAFICO}`}>
            {/* La línea del cero. Se reparte según los datos: una serie toda
                positiva no desperdicia media caja vacía. */}
            <div
              className="absolute inset-x-0 border-t border-ink-3/50"
              style={{ top: topCero }}
              aria-hidden="true"
            />
            <div
              className="absolute inset-0 grid gap-1"
              style={{ gridTemplateColumns: `repeat(${medidas.length}, minmax(0, 1fr))` }}
            >
              {medidas.map((m, i) => (
                <Barra
                  key={m.clave || i}
                  medida={m}
                  modo={modo}
                  escala={escala}
                  topCero={topCero}
                  topMarca={topMarca}
                  altoAbajo={altoAbajo}
                  activa={i === indice}
                  onElegir={() => setElegida(i)}
                  descripcion={`${rangoSemana(m.inicio, m.fin)}: ${
                    m.estado === 'sin-medicion' ? 'sin medición' : fmtPlata(valorDe(m, modo))
                  }`}
                />
              ))}
            </div>
          </div>

          {/* Eje. Dos cosas que parecen detalles y no lo son:
              · La cuenta va DESDE EL FINAL, para que la semana más reciente
                siempre quede rotulada.
              · La fecha no se recorta ni se esconde con `hidden`: recortada
                quedaban las seis etiquetas en puntos suspensivos a 375px, y
                esconder la celda la saca de la grilla y descoloca el eje entero
                respecto de las barras. Se deja desbordar sobre el aire de las
                celdas vacías vecinas, y en pantalla angosta se rotula una de
                cada cuatro (desde `sm`, una de cada dos). */}
          <div
            className="grid gap-1 mt-2"
            style={{ gridTemplateColumns: `repeat(${medidas.length}, minmax(0, 1fr))` }}
          >
            {medidas.map((m, i) => {
              const desdeElFinal = medidas.length - 1 - i
              const cadaDos = desdeElFinal % 2 === 0
              const cadaCuatro = desdeElFinal % 4 === 0
              return (
                <span
                  key={m.clave || i}
                  className={`text-center text-[10px] tabular whitespace-nowrap ${
                    cadaCuatro ? '' : 'invisible sm:visible'
                  } ${m.enCurso ? 'text-data-violet' : 'text-ink-3'}`}
                >
                  {cadaDos ? diaCorto(m.inicio) : ''}
                </span>
              )
            })}
          </div>

          <Leyenda modo={modo} porBroker={porBroker} />
        </div>

        <Detalle
          medida={foco}
          modo={modo}
          porBroker={porBroker}
          enPesos={currency === 'ARS'}
          fmtPlata={fmtPlata}
        />
      </div>
    </Panel>
  )
}

function Cabecera({ modo, porBroker, onModo, cantidad }) {
  return (
    <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
      <div>
        <p className="eyebrow mb-1">Rendimiento</p>
        <h3 className="text-base font-semibold text-ink-0 leading-tight">Semana a semana</h3>
        <p className="text-xs text-ink-2 mt-1">
          {porBroker
            ? 'Lo que cerraste en este broker, semana por semana'
            : modo === 'abiertas'
            ? 'Sólo lo que se movieron tus posiciones abiertas'
            : 'Lo que se movió tu cartera, semana por semana'}
          {cantidad > 0 && ` · últimas ${cantidad}`}
        </p>
      </div>
      {!porBroker && (
        <div className="inline-flex bg-bg-2 border border-line rounded-sm p-0.5 shrink-0">
          {[
            { id: 'todo', texto: 'Todo' },
            { id: 'abiertas', texto: 'Sólo abiertas' },
          ].map(op => (
            <button
              key={op.id}
              type="button"
              onClick={() => onModo(op.id)}
              aria-pressed={modo === op.id}
              className={`px-3 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                modo === op.id ? 'bg-bg-3 text-ink-0' : 'text-ink-2 hover:text-ink-0'
              }`}
            >
              {op.texto}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Barra({ medida, modo, escala, topCero, topMarca, altoAbajo, activa, onElegir, descripcion }) {
  const pedazos = pedazosDe(medida, modo)
  const arriba = pedazos.filter(p => p.valor > 0)
  const abajo = pedazos.filter(p => p.valor < 0)
  const sinMedicion = medida.estado === 'sin-medicion'
  // Nada que dibujar aunque la semana SÍ se haya medido: cero es un resultado.
  // Se marca con una rayita apoyada en el cero para que no se confunda con el
  // hueco de la semana que no se pudo medir.
  const enCero = !sinMedicion && arriba.length === 0 && abajo.length === 0

  return (
    <button
      type="button"
      onMouseEnter={onElegir}
      onFocus={onElegir}
      onClick={onElegir}
      aria-current={activa ? 'true' : undefined}
      aria-label={descripcion}
      className={`relative h-full rounded-sm transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-data-violet ${
        activa ? '' : 'hover:bg-bg-2/40'
      }`}
    >
      {/* La marca de la semana elegida va ABAJO, sobre el eje: un bloque de
          altura completa detrás de la barra se lee como otra barra — en 375px
          se leía como la más alta de la tira. */}
      {activa && (
        <span
          className="absolute inset-x-0 -bottom-0.5 h-0.5 bg-data-violet rounded-full"
          aria-hidden="true"
        />
      )}

      {sinMedicion && (
        <span
          className="absolute inset-x-1 border border-dashed border-ink-3/80 rounded-xs"
          style={{ top: topMarca, height: '13%' }}
          aria-hidden="true"
        />
      )}

      {enCero && (
        <span
          className="absolute inset-x-1 h-0.5 bg-ink-2 rounded-full"
          style={{ top: topCero }}
          aria-hidden="true"
        />
      )}

      {/* Lo positivo, apoyado sobre la línea del cero y creciendo hacia arriba.
          El pedazo de posiciones abiertas va último para que quede pegado a la
          línea: es el que se lee primero. */}
      <span
        className="absolute inset-x-1 top-0 flex flex-col justify-end gap-px"
        style={{ bottom: altoAbajo }}
        aria-hidden="true"
      >
        {[...arriba].reverse().map(p => (
          <span
            key={p.tipo}
            className={`w-full rounded-xs min-h-px ${claseDePedazo(p)}`}
            style={{ height: `${altoPorcentual(p.valor, escala.arriba)}%` }}
          />
        ))}
      </span>

      {/* Lo negativo, colgando de la línea hacia abajo. */}
      <span
        className="absolute inset-x-1 bottom-0 flex flex-col justify-start gap-px"
        style={{ top: topCero }}
        aria-hidden="true"
      >
        {abajo.map(p => (
          <span
            key={p.tipo}
            className={`w-full rounded-xs min-h-px ${claseDePedazo(p)}`}
            style={{ height: `${altoPorcentual(p.valor, escala.abajo)}%` }}
          />
        ))}
      </span>
    </button>
  )
}

// ⚠️ LOS CUADRADITOS DE LA LEYENDA VAN EN NEUTRO, NO EN VERDE.
// Lo que distingue a los dos pedazos es la OPACIDAD; el color es el signo. Con
// los cuadraditos en verde, un trimestre entero en rojo tenía una leyenda que
// señalaba un verde que no estaba dibujado en ninguna parte de la tira.
function Leyenda({ modo, porBroker }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3 text-[11px] text-ink-2">
      {!porBroker && (
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-xs bg-ink-0" aria-hidden="true" />
          Posiciones abiertas
        </span>
      )}
      {(modo === 'todo' || porBroker) && (
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-xs bg-ink-0/35" aria-hidden="true" />
          Ventas y dividendos
        </span>
      )}
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block w-0 h-2.5 border-l border-dashed border-ink-3/70" aria-hidden="true" />
        Sin medición
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block w-2.5 h-2.5 rounded-xs bg-rendi-pos" aria-hidden="true" />
        <span className="inline-block w-2.5 h-2.5 rounded-xs bg-rendi-neg -ml-0.5" aria-hidden="true" />
        Ganaste / perdiste
      </span>
    </div>
  )
}

function Detalle({ medida, modo, porBroker, enPesos, fmtPlata }) {
  if (!medida) return null

  const titulo = (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[12.5px] text-ink-1 font-medium">
        {rangoSemana(medida.inicio, medida.fin)}
      </span>
      {medida.enCurso && (
        <span className="text-[10.5px] text-data-violet border border-data-violet/30 bg-data-violet/10 px-1.5 py-0.5 rounded-sm font-medium shrink-0">
          En curso
        </span>
      )}
    </div>
  )

  if (medida.estado === 'sin-medicion') {
    return (
      <div className="rounded-lg border border-line bg-bg-2/50 p-3.5 flex flex-col gap-2.5">
        {titulo}
        <div className="text-lg font-semibold text-ink-3">Sin medición</div>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Falta el cierre que abre la semana, así que no se puede calcular cuánto
          rindió. Se completa sola cuando tu cartera vuelve a medirse.
        </p>
        {medida.cerradas !== 0 && (
          <p className="text-[11px] text-ink-2 leading-relaxed border-t border-line pt-2.5">
            Lo único medible de esa semana: cerraste operaciones por{' '}
            <span className={`tabular ${colorClass(medida.cerradas)}`}>{fmtPlata(medida.cerradas)}</span>.
          </p>
        )}
      </div>
    )
  }

  const valor = valorDe(medida, modo)
  // El porcentaje del motor se mide siempre en dólares, también cuando el
  // selector global está en Pesos (la conversión del % está limitada a mes y
  // año). Se aclara en vez de esconderlo: el número es cierto, lo que cambia es
  // en qué moneda está medido.
  const pct = modo === 'abiertas' || medida.pct == null
    ? null
    : `${medida.pct >= 0 ? '+' : ''}${medida.pct.toFixed(2).replace('.', ',')}%${enPesos ? ' en dólares' : ''}`

  return (
    <div className="rounded-lg border border-line bg-bg-2/50 p-3.5 flex flex-col gap-2.5">
      {titulo}

      <div>
        <div className={`text-2xl font-semibold tabular leading-none ${colorClass(valor)}`}>
          {fmtPlata(valor)}
        </div>
        {pct && <div className="text-[11px] text-ink-3 tabular mt-1.5">{pct}</div>}
      </div>

      {medida.estado === 'quieta' && (
        <p className="text-[11px] text-ink-3 leading-relaxed">
          {medida.cerradas !== 0
            /* El motor marca la semana como sin actividad mirando las operaciones
               cerradas, y cobrar un dividendo no es una: sin esta rama, la tarjeta
               decía "ni operaciones cerradas" con el monto de ese dividendo
               impreso dos renglones más abajo. */
            ? 'Semana tranquila: lo que se movió vino de lo cobrado, no de operaciones.'
            : 'Semana sin movimientos: ni operaciones cerradas ni cambios de fondo en el valor de la cartera.'}
        </p>
      )}

      {modo === 'todo' && !porBroker && (
        <dl className="flex flex-col gap-2 border-t border-line pt-2.5">
          <Fila
            texto="Posiciones abiertas"
            valor={medida.abiertas}
            tono={medida.abiertas > 0 ? 'bg-rendi-pos' : medida.abiertas < 0 ? 'bg-rendi-neg' : 'bg-ink-3'}
            fmtPlata={fmtPlata}
          />
          <Fila
            texto="Ventas y dividendos"
            valor={medida.cerradas}
            tono={medida.cerradas > 0 ? 'bg-rendi-pos/40' : medida.cerradas < 0 ? 'bg-rendi-neg/40' : 'bg-ink-3/40'}
            fmtPlata={fmtPlata}
          />
        </dl>
      )}

      <p className="text-[11px] text-ink-3 leading-relaxed border-t border-line pt-2.5">
        {/* ⚠️ Las TRES ramas son necesarias. Con un broker elegido `modo` está
            forzado en 'todo', así que sin la rama del medio esta nota explicaba
            una resta que el motor no hace en ese estado — y contradecía al
            cartel que está tres centímetros más arriba. */}
        {modo === 'abiertas'
          ? 'Sólo lo que se movió el precio de lo que seguís teniendo.'
          : porBroker
          ? 'De un broker solo se puede medir lo que cerraste: el valor de lo que tenés se mide sobre la cartera completa.'
          : 'Lo de las posiciones abiertas sale de restarle al total lo que dejaron las ventas, así que también recoge cualquier otro movimiento de la cuenta — por ejemplo, pesos quietos cuando cambia el dólar.'}
      </p>
    </div>
  )
}

function Fila({ texto, valor, tono, fmtPlata }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-[11px]">
      <dt className="text-ink-2 flex items-center gap-1.5 min-w-0">
        <span className={`inline-block w-2 h-2 rounded-xs shrink-0 ${tono}`} aria-hidden="true" />
        <span className="truncate">{texto}</span>
      </dt>
      <dd className={`tabular font-medium shrink-0 ${colorClass(valor)}`}>{fmtPlata(valor)}</dd>
    </div>
  )
}
