# Capacidad: lo de Yahoo portado al motor nuevo — medición antes / después

30/10/2026. Repite la medición de `audit/11_capacidad_arreglos` (rama `claude/quirky-wing-89c2d8`,
24/10), ahora sobre el motor de la integración del técnico: turnos por persona (E4), `_yahoo.varios`
y 5 años de historia. «Antes» = `d475f18b` (la integración sin el port). «Después» = `cb305740`.

Cómo: la lista de la copia de producción del 16/08 (`~/Downloads/trading-2026-08-16.db`, copiada a
una base descartable y migrada por `init_db`; el original no se toca), y **la corrida nocturna de
verdad** (`velas_diarias.correr`: el orden por persona, el S&P 500 y los cambios de ratio) **dos veces
seguidas** contra Yahoo real desde la Mac. `scripts/dos_noches.py`, `scripts/lista.py`. Con
`YF_TZ_CACHE_LOCATION` en una carpeta nueva (ver la regla del caché de yfinance).

| | 24/10 motor viejo (antes → después) | 30/10 motor nuevo, antes | 30/10 motor nuevo, **después** |
|---|---|---|---|
| Pedidos a Yahoo por noche | 1.411 → 1.158 | 2.468 | **2.003** (465 no son tickers) |
| 1ª corrida: bajados | 388 → 587 | 717 | **721** |
| 2ª corrida seguida: bajados | **2 → 585** | **75** | **719** |
| 2ª: anotados «Yahoo no devolvió velas» | 1.409 → 573 | 2.393 | **1.284** (= los que de verdad no tiene) |
| 2ª: pausas por corte | — → 1 | — | 3 |
| Splits sin respuesta (cambios de ratio) | — | 860 / 844 | 865 / 863 (no se guardan: lo anterior queda) |

La lista de hoy es más larga que la del 24/10 porque la noche sigue también la lista de BYMA (E4).

**Hallazgo abierto:** los splits de Yahoo se piden DESPUÉS de las ~2.000 velas, con Yahoo ya
cortado: casi ninguno contesta (uno suelto, minutos después, sí: AAPL 5, NVDA 6, KO 8). No se
pierde nada (sin respuesta = se conservan las filas que vinieron de Yahoo, y no se guarda una lista
vacía), y al ser semanales la carga baja a ~1/7. Lo que detecta los cambios de ratio es el cociente
de las velas, de cada noche.
