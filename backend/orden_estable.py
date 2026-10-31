"""El orden de las filas del MISMO día, igual en SQLite y en Postgres.

Las fechas de Rendi no tienen hora (`operations.date` es «2024-03-04»), así que
todo un día empata. Una consulta que ordena SÓLO por fecha deja ese empate al
motor, y los dos motores no lo resuelven igual:

  · SQLite lo resuelve sin que nadie se lo pida, y no siempre de la misma forma
    (medido el 31/10/2026, `tests/test_empate_de_fecha.py`):
      - las OPERACIONES DE UN USUARIO salen por el índice
        `idx_operations_user_date (user_id, date DESC)`, que dentro de un día va
        por número de fila. Ordenando por fecha DESCENDENTE el empate sale con
        `id` ascendente; ASCENDENTE (el índice al revés), con `id` DESCENDENTE.
      - lo que SQLite ordena DESPUÉS de leer (posiciones, objetivos, operaciones
        de todos los usuarios) queda en el orden en que lo leyó: `id` ascendente.
  · Postgres no garantiza nada: el empate sigue el orden físico de las filas, y
    puede cambiar entre dos corridas iguales.

Y hay números que dependen del empate: «promediar a la baja» compara cada compra
con la anterior; el patrón de compras que lee la IA, también. Medido: con los
mismos datos, 10 % de caída en SQLite y 18,18 % en Postgres.

POR QUÉ ESTE ORDEN Y NO OTRO. Es el que producción muestra HOY, en SQLite: así la
mudanza no cambia ningún número. Que sea el CORRECTO es otra pregunta —un día sin
hora no tiene un orden verdadero— y no se decide acá (memoria
`project_orden_filas_desempate`).

Toda consulta que ordene por fecha sobre una tabla de la plata pasa por acá o
desempata a mano; `tests/test_orden_con_desempate.py` da rojo si no.
"""


def operaciones_por_fecha(desc: bool = False, alias: str = "") -> str:
    """`ORDER BY` de las operaciones DE UN USUARIO por fecha, con el desempate que
    da SQLite por su índice `(user_id, date DESC)`: el `id` va al revés que la
    fecha."""
    p = f"{alias}." if alias else ""
    return f"{p}date DESC, {p}id ASC" if desc else f"{p}date ASC, {p}id DESC"


def por_fecha(columna: str = "date", desc: bool = False, alias: str = "") -> str:
    """`ORDER BY` por fecha de todo lo demás: el empate por `id` ascendente, que
    es lo que da SQLite cuando ordena después de leer en orden de fila."""
    p = f"{alias}." if alias else ""
    return f"{p}{columna} {'DESC' if desc else 'ASC'}, {p}id ASC"
