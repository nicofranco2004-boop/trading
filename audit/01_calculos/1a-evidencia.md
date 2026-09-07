# 1A — Base de evidencia de los 15 puntos URGENTE

Auditoría de la auditoría: **de dónde sale cada magnitud reportada.**

## La corrección primero

En el resumen de la tanda usé la palabra "medido" para cifras que **no se midieron ejecutando código**. Al verificar los ocho informes, el saldo real es:

| | informes |
|---|---|
| **Ejecutaron código real** | **1 de 8** — `1a-costo-fifo.md`, único con un bloque `**Método:**` declarando que corrió los motores contra una base temporal, y único con trazas de salida (`[rebuild._replay_asset] …`) en el cuerpo |
| Sólo lectura + aritmética a mano | 7 de 8 |

Los otros siete usan la palabra "medido" para **ejemplos numéricos calculados a mano** sobre código verificado. No es lo mismo, y yo lo transmití como si lo fuera.

**Criterio usado acá:**
- **MEDIDO** = alguien ejecutó el código real y leyó la salida.
- **DEDUCIDO** = se leyó el código (cita verificada) y se calculó el ejemplo a mano.
- **DEDUCIDO (estructural)** = no hay magnitud que medir: la afirmación es que una línea existe, falta o difiere. Se verifica con `grep`, no con una corrida.

Un DEDUCIDO no es una sospecha: en todos los casos la cita fue abierta contra el código real. Pero la aritmética del ejemplo no fue ejecutada, y esa distinción importa para decidir qué se arregla primero.

---

## Los 15 puntos

### A — escriben datos falsos que quedan

| # | qué | estado | evidencia |
|---|---|---|---|
| **A-1** | snapshots: costo en pesos contado como dólares | ✅ **MEDIDO** | Deducido por 3 agentes; **ejecutado por mí** en `/tmp/repro-1a/repro_a1_a2_a3.py`. Factor real: **invested ×1.450, value ×1.359,4** (el agente dedujo ×1.360 — correcto) |
| **A-2** | `position_price_key` no mira `currency` → ticker US en vez de `.BA` | ⚠️ **mecanismo MEDIDO, magnitud DEDUCIDA** | La divergencia de símbolo está ejecutada (`'GGAL'` vs `'GGAL.BA'`). El **−US$ 695.500** del informe **no** está medido |
| **A-3** | el cron pisa la foto del browser | ✅ MEDIDO (SQL) — **y reclasificado**, ver abajo | UPSERT literal ejecutado en sqlite en memoria |
| **A-4** | el recalc borra el `capital_inicio` del usuario | DEDUCIDO (estructural) | `main.py:9639-9652` + `:9607`. No hay magnitud: o se borra o no |
| **A-5** | amortización manual guarda el cash bruto como `pnl_usd` | DEDUCIDO (estructural) | `main.py:10484` vs `:10508`. La ganancia correcta se calcula y se descarta |
| **A-6** | `reconcile-cash` divide por 1415 hardcodeado | DEDUCIDO | Default y único caller verificados. El **+7,3 %** es aritmética: `1518/1415 − 1` |
| **A-7** | `fx_to_usd = 1.0` con el P&L dividido por otro número | DEDUCIDO | Código citado literal (`main.py:11283`, `:11310`, `:11389`). El **~1.400×** es el MEP, no una corrida |
| **A-8** | `SellModal` sin `fxHist` en mobile | DEDUCIDO (estructural) | Ausencia de una prop en un JSX. El **68 %** es un escenario ilustrativo, no una medición |
| **A-9** | conversión ARS→USD importada crea capital | DEDUCIDO | El **+US$ 293 / US$ 1.000** sale de `1/1415` vs `1/1000`, a mano |

### B — salen de la app o alimentan a la IA

