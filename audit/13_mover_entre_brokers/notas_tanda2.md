# Notas que arrastra la tanda 2 (E4–E11) desde la tanda 1

Estado al empezar la tanda 2 (rama claude/mover-entre-brokers):
- Commits: 6f28f2fc E1 · bf0eaac4 E2a · abded817 E2b · 3b358296 E3 · 0bbace1d arreglos E1–E3 · af736748 E12 (pantalla completa).
- Informes completos de la tanda 1 en este mismo directorio, carpeta t1/:
  01_E1_esquema · 04_E2a · 06_E2b_motores · 07_E3_historia · 08/09/10 revisiones · 11_arreglos_servidor ·
  02_E12_pantalla · 03_revisión pantalla · 05_arreglos_pantalla.
- Suite del backend tras la tanda 1: 3 tercios en verde (≈8740 passed). Frontend: 382 archivos, 5877 passed.

## Lo que ya existe y NO hay que rehacer
- Esquema completo (A.1–A.5), ida y vuelta de las 6 columnas, tabla traspasos_a_mano, OPERATION_TYPES_INTERNOS.
- importing/tramo.py costo_y_resultado_del_tramo (única cuenta del tramo para persister y rebuild).
- Persister y rebuild entienden BUY con traspaso_id/fecha_compra (llegada) y SELL con traspaso_id (salida).
  - La salida del pase NUNCA cruza de moneda (rebuild: spill_qty=0 → semilla a precio 0 visible en `traspasos`; persister: «No alcanzan los títulos para el pase.»).
  - _cancel_conduit_pairs: filas con traspaso_id no son candidatas y cuentan en la compuerta sólo para ventas posteriores.
  - persister._fila_de_pase_sin_plata: el freno «pesos a una sub-cuenta en dólares» no frena TRASPASO_* ni la SELL transfer_out a 0 con traspaso_id (FEE y BUY siguen frenadas).
- _devolver_al_lote(conn, uid, foto, cantidad, inv, com, *, link=None) en main.py (actualiza también created_position_id si link).
- importing/traspaso_a_mano.py existe con FORMATO, raices_de_brokers, lotes_a_mano_que_salieron, llegadas_por_lote. El resto de D.7 lo agregan E5–E11.
- Historia a mercado (D.13) completa, MOTOR_VERSION 4, _tipo_de_las_compras (no MAX alfabético).
- Gancho COMENTADO `traspaso_a_mano.marcar_desfasados(conn, uid, replay)` en las dos funciones de rebuild → lo activa E10.

