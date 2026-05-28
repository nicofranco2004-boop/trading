// PerfilInversor — página dedicada para el test de 7 preguntas que alimenta
// el Coach IA. Originalmente vivía en /config y después tuvo su propia ruta
// dentro del grupo "Personal" del sidebar.
//
// Restructure 2026-05-27: el test pasa a ser una tab dentro de /analisis.
// La ruta /perfil-inversor sigue siendo válida (redirect a /analisis?tab=perfil
// configurado en App.jsx) para back-compat. Cuando se embebe dentro de Análisis,
// se le pasa `_embeddedInAnalisis` para no duplicar el PageHeader del wrapper.

import PageHeader from '../components/PageHeader'
import InvestorProfileForm from '../components/InvestorProfileForm'

export default function PerfilInversor({ _embeddedInAnalisis = false }) {
  return (
    <div className={_embeddedInAnalisis ? '' : 'page-shell max-w-3xl'}>
      {!_embeddedInAnalisis && (
        <PageHeader
          eyebrow="Personal / Coach IA"
          title="Perfil de inversor"
          subtitle="7 preguntas para que el Coach IA te conozca mejor. Las respuestas viajan al prompt cuando le hablás al modelo — no se comparten con nadie."
        />
      )}
      <div className="border border-line/60 bg-bg-1 rounded-lg mt-4 max-w-3xl">
        <InvestorProfileForm />
      </div>
    </div>
  )
}
