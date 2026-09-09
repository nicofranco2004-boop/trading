# Prompt — los 27 tests en rojo de `main`

## Contexto

Rendi es una app de seguimiento de carteras de inversión multi-broker para Argentina. Backend
FastAPI + SQLite (con soporte Postgres detrás de `USANDO_PG`), frontend React, corre en Railway.

**La suite de tests de `main` tiene 27 tests en rojo.** Están así hace al menos varios días, en
producción, y nadie los mira. El costo real no es que fallen: es que **con 27 en rojo la suite ya
no sirve para frenar nada** — cuando alguien rompa algo de verdad, va a entrar tapado entre el
ruido. Tu trabajo es devolverle esa capacidad.

Comando (importante, `pytest` a secas recoge también `scripts/test_*.py` y no es lo mismo):

```bash
cd backend && python3 -m pytest tests/ -q
```

Tarda ~60 s. Estado al 2026-09-08 sobre `main` (`56c26782`):
**27 failed, 3986 passed, 93 skipped, 10 xfailed.**

## Lo que ya está medido — no lo repitas

Lo corrí varias veces sobre commits distintos y comparé las listas completas de fallos, no los
totales (comparar totales me hizo sacar una conclusión falsa una vez; las listas son lo que vale):

| commit | resultado |
|---|---|
| `897b0d63` (antes de la tanda de fixes F1) | 27 failed, 3935 passed |
| `04a5736e` (después de F1, 15 commits) | 27 failed, 3979 passed |
| `56c26782` (main de hoy) | 27 failed, 3986 passed |

**Las listas de los 27 son idénticas en los tres.** La tanda F1 no rompió ninguno ni arregló
ninguno, y el commit de seguridad tampoco: los `passed` suben porque cada tanda agregó tests
nuevos que pasan. **Así que no busques el culpable en los cambios recientes: no está ahí.**

La lista completa está en `audit/_scripts/_tests_en_rojo.txt` y la salida cruda con el motivo de
cada fallo en `audit/06_tests_rojos/_salida_pytest_main.txt`.

Reparto por archivo:

| archivo | fallos |
|---|---:|
| `tests/test_events.py` | 9 |
| `tests/test_news.py` | 7 |
| `tests/test_bond_conduit.py` | 3 |
| `tests/test_billing.py` | 3 |
| `tests/test_importer.py` | 2 |
| `tests/test_cedear_usd_price.py` | 1 |
| `tests/test_billing_lifecycle.py` | 1 |
| `tests/test_backfill_recompute.py` | 1 |

## ⚠️ Hallazgo posterior: la suite NO es determinista

Medido el 2026-09-08, después de escribir lo de arriba. **El número 27 no es estable.** Una
corrida de la suite completa sobre el mismo código dio **30 fallos** en vez de 27, con la
máquina cargada (157 s contra los 58 s habituales). Los que aparecieron de más:

```
tests/test_quota_window_corte.py::DiaDieciseisTest::test_no_hace_falta_que_corra_ningun_cron
tests/test_quota_window_corte.py::HelperDelPisoTest::test_gana_la_fuente_mas_nueva
tests/test_reports_variaciones_f4.py::VariacionesF4Test::test_b1_migracion_startup_no_rompe_delta_chips
tests/test_reports_variaciones_f4.py::VariacionesF4Test::test_h7_delta_chips_netdep_con_baseline
```

Y en la misma corrida **uno de los 27 de la lista base pasó**. O sea que el conjunto varía en
las dos direcciones.

Dato que acota el problema: esos 4 **fallan siempre si se los corre solos**
(`pytest tests/test_quota_window_corte.py tests/test_reports_variaciones_f4.py`), y fallan
igual en el commit anterior — no los rompió ningún cambio reciente. O sea que **dependen del
orden**: pasan cuando otros tests corrieron antes y les dejaron estado.

`tests/test_relojes_del_conftest.py` documenta un caso parecido y ya resuelto (tres relojes de
Postgres cuyo desorden hacía variar el número de fallas con la carga de la máquina). Leelo: el
diagnóstico que está ahí escrito es el mismo que necesitás acá, y puede que la causa también.

**Esto cambia el trabajo.** No alcanza con arreglar 27 tests podridos: mientras el resultado de
la suite dependa del orden y de la velocidad de la máquina, **no se puede usar para frenar
nada**, ni siquiera con 0 en rojo. Un test que pasa por casualidad no es una red de seguridad.
Tratá el no-determinismo como el primer problema y los tests podridos como el segundo.

Para separar los dos: corré la suite tres veces seguidas y compará las **listas** de fallos, no
los totales (comparar totales me llevó a una conclusión falsa; las listas son lo que vale).

