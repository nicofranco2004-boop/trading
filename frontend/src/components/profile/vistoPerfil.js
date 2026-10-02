// vistoPerfil — ¿el Tablero del perfil ya está a la vista? Lo provee
// ProfileDashboard (useAlVerse) y lo leen las tarjetas de adentro para arrancar
// SUS animaciones (el radar que crece, el punto que viaja, las barras, la
// torta, los números que cuentan) recién cuando se ven: si el tablero carga
// más abajo de la pantalla, animar al montar las terminaba antes de que nadie
// llegara. Fuera del tablero (pruebas, otra pantalla) vale true: todo quieto y
// en su lugar final.
import { createContext, useContext } from 'react'

export const VistoPerfil = createContext(true)
export const useVistoPerfil = () => useContext(VistoPerfil)

// El formato de un porcentaje que CUENTA hasta `valor`: con los mismos
// decimales que el número final (46 → "46%", 20,5 → "20,5%"), así el último
// cuadro es idéntico a lo que mostraba la tarjeta quieta.
import { pctTxt } from '../../utils/format'
export function formatoQueCuenta(valor) {
  const dec = Math.min(2, (String(valor).split('.')[1] || '').length)
  return (n) => pctTxt(n, dec)
}
