// Cuál de los archivos subidos es la FOTO de tenencia y cuáles son Movimientos.
// La regla de «qué es una foto» la tiene el servidor (/imports/classify-tenencia):
// acá se prueba que la pantalla le pregunte y obedezca, en especial con Cocos, que
// el 24/11/2026 cambió su portfolio (3 columnas más) y la copia que tenía la
// pantalla dejó de reconocerlo: el portfolio iba como Movimientos y el servidor lo
// rechazaba por «header distinto».
import { describe, it, expect, vi } from 'vitest'
import { separarLaFoto } from './ImportWizard'

const archivo = (name, contenido = 'x') => new File([contenido], name, { type: name.endsWith('.pdf') ? 'application/pdf' : 'text/csv' })
const MOV = 'nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n'
const FOTO_NUEVA = 'instrumento;cantidad;precio;precioAsOf;moneda;total;usedFallbackPrice;missingPrice\n'

/** Un clasificador de mentira que contesta lo que contestaría el servidor. */
function servidorQueDice(nombre, formato) {
  return vi.fn(async (fd) => {
    expect(fd.getAll('files').length).toBeGreaterThan(0)
    return nombre ? { file_name: nombre, format: formato, files: [{ file_name: nombre, format: formato }] } : { file_name: null, format: null, files: [] }
  })
}

describe('separarLaFoto', () => {
  it('Cocos: le pregunta al servidor y aparta el portfolio NUEVO (con las columnas de más) de los Movimientos', async () => {
    const movs = [archivo('movimientos_cuenta-2.csv', MOV), archivo('movimientos_cuenta-3.csv', MOV), archivo('movimientos_cuenta-8.csv', MOV)]
    const foto = archivo('portfolio_report_20261124.csv', FOTO_NUEVA)
    const clasificar = servidorQueDice('portfolio_report_20261124.csv', 'cocos')
    const r = await separarLaFoto([...movs, foto], 'cocos', clasificar)
    expect(clasificar).toHaveBeenCalledTimes(1)
    expect(clasificar.mock.calls[0][0].getAll('files').map(f => f.name)).toContain('portfolio_report_20261124.csv')
    expect(r.tenFile).toBe(foto)
    expect(r.tenFmt).toBe('cocos')
    expect(r.ccFiles.map(f => f.name)).toEqual(['movimientos_cuenta-2.csv', 'movimientos_cuenta-3.csv', 'movimientos_cuenta-8.csv'])
  })

  it('Cocos con un solo archivo: también pregunta (para poder avisar que falta el de Movimientos)', async () => {
    const foto = archivo('portfolio_report_20261124.csv', FOTO_NUEVA)
    const r = await separarLaFoto([foto], 'cocos', servidorQueDice('portfolio_report_20261124.csv', 'cocos'))
    expect(r.tenFile).toBe(foto)
    expect(r.ccFiles).toEqual([])
  })

  it('Cocos sin foto: todo va como Movimientos', async () => {
    const movs = [archivo('a.csv', MOV), archivo('b.csv', MOV)]
    const r = await separarLaFoto(movs, 'cocos', servidorQueDice(null))
    expect(r.tenFile).toBeNull()
    expect(r.ccFiles).toEqual(movs)
  })

  it('si la pregunta al servidor falla, no rompe: todo va como Movimientos', async () => {
    const movs = [archivo('a.csv', MOV), archivo('portfolio.csv', FOTO_NUEVA)]
    const r = await separarLaFoto(movs, 'cocos', vi.fn(async () => { throw new Error('sin red') }))
    expect(r.tenFile).toBeNull()
    expect(r.ccFiles).toEqual(movs)
  })

  it('Bull Market: la foto es el PDF y no hace falta preguntar', async () => {
    const pdf = archivo('tenencia.pdf')
    const xlsx = archivo('cuenta_corriente.xlsx')
    const clasificar = servidorQueDice(null)
    const r = await separarLaFoto([xlsx, pdf], 'bullmarket', clasificar)
    expect(clasificar).not.toHaveBeenCalled()
    expect(r.tenFile).toBe(pdf)
    expect(r.ccFiles).toEqual([xlsx])
  })

  it('PPI, IEB e inviu: con un solo archivo no pregunta (no hay nada que separar); con dos, sí', async () => {
    const uno = archivo('movimientos.xlsx')
    const clasificar = servidorQueDice(null)
    await separarLaFoto([uno], 'ppi', clasificar)
    expect(clasificar).not.toHaveBeenCalled()
    const foto = archivo('estado.xlsx')
    const r = await separarLaFoto([uno, foto], 'ppi', servidorQueDice('estado.xlsx', 'ppi'))
    expect(r.tenFile).toBe(foto)
    expect(r.tenFmt).toBe('ppi')
  })

  it('un broker sin foto (Binance): no pregunta nada', async () => {
    const clasificar = servidorQueDice(null)
    const r = await separarLaFoto([archivo('a.csv'), archivo('b.csv')], 'binance', clasificar)
    expect(clasificar).not.toHaveBeenCalled()
    expect(r.tenFile).toBeNull()
  })
})