| # | qué | estado | evidencia |
|---|---|---|---|
| **B-1** | el Wrapped rotula «TWR» una fórmula que no lo es | DEDUCIDO | La ausencia del `0,5·F` es estructural y sólida. **+213,8 % vs +115,7 %** es composición a mano: `1,10¹²` vs `1,0667¹²` |
| **B-2** | el chat del libro sin `_es_base_de_mercado` | DEDUCIDO (estructural) | Dos call sites, uno con el filtro y otro sin. Sin magnitud |
| **B-3** | la IA recibe el P&L de por vida ×2 | DEDUCIDO (estructural) | Un `.filter()` presente en un archivo y ausente en otros dos. El ×2 es exacto **por construcción**, no estimado |
| **B-4** | `Interés PF` sin conversión ni filtro | DEDUCIDO | Los **US$ 328.767** son aritmética sobre un PF hipotético de $10M |

### C — muestran mal

| # | qué | estado | evidencia |
|---|---|---|---|
| **C-1** | `/reportes` publica un stock como flujo | DEDUCIDO | Que lea el acumulado es estructural. El **33×** depende de la antigüedad de la cuenta: es ilustrativo |
| **C-2** | `SELECT br.currency AS currency` pisa la moneda del lote | DEDUCIDO (estructural) | Un alias en un SQL |

---

## Reclasificación de A-3

Al abrir el código, **A-3 no es un bug**. Que el cron pise la foto del browser está documentado como intencional y la razón es correcta:

> `snapshots_job.py:783-784` — *"El cron SÍ pisa una foto intradía del browser: su cierre es la medición buena del día."*

Y el lado inverso también está razonado, con guard explícito en `main.py:5044-5060`:

> *"⚠️ UN CIERRE DEL CRON NO SE PISA — NI LA MARCA NI EL VALOR. […] El cierre del cron es LA medición del día."*

Como regla de producto es la correcta. **A-3 no es una causa: es lo que impide que A-1 y A-2 se auto-corrijan** cuando el browser calcula bien. Arreglado A-1, A-3 deja de importar. Lo bajo de "urgente" a "consecuencia".

**Quedan 14 puntos urgentes, no 15.**

---

## El script de reproducción

Vive fuera del repo, como pediste: `/tmp/repro-1a/repro_a1_a2_a3.py`. Como `/tmp` se purga, queda embebido acá abajo.

No toca el repo ni la base del usuario: importa las funciones **reales** desde `/tmp/rendi-main` (commit `b74f450f`) y usa una sqlite en memoria para el UPSERT.

```bash
python3 /tmp/repro-1a/repro_a1_a2_a3.py
```

### Salida

```
A-1 · A compute_broker_value_usd le falta la rama 'costo en pesos en cuenta USD'
  lote: 100 MELI (CEDEAR), invested = ARS 1.500.000, broker 'Cocos · USD', MEP = 1,450
  precio MELI.BA = ARS 16.000

                                 invested            value
  correcto (÷MEP)                1,034.48         1,103.45
  compute_broker_value       1,500,000.00     1,500,000.00

  → factor invested:    1,450.0×
  → factor value   :    1,359.4×

  ¿por qué el value queda en el costo y no en 1,103.45?
    _trust_mkt_value(mkt=1,103.45, real_cost=1,500,000) = False
    multiplo = 0.000736  (banda no-renta-fija: 0.002 .. 50)
    el guard compara USD contra PESOS → rechaza el precio REAL y cae al costo inflado.

  guard de cobertura (MIN_COVERAGE = 0.95):
    position_price_key       = 'MELI.BA'  (está en prices)
    _has_price               = True
    cobertura                = 100%  → NO bloquea, el snapshot se escribe
    y el peso de esta posición en la ponderación es 1,500,000 USD (inflado ×1,450)

A-2 · position_price_key no mira `currency`: pide el ticker US en vez del .BA
  lote: GGAL currency='ARS' alojado en 'Schwab' (broker USD genuino, sin padre AR)

    backend  position_price_key  → 'GGAL'
    frontend valuationPriceKey   → 'GGAL.BA'   (por la rama `|| costInPesos(p)`)

  → DIVERGEN: el backend cotiza el ADR de NYSE y el frontend la acción local de BYMA.

  guard con el ADR: mkt = 4,500.00, cost = 5,000.00, multiplo = 0.90
    _trust_mkt_value = True  ← DENTRO de la banda 0.002..50
    o sea: el guard NO lo rechaza. Se persiste un precio del instrumento equivocado.

A-3 · el cron pisa la foto del browser (y el browser no pisa al cron)
  1) el cron escribe (motor SIN la rama 2)      → total_value = 1,500,000.00
  2) el browser calcula bien 1.103,45 …
     pero main.py:5060-5064 NO pisa una fila source='cron' (condición en el DO UPDATE)
  3) el cron vuelve a correr y pisa de nuevo, incondicionalmente:
     → total_value = 1,500,000.00
```

