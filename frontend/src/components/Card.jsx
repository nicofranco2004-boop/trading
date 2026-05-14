// Card — DEPRECADO en V2 (mayo 2026).
// ═══════════════════════════════════════════════════════════════════════════
// Re-exporta Panel para mantener compatibilidad con componentes existentes
// que importan Card. Migración progresiva — los nuevos imports deben usar
// `import Panel from './Panel'` directo.
//
// API estable: mismo shape de props, mismo render.

import Panel, { PanelHeader } from './Panel'

export default Panel
export const CardHeader = PanelHeader
