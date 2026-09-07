# EL EJE X COMPRIME DIEZ MESES EN LA QUINTA PARTE DEL ANCHO

Sos el chat IMPLEMENTADOR. Ronda corta y de una sola cosa. **No toques datos ni cálculo**: esto
es enteramente cómo se dibuja.

---

## 1 · EL SÍNTOMA

En **Estimado · MAX**, la cuenta demo muestra el eje X así:

```
30/11   13/07   24/07   02/08   13/08   25/08
  └───────┘
  siete meses en un paso, al lado de pasos de once días
```

La parte contable (dotted) se ve como un pico casi vertical subiendo a +14 %. **No es que la
cartera saltara**: son diez meses apretados contra el margen izquierdo.

## 2 · LA CAUSA, YA LOCALIZADA — no la busques

`pages/Insights.jsx:2848`:

```jsx
<XAxis dataKey={resolucionChart === 'diaria' ? "labelDia" : "label"} ... />
```

Es un **eje de CATEGORÍA** (sin `type`), y un eje de categoría reparte los puntos **en partes
iguales por índice, ignorando la fecha**. Medido en la cuenta demo, modo Estimado · MAX:

```
59 filas en total
 11 slots  →  10 meses de historia contable   (un punto por cierre de mes)
 48 slots  →   6 semanas de mediciones diarias
```

El tiempo queda comprimido unas **40 veces** del lado izquierdo.

⚠️ Esto es un efecto secundario de la ronda anterior, y era **inevitable con ese arreglo**: al
pasar la resolución a `'diaria'` para no tirar los puntos medidos (que era el bug real, y está
bien arreglado), la serie quedó con dos densidades muy distintas conviviendo. Antes se veía
"prolijo" porque se tiraban 44 de 46 puntos. **No es una regresión a revertir: es la mitad que
falta.**

## 3 · LO QUE VAS A NECESITAR (medido, para que no lo descubras a mitad de camino)

**3.1 · La fila no tiene ninguna fecha legible por máquina.** Las claves de cada punto de
`chartData` son:

```
label ("Sep '25")   labelDia ("30/09")   estimado   solo   total   <series...>
```

Las dos son strings de presentación. Y **`labelDia` no lleva año** — en una vista multi-año
`30/09` se repite y es ambiguo. Vas a tener que agregar un campo aditivo con el timestamp
(mismo patrón que `base` en la ronda anterior: viaja en el punto, nadie más lo lee).

**3.2 · Las filas de corte vienen con TODO vacío.** Son los separadores que `cortarPorTramo`
inserta para que Recharts deje el hueco a la vista. En la cuenta demo hay tres (índices 10, 31,
33) y se ven así:

```json
{"label":"", "labelDia":"", "total":null, "Demo P/L vendido":null, "Demo estimado":null, ...}
```

En un eje de categoría ocupan un casillero y listo. **En un eje temporal necesitan una fecha**,
o rompen el orden. Decidí qué timestamp les corresponde (entre sus vecinos) y dejalo escrito.

⚠️ **Esos cortes son correctos y no se tocan.** Marcan dónde cambia la REGLA de valuación:
el corte 10 separa lo contable de lo medido, y los cortes 31/33 aíslan el `31/07` —la foto de
fin de mes del import— que cae en el medio del tramo medido. Unir `30/07` (−0,49 %, medido) con
`31/07` (+16,86 %, contable) dibujaría un salto de 17 puntos que nunca ocurrió. Es el
acantilado del bug original en miniatura, y el corte es el sistema negándose a mentirlo.

## 4 · QUÉ HACER

Que **cada punto caiga donde le corresponde en el tiempo**. La dirección natural es un eje
numérico con escala temporal (`type="number"` + `scale="time"` + `domain={['dataMin','dataMax']}`)
sobre el timestamp del §3.1, con `tickFormatter` para el texto.

No te casés con esa implementación si encontrás una mejor — **el criterio es el resultado**: que
la distancia horizontal entre dos puntos sea proporcional al tiempo entre ellos.

## 5 · 🔴 LO QUE NO SE PUEDE ROMPER