### Lo que el repro demuestra que la deducción no tenía

1. **El factor de `invested` es ×1.450 exacto (= el MEP), no ×1.360.** El ×1.359,4 es el del *value*. Los dos números conviven en la misma posición y el informe sólo reportaba uno.
2. **La cadena causal completa está confirmada en una sola corrida:** costo inflado → el guard `_trust_mkt_value` calcula un múltiplo de `0,000736` → cae fuera de la banda `0,002 … 50` → **descarta el precio de mercado correcto** → persiste el costo inflado. El guard no es que "no ayude": es que **el costo corrupto lo convierte en cómplice**.
3. **El guard de cobertura del 95 % da 100 % y además pondera con el costo inflado**, o sea que esa posición pesa ×1.450 más de lo que debería en la decisión de escribir o no. Verificado ejecutando las dos closures literales.
4. **A-2 divergía de verdad**, y el guard no puede atraparlo: con el ADR el múltiplo da `0,90`, cómodamente dentro de la banda.

### El código

```python
#!/usr/bin/env python3
"""
Reproducción mínima de A-1, A-2 y A-3 de la tanda 1A.

NO toca el repo ni la base del usuario: importa las funciones REALES desde la
copia de solo lectura /tmp/rendi-main (commit b74f450f) y, para A-3, arma una
sqlite en memoria con el mismo esquema mínimo.

Uso:  python3 /tmp/repro-1a/repro_a1_a2_a3.py
"""
import sys, os, sqlite3, re

BACKEND = '/tmp/rendi-main/backend'
assert os.path.isdir(BACKEND), "Falta /tmp/rendi-main. Recrear con: git archive b74f450f | tar -x -C /tmp/rendi-main"
sys.path.insert(0, BACKEND)

from snapshots_job import (
    compute_broker_value_usd, position_price_key, _broker_name_sets, _trust_mkt_value,
)

def h(t): print('\n' + '=' * 78 + '\n' + t + '\n' + '=' * 78)

# ── Escenario común ────────────────────────────────────────────────────────
MEP = 1450.0
BROKERS = [
    {'id': 1, 'name': 'Cocos',       'currency': 'ARS', 'parent_broker_id': None},
    {'id': 2, 'name': 'Cocos · USD', 'currency': 'USD', 'parent_broker_id': 1},
    {'id': 3, 'name': 'Schwab',      'currency': 'USD', 'parent_broker_id': None},
]
ars_names, ar_usd_names = _broker_name_sets(BROKERS)

# ═══ A-1 ═══════════════════════════════════════════════════════════════════
h("A-1 · A compute_broker_value_usd le falta la rama 'costo en pesos en cuenta USD'")

POS = {'asset': 'MELI', 'asset_type': 'CEDEAR', 'is_cash': 0,
       'currency': 'ARS',            # ← el lote se pagó EN PESOS
       'quantity': 100, 'invested': 1_500_000.0, 'commissions': 0,
       'price_override': None, 'broker': 'Cocos · USD'}
PRICES = {'MELI.BA': 16_000.0}       # precio local en ARS

# … (script completo en /tmp/repro-1a/repro_a1_a2_a3.py)
```
