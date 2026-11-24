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

## Del control a mitad de camino (revisión adversarial de E4–E6)
Arreglado en el commit «E4-E6 — arreglos del control a mitad de camino» (detalle en su mensaje y en las pruebas):
#16 desde el mismo día en B; el precio cargado sólo a las patas de B que reciben y en la moneda en que lo lee
Cartera; la «· USD» suelta con movimientos frena (409); el turno del confirmar en los dos motores; la etiqueta y la
fecha del precio las decide el servidor; piso de cantidad (1e-6); el capital final del MES EN CURSO lleva lo que
cambia el recálculo (patas de pase y de conversión); las pruebas de «la vista previa no escribe» miran la sentencia
(`tests/_sentencias.py`).

Pendientes que quedan para las etapas siguientes:
- **E7**: el deshacer corre `_cascade_after_movement_delete` → el recálculo ya deja al día el capital del mes en
  curso (no hace falta nada aparte). Filtrar `traspasos_a_mano WHERE id=? AND user_id=?`; tomar `_tomar_turno` (no el
  de la puerta) antes de leer. `fila_destino_raw_row_id` y `fila_origen` ya están fijados por prueba (PaseTotal).
  `precio_cargado_en_destino.brokers_destino` ahora son exactamente las patas que lo recibieron.
