// Reintento ante errores de INFRAESTRUCTURA (no del backend): el gateway no
// pudo hablar con el servidor. Pasa de verdad cada vez que deployamos —el
// backend reinicia unos segundos— y también cuando estaba dormido. Al usuario le
// llegaba un críptico "HTTP 502" en medio de una importación (reporte real,
// 2026-08-08).
//
// Vive en su propio archivo para que el test pueda importar ESTA función. Antes
// api.js hacía side-effects de localStorage/window al importarse, así que el
// test se copiaba la implementación y la probaba a ella: cualquier bug del
// código real (como el de AbortError de acá abajo) pasaba los tests igual.
export const GATEWAY_ERRORS = [502, 503, 504]
export const RETRY_DELAYS_MS = [800, 2500, 5000]   // ~8s en total, cubre un reinicio

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

// ±20% de ruido sobre cada espera. Sin esto, un reinicio del backend deja a
// TODOS los clientes reintentando en el mismo instante (a los 800ms, a los
// 3,3s...): la avalancha le pega justo mientras está levantando y lo puede
// volver a tirar. Con el ruido, los reintentos se desparraman solos.
export function conJitter(ms, rnd = Math.random) {
  return Math.max(0, Math.round(ms * (0.8 + rnd() * 0.4)))
}

// Una cancelación NO es una caída de red. Cuando el que llama aborta (navegar a
// otra pantalla, un unmount, un AbortController), fetch rechaza con un
// DOMException 'AbortError' — y caía en el mismo catch que un servidor caído:
// dormía y reintentaba hasta 3 veces más. La cancelación tardaba ~8,3 segundos
// en surtir efecto y mientras tanto seguían saliendo pedidos que ya no le
// importaban a nadie.
export function fueCancelado(err, signal) {
  return err?.name === 'AbortError' || err?.code === 20 || !!signal?.aborted
}

// Reintenta `doFetch` mientras el gateway falle. SOLO para pedidos que se pueden
// repetir sin efectos: si el servidor llegó a procesar, repetir un alta
// duplicaría datos. Por eso confirm/borrar NO pasan por acá.
export async function withGatewayRetry(doFetch, { signal } = {}) {
  for (let i = 0; ; i++) {
    let res
    try {
      res = await doFetch()
    } catch (netErr) {
      // Falla de red (servidor no alcanzable): mismo tratamiento.
      if (fueCancelado(netErr, signal)) throw netErr
      if (i >= RETRY_DELAYS_MS.length) throw netErr
      await sleep(conJitter(RETRY_DELAYS_MS[i]))
      continue
    }
    if (!GATEWAY_ERRORS.includes(res.status) || i >= RETRY_DELAYS_MS.length) return res
    if (signal?.aborted) return res
    await sleep(conJitter(RETRY_DELAYS_MS[i]))
  }
}
