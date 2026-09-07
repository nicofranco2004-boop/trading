# Auditoría de Snapshots Job - Análisis de Consistencia

## PROBLEMA 1: Desfase en `net_deposited` del snapshot inicial vs live

**Ubicación:** 
- `snapshots_job.py:540` - Cálculo de `net_deposited` en snapshot
- `reporting/builder.py:311-325` - Cálculo de `end_netdep` cuando período es actual

**Descripción:**
En `take_snapshot_for_user()` línea 540, el `net_deposited` se calcula como:
```python
net_deposited = compute_net_deposited(monthly)
```

Donde `monthly` se carga en línea 458-462 del snapshots_job.py:
```python
monthly = [dict(r) for r in conn.execute(
    "SELECT broker, year, month, capital_inicio, deposits, withdrawals "
    "FROM monthly_entries WHERE user_id=?",
    (uid,)
).fetchall()]
```

Esto trae TODOS los monthly_entries del usuario, luego `compute_net_deposited()` en línea 268-282 filtra solo los con `broker='global'` y suma:
```python
baseline + flows
```

**El problema:** Cuando se usa el snapshot en un período en curso (day/week), la línea 311-325 de `builder.py` calcula `end_netdep` así:

```python
if live_value is not None and is_period_current(...):
    row = conn.execute(
        "SELECT COALESCE(SUM(deposits - withdrawals), 0) AS net FROM monthly_entries WHERE user_id=? AND broker='global'",
        (uid,),
    ).fetchone()
    end_netdep = float(row["net"] or 0)
```

**¿Dónde está la inconsistencia?**
- El snapshot persiste `net_deposited` INCLUYENDO `capital_inicio` (baseline)
- El reporte en vivo calcula `end_netdep` SOLO con SUM(deposits - withdrawals), SIN baseline

Si el usuario tiene `capital_inicio=5000` y luego deposita 1000:
- Snapshot: net_deposited = 5000 + 1000 = 6000
- Reporte live: end_netdep = 1000 (sin baseline)
- **Delta desfasado de +5000 USD**

## PROBLEMA 2: `include_baseline` inconsistente en `compute_net_deposited_db`

**Ubicación:**
- `snapshots_job.py:226` - Función `compute_net_deposited_db` con parámetro `include_baseline`
- `reporting/builder.py:167-174` - Llamada a `fetch_cum_deposits_until` que delega en `compute_net_deposited_db`

**Descripción:**
La función `compute_net_deposited_db()` tiene:
```python
def compute_net_deposited_db(conn, uid: int, *,
    as_of_date: Optional[str] = None,
    broker_filter: str = "global",
    include_baseline: bool = True) -> float:
```

Pero en `reporting/builder.py:167-174`:
```python
def fetch_cum_deposits_until(conn, uid: int, end_date: str, broker_filter: str = "global") -> float:
    from snapshots_job import compute_net_deposited_db
    return compute_net_deposited_db(
        conn, uid,
        as_of_date=end_date,
        broker_filter=broker_filter,
        include_baseline=False,  # <-- ¡SIN baseline!
    )
```

**¿Cuál es el problema?**
- Los snapshots se persisten CON baseline (`include_baseline=True` implícito)
- Los reportes usan `include_baseline=False` para mantener "semántica histórica"
- La métrica `delta_pct_over_contrib` (línea 344-345) usa `cum_aportado` (sin baseline)
- Pero los flows en week/day derivan de diff de snapshots (con baseline)

**Inconsistencia:** En un período sub-mensual (semana/día), los flows calculados en línea 329-330 pueden no reflejar bien los cash flows reales si hay baseline sin contabilizar.

## PROBLEMA 3: `total_invested` del snapshot vs cálculo live

**Ubicación:**
- `snapshots_job.py:537` - Persiste `total_invested` en snapshot
- `snapshots_job.py:615-621` - Calcula `total_value` en `compute_live_portfolio_value`

**Descripción:**
En el snapshot se persisten DOS valores:
1. `total_value` - valor ACTUAL de las posiciones (price × qty)
2. `total_invested` - cost basis acumulado (sum de invested + commissions)

Pero en `compute_live_portfolio_value()` (línea 573-627) SOLO se devuelve `total_value`, nunca `total_invested`.