- **E8**: C.11 lado B sigue con `date < fecha` para lo que llega DESPUÉS del pase (correcto: el persister y el rebuild
  consumen igual). El borde «mismo día» es sólo para lo que ya estaba (B.6 #16).
- **E11**: `migrate_user_fx` / `_auto_migrar_fx_post_import` no toman el turno: agregarlo junto con `revaluar_patas`
  (el turno solo no arregla nada: una migración posterior al pase igual deja las patas con números v1). Cualquier
  import posterior pasa sola una cuenta v1 a v2 (medido por el revisor contable): `revaluar_patas` tiene que estar
  antes de prender el interruptor. `receta.precio.fecha` ya es siempre una fecha válida.
- **Integración / pantalla**: `traspaso_neto_pesos` de 'global' suma `valor_ars` de todas las patas (también las de
  lotes en dólares, que en las filas por broker van a `traspaso_usd_con_dia`); sólo se nota con una pata huérfana.
  Los avisos nuevos: «Vamos a sumar tu broker «X · USD» como la cuenta en dólares de X.» y el 409 de la pata suelta.

## De E7 (deshacer, GET /traspasos y las guardas)
Hecho: `POST /api/positions/traspaso/{id}/deshacer` (anda con el interruptor apagado; vivo, incompleto
de cualquier lado y con los dos borrados), `GET /api/positions/traspasos` ({habilitado, traspasos} con
estado vivo/incompleto/desfasado, puede_deshacer, motivo, aviso), D.3.4 en `revert_batch`, D.10 #1–#15
(la #16 del importador es de E8), D.19, la regla C4 en `sell_position_fifo` y `pase_que_cambia` (C.11)
ya escrita y usada por las puertas de borrado y de deshacer-borrado.
Pendientes que deja para las etapas siguientes:
- **E8**: `pase_que_cambia(conn, uid, filas)` ya existe (lado A y lado B, `excluir`, devuelve
  {traspaso_id, lado, fecha, contraparte, asset, broker, op, fecha_fila, mensaje}); falta llamarla en
  `import_confirm` (D.10.16) DESPUÉS de `filas_ya_traspasadas` (si no, frena el Débito que el antiduplicado
  tiene que omitir) y en `run_preview` (`cambian_un_pase`). `MSG_IMPORT_CAMBIA_UN_PASE` está definido.
  El deshacer ya lee `omitidas_json` [{batch_id, row_index, lado}] (C.8 #2): E8 sólo tiene que escribirlo.
  Un SELL importado en B con fecha anterior a la llegada todavía lo consumiría el persister desde la
  tabla de hoy: lo frena C.11 lado B en el confirm (E8).
- **E9**: Movimientos tiene que poner `traspaso_id`, `contraparte` y `estado` en las filas del pase (el
  botón «Deshacer pase» de la pantalla los usa); `traspasos_vivos` ya calcula `estado`.
- **E10**: `marcar_desfasados` → `desfasado_at`/`desfasado_motivo`; GET ya los muestra (`aviso`).
- **E11**: el deshacer no recalcula V ni C: si `revaluar_patas` cambia la receta, el deshacer no se entera
  (no los usa); sí usa `receta.lotes[].invested/commissions` (no dependen del dólar).
- **Antes de volver atrás un deploy (G.3)**: apagar el interruptor y deshacer los pases vivos
  (`SELECT id, user_id FROM traspasos_a_mano WHERE deshecho_at IS NULL`); el deshacer no mira el interruptor.

## De E8 (antiduplicado, freno de imports y omitidas)
Hecho: `pipeline.repeticiones` / `filas_repetidas` (la deduplicación única: huella ∪
`traspaso_a_mano.filas_ya_traspasadas`; el pase va PRIMERO, porque el «Débito» del día
del pase tiene la huella de la SELL del pase y lo omitido por el pase tiene que quedar
anotado), usada por la vista previa (lista + cruce automático, D.6 `ya_traspasadas`),
`already_imported_row_indices` y el confirm (siempre, también con `include_duplicates`).
`preview_payload`: `ya_traspasados`, `cambian_un_pase` (UN objeto con `mensaje`, o
null: la pantalla lo trata como objeto y bloquea con cualquier valor verdadero) y
`avisos_de_pases` (nuevo; la pantalla todavía no lo muestra). `list_batches[].traspaso`
= {id, asset, cantidad, lado, contraparte, estado (vivo|incompleto|desfasado|deshecho)}.
Confirm: `_antiduplicado_del_confirm` + `traspaso_a_mano.freno_del_import` (frenos de
la ventana 4–60 días primero, después `pase_que_cambia` con `MSG_IMPORT_CAMBIA_UN_PASE`)
+ `anotar_omitidas`, todo dentro de la transacción; la respuesta suma
`omitidas_por_pases`.
Pendientes que deja:
- **Integración / pantalla**: `duplicate_row_indices` incluye las filas del pase (lo
  pide D.2.3): el asistente las muestra también en «filas ya estaban importadas».
  `avisos_de_pases` no se dibuja. La vista previa de la FOTO de tenencia (otro camino
  en main) no trae `cambian_un_pase`: el confirm frena igual (409).
- **En duda (no es de la spec)**: editar en grupo el precio promedio o el tipo de
  cambio reescribe las COMPRAS vinculadas del registro (también la del lote partido
  por un pase) y no pasa por `pase_que_cambia`; lo vería el detector de E10.

## De E9 (Movimientos, el CSV de transacciones y las comisiones)
Hecho: `GET /api/movements` saltea las compras y ventas internas del pase
(`traspaso_a_mano.es_fila_interna_del_pase`: BUY/SELL con `traspaso_id`) y muestra las
dos patas (`main._movimiento_de_pata_de_pase`: `amount_usd` = V, `fx_to_usd` =
V_ars / V, `unit_price` = V en la moneda de los lotes / cantidad, `fees_usd` 0,
`source` 'traspaso', `traspaso_id`, `borrable: False`, `contraparte`, `estado`); la FEE
del gasto suma `traspaso_id` y `borrable: False`; la compra original de cada lote
cargado a mano que salió (`trp-{pase}-{k}`, `main._movimiento_de_compra_pasada`, con
`traspaso_id`, `borrable: False`, `source` 'traspaso') con la MISMA cuenta que una
posición manual (`main._compra_a_mano_en_usd`, unificada). `transactions.csv`:
«TRASPASO (SALE)/(ENTRA)» con monto en la moneda de los lotes y las notas «pasaron a
X / llegaron desde X · costo original US$ C»; sin la VENTA ni las COMPRAS internas; la
compra pasada como COMPRA. `/api/insights/commissions` y el diagnóstico de admin
igual antes y después. `DELETE /api/movements/trp-…` → 409 `MSG_DESHACE_EL_PASE`.
Pendientes que deja:
- **Integración / pantalla**: las filas `trp-` llevan `traspaso_id` (lo pidió el
  orquestador), así que `esDeUnPase` de `components/operations/shared.js` las cuenta en
  el filtro «Pases» y en su número (el comentario y `moverDeBroker.test.js` suponen
  que vienen SIN `traspaso_id`). Decidir: excluir `source === 'traspaso'` /
  `id` `trp-` en `esDeUnPase`, o sacarles `traspaso_id` en el servidor.
- `count` de `/api/insights/commissions` sube 1 cuando se pasa PARTE de un lote cargado
  a mano (la compra queda en dos renglones: lo que quedó y lo que se pasó); el total no
  cambia. Insights muestra «promedio por operación» = total / count.
- **E10**: Movimientos ya pasa `estado = 'desfasado'` si `desfasado_at` está puesto.
- **E11**: Movimientos y el CSV leen `valor_usd`/`valor_ars`/`costo_usd` de las filas:
  `revaluar_patas` tiene que reescribir las dos patas (nada que cambiar acá).

## De E10 (el detector de pases desfasados)
Hecho: `traspaso_a_mano.marcar_desfasados(conn, uid, replay)` corre en las DOS
reconstrucciones (`rebuild_fifo_after_import` y `rebuild_pair_asset`, después de
escribir, dentro de su SAVEPOINT y en un punto de guardado propio: si falla, lo
anota y la reconstrucción sigue). Todos los escritores que rearman lotes pasan por
ellas: el confirm del importador y Wallbit, `recompute_user` (backfill),
`migrate_user_fx`, los borrados (`_delete_operation_cascade`,
`_delete_position_cascade`, `_delete_asset_history_cascade` y sus deshacer) y el
deshacer del pase. Sin pases en el replay no consulta nada.
- **Lado A ('origen')**: lo que la salida del pase se llevó del registro
  (`replay["traspasos"][tid]`) contra los lotes IMPORTADOS de la receta, con la MISMA
  comparación que la comprobación en seco antes de escribir (`_coinciden`, C.2.6).
  Desvío de la spec: compara contra la receta y no contra las COMPRAS del lote de B
  (son los mismos números; la receta sirve también con B borrado, donde las compras de
  B ya no están vivas y la regla literal marcaba en falso).
- **Lado B ('destino')**: una semilla del replay de B ANTERIOR a la llegada, fabricada
  por una venta (no de otro pase) ESCRITA DESPUÉS del pase (id de su fila mayor que el
  de las filas del pase, la misma regla de «posterior» que C.8 #3). Desvío de la spec:
  la regla literal («una semilla anterior a la llegada») marcaba en falso a quien ya
  tenía, ANTES de hacer el pase, una venta de B sin compras (archivo de B que empieza
  tarde). El replay suma `semillas_detalle` (`semillas` queda igual).
- Desmarca sólo si el lado que acaba de mirar vuelve a cuadrar y el motivo era ese lado.
- Deshacer un desfasado por 'origen' con A no reconstruible (se cargó algo a mano del
  activo en A después) frena con `MSG_DESFASADO_CON_A_MANO` (la salida: borrar lo
  cargado a mano; con A a salvo el deshacer la rearma desde el registro).
- Las pruebas: `_rebuild()` del arnés afirma qué pases quedaron marcados (ninguno salvo
  los que la prueba desfasó): toda prueba que rearma con pases sanos es también una
  prueba de que no hay falsos.
Pendientes que deja:
- **E11**: `revaluar_patas` no cambia lo que compara el detector (cantidades y montos en
  la moneda de los lotes, no en dólares). Un `tc_mode` en la edición de grupo de A
  reescribe `tc_compra` de la compra del archivo: C (en dólares) de las patas queda con
  el dólar viejo y el detector NO lo ve (no compara dólares). Si `revaluar_patas`
  recalcula C desde la receta, usa el `tc_compra` de la foto (el viejo).
- Un pase desfasado por un lado que después también deja de cuadrar del otro queda con
  el primer motivo; si el primero vuelve a cuadrar, se desmarca y el otro lado se
  marca recién en el próximo rearmado de ESE par.
- El lado B sólo se mira cuando el par de B tiene alguna venta (`rebuild_fifo_after_import`
  saltea los pares sin ventas; `rebuild_pair_asset` corre siempre). Sin ventas en B no
  hay semillas, así que no se pierde nada.