## La hipótesis principal, con la evidencia que la sostiene

**Buena parte de la suite depende del calendario y se pudre sola con el paso del tiempo.**
No está confirmada para los 27; está confirmada para dos grupos:

**1. `test_events.py` — el comentario lo dice solo.** La línea 136 dice textualmente:

```python
# 30 días: sólo el cercano (de 2026-06-01, asumiendo today ~2026-05-12)
```

Los tests siembran eventos con fechas fijas de mayo a julio de 2026 (19 fechas hardcodeadas en
el archivo) y después consultan una ventana de "próximos 30 días". **Hoy es 2026-09-08**: la
ventana ya pasó de largo por encima de todos los eventos sembrados. De ahí salen los
`IndexError: list index out of range`, `Lists differ: [] != ['AAPL']` y
`'2026-06-01' not found in set()`.

**2. `test_bond_conduit.py` — el bono siguió amortizando.** El test espera `720.0` y obtiene
`640.0`. El comentario de la línea 103 explica el número: *"el genuino 1000 → amortizado a 720
(R=0.72 a jun-2026)"*. El AL30 amortiza con el calendario: a septiembre el residual ya no es
0,72 sino 0,64. El test congeló un factor que se mueve.

**Verificado y descartado:** en el repo **no existe** ningún mecanismo para congelar "hoy" en los
tests — no hay `freezegun` ni `time-machine` en `requirements.txt` y ningún test parchea
`date.today`. (`RENDI_TEST_RELOJ_PRUEBA` existe pero es de *timeouts* de Postgres, no de fecha:
no te sirve, no pierdas tiempo ahí.)

Los otros grupos (`test_news`, `test_billing`, `test_importer`) **no los caractericé.** Algunos
motivos sugieren otra cosa: `KeyError: 'reused'`, `502 != 200`, `'IMPUESTO' != 'FEE'`,
`AssertionError: 0.15871691703796387 not greater than 0.25 : too fast — workers not capped?`
(este último huele a test sensible a la velocidad de la máquina, o sea intermitente). Empezá por
correrlos y mirar.

## Lo que NO quiero

**No actualices los números esperados.** Cambiar `720.0` por `640.0` hace desaparecer el rojo hoy
y lo trae de vuelta en tres meses, con la diferencia de que la próxima vez nadie va a saber si el
número nuevo es el correcto o el que hizo falta para que pasara. Es el parche exacto que el
`CLAUDE.md` de este repo prohíbe.

El arreglo de fondo va en una de estas dos direcciones, y quiero que me digas cuál elegís y por qué:

- **congelar el tiempo** en los tests afectados (agregar la dependencia, o un helper propio), o
- **hacer las semillas relativas a hoy** (sembrar "dentro de 15 días" en vez de "2026-06-01").

Para los bonos, ojo: el factor de amortización sale de datos reales que se mueven. Ahí la
pregunta es si el test debería fijar la fecha de valuación en vez del resultado.

**Y antes de arreglar, contestá esto:** ¿alguno de los 27 está señalando un bug real del producto
en vez de un test podrido? Un test que se pudre es molesto; un test que falla porque el código
está mal y lo estamos por silenciar es otra cosa. Separá los dos grupos antes de tocar nada.

## Reglas

- **No toques producción.** No hagas peticiones a la app desplegada. Todo local.
- **No hagas operaciones de git sobre otras ramas.** Hay más sesiones trabajando en este repo.
  Trabajá en una rama propia y no la mandes a `main` sin que te lo pidan.
- Seguí las dos reglas permanentes del `CLAUDE.md` de la raíz: arreglar el proceso y no el
  síntoma, y propagar el fix a todos los call sites. Si el mismo patrón de test podrido está en
  cinco archivos, arreglá uno y decime dónde están los otros cuatro.
- Nada de "medido" sobre algo que no ejecutaste. Si deducís, decí con qué supuestos.

## Entregable

Un informe en `audit/06_tests_rojos/informe.md` con:

1. Los 27, uno por uno: archivo, test, motivo real, y en qué grupo cae
   (**test podrido** / **bug real del producto** / **intermitente**).
2. La causa raíz de cada grupo, con la cita `archivo:línea` que la demuestra.
3. Qué arreglaste y qué dejaste, con el porqué.
4. La suite corriendo en verde, o la lista de lo que queda en rojo **con el motivo de por qué se
   deja**. Un rojo justificado y documentado es un resultado aceptable; un rojo sin explicar, no.
5. Si encontraste un bug real del producto escondido detrás de un test en rojo, eso va primero y
   en negrita: es el hallazgo más valioso que puede salir de este trabajo.