**¿Dónde rompe?**
Si el frontend o algún reporte usa `total_invested` del snapshot para calcular `unrealized_pnl = total_value - total_invested`, pero luego el live_value usa un `total_invested` diferente (porque hubo transacciones entre el snapshot y ahora), el PnL estará desfasado.

**Ejemplo:**
- Snapshot ayer a las 22h UTC: total_value=10000, total_invested=8000, unrealized=2000
- Hoy 10h UTC: compré NVDA por 500 USD
  - Nueva total_invested = 8500 (si recalculamos)
  - Pero el snapshot sigue diciendo total_invested=8000
  - Si live_value=10100, unrealized aparecería como 10100-8000=2100 (erróneo, debería ser 1600)

## PROBLEMA 4: Cobertura de precios y fallback a last_known_price

**Ubicación:**
- `snapshots_job.py:488` - `apply_last_known_prices()` completa precios None
- `snapshots_job.py:516-526` - Gate de cobertura mínima 95%

**Descripción:**
Si yfinance no devuelve precio hoy pero sí lo hizo ayer:
- Se persiste el precio de AYER en el snapshot de HOY
- Esto NO es incorrecto per se, pero introduce un lag de 1 día en la valuación
- Para un activo que subió 10% en la madrugada (después del cierre de yfinance), el snapshot de mañana seguirá con el precio de ayer

**¿Dónde rompe?**
- Usuario ve delta intraday INFLADO (mañana, cuando el snapshot corre, el precio habrá bajado de nuevo)
- Para CEDEARs/BYMA especialmente (cierre 17h ARS), yfinance puede tardar horas en actualizar

## PROBLEMA 5: `fx_to_usd_blue` no se usa en `compute_live_portfolio_value`

**Ubicación:**
- `snapshots_job.py:554` - Persiste `fx_to_usd_blue` en snapshot
- `snapshots_job.py:614` - En `compute_live_portfolio_value()` se pasa el `tc_blue` actual, no el histórico

**Descripción:**
El snapshot persiste el tc_blue de la fecha para que después el frontend pueda convertir el valor en ARS usando la cotización histórica.

Pero en `compute_live_portfolio_value()` (línea 614), se usa el `tc_blue` ACTUAL (pasado como parámetro):
```python
tc_cedear = _user_tc_cedear(conn, uid, tc_blue)  # tc_blue ACTUAL
```

**¿Dónde rompe?**
Cuando el usuario mira el dashboard en ARS:
- Snapshot histórico: se convierte con fx_to_usd_blue CORRECTO (tc de esa fecha)
- Live value actual: se convierte con tc_blue ACTUAL
- Si el dólar subió 5% hoy, el delta en ARS se infla erróneamente

**Solución requerida:** Pasar el tc_blue histórico al calcular live_value si la comparación es intraday, o aclarar que live_value NO es históricamente correcto en ARS.

## PROBLEMA 6: Serialización `holdings_json` no se persiste en snapshots

**Ubicación:**
- `snapshots_job.py` - NO hay referencias a `holdings_json`
- `snapshots.py` schema - NO tiene columna `holdings_json`

**Descripción:**
Si se agrega `holdings_json` (array de holdings en JSON) al snapshot en el futuro, cambiaría:
- El storage: snapshot.total_value se recalcularía desde holdings_json
- Pero el current code calcula total_value antes de persistir holdings_json
- Si la serialización muta el orden o estructura, el recálculo daría otro total_value

**¿Es problema ahora?** NO, pero es un riesgo si se implementa sin cuidado.

## Resumen de Concerns

| Severity | Issue | Impact |
|----------|-------|--------|
| HIGH | `net_deposited` baseline inconsistency | Flows en day/week período pueden estar +5000 USD si hay baseline |
| HIGH | Live `end_netdep` sin baseline vs snapshot con baseline | P&L período actual diverge de esperado |
| MEDIUM | `total_invested` snapshot no se recalcula live | Unrealized PnL puede estar off si hay trades entre snapshot y now |
| MEDIUM | Cobertura mínima 95% silenciosamente usa last_known_price | Delta intraday puede estar lagueado 1 día para algunos activos |
| MEDIUM | `fx_to_usd_blue` no afecta live_value | ARS delta histórico no es comparable (mezcla blue actual + histórico) |
| LOW | `holdings_json` serialización futura | Risk de inconsistencia si se agrega sin recalcular total_value |