**El modo CERTERO tiene que verse igual.** Ahí todos los puntos son diarios y consecutivos, así
que un eje temporal y uno de categoría dan casi lo mismo — pero *casi* no alcanza: verificalo.
Certero es la propiedad que se viene sosteniendo bit-idéntica desde la Fase 2 y es lo que
sostiene todo el trabajo anterior.

**Y no toques el dato.** Si te encontrás editando `twr.py`, `performance.py`, el endpoint, o la
lógica de `resolucionChart` / `windowSeries` / `cortarPorTramo`, parate: el arreglo de la ronda
anterior está verificado (invariante 493/493 en el backend, filtro no-op en certero por
construcción) y esto es sólo presentación.

**Los otros dos gráficos** (`Insights.jsx:2910` y `:2971`) también usan `dataKey="label"` en eje
de categoría. **Miralos, pero no los arregles de arriba**: si sus series son de una sola
densidad, no tienen este problema y tocarlos es riesgo gratis. Si los cambiás, justificá por qué.

## 6 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura.
- ❌ NO toques `schema_pg.sql`, `mkschema.py`, `verificar_copia.py`, el hook de `estampar_base`
  en `main.py`, ni `pytest.ini`.
- ⚠️ **Respaldá antes de empezar.** Hay nueve rondas sin commitear.
- La suite corre: `python3 -m pytest tests/` (52 s), baseline **29 fallas conocidas**
  (`tests/fallas_conocidas.txt`); el hook de `conftest.py` avisa si aparece una nueva.

### Instrumento — el gráfico ya engañó a los dos chats siete veces

Entre auditor e implementador van **siete** mediciones equivocadas del mismo gráfico. Todas por
medir el **dibujo** en vez del **dato**:

1. Leer ticks con un selector de toda la página → mezcla **dos** `.recharts-wrapper` distintos.
2. Dar por bug lo que era una **sesión expirada** (403 y curvas vacías).
3. Contar vértices con `M`/`L` → Recharts dibuja con curvas `C`.
4. Contar `dots` → `DotSolo` sólo renderiza los puntos aislados.
5. Contar `C + 1` en vez de `C + M` → cada hueco abre un sub-path.
6. Contar **un solo path** → la cartera vive en dos claves (área medida + punteada contable).
7. Adivinar el nombre de las claves de la serie en vez de enumerarlas.

**Lo que sí funcionó las dos veces**: leer `chartData` del fiber de React
(`__reactFiber$` → subir por `.return` hasta el `memoizedProps.data`), o los ticks del eje
**acotados al primer wrapper**. Usá eso y enumerá las claves antes de filtrarlas.

**Datos**: `http://localhost:5199`, `demo.metricas@rendi.test` / `demo1234`. La cuenta tiene
11 puntos contables (sep-2025 → jul-2026) + 45 medidos (jul → ago-2026): el caso que exhibe el
problema. Copia de producción estampada en `.../scratchpad/pico.db`.

## 7 · CRITERIO DE SALIDA

1. En Estimado · MAX, la distancia horizontal entre dos puntos es proporcional al tiempo:
   diez meses ocupan diez meses de ancho, no la quinta parte.
2. El eje no muestra dos fechas a siete meses de distancia como si fueran vecinas.
3. **Certero se ve igual que antes** — verificado, no supuesto.
4. Los tres cortes siguen ahí y en su lugar.
5. Sin fallas nuevas; `fallas_conocidas.txt` no crece. Frontend verde.
6. **Capturas de los dos modos en `1M`, `3M`, `1A` y `MAX`**, antes y después.

## 8 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line`.
2. Las capturas del §7.6.
3. Los conjuntos de tests, antes y después.
4. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito.

## 9 · FUERA DE ALCANCE

- **El clamp de plausibilidad** — 21 de 95 alertas del asesor con pico ≥5× la cartera. Espera
  decisión del dueño.
- **La ruta de cobro sin tests**: `test_billing*.py` mockea `billing.mercadopago` pero el
  endpoint hace `from billing import rebill` (`main.py:25939`).
- `test_bond_conduit.py` — 640 donde se espera 720; el mejor candidato a bug real de las 29.
- ARS, Postgres, Fases 3 y 4.
