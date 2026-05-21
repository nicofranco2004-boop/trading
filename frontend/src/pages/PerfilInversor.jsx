// PerfilInversor — página dedicada para el test de 7 preguntas que alimenta
// el Coach IA. Antes vivía en /config junto al cambio de contraseña; lo
// movimos a su propia ruta dentro de "Personal" porque tiene entidad propia
// como configuración del modelo de usuario (no es un setting administrativo).

import PageHeader from '../components/PageHeader'
import InvestorProfileForm from '../components/InvestorProfileForm'

export default function PerfilInversor() {
  return (
    <div className="page-shell max-w-3xl">
      <PageHeader
        eyebrow="Personal / Coach IA"
        title="Perfil de inversor"
        subtitle="7 preguntas para que el Coach IA te conozca mejor. Las respuestas viajan al prompt cuando le hablás al modelo — no se comparten con nadie."
      />
      <div className="border border-line/60 bg-bg-1 rounded-lg mt-4">
        <InvestorProfileForm />
      </div>
    </div>
  )
}