## Pendientes asignados a etapas de la tanda 2
- **E5**: decidir la contradicción C.1.3 (excepción: lote en pesos que vive en la pata en dólares, caso #9) contra C.1.4 segunda condición (misma moneda de cuenta en origen y destino → #22). Recomendación de la tanda 1: aplicar la segunda condición de C.1.4 SÓLO a cripto (que es su motivo) y mantener la excepción de C.1.3; el persister ya no estorba.
- **E5/E6**: `fx.py` `tiene_historia` (≈:596/633) cuenta lotes de pase como historia: revisar qué pasa si un pase llega a una cuenta sin fx_version resuelta.
- **E6**:
  - `persist_batch` atrapa PersistError POR FILA y la manda a `skipped_rows` («No alcanzan los títulos para el pase.», «Fila interna de pase sin pase.»). `aplicar_plan` tiene que exigir `skipped_rows == []` y si no, deshacer TODO (C.7) y responder el error correcto (no un 500 genérico si es un caso de usuario).
  - Guardar `fecha_compra = entry_date[:10]` (el orden H2 compara textos).
  - `billing/trial.py` (≈:930) suma `valid_rows` de lotes confirmados → un pase sumaría «operaciones cargadas» en el mail de la prueba: excluir parser_format 'traspaso_a_mano'. Revisar también las métricas de actividad del admin (billing/trial.py ≈1843/1926, main.py ≈29006/31308) y decidir/explicar.
  - Versión por HTTP de #46 (test_cuenta_manual_no_se_vuelve_reconstruible): pase y deshacer por los endpoints reales.
  - #11/#12: `_holdings_asof` valúa con costo PROMEDIO (preexistente). En una cuenta con una venta parcial previa, el global de la historia a mercado muestra un escalón el mes del pase (A valúa al promedio, B al costo real). Es preexistente: las pruebas no deben afirmar lo contrario; documentarlo.
- **E7**:
  - D.3.4 en `revert_batch` (hoy revertir un lote de pase devolvería caja por la BUY de llegada).
  - Probar `_devolver_al_lote(link=…)`: deshacer con A NO reconstruible, y después revertir el archivo original de A sin dejar el lote huérfano.
  - Regla nueva (hueco de la spec, C4 de la revisión): una venta a mano (`sell_position_fifo`) no puede consumir lotes con `COALESCE(en_broker_desde, entry_date) > fecha de la venta`; si los necesita → 409 con mensaje claro. Propagar a cualquier otra puerta que consuma lotes por fecha.
- **E10**: activar `marcar_desfasados` (D.5.5).

## Contrato que la PANTALLA (ya construida, commit af736748) espera del servidor
La pantalla se programó contra la spec. Los nombres exactos de campos los tenés que leer en:
frontend/src/utils/moverDeBroker.js, utils/resultadoDelMes.js, utils/capitalAportado.js, hooks/useMoverDeBroker.jsx,
components/cartera/MoverDeBrokerModal.jsx y VistaPreviaDelPase.jsx, components/operations/shared.js,
MovementsTable.jsx, MovementsFeed.jsx, pages/Operations.jsx, pages/Imports.jsx, components/import/ImportWizard.jsx,
components/MonthlySummary.jsx, utils/avisoBorrarBroker.js, utils/demo.js (respuestas simuladas).
Supuestos que la pantalla hace y el servidor tiene que cumplir (o, si la spec dice otra cosa, se reconcilia y se anota):
1. `GET /api/positions/traspasos` → `{habilitado: bool, traspasos: [...]}`.
2. Vista previa / confirmar: los textos con montos llevan la moneda adelante (US$, $, ARS) para que el «ojito» (taparMontos) los tape. Ej.: C.8 #4 «({n} a {costo})», el aviso «la caja queda en {monto}».
3. `preview.cambian_un_pase[]`: que traiga `mensaje` ya armado (si no, la pantalla necesita op, asset, broker, fecha_fila, fecha, contraparte, lado).
4. `list_batches[].traspaso.lado` ∈ {'salida','entrada'}.
5. `/api/monthly`: `traspaso_neto_usd` CON signo (+ entró, − salió); `traspaso_neto_pesos` (la pantalla toma valor absoluto); `puente_salida_usd`, `puente_entrada_usd`, `gasto_pase_usd`. **La fila GLOBAL debe mandar el puente NETO (o 0 cuando las dos patas viven), no las sumas crudas**: si no, /mensual global dibuja dos renglones que se anulan.
6. Movimientos: filas de pase con `traspaso_id`, `contraparte` y `estado` (vivo/incompleto/desfasado). Las compras sintéticas `trp-…` (D.9.2) con `borrable: false` y, mejor, también `traspaso_id`.
7. Capital aportado: patas `traspaso_pesos_*`, `traspaso_usd_con_dia`, `traspaso_neto_*` (ver capitalAportado.js).
Si encontrás que la pantalla supone algo distinto a lo que conviene en el servidor, NO toques el frontend en las etapas E4–E11: anotalo en tu informe en una sección «Contrato con la pantalla»; lo reconcilia la etapa de integración.

## Medición pendiente (NO la hagas: necesita OK del dueño)
- G.1 E3 / Publicación 1: medición sobre la copia de producción (R2). No se toca producción en esta tanda.
