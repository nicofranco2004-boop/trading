// CabeceraPublica — el encabezado de las páginas que también ve un visitante
// sin sesión (Guía y Blog): el logo y, a la derecha, los enlaces que cada
// página pasa como hijos (Planes, Iniciar sesión, Probar gratis…).
//
// Con la sesión abierta esas mismas páginas se dibujan ADENTRO de la app (con
// el menú lateral o la barra del celular), y el encabezado sobraba: repetía el
// logo y le ofrecía "Iniciar sesión" o "Probar gratis" a quien ya estaba
// adentro (tocarlo lo llevaba al Inicio). Estaba copiado en las cuatro páginas;
// ahora es esta pieza y la regla vive en un solo lugar.

import { Link } from 'react-router-dom'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'

export default function CabeceraPublica({ ancho = 'max-w-3xl', children }) {
  const { user } = useAuth()
  if (user) return null
  return (
    <header className="border-b border-line">
      <div className={`${ancho} mx-auto px-6 py-4 flex items-center justify-between`}>
        <Link to="/" className="flex items-center gap-2 hover:opacity-90">
          <RendiLogo size={28} />
          <span className="font-semibold text-base tracking-tight">rendi</span>
        </Link>
        <nav className="flex items-center gap-5 text-sm">
          {children}
        </nav>
      </div>
    </header>
  )
}
