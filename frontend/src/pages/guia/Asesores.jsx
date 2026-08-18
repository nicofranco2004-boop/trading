// /guia/asesores — sección 7 del manual.
//
// Documenta SOLO lo que existe hoy en la app (relevado contra las rutas reales:
// AdvisorDashboard, AdvisorClients, AdvisorNovedades, components/advisor/* y los
// endpoints /api/advisor/*). Si se agrega una funcionalidad al asesor, actualizar acá.

import GuidePage from '../../components/guide/GuidePage'

export default function Asesores() {
  return (
    <GuidePage
      n={0}
      title="Para asesores"
      intro="Si tu cuenta es de asesor, Rendi cambia: en vez de una cartera propia ves TU LIBRO — todos tus clientes juntos. Acá está lo que es exclusivo tuyo: clientes, grupos, operación grupal, la IA del libro, alertas e informes con tu marca. Lo operativo (cargar posiciones, vender, marcar depósitos) lo hacés adentro de cada cliente y funciona igual, así que está en las secciones siguientes — y en cada una vas a encontrar un bloque violeta 'Si sos asesor' con lo que cambia para vos."
      next={{ to: '/guia/empezar', label: 'Empezar' }}
      metaTitle="Guía para asesores — Rendi"
      metaDescription="Cómo funciona Rendi para asesores financieros: tu libro, clientes, grupos, operación grupal, alertas, informes con tu marca y el brief diario."
      canonicalPath="/guia/asesores"
    >
      <h2>Qué cambia en tu cuenta</h2>
      <p>
        Con una cuenta de asesor, las mismas secciones muestran otra cosa:
      </p>
      <ul>
        <li><strong>Dashboard</strong> pasa a ser <strong>Tu libro</strong>: el total de lo que administrás, no una cartera personal.</li>
        <li><strong>Novedades</strong> pasa a ser cross-cliente: eventos y noticias de los activos de <em>todos</em> tus clientes.</li>
        <li>Aparece <strong>Clientes</strong> en el menú.</li>
      </ul>
      <p>
        Cuando <strong>entrás a un cliente</strong>, Rendi se ve exactamente como lo ve él:
        su cartera, sus movimientos, sus análisis. Arriba queda una barra que te recuerda
        en la cuenta de quién estás parado — y por dónde salir. Todo lo que hacés ahí
        adentro queda en la cuenta de ese cliente, no en la tuya.
      </p>

      <h2>Tus clientes</h2>
      <p>
        En <strong>Clientes</strong> los ves a todos con su valor de cartera y su
        rendimiento. Desde ahí podés:
      </p>
      <ul>
        <li><strong>Agregar un cliente</strong> con su email real. Le armás la cuenta vos y le cargás la cartera; él todavía no necesita entrar.</li>
        <li><strong>Invitarlo</strong> cuando quieras que tome el control: recibe un mail para reclamar su cuenta y ponerle contraseña. La cartera que le armaste ya está adentro.</li>
        <li><strong>Revocar</strong> el acceso.</li>
        <li><strong>Escribirle por WhatsApp</strong> directo desde su fila.</li>
      </ul>

      <h2>Grupos</h2>
      <p>
        Un grupo es un recorte de tu libro que se guarda y se mantiene solo. Los armás
        por condiciones, no eligiendo cliente por cliente:
      </p>
      <ul>
        <li><strong>Tienen este activo</strong> (por ejemplo, todos los que tienen AMZN).</li>
        <li><strong>Tamaño de la cartera</strong> (por ejemplo, menos de US$10.000).</li>
      </ul>
      <p>
        Son <strong>dinámicos</strong>: si mañana un cliente compra ese activo, entra al
        grupo solo. Antes de guardarlo podés ver quiénes quedarían adentro.
      </p>

      <h2>Operar sobre un grupo</h2>
      <p>
        Podés aplicar <strong>una misma operación a todos los clientes de un grupo</strong>
        de una sola vez — la compra que decidiste para ese perfil, por ejemplo. Antes de
        confirmar, Rendi te muestra a quiénes va a impactar y con qué monto en cada uno.
      </p>
      <p>
        Y si te equivocaste, la operación grupal se puede <strong>deshacer entera</strong>:
        vuelve atrás en todos los clientes a la vez, incluida la plata.
      </p>
      <p>
        También podés <strong>escribirle por WhatsApp a todo un grupo</strong>, con un
        mensaje que se personaliza para cada uno.
      </p>

      <h2>La IA de tu libro</h2>
      <p>
        A tu nivel, <strong>Rendi AI responde mirando todas las carteras de tus clientes
        juntas</strong>. Es la diferencia más grande contra la IA de un usuario, que solo
        ve una cartera.
      </p>
      <p>
        Sirve sobre todo para lo que a mano es tedioso: <strong>quién tiene qué</strong>.
        Preguntale “¿quiénes tienen AL30 y cuánto pesa en cada cartera?” y te cruza todo
        el libro. También te ordena rankings de clientes, la concentración por activo y
        qué se movió.
      </p>
      <p>
        Además podés <strong>dictarle una compra grupal</strong>: “registrale a Juan
        300.000 pesos y a Ana 400.000 del CEDEAR de Tesla a 58.900”. Te la deja armada
        para que la confirmes, igual que la operación grupal de la pantalla. Solo compras:
        las ventas van cliente por cliente desde la app.
      </p>
      <p>
        Cuando <strong>entrás a un cliente</strong>, la IA te sigue: pasa a responder con
        los datos de esa cartera. El <strong>chat libre</strong> ya viene en tu plan, en
        los dos niveles.
      </p>

      <h2>Alertas del libro</h2>
      <p>
        A tu nivel no tenés alertas de precio: tenés dos avisos, y los dos son sobre el
        libro. Están juntos en <strong>Alertas</strong>.
      </p>
      <p>
        El principal es <strong>Movimiento en la cartera de un cliente</strong>: te
        avisamos cuando la cartera de <em>cualquiera</em> de tus clientes se mueve más de
        lo que vos digas. Ponés un umbral para <strong>suba</strong> y otro para{' '}
        <strong>baja</strong>, en <strong>porcentaje</strong> (no en pesos), y podés dejar
        uno solo de los dos. Elegís si te llega por push, por mail o por los dos.
      </p>
      <p>
        Queda un <strong>historial</strong> de lo avisado, así ves qué pasó mientras no
        mirabas.
      </p>
      <p>
        El otro es el <strong>brief diario</strong>, acá abajo. Y si querés seguir un
        precio puntual de un cliente, entrá a su cuenta y creá la alerta ahí: el aviso te
        llega a vos, con el nombre del cliente adelante.
      </p>

      <h2>Informes con tu marca</h2>
      <p>
        Desde Tu libro generás el <strong>informe del período</strong> para un cliente: lo
        que pasó con su cartera en ese lapso, listo para mandar.
      </p>
      <p>
        Lleva <strong>tu marca</strong>: subís tu logo y aparece en el informe. Si no
        cargás ninguno, usa tus iniciales.
      </p>

      <h2>Brief diario</h2>
      <p>
        Un resumen de tu libro por mail, dos veces por día hábil: uno a la mañana con el
        plan del día y otro al cierre con cómo terminó. Desde{' '}
        <strong>Brief de tu libro</strong> elegís qué recibir, y podés ver una{' '}
        <strong>vista previa</strong> antes de activarlo.
      </p>

      <h2>El rendimiento de tu libro</h2>
      <p>
        Tu libro muestra el <strong>capital administrado</strong>, su detalle, y{' '}
        <strong>qué activos mueven a tus clientes</strong> — dónde está concentrado lo que
        manejás.
      </p>
      <p>
        El rendimiento se calcula con <strong>TWR</strong> (time-weighted return), que es
        el estándar para medir gestión: descuenta el efecto de los depósitos y retiros, así
        que mide <em>tus decisiones</em> y no si el cliente puso más plata. Junto al número
        vas a ver un <strong>semáforo de calidad de datos</strong>: si a un cliente le
        falta historial, el número te lo avisa en vez de mentirte.
      </p>

      <h2>Preguntas frecuentes</h2>
      <p>
        <strong>¿El cliente ve que entré a su cuenta?</strong> El cliente ve su cartera
        normal. Vos ves una barra que te indica en qué cuenta estás.
      </p>
      <p>
        <strong>¿Puedo cargarle la cartera antes de que él tenga cuenta?</strong> Sí: lo
        agregás con su email, le armás todo, y recién cuando quieras lo invitás a
        reclamarla.
      </p>
      <p>
        <strong>Si deshago una operación grupal, ¿vuelve todo?</strong> Sí, en todos los
        clientes del lote: las posiciones y el efectivo que se había movido.
      </p>
    </GuidePage>
  )
}
