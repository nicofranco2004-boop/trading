// squarify — reparte un rectángulo en cuadros proporcionales a un peso (un
// «treemap» simplificado, sin librería externa). Lo usan el mapa de calor del
// mercado del inicio (components/home/Heatmap.jsx, peso = raíz del valor de
// mercado) y el de tu cartera en el Dashboard (components/MapaCartera.jsx, peso
// = lo que pesa cada activo en tu plata). Vivía adentro de Heatmap.jsx.
//
// Layout: tomamos los más grandes en una fila hasta que el aspect ratio se
// vuelve mejor en una nueva (algoritmo greedy).

/**
 * @param blocks  lo que se reparte (cada uno vuelve con x, y, w, h agregados)
 * @param width   ancho del rectángulo
 * @param height  alto del rectángulo
 * @param weightOf  b → peso (> 0)
 */
export function squarify(blocks, width, height, weightOf) {
  const total = blocks.reduce((s, b) => s + weightOf(b), 0)
  if (total === 0) return []
  const totalArea = width * height
  const items = blocks.map(b => ({
    ...b,
    area: (weightOf(b) / total) * totalArea,
  }))
  // Ordenar desc
  items.sort((a, b) => b.area - a.area)

  const result = []
  let x = 0, y = 0
  let availW = width, availH = height
  let i = 0

  while (i < items.length) {
    // Tomamos una "fila" en la dirección más corta
    const isHoriz = availW >= availH
    const lineLen = isHoriz ? availW : availH
    const lineThickness = isHoriz ? availH : availW

    // Acumulamos hasta que el aspect ratio empeore
    let row = []
    let rowArea = 0
    let bestAspect = Infinity

    while (i < items.length) {
      const next = items[i]
      const tryArea = rowArea + next.area
      const tryRowDepth = tryArea / lineLen
      // Aspect ratio peor de la fila
      let worst = 0
      for (const it of [...row, next]) {
        const w = isHoriz ? (it.area / tryRowDepth) : tryRowDepth
        const h = isHoriz ? tryRowDepth : (it.area / tryRowDepth)
        const ar = Math.max(w / h, h / w)
        if (ar > worst) worst = ar
      }
      if (worst < bestAspect || row.length === 0) {
        row.push(next)
        rowArea = tryArea
        bestAspect = worst
        i++
      } else {
        break
      }
    }

    // Render fila
    const rowDepth = Math.min(rowArea / lineLen, lineThickness)
    let cursor = 0
    for (const it of row) {
      const sideLen = it.area / rowDepth
      const block = {
        ...it,
        x: isHoriz ? (x + cursor) : x,
        y: isHoriz ? y : (y + cursor),
        w: isHoriz ? sideLen : rowDepth,
        h: isHoriz ? rowDepth : sideLen,
      }
      result.push(block)
      cursor += sideLen
    }

    if (isHoriz) {
      y += rowDepth
      availH -= rowDepth
    } else {
      x += rowDepth
      availW -= rowDepth
    }
  }
  return result
}
