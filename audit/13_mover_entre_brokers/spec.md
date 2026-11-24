# «Mover a otro broker»: especificación final (v1)

**Base.** Worktree `/Users/nicolaspussetto/Documents/trading/.claude/worktrees/mover-entre-brokers`, HEAD `8319ccab`. Los informes de mapeo se hicieron sobre `fb7b11ee`. En `backend/main.py`, todo lo que está después de la línea 34204 quedó corrido +47 líneas respecto de esos informes; acá uso las líneas del HEAD actual. Las de `importing/*`, `ledger_replay.py`, `resultado_dual.py`, `scripts/backfill_historical_mtm.py`, `reporting/*` y del frontend no cambiaron.

- **[V]** = lo leí en el código.
- **[D]** = decisión de diseño de esta especificación.

Las rutas son relativas a `backend/` salvo que digan `frontend/`. Para escribir esta versión volví a verificar en el código cada problema que marcaron los tres revisores. No edité el repo ni corrí tests. Al final hay una tabla que dice a qué sección fue cada corrección, y otra con lo que descarté o adapté y por qué.

---

## 0. Qué va a notar el usuario y resumen del diseño

**Lo que van a notar:**
1. **Una opción nueva en el menú ⋯ de cada tenencia de Cartera, en la compu y en el celular: «Mover a otro broker».** No aparece en efectivo, bonos, fondos comunes ni Wallbit.
2. **En el mes del pase, el resultado del broker de origen (A) en /mensual incluye una ganancia o pérdida de US$ (V−C), y el del destino (B) la misma con el signo al revés.** V es lo que valían los títulos ese día y C lo que costaron. Ese monto es el «puente»: no es una venta. Cada fila lo explica en una línea, y **no entra en el % de rendimiento del mes**. En el total de la cuenta se anula.
3. **El capital aportado de B sube V y el de A baja V. El aportado total no cambia.**
4. **El modal «Editar posición» ya no deja cambiar el broker, ni en la compu ni en el celular.** En su lugar hay un enlace «Mover a otro broker».
5. **Movimientos muestra filas «Pase (salió)» y «Pase (entró)» con un botón «Deshacer pase», y suma un filtro «Pases».** Las compras y ventas internas del pase no aparecen.
6. **Un archivo que trae movimientos de un activo ya pasado, con fecha anterior al pase, se frena con instrucciones.** Pasa con compras o ventas en A, o con ventas en B. Las instrucciones son: deshacé el pase, importá el archivo y volvé a moverlo.
7. **La fecha del pase hay que elegirla.** No viene puesta «hoy» por defecto.
8. **Al publicar la primera tanda, la historia a mercado de todas las cuentas se rearma una vez.** Sube la versión del motor. Hay dos casos en que la curva del pasado cambia porque hoy está mal:
   - quien vendió **a mano** un lote que había venido de un archivo: hoy la historia sigue mostrando ese papel como si no se hubiera vendido;
   - quien tiene en un mismo broker ventas importadas con un tipo de activo distinto del de las compras.

   A nadie más se le mueve un número.

**El diseño en 12 líneas:**
1. Cada pase escribe **dos `import_batches` confirmados**: uno con `broker = cuenta A` y otro con `broker = cuenta B`, los dos con `parser_format='traspaso_a_mano'`. Una tabla nueva, `traspasos_a_mano`, los une y guarda la receta para deshacer.
2. **Lote de A:**
   - para los lotes **importados**, una SELL `transfer_out` con precio 0 y monto 0 por cada tramo contiguo de la cola FIFO que vive en la misma pata;
   - una fila `TRASPASO_SALIDA` por cada par (pata de A → pata de B), con V y C;
   - la FEE del gasto, si hay. El gasto siempre sale de la caja de A.
3. Los lotes **cargados a mano** en A salen editando `positions`, antes que nada, y su foto queda en la receta.
4. **Lote de B:** una BUY por lote, con su costo, comisiones, moneda, `tc_compra`, tipo y `fecha_compra` original, y una `TRASPASO_ENTRADA` por par. Las BUY **no tocan la caja**.
5. Columnas nuevas:
   - en `import_normalized_tx`: `traspaso_id`, `fecha_compra`, `valor_usd`, `valor_ars`, `costo_usd`, `costo_nativo`;
   - en `positions`: `en_broker_desde`.
6. Las patas de capital y el puente se calculan **al leer**, dentro de los lectores de flujos y del recálculo. El global es el **neto de las patas vivas**, por traspaso. El gasto cuenta como pérdida del broker que lo paga.
7. El persister **no escribe 'Venta'** para las SELL del pase, y el rebuild tampoco. El rebuild consume los lotes por `entry_date`.
8. **El pase no corre ningún rebuild.** Antes de escribir, un replay en seco del registro de A, con la SELL planificada, tiene que consumir exactamente los lotes que el plan va a mover. Si no coincide, el pase se frena.
9. Todo pasa en **una** transacción, con los lotes de A y de B tomados antes de leer. Si una fila se saltea, todo se deshace.
10. Para deshacer:
    - se marcan los lotes `reverted`;
    - A se repone: con rebuild si A queda reconstruible, si no por el vínculo con la fila de origen;
    - después se reponen los lotes que eran cargados a mano;
    - se devuelve el gasto y se recalcula.

    Funciona también si se borró uno de los dos brokers. **No borra fotos medidas.**
11. Una sola regla, `pase_que_cambia`, frena en todas las puertas lo que reescribiría la historia anterior al pase: importar, revertir, borrar, deshacer un borrado y editar en grupo. Hay además un detector de «desfasado» que avisa en pantalla.
12. Antidoble conteo en los imports que vienen después: una función única, `filas_ya_traspasadas`, que se aplica siempre, aunque el usuario fuerce los repetidos. En el orden inverso (primero se importó el archivo de B y después se mueve), el pase se **frena con instrucciones**.

---

## A. Modelo de datos

### A.1 Columnas nuevas

| Tabla.columna | SQLite | PG (lo genera mkschema) | Significado | NULL = |
|---|---|---|---|---|
| `import_normalized_tx.traspaso_id` | `TEXT` | `text` | id del pase (= `traspasos_a_mano.id`). Va en **todas** las filas del pase: SELL, BUY, TRASPASO_* y FEE | no es de un pase |
| `import_normalized_tx.fecha_compra` | `TEXT` | `text` | fecha de compra original del lote (`YYYY-MM-DD`). Sólo en las BUY de B | igual a `date` |
| `import_normalized_tx.valor_usd` | `REAL` | `double precision` | V en USD (TRASPASO_*); el gasto en USD (FEE del pase) | — |
| `import_normalized_tx.valor_ars` | `REAL` | `double precision` | V en pesos. El mismo número en las dos patas | — |
| `import_normalized_tx.costo_usd` | `REAL` | `double precision` | C en USD, comisiones incluidas, de los lotes de ese par (TRASPASO_*) | — |
| `import_normalized_tx.costo_nativo` | `REAL` | `double precision` | Costo en la moneda de los lotes. **En TRASPASO_*:** inversión + comisiones (sale de acá el puente en pesos). **En la SELL del pase:** inversión **sin** comisiones, la misma unidad que el `gross_amount` de una BUY (la usa `_holdings_asof`, D.13) | — |
| `positions.en_broker_desde` | `TEXT` | `text` | desde qué día el lote está en ESTE broker | igual a `entry_date` |

**[D] El valor no va en `gross_amount` ni en `gross_amount_usd`:**
- el rebuild trata como venta real una SELL `transfer_out` con monto distinto de 0 (`rebuild.py:454-455`);
- `stamp_tx_gross_usd` y `fx_migrate.py:335-365` reestampan `gross_amount_usd`.

Las filas TRASPASO_* llevan `gross_amount = NULL`. Así las ignoran `_plata_de_fila_importada` (`main.py:22065`), `cash_en` (`ledger_replay.py:149`, que hace `monto<=0 → continue`) y el reestampado. [V]

**Sin índice nuevo en `import_normalized_tx`.** [D] Toda lectura por `traspaso_id` llega por `batch_id`, que ya tiene índice, o recorre las filas del usuario por `TX_VIVAS`. Los `ADD COLUMN` sin default son instantáneos en PG.

### A.2 Tabla nueva `traspasos_a_mano`

En `init_db()`, en un `executescript` propio junto a `import_mappings` (`main.py:~4537`):

```sql
CREATE TABLE IF NOT EXISTS traspasos_a_mano (
  id TEXT PRIMARY KEY,            -- secrets.token_hex(16); = import_normalized_tx.traspaso_id
  user_id INTEGER NOT NULL,
  lote_salida TEXT NOT NULL,      -- import_batches.id del lote de A
  lote_entrada TEXT NOT NULL,     -- import_batches.id del lote de B
  fecha TEXT NOT NULL,            -- fecha del pase YYYY-MM-DD
  asset TEXT NOT NULL,
  cantidad REAL NOT NULL,
  moneda TEXT NOT NULL,           -- 'ARS' | 'USD' (moneda de los lotes movidos)
  receta_json TEXT NOT NULL,
  creado_at TEXT DEFAULT (datetime('now')),
  deshecho_at TEXT,
  desfasado_at TEXT,              -- la historia cambió y el pase ya no cuadra
  desfasado_motivo TEXT,          -- 'origen' | 'destino'
  omitidas_json TEXT              -- filas de imports posteriores que se omitieron por este pase
);
CREATE INDEX IF NOT EXISTS idx_traspasos_a_mano_user ON traspasos_a_mano(user_id);
```

- No tiene `REFERENCES`, así que no aplica `test_referencias_con_indice.py`.
- **No tiene ninguna columna con «broker» en el nombre.** Así no se dispara `CadaColumnaDeBrokerSeRenombra` (`tests/test_renombre_broker_recetas.py:1274-1300`). `omitidas_json` guarda sólo ids de lote e índices de fila. [D]

**`receta_json`, versión 1.** Toda clave que guarda un nombre de broker contiene la palabra «broker». Así la reescribe `renombre_broker` (`es_clave_de_broker`, `renombre_broker.py:119-121`, que también recorre listas). [V] La clave `patas_usd_creadas` del borrador no la contenía y quedaba con el nombre viejo: se llama `brokers_usd_creados`.

```json
{
  "v": 1,
  "broker_origen": "Cocos",            // cuenta raíz A
  "broker_destino": "Balanz",          // cuenta raíz B
  "fx_version": "v2",                  // con qué regla se calcularon V y C (D.21)
  "lotes": [{
     "origen": "a_mano" | "importado",
     "lote_id": 123,                   // positions.id en A al momento del pase
     "broker": "Cocos",                // pata de A donde vivía el lote
     "broker_destino": "Balanz",       // pata de B donde llega
     "fila_origen": {"batch_id": "…", "raw_row_id": 55} | null,  // sólo importados (import_op_links)
     "fila_destino_raw_row_id": 991,   // import_raw_rows.id de la BUY en el lote de B
     "cantidad": 4.0, "invested": 120000.0, "commissions": 600.0,   // lo que se movió de ese lote
     "parcial": false,
     "foto": { ...fila completa de positions ANTES del pase: id, broker, asset, quantity, invested,
               commissions, buy_price, entry_date, currency, tc_compra, asset_type, notes,
               undo_meta_json, price_override, split_adjusted_through, en_broker_desde }
  }],
  "gasto": {"broker": "Cocos", "monto": 5000.0, "moneda": "ARS"} | null,
  "precio": {"unitario": 25000.0, "moneda": "ARS", "fuente": "cierre_del_dia", "fecha": "2026-11-20"},
  "valor_nativo": 250000.0, "valor_usd": 178.57, "valor_ars": 250000.0, "costo_usd": 92.30,
  "tc_pase": 1400.0, "tc_venta": 1400.0,
  "brokers_usd_creados": ["Balanz · USD"],
  "precio_cargado_en_destino": {"brokers_destino": ["Balanz"], "antes": null, "puesto": 25000.0} | null
}
```

**[D] Por qué hace falta la tabla además de los dos lotes:**
- la foto de los lotes cargados a mano no tiene otro lugar donde vivir;
- el «deshacer» y las guardas necesitan saber qué filas de origen y qué lotes tocó el pase;
- `_tenencia_no_vista` necesita saber que un lote cargado a mano estuvo en A hasta el día del pase;
- el antiduplicado necesita anotar qué omitió.

Las patas de capital **no** se leen de la tabla: salen del registro de lo importado. Así, borrar A o B hace lo correcto sin nada extra.

### A.3 Migración en las dos bases

**SQLite (`init_db`, `main.py:1962+`):**
- Las columnas de `import_normalized_tx` van con ALTER **literales**, porque `test_schema_pg_al_dia.py` los busca con una expresión regular. Van después del bloque de `excluded_at`/`idx_import_norm_excluded` (`main.py:~4485-4496`) y antes del de `override_info` (`main.py:~4512`):
  ```python
  norm_cols = _table_cols(conn, 'import_normalized_tx')
  if norm_cols and 'traspaso_id' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN traspaso_id TEXT")
  if norm_cols and 'fecha_compra' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN fecha_compra TEXT")
  if norm_cols and 'valor_usd' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN valor_usd REAL")
  if norm_cols and 'valor_ars' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN valor_ars REAL")
  if norm_cols and 'costo_usd' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN costo_usd REAL")
  if norm_cols and 'costo_nativo' not in norm_cols:
      conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN costo_nativo REAL")
  ```
- `positions.en_broker_desde`: un ALTER literal con `_table_cols(conn, 'positions')`, junto al bloque de `undo_meta_json` (`main.py:2486-2491`). `positions` está en la lista blanca de `_table_cols` (`main.py:832-842`). ⚠️ `positions` **no** está en el censo `tests/fixtures/columnas_de_las_tablas.json`: el ALTER es la única garantía para las bases SQLite viejas.
- `traspasos_a_mano`: el `CREATE TABLE IF NOT EXISTS` de A.2.

**Postgres:**
- `cd backend && python3 scripts/mkschema.py` **dentro del worktree**, que no tiene `.env`. Se commitea el `schema_pg.sql` regenerado; **no se edita a mano**.
- En el arranque, `_esquema_pg_al_dia()` (`main.py:1449-1505`) aplica `ADD COLUMN IF NOT EXISTS` y `CREATE TABLE IF NOT EXISTS`. El primer arranque vuelve a aplicar el esquema entero una vez: **publicar fuera de 23:59–01:15**.

**Censo** (`tests/fixtures/columnas_de_las_tablas.json`): sumar las 6 columnas nuevas de `import_normalized_tx` y la tabla `traspasos_a_mano` con sus 14 columnas.

### A.4 Listas y guardianes por los que entra la tabla

| Lugar | Cambio |
|---|---|
| `main.py:7140` `BROKER_POR_NOMBRE` | `"traspasos_a_mano": ("json", "conservar")`. Al borrar un broker la receta queda: el pase pasa a «incompleto» y se puede deshacer lo que queda (C.8) |
| `renombre_broker.py:44` `COLUMNAS_JSON` | `("traspasos_a_mano", "receta_json")` |
| `main.py:6151` `_RESET_PORTFOLIO_TABLES` | `"traspasos_a_mano"` |
| `tests/fixtures/columnas_de_las_tablas.json` | ver A.3 |
| `tests/test_tx_vivas.py:32` `LEEN_EL_LOG` | anotar cualquier lector de D.7 que lea filas de lotes revertidos (el deshacer de un pase incompleto lee las filas BUY del lote que sobrevive, por `TX_VIVAS`; si la implementación necesita las del revertido, se anota con el motivo) |

### A.5 Tipos de fila y campos nuevos (`importing/schema.py`)

- Al lado de los `OP_*` (`schema.py:80-91`):
  ```python
  OP_TRASPASO_SALIDA = "TRASPASO_SALIDA"
  OP_TRASPASO_ENTRADA = "TRASPASO_ENTRADA"
  OPERATION_TYPES_INTERNOS = frozenset({OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA})
  ```
  **[D] No se suman a `OPERATION_TYPES` ni a `OP_TYPE_ALIASES`.** Un CSV del usuario, el genérico o el que arma la IA nunca tiene que poder fabricar una pata de capital.
- `NormalizedTx` (`schema.py:264-333`): campos nuevos al final, todos `Optional[...] = None`: `traspaso_id`, `fecha_compra`, `valor_usd`, `valor_ars`, `costo_usd`, `costo_nativo`.
- ⚠️ `NormalizedTx.__post_init__` traduce códigos de ticker viejos a los vigentes (`schema.py:335-350`) [V]. Por eso B.6 #11 frena un activo que en `positions` tiene el código viejo.

### A.6 Las filas sintéticas, columna por columna

Valen para todas:
- `date` = fecha del pase;
- `traspaso_id` = id del pase;
- `asset_symbol_raw` = NULL;
- `row_index` = `-49999 + k`, con k = 0, 1, 2… en orden de inserción. Así el orden del persister (`persister.py:303-308`) coincide con el `n.id` que usa el rebuild.

**Las notas no llevan ningún nombre de broker** (H16), ni «Estado inicial», «Tenencia —», «amortiz» ni «GTOS/GASTOS TRANS».

| Fila | Lote | operation_type | broker | asset_type | quantity | unit_price | gross_amount | fees | currency | fecha_compra | valor_usd / valor_ars / costo_usd / costo_nativo | transfer_out / transfer_in | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Salida de importados**: una por tramo contiguo de la cola FIFO de lotes importados elegidos que vive en la misma pata (ver nota 1) | A | `SELL` | la pata de A de ese tramo | el de la fila BUY de origen del primer lote del tramo | Σ de lo movido en el tramo | `0` | `0` | `0` | moneda de los lotes | NULL | — / — / — / **Σ inversión movida, sin comisiones** | `1` / `0` | `"Traspaso a otro broker tuyo el {dd/mm/aaaa} — sale al costo, sin ganancia"` |
| **Pata de salida**: una por par (pata A → pata B) | A | `TRASPASO_SALIDA` | pata A del par | tipo del lote | cantidad del par (importados + cargados a mano) | V_par / cantidad, en la moneda del precio | `NULL` | `0` | moneda de los lotes | NULL | V_par, V_ars_par, C_par, C_nativo_par (con comisiones) | `0` / `0` | `"Salieron {q} {asset} a otro broker tuyo (valor del día)"` |
| **Llegada**: una por lote | B | `BUY` | pata de B (C.1) | `asset_type` del lote; si no tiene, el de la fila de origen | lo movido | `buy_price` del lote, o `costo_del_lote`/cantidad si es NULL | inversión movida, en su moneda | comisiones movidas | moneda del lote (`behavioral._native_ccy`) | `entry_date` del lote | NULL | `0` / **`0`** | `"Llegó desde otro broker tuyo el {dd/mm/aaaa} · compra original del {dd/mm/aaaa}"` |
| **Pata de entrada**: una por par | B | `TRASPASO_ENTRADA` | pata B del par | igual | igual que su par | igual | `NULL` | `0` | igual | NULL | **los mismos cuatro números** que su par | `0` / `0` | `"Entraron {q} {asset} desde otro broker tuyo (valor del día)"` |
| **Gasto** (opcional) | A | `FEE` | `_pata_de_la_moneda(raíz_A, moneda_gasto)` | — | — | — | monto, positivo (`_apply_cash_flow` exige > 0, `persister.py:1235-1237`) | `0` | moneda del gasto | NULL | **valor_usd = gasto en USD** (al `tc_venta` del pase si es en pesos) | `0` / `0` | `"Costo del pase de {asset} a otro broker tuyo"` |

**Nota 1, sobre los tramos de la SELL** [D]. El persister vende consumiendo por moneda dentro del par (`broker_pair(tx.broker)`, `persister.py:819-824`), y el rebuild igual. Una SELL en la pata padre puede comerse primero un lote de la hija si es más viejo [V]. Por eso la cola FIFO de lotes importados elegidos se parte en tramos contiguos de la misma pata. Ejemplo: [hija 5, padre 3, hija 2] da tres SELL en ese orden. Así cada SELL consume justo los lotes de su pata, también en `_holdings_asof`, que agrupa por broker. En el caso común (todo en una pata) queda una sola SELL por pata, que además coincide por huella con el «Débito» de Balanz.

Otros campos de las BUY de B:
- `tc_compra` = el del lote;
- `asset_name` = el de la fila de origen, si existe.

**Por qué la BUY de B no lleva `transfer_in`:** `traspasos.entradas_ya_confirmadas` (`traspasos.py:143-163`) la tomaría como la entrada de otro broker, y el cruce automático podría proponer cerrar un tercero.

**Por qué la SELL de A lleva «Traspaso a »:** `traspasos_ya_cerrados` (`traspasos.py:112-140`, `LIKE '%Traspaso a %'`) y `_libro_vivo` la cuentan como cierre ya hecho. Así el cruce automático no vuelve a cerrar lo mismo. [V]

**Sobre la huella:** las filas guardan `fingerprint`, porque lo calcula `store_preview_txs`. Así **no** caen en `estado_inicial()` (`schema.py:73-75`). La huella es fecha|broker|tipo de operación|activo|cantidad|precio|monto, sin el tipo de activo (`pipeline.py:192-203`) [V].

### A.7 Los dos `import_batches`

Se crean con `pipeline.store_preview_txs(conn, uid, broker=<raíz>, parser_format="traspaso_a_mano", file_name="Pase entre brokers", txs=…)` (`pipeline.py:1713`). Eso deja `route_by_currency=0`, así el broker de cada fila va tal cual, y `status='preview'`. Después `persist_batch` los confirma.

- `broker` = nombre de la **cuenta raíz**, A o B. Así `delete_broker`/`_wipe_broker_data`, que juntan padre e hijos, revierten justo un lado (`main.py:7303-7309`).
- `file_name` va sin nombres de broker.
- `parser_format` va **sin** la palabra «tenencia».

### A.8 Ida y vuelta por la base

| Lugar | Cambio |
|---|---|
| `pipeline.store_preview_txs` (`pipeline.py:1745-1762`) | sumar las 6 columnas al INSERT, con `getattr(tx, "…", None)` |
| `pipeline.load_session_for_confirm` (`pipeline.py:1765-1834`) | rehidratar los 6 campos, con el patrón `if "x" in r.keys()` |
| `pipeline.run_preview` (INSERT de `:~1440`), la relectura con «Estado inicial» (`:~1959`) y el seed del persister (`persister.py:284`) | **sin cambio.** [D] Un pase nunca pasa por esos caminos |

---

## B. Endpoints

Los cuatro van en `main.py`, al lado de `POST /api/positions/sell` (`main.py:19743`). Así el censo `test_turno_en_todas_las_puertas.py` los cubre. La lógica vive en `importing/traspaso_a_mano.py` (D.7). Todos son `def` y no `async def`. Hay que correr `test_rutas_tapadas.py`.

**Interruptor.** Los cuatro endpoints miran `interruptor("mover_entre_brokers", conn)` (`main.py:15762`). Apagado, confirmar responde 403 «Esta opción no está disponible por ahora.»; deshacer sigue funcionando. `GET /traspasos` devuelve `habilitado`, y el frontend esconde el ítem del menú si viene en falso. [D] Sirve para la publicación por tandas (G.1) y para frenar pases nuevos si aparece un problema. **Ojo: volver atrás el deploy con pases ya hechos rompe las cuentas**, porque el código viejo no conoce las filas nuevas (G.3). Antes de volver atrás hay que apagar el interruptor y deshacer los pases.

### B.1 Modelos

```python
class GastoDelPaseIn(BaseModel):
    model_config = {"extra": "forbid"}
    monto: float = Field(..., gt=0)
    moneda: Literal["ARS", "USD"]          # sale siempre de la caja de A

class ValuacionIn(BaseModel):
    model_config = {"extra": "forbid"}
    precio_unitario: float = Field(..., gt=0)
    moneda_precio: Literal["ARS", "USD"]
    fuente: Literal["cierre_del_dia", "ultimo_precio", "precio_cargado", "precio_a_mano"]
    fecha_precio: str
    dolar: float = Field(..., gt=0)

class PaseIn(BaseModel):
    model_config = {"extra": "forbid"}
    broker_origen: str = Field(..., min_length=1, max_length=120)   # la pata de la opción elegida
    asset: str = Field(..., min_length=1, max_length=40)
    moneda: Literal["ARS", "USD"]                                    # moneda de la opción (como la venta)
    broker_destino: str = Field(..., min_length=1, max_length=120)   # cualquier pata de la cuenta B
    cantidad: Optional[float] = Field(None, gt=0)                    # None = todo lo disponible a esa fecha
    fecha: str                                                       # YYYY-MM-DD, obligatoria
    precio_manual: Optional[float] = Field(None, gt=0)               # por unidad, en la moneda del precio
    gasto: Optional[GastoDelPaseIn] = None
    firma: Optional[str] = None                                      # obligatoria al confirmar
    valuacion: Optional[ValuacionIn] = None                          # la de la vista previa; obligatoria al confirmar
```

### B.2 `POST /api/positions/traspaso/vista-previa`: lee y no escribe

- Decorado con `@no_escribe_en_el_cliente` (`main.py:4817`). Hay que sumar `("POST", "/api/positions/traspaso/vista-previa")` a la lista exacta de `tests/test_asesor_solo_lectura_post.py:125-135`, y escribir aparte la prueba de que no escribe (F.2 #24). [V: la prueba compara una lista exacta, no cuenta filas]
- Cuerpo:
  ```python
  with db_abierta() as conn:
      plan = traspaso_a_mano.armar_plan(conn, uid, body, hoy=_iso_today(),
                                        helpers=_import_helpers, para_confirmar=False)
      return plan.para_la_pantalla()
  ```
- No toma turno y nunca crea «B · USD»: `armar_plan` usa siempre `_pata_de_la_moneda(..., crear=False)` y `por_que_no_hay_pata_usd`.
- Los splits de Yahoo (`_fetch_ba_splits`) pueden ir a la red. En la vista previa está permitido, porque no hay candado. Si escriben en una tabla de caché compartida, no es la cuenta del cliente.
- Respuesta 200:
```json
{
 "ok": true,
 "origen": {"cuenta": "Cocos", "etiqueta": "Cocos · en pesos"},
 "destino": {"cuenta": "Balanz", "brokers_a_crear": ["Balanz · USD"]},
 "asset": "NVDA", "moneda": "ARS", "fecha": "2026-11-20",
 "cantidad": 10, "cantidad_disponible": 25,
 "lotes": [{"lote_id": 123, "a_mano": false, "fecha_compra": "2024-03-10", "cantidad": 4,
            "de_un_lote_de": 4, "costo": 120000.0, "comisiones": 600.0, "moneda": "ARS",
            "broker_origen": "Cocos", "broker_destino": "Balanz"}],
 "valuacion": {"precio_unitario": 25000.0, "moneda_precio": "ARS", "fuente": "cierre_del_dia",
               "fecha_precio": "2026-11-20", "dolar": 1400.0},
 "valor_nativo": 250000.0, "valor_ars": 250000.0, "valor_usd": 178.57,
 "costo_usd": 92.30, "puente_usd": 86.27,
 "gasto": {"monto": 5000.0, "moneda": "ARS", "broker": "Cocos", "caja_queda_negativa": false} | null,
 "avisos": ["…"],
 "firma": "9f2c…(16 hex)"
}
```
- Errores: `HTTPException(status, detail)` con el texto de B.6. Si falta precio, `detail` es un objeto `{"codigo": "sin_precio", "mensaje": "…", "moneda_precio": "ARS"}`.

### B.3 `POST /api/positions/traspaso`: confirmar, todo o nada

```python
@app.post("/api/positions/traspaso")
@reintentar_si_trabada
def confirmar_pase(body: PaseIn, uid: int = Depends(get_effective_user)):
    with db_abierta() as conn:
        _exigir_interruptor(conn, "mover_entre_brokers")
        # 0. Lo que va a la red, ANTES de cualquier candado (patrón de /adjust-ratio, main.py:16253-16265):
        #    los splits de Yahoo del activo y, si es cripto en una cuenta en pesos, el dólar cripto.
        traspaso_a_mano.precargar(conn, uid, body)
        try:
            with conn:
                _tomar_turno_de_la_puerta(conn, uid)                                  # 1. PG: turno por usuario
                cuentas = traspaso_a_mano.cuentas_del_pedido(conn, uid, body)         # 2. valida 1-7 de B.6 (sólo `brokers`)
                _tomar_lotes(conn, uid, cuentas.patas_a, cuentas.asset)               # 3. SQLite y PG: los lotes de A
                _tomar_lotes(conn, uid, cuentas.patas_b, cuentas.asset)               #    y de B, ANTES de leerlos
                plan = traspaso_a_mano.armar_plan(conn, uid, body, hoy=_iso_today(), cuentas=cuentas,
                                                  helpers=_import_helpers, para_confirmar=True)
                if not body.firma or body.firma != plan.firma:                        # 4.
                    raise HTTPException(409, traspaso_a_mano.MSG_CARTERA_CAMBIO)
                plan.fijar_valuacion(body.valuacion)                                  # 5. ver abajo
                antes = _foto_contable(conn, uid)                                     # 6. validado, antes de escribir
                out = traspaso_a_mano.aplicar_plan(conn, uid, plan, helpers=_import_helpers)   # 7. C.7
                _cascade_after_movement_delete(conn, uid, plan.fecha, set(plan.patas_tocadas),
                                               antes=antes)                           # 8. recálculo + cadena + fotos
        except traspaso_a_mano.PaseInvalido as ex:
            raise HTTPException(ex.status, ex.detalle)
    _ai_cache_invalidate(uid)
    return {"ok": True, "traspaso_id": out["traspaso_id"], "mensaje": out["mensaje"]}
```

- **Concurrencia en SQLite.** [V] `_tomar_turno_de_la_puerta` no hace nada en SQLite (`main.py:1647-1677`), y la base recién se tomaba en `_foto_contable` (`main.py:22494`), después del plan. Con dos pedidos a la vez, los dos leían los mismos lotes. `_tomar_lotes` (`main.py:18903-18912`) hace `UPDATE positions SET quantity=quantity` sobre (patas, activo): en SQLite toma la base y en PG traba esas filas. Por eso todo lo que va a la red se lee antes (paso 0) y `armar_plan` en modo confirmar no sale a la red.
- **Valuación (paso 5).** El servidor confirma con el precio que el usuario vio en la vista previa (`body.valuacion`). Valida tres cosas:
  - `moneda_precio` tiene que ser la que corresponde a la clave de precio (C.4); si no, 400 «Precio inválido.»;
  - `dolar` tiene que estar a ±3 % del dólar que calcula el servidor para esa fecha (C.4.3); si no, 409 «El dólar de ese día cambió (de {X} a {Y}). Revisá la vista previa antes de confirmar.»;
  - la banda del precio (B.6, aviso), que no frena.

  [D] Aceptar el precio que manda el cliente no abre nada nuevo: el usuario ya puede escribir el precio que quiera con `precio_manual`.
- **Atomicidad.** Todo pasa dentro de un solo `with conn:`. `aplicar_plan` levanta `PaseInvalido` en cuatro casos:
  - un `persist_batch(...)["skipped_rows"]` vino con algo (H7) → 500 `MSG_NO_SE_GUARDO`;
  - un `PersistError` del freno de pesos, que sale antes del bucle (`persister.py:418-448`) → 409 con su mensaje (convertido, no un 500 crudo);
  - un `HTTPException(409)` de `_ensure_usd_sibling` (`main.py:19315`) → 409 con su motivo;
  - un `UPDATE/DELETE … AND quantity=?` de un lote cargado a mano tocó 0 filas → 409 `MSG_CARTERA_CAMBIO`.

  Cualquiera de esas excepciones sale del `with` y la base deshace **todo**, incluido el «B · USD» recién creado. Ninguna de estas funciones hace `commit()` por dentro.
- `_cascade_after_movement_delete` (`main.py:23256`) sirve tal cual:
  - repara la cadena de cada pata tocada y del global;
  - corre el recálculo autoritativo;
  - borra sólo las fotos **sintéticas** de fin de mes desde la fecha;
  - corrige `net_deposited` de las fotos reales con `_cambio_de_aportado` (en un pase normal el aportado global no cambia);
  - borra la foto de hoy («HOY: se borra siempre», docstring);
  - rehace el backfill.

  **No borra fotos medidas.** La reconstrucción a mercado la dispara el middleware `_ReconstruirAlTerminar`.

### B.4 `POST /api/positions/traspaso/{traspaso_id}/deshacer`

El mismo esqueleto que B.3:
1. `precargar` (nada) → turno;
2. `_tomar_lotes` sobre las patas de A y de B que todavía existan;
3. `traspaso_a_mano.validar_deshacer` (C.8);
4. `antes = _foto_contable`;
5. `traspaso_a_mano.deshacer(...)`;
6. `_cascade_after_movement_delete(conn, uid, fecha_del_pase, patas, antes=antes)`;
7. `_ai_cache_invalidate`.

Funciona aunque el interruptor esté apagado. Respuesta: `{"ok": true, "mensaje": "Listo: los 10 NVDA volvieron a Cocos."}` (los textos de los casos incompletos están en C.8).

### B.5 `GET /api/positions/traspasos`

Devuelve `{"habilitado": bool, "traspasos": [...]}` con los registros que tienen `deshecho_at IS NULL`:

```json
{"id": "…", "fecha": "2026-11-20", "asset": "NVDA", "cantidad": 10, "moneda": "ARS",
 "broker_origen": "Cocos", "broker_destino": "Balanz",
 "valor_usd": 178.57, "costo_usd": 92.3,
 "estado": "vivo" | "incompleto" | "desfasado",
 "puede_deshacer": true,
 "motivo": null | "Ya vendiste 3 de los 10 NVDA que pasaste a Balanz…",
 "aviso": null | "Cambió la historia de Cocos y este pase quedó desactualizado: deshacelo y hacelo de nuevo."}
```

- Los nombres salen de `import_batches.broker` de cada lote, que el renombre ya mantiene al día. Si un lado se borró, sale de la receta.
- `incompleto` = uno de los dos lotes está `reverted`, porque se borró ese broker. Igual se puede deshacer (C.8).
- `desfasado` = `desfasado_at` no es NULL.

### B.6 Validaciones de la vista previa y del confirmar, en este orden

Los mensajes son exactos; las llaves `{}` se completan.

| # | Condición | Status | Mensaje |
|---|---|---|---|
| 1 | `fecha` falta o no tiene formato `YYYY-MM-DD` válido | 400 | «Elegí la fecha del pase.» si falta; «Fecha inválida. Usá el formato día/mes/año.» si es inválida |
| 2 | `fecha > _iso_today()` (`main.py:43295`; nunca `date.today()`) | 400 | «La fecha del pase no puede ser posterior a hoy.» |
| 3 | `broker_origen` no es del usuario | 404 | «No encontramos ese broker en tu cuenta.» |
| 4 | `broker_destino` no es del usuario | 404 | «No encontramos el broker al que querés pasarlo. Si es nuevo, crealo primero.» |
| 5 | misma cuenta raíz (incluye padre ↔ su «· USD») | 400 | «Ése es el mismo broker: las dos monedas de una cuenta son una sola. Elegí otro broker.» |
| 6 | alguna pata de A o B es Wallbit (`user_broker_credentials.broker` del usuario, o `lower()=='wallbit'`) | 400 | «Wallbit se sincroniza sola con tu cuenta real: no se le pueden pasar ni sacar títulos a mano.» |
| 7 | familias distintas (C.1) | 400 | AR↔exterior: «No se puede pasar de {A} a {B}: uno opera en el mercado argentino y el otro afuera. Un CEDEAR no es lo mismo que la acción de Estados Unidos.» Exchange con otra familia: «No se puede pasar de {A} a {B}: uno es un exchange cripto y el otro un broker.» |
| 8 | el activo es efectivo (`USD`, `USDT`, `ARS` o `is_cash`) | 400 | «El efectivo no se mueve con esta opción. Usá Retirar en un broker y Depositar en el otro.» |
| 9 | bono o letra: algún lote `asset_type='BOND'`, o `ai.ar_bonds_metadata.is_known_ar_bond(asset)`, o `importing.maturity.is_bond_like_name(asset)` | 400 | «Por ahora los bonos y las letras no se pueden pasar entre brokers desde Rendi.» |
| 10 | FCI: `asset` empieza con `FCI:` o `asset_type='FUND'`. [D] En la realidad no se transfieren entre ALyCs, y `fci_prices` guarda sólo el último precio | 400 | «Los fondos comunes no se pasan entre brokers: se rescatan en uno y se suscriben en el otro. Registralo como una venta y una compra.» |
| 11 | el activo tiene en `positions` un código de ticker viejo (`tickers_renombrados.ticker_importado(asset) != asset`) | 409 | «{viejo} ahora cotiza como {nuevo}. Editá el lote para que diga {nuevo} y volvé a moverlo.» |
| 12 | el traspaso automático ya cerró ese activo hacia B: SELL viva en las patas de A con `notes LIKE '%Traspaso a %'`, `traspaso_id IS NULL`, el mismo activo, `traspasos.destino_de(notes)` entre los nombres (actuales o `nombres_anteriores`) de las patas de B, y \|fecha − n.date\| ≤ 4 días | 409 | «Rendi ya pasó estos {asset} de {A} a {B} el {dd/mm}, cuando importaste el archivo de {B}. No hace falta moverlos otra vez.» |
| 13 | B ya tiene la entrada importada: BUY viva en las patas de B, el mismo activo, `traspaso_id IS NULL`, con `transfer_in=1` o `notes LIKE '%IEB:DETR%'`, `quantity ≤ cantidad + 1e-6`, y \|fecha − date\| ≤ `DIAS_TRASPASO_TARDIO` (60) | 409 | «{B} ya tiene registrada la llegada de {q} {asset} el {dd/mm} (vino en el archivo que importaste). Si la movés también a mano, se cuentan dos veces.\n\nHacé esto: en Movimientos, filtrá por {B} y borrá la «Compra» de {asset} del {dd/mm} y el «Depósito» del mismo día. Después volvé y mové los {asset} desde {A} con fecha {dd/mm}: así quedan con lo que pagaste originalmente.» |
| 14 | la fecha cae en un mes anterior al primer renglón de A o de B en `monthly_entries`, y ese renglón tiene `capital_inicio ≠ 0` (capital declarado a mano). [V] `_repair_monthly_chain` nunca toca el primer renglón; uno nuevo más viejo lo vuelve segundo y le pisa el capital declarado con el de la cadena (`main.py:17308+`, docstring de `_borrar_filas_de_la_cadena` `:17403-17420`) | 409 | «Tu historia de {broker} en Rendi arranca en {mes de aaaa} con un capital inicial que cargaste a mano. El pase no puede tener una fecha anterior: elegí desde el {01/mm/aaaa}.» |
| 15 | movimientos posteriores en A: una 'Venta' en `operations` en las patas de A, el mismo activo, `date > fecha`; **o** una SELL viva del registro con `date > fecha` | 409 | Venta: «Después del {dd/mm/aaaa} vendiste {asset} en {A}. Para no cambiar esas ventas, elegí una fecha del {dd/mm/aaaa de la última} en adelante.» Pase posterior (SELL con `traspaso_id`): «El {dd/mm/aaaa} ya pasaste {asset} de {A} a {C}. Elegí una fecha del {dd/mm/aaaa} en adelante, o deshacé primero ese pase.» |
| 16 | ventas posteriores en B, con el mismo criterio. [D] Si no, FIFO en B haría que esas ventas consumieran los lotes movidos, que son más viejos | 409 | «Después del {dd/mm/aaaa} vendiste {asset} en {B}. Si lo pasamos con esa fecha cambiarían esas ventas: elegí una fecha del {dd/mm/aaaa} en adelante.» |
| 17 | no hay lotes elegibles (C.2) | 400 | Normal: «No tenés {asset} en {A} en {pesos\|dólares} que estuvieran ahí el {dd/mm/aaaa}.» Si además hay una SELL `transfer_out` viva en A, del mismo activo, a ±60 días y sin `traspaso_id`: «En {A} ya figura la salida de {asset} del {dd/mm} (vino en el archivo de {A}). En Movimientos, filtrá por {A} y borrá la «Venta» de {asset} del {dd/mm}. Después volvé y movelos desde acá: así llegan a {B} con lo que pagaste.» |
| 18 | `cantidad > disponible + 1e-9` | 400 | «En {A} tenés {disp} {asset} en {pesos\|dólares} que estaban ahí el {dd/mm/aaaa}. No podés pasar {cantidad}.» |
| 19 | algún lote elegido sin `entry_date` | 400 | «Uno de los lotes que se moverían no tiene fecha de compra. Editalo, poné la fecha y volvé a intentar.» |
| 20 | cambio de ratio pendiente en A: `_cambios_a_ofrecer(conn, uid, lote, _marcas_de_split(conn, uid), cache)` (`main.py:16134`) devuelve algo para un lote elegido, evaluado sólo si `_por_que_no_se_ajusta_el_ratio(conn, uid, lote) is None` (`main.py:16193`). [V] Con la cantidad sin ajustar y la vela ya ajustada, V saldría corrido por el ratio | 409 | «{asset} tuvo un cambio de ratio que todavía no ajustaste en {A}. Primero ajustalo en Cartera (el aviso «Ajustar» de esa fila) y después volvé a moverlo.» |
| 21 | B ofrecería un ajuste que A no ofrece (C.2, regla de split) | 409 | «En {A} estos {asset} ya tienen aplicado un cambio de ratio que {B} no conoce: si los pasamos, quedarían contados dos veces. Por ahora no se pueden pasar. Si los pasaste de verdad, podés registrar una venta en {A} y una compra en {B} (así sí cuenta como venta).» |
| 22 | la valuación cambia de A a B: distinta clave de precio, o distinta moneda de cuenta de la pata (C.1.4) | 400 | «En {B} {asset} se cotiza distinto que en {A}, así que no se puede pasar.» |
| 23 | el registro de A no consumiría los mismos lotes que el plan (C.2, comprobación con el replay en seco) | 409 | Si es un lote importado y editado a mano: «El lote de {asset} del {dd/mm/aaaa} en {A} vino de un archivo y lo cambiaste a mano ({qué cambió: cantidad\|costo\|fecha}). Rendi arma {A} desde tus archivos, así que el pase no cuadraría. Para corregirlo de forma que quede: Importaciones → ese archivo → «Editar y rehacer», corregí la fila y volvé a moverlo.» Otro caso: «En {A} los lotes de {asset} no coinciden con tus archivos, así que no podemos saber cuáles pasar. Escribinos y lo revisamos.» |
| 24 | la pata «· USD» de B no se puede crear (`pipeline.por_que_no_hay_pata_usd`, `pipeline.py:846`) | 409 | el motivo que devuelve esa función, tal cual |
| 25 | un lote en pesos iría a una pata que no acepta pesos (`pipeline.brokers_que_no_aceptan_pesos`, `pipeline.py:770`) | 400 | «{pata de B} no tiene caja en pesos, y estos {asset} se compraron en pesos.» |
| 26 | no hay precio y no vino `precio_manual` | 409 | `{"codigo": "sin_precio", "mensaje": "No encontramos a cuánto cotizaba {asset} el {dd/mm/aaaa}. Escribí el precio de ese día (en {pesos\|dólares}) para calcular cuánto valía lo que pasaste.", "moneda_precio": "ARS\|USD"}` |
| 27 | gasto en una moneda sin caja en A (familia exterior + ARS) | 400 | «{A} no tiene caja en pesos.» |
| 28 | confirmar sin firma o con firma distinta | 409 | `MSG_CARTERA_CAMBIO` = «Tu cartera cambió desde que armaste la vista previa. Revisala de nuevo antes de confirmar.» |
| 29 | confirmar sin `valuacion`, o con el dólar a más de ±3 % | 400 / 409 | «Falta la vista previa del pase.» / «El dólar de ese día cambió (de {X} a {Y}). Revisá la vista previa antes de confirmar.» |
| 30 | falla al aplicar | 500 | `MSG_NO_SE_GUARDO` = «No pudimos guardar el pase ({motivo}). No se cambió nada en tu cartera.» |

**Avisos que no frenan** (`plan.avisos`), uno por renglón:
- B tiene una entrada importada de ese activo a más de 60 días de la fecha: «Ojo: {B} ya tiene una entrada de {asset} por traspaso del {dd/mm} (del archivo). Si es la misma, no la muevas a mano.»
- Se va a crear «{B} · USD»: «Vamos a crear «{B} · USD» para los lotes en dólares.»
- El precio, de mercado o escrito a mano, queda fuera de [0,002; 50] veces el costo unitario, **comparando los dos en dólares** (precio ÷ dólar del pase contra C ÷ cantidad): «El precio de ese día está muy lejos de lo que pagaste (×{k}). Si no es correcto, escribí el precio a mano.» Si el precio lo escribió el usuario, el texto termina «Revisá que esté en {pesos\|dólares}.». [D] Antes era un 400 en la moneda del lote, y rechazaba precios correctos de lotes en pesos de 2018-2020: el dólar se multiplicó más de 35 veces desde entonces.
- El precio es la última vela y no la del día: «Usamos el cierre del {día de la semana} {dd/mm}.» (por ejemplo «del viernes 20/11»).
- El gasto deja la caja de A en negativo: «Con el gasto, la caja de {A} queda en {monto negativo}.»

**Cupo del plan:** no se toca. B se crea con el flujo normal de alta de brokers, que ya aplica el cupo. La pata «· USD» no cuenta (`ai/plan.py:190-195`).

### B.7 Autorización, IDOR y concurrencia

- `uid = Depends(get_effective_user)`. La regla de sólo lectura del asesor (`main.py:4830-4839`) ya responde 403 en confirmar y en deshacer, y deja pasar la vista previa porque está marcada.
- **Toda** consulta filtra por `user_id`: `brokers`, `positions`, `import_batches.user_id` (con `TX_VIVAS` o un JOIN) y `traspasos_a_mano WHERE id=? AND user_id=?`. Un broker o un `traspaso_id` de otra cuenta da el mismo 404 que uno que no existe.
- Concurrencia:
  - turno → `_tomar_lotes` → lectura;
  - firma (detecta cambios entre la vista previa y la confirmación);
  - `UPDATE/DELETE … AND quantity=?` en los lotes cargados a mano;
  - los lotes se reclaman con `UPDATE import_batches SET status=status … AND status='preview'` (`persister.py:220-225`).
- Doble click: `useEnVuelo`. Ante un 502/503/504 no se reintenta, porque es una escritura.

---

## C. Algoritmo, paso a paso

### C.1 Cuentas, patas, familia y destino

1. `_cuenta_de(conn, uid, nombre)`. Si la fila tiene `parent_broker_id`, la raíz es el padre. Las **patas** = `persister.broker_pair(conn, uid, raíz)`, siempre desde el padre: desde un hijo no ve a los hermanos (`persister.py:130-152`) [V].
2. Familia, con la misma fuente que la valuación:
   - `ars, ar_usd = snapshots_job._broker_name_sets(brokers)` (`snapshots_job.py:97`);
   - `AR` si la raíz está en `ars ∪ ar_usd`;
   - si no, `EXCHANGE` si `cripto.is_exchange_broker(raíz)` (`cripto.py:134`);
   - si no, `EXTERIOR`.
3. Pata destino de cada lote [D]:
   - lote en la raíz de A → raíz de B;
   - lote en una hija USD de A → `_pata_de_la_moneda(conn, uid, raíz_B, "USD", crear=False)` (`main.py:19338`);
   - **excepción:** un lote con moneda ARS que vive en una pata en dólares de A va a la raíz de B. Si no, el freno de pesos del persister (`persister.py:418-448`) lo rechazaría [V].

   Si la hija de B no existe y hace falta, `por_que_no_hay_pata_usd` decide entre #24 y el aviso «Vamos a crear…». **`armar_plan` nunca crea**: la pata se crea sólo en `aplicar_plan` (C.7.2). Después se valida #25 con `brokers_que_no_aceptan_pesos`.
4. Invariante de valuación, por lote, con dos condiciones:
   - `snapshots_job.position_price_key(lote, ars, ar_usd)` == `position_price_key({**lote, "broker": pata_B}, ars', ar_usd')`, donde `ar_usd'` incluye la «B · USD» a crear si la raíz de B es ARS;
   - la moneda de cuenta (ARS contra dólar) de la pata de origen == la de la pata destino. La cripto en una cuenta en pesos se valúa con el factor del dólar cripto (`snapshots_job.py:396-415`, `crypto_broker_factor` `main.py:11279`) y en una en dólares sin él [V].

   Si alguna de las dos falla, es el #22.

### C.2 Lotes elegibles, FIFO y comprobación

```sql
SELECT * FROM positions
 WHERE user_id=? AND broker IN (<patas de A>) AND asset=? AND is_cash=0 AND quantity > 0
 ORDER BY COALESCE(entry_date,'9999-12-31') ASC, id ASC          -- el mismo orden que persister.py:822
```

1. Se filtran en Python con `behavioral._native_ccy(dict(p)) == moneda`, el mismo criterio que `_by_ccy` del persister (`persister.py:798-806`). **No** se cae a «todos» si no hay de esa moneda: eso es el #17.
2. **Elegibles:** `entry_date` no nulo (si no, #19) y **`COALESCE(en_broker_desde, entry_date)[:10] <= fecha`**. [D] Un lote que llegó a A por un pase anterior tiene la fecha de compra vieja, pero en el registro de A su compra está fechada el día en que llegó. Si se filtrara por la fecha de compra, un pase encadenado con fecha anterior a esa llegada duplicaría la tenencia en el próximo rebuild de A.
3. `disponible = Σ quantity`. `cantidad = body.cantidad or disponible`. Elegidos: el prefijo FIFO hasta juntar `cantidad`.
4. Clasificación de cada lote:
   - **importado** si `_src_tx_for_position(conn, uid, pid)` (`main.py:15343`) devuelve la fila de origen viva; se guarda `(batch_id, raw_row_id)` y su `asset_type`;
   - si no, **a mano**.
5. **Splits (#20 y #21).** Con la fuente única `_cambios_a_ofrecer` y `nuevo = interruptor(AVISO_RATIO_NUEVO, conn)`, sólo para lotes donde `_por_que_no_se_ajusta_el_ratio` da None:
   - `ofrecidos_A = _cambios_a_ofrecer(conn, uid, lote, marcas, cache, nuevo)`. Si no está vacío → #20;
   - `ofrecidos_B = _cambios_a_ofrecer(conn, uid, {**lote, "broker": pata_B, "split_adjusted_through": None}, marcas_B, cache, nuevo)`, donde `marcas_B` es una copia de `marcas` a la que se le agrega, en `marcas_B["cero"][(pata_B, base)]`, la `fecha_compra` de cada lote elegido con `buy_price` 0 e `invested` 0 (esa marca viaja por D.11). Las marcas de foto y de split corporativo **no** viajan. Si `ofrecidos_B` no está vacío → #21.
6. **Comprobación contra el registro (#23).** [D] Se calcula `a_salvo_despues` = `_is_safe_to_rebuild`, pero sobre las posiciones de A que quedan después del pase (sin los lotes elegidos) y las 'Venta' actuales. Si da verdadero, los rebuilds futuros de A van a rearmar A desde el registro, así que el registro tiene que coincidir con lo que el plan mueve:
   - `eventos = _full_events(conn, uid, patas_A, asset)` + las SELL planificadas de A.6 (eventos sintéticos con `traspaso_id` = id provisorio, `date` = fecha y `n.id` mayor que cualquier existente), ordenados como `_full_events`;
   - `replay = rebuild._replay_asset(rebuild._cancel_conduit_pairs(eventos, …), broker_currency, tc, use_hist=…, conn=conn, …)`. Es de sólo lectura;
   - el multiconjunto `replay["traspasos"][id_provisorio]` de `(entry_date[:10], qty, invested, commissions)` tiene que coincidir con los lotes **importados** del plan, con tolerancia 1e-6 en cantidad y 1e-4 relativo en montos. Si no coincide → #23. Para el texto se compara el lote del registro con el de `positions` por `(batch_id, raw_row_id)` y se dice qué campo difiere.

   [V] `PUT /api/positions/{pid}` cambia cantidad, costo y fecha de un lote importado sólo en `positions` (`main.py:15667-15681`); lo único que copia al registro es el tipo (`_cambiar_tipo_del_lote`, `:15359`). Lo mismo hace `/adjust-ratio` con la cantidad (`main.py:16300-16310`). Sin esta comprobación, el persister movería el lote editado y el próximo rebuild de A consumiría otro.
7. Si A no queda «a salvo» (le siguen quedando lotes cargados a mano de ese activo), `positions` manda y no hay comprobación. Si algún día A pasa a estar a salvo y no cuadra, lo marca el detector (D.5.5).

### C.3 Partir el último lote

Si el último lote no se toma entero:
- `base_inv = fx.costo_del_lote(invested, buy_price, qty)`: un lote cargado a mano puede no tener `invested` (`persister.py:~917`);
- `take = cantidad − Σ(anteriores)` y `ratio = take / qty`;
- `queda_inv = round(base_inv × (1 − ratio), 6)` y `queda_com = round(commissions × (1 − ratio), 6)`. Es la misma fórmula del persister (`persister.py:1020-1031`);
- lo **movido** es el complemento: `mov_inv = base_inv − queda_inv` y `mov_com = commissions − queda_com`.

### C.4 Valor de mercado el día del pase

1. Clave de precio: `position_price_key(lote_A, ars, ar_usd)`. `X.BA` cotiza en pesos; el ticker de EE.UU. y la cripto, en dólares. **Excepción, cripto en una cuenta en pesos:** el precio se expresa en pesos = spot en USD × dólar cripto, como la valúa Cartera.
2. Fuente, en este orden:
   - (a) `body.precio_manual` → `"precio_a_mano"`;
   - (b) si `fecha == hoy` y algún lote elegido tiene `price_override` → ese valor, `"precio_cargado"`;
   - (c) **cripto en una cuenta en pesos:** si `fecha == hoy`, el spot de `read_last_prices` × `main._current_cripto_rate()` (leído en `precargar`) → `"ultimo_precio"`. Si la fecha es pasada → #26 con `moneda_precio: "ARS"`: no hay dólar cripto histórico;
   - (d) si `fecha == hoy`: `snapshots_job.read_last_prices(conn, [clave], fresh_since=hoy−5 días)` (`snapshots_job.py:917`) → `"ultimo_precio"`;
   - (e) `velas_diarias.serie(conn, clave, desde=fecha−10 días)` (`velas_diarias.py:1797`): la última vela con `date <= fecha` y `fecha − date <= 7` → `"cierre_del_dia"` si `date == fecha`, si no `"ultimo_precio"` con aviso. `serie` ya viene ajustada por splits y empalmada por ratio;
   - (f) sin precio → #26.

   Todas estas lecturas son de la base, salvo el dólar cripto, que va en `precargar`. `fx.fx_for_date` lee `fx_rates_daily` (`fx.py:170-233`) [V].
3. Dos dólares distintos. [D] Esto corrige el borrador, que usaba uno solo:
   - **`tc_venta`, para el costo C.** Se elige por la **moneda del lote**, como el persister (`persister.py:894-900`) [V]: lote USD → 1; lote ARS → `fx.fx_for_date(conn, fecha, fallback=tc_blue)` en cuentas v2 y `tc_blue` de la config en v1. En la vista previa la versión se lee con `fx.fx_version_lectura`; al confirmar, con `fx.fx_version`;
   - **`tc_pase`, para V.** Precio en USD → 1. Precio en ARS con lote ARS → el mismo `tc_venta`, así el puente es exactamente el resultado de vender a V ese día. Precio en ARS con lote USD (CEDEAR en dólares, que Cartera valúa como `.BA ÷ MEP`) → `fx.fx_for_date(conn, fecha, fallback=tc_blue)`.
   - El `dolar` que se muestra y se valida al confirmar es `tc_pase` si el precio es en pesos y `fx_for_date(fecha)` si es en dólares.
4. Valores por par:
   - `V_nativo = Σ take × precio`;
   - precio en ARS: `V_usd = V_nativo / tc_pase` y `V_ars = V_nativo`;
   - precio en USD: `V_usd = V_nativo` y `V_ars = V_usd × fx.fx_for_date(conn, fecha, fallback=tc_blue)`;
   - **las dos patas del par guardan exactamente los mismos números**;
   - no se usa `compute_broker_value_usd`, que con su guarda de confianza devuelve el costo en silencio.

### C.5 Costo en USD (C) y puente

**[D] Se extrae** el cálculo por tramo, hoy duplicado en `_persist_sell_fifo` (`persister.py:~919-990`) y `_replay_asset` (`rebuild.py:~397-470`), a `importing/tramo.py`:

```python
def costo_y_resultado_del_tramo(conn, *, lote: dict, take: float, currency: str, sell_currency: str,
                                exit_price: float, chunk_commission: float, tc_venta: float,
                                tc_blue: float, hist: bool, op_date: str, transfer_out: bool) -> dict:
    # -> {"pnl_usd", "invested_usd", "proceeds_native", "resultado", "costo_en_su_moneda"}
```

- Es código movido, no reescrito: `costo_del_lote` + comisiones → `costo_en_moneda_de_venta` → la rama `transfer_out` / ARS / USD → `resultado_dual.resultado_en_dos_monedas(...)` + `resultado_en_dolares`.
- Para el pase: `C_tramo = costo_y_resultado_del_tramo(..., sell_currency=moneda_lote, exit_price=precio expresado en la moneda del lote (precio ÷ o × el dólar de C.4.3 si las monedas difieren), chunk_commission=0, transfer_out=False, op_date=fecha, tc_venta=tc_venta)["invested_usd"]`.
- `C_par = Σ C_tramo`, `C_nativo_par = Σ (mov_inv + mov_com)` y `puente_par = V_usd_par − C_par`.

### C.6 Armado de las filas

Según A.6:
- **Lote A:** las SELL por tramo contiguo (sólo importados, en orden FIFO) → las TRASPASO_SALIDA por par → la FEE si hay gasto.
- **Lote B:** las BUY (una por lote, en orden FIFO) → las TRASPASO_ENTRADA por par.

### C.7 Aplicar, todo dentro de la transacción del endpoint

1. `traspaso_id = secrets.token_hex(16)`.
2. Crear las patas «· USD» que hagan falta: `_pata_de_la_moneda(..., crear=True)` → `_ensure_usd_sibling` (`main.py:19274`). Va antes de cualquier otra escritura. Su `HTTPException(409)` se convierte en `PaseInvalido(409, motivo)`.
3. **Lotes cargados a mano de A, primero** (H22):
   - entero: `DELETE FROM positions WHERE id=? AND user_id=? AND quantity=?` (si borra 0 filas → 409);
   - parcial: `UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=? AND quantity=?`.

   No se toca la caja ni la receta del lote. El prefijo FIFO garantiza que, después de esto, los lotes importados elegidos son los primeros de la cola que queda.
4. `sid_a = store_preview_txs(..., broker=raíz_A, txs=filas_A)` y `sid_b = store_preview_txs(..., broker=raíz_B, txs=filas_B)`.
5. `INSERT INTO traspasos_a_mano (...)` con la receta. `fila_destino_raw_row_id` sale de `load_session_for_confirm(sid_b)`.
6. Para cada `sid` en `(sid_a, sid_b)`:
   - `txs, raw = load_session_for_confirm(conn, uid=uid, session_id=sid)`;
   - `r = persist_batch(conn, uid=uid, batch_id=sid, txs=txs, raw_row_ids_by_index=raw, helpers=_import_helpers)`.

   `PersistError` → `PaseInvalido(409, ex.message)`; `r["skipped_rows"]` con algo → `PaseInvalido(500, MSG_NO_SE_GUARDO.format(primer mensaje))`.
7. **Sin rebuild.** [D] El persister ya consumió exactamente lo planificado (C.2.6), y lo escrito por el persister es lo mismo que daría un rebuild. Al no rebuildear, los ids de los lotes que quedan en A no cambian.
8. `price_override`: si los lotes de A tenían uno y B no tiene ninguno para ese activo → `UPDATE positions SET price_override=? WHERE user_id=? AND broker IN (patas B) AND asset=? AND is_cash=0`, y se anota `precio_cargado_en_destino` en la receta, para deshacerlo.
9. Devuelve `{traspaso_id, mensaje: "Listo: pasaste {q} {asset} de {A} a {B}.", patas_tocadas}`.

### C.8 Deshacer

**Validaciones, en este orden:**
1. El registro existe, es del usuario y `deshecho_at IS NULL`. Si no: 404 «No encontramos ese pase.» o 409 «Ese pase ya se deshizo.».
2. **Filas omitidas que siguen vivas.** Si `omitidas_json` tiene filas cuyo lote sigue `confirmed` → 409: «Cuando importaste el archivo de {broker} del {dd/mm/aaaa}, Rendi no cargó la {llegada\|salida} de {asset} porque ya estaba este pase. Si lo deshacés, esos títulos quedarían sin registrar. Primero revertí ese archivo (Importaciones → el archivo del {dd/mm/aaaa} → Revertir), después deshacé el pase y volvé a subir el archivo.» [V] El confirm borra de `import_normalized_tx` las filas que omite (`main.py:48781-48797`).
3. **A después del pase** (sólo si el lote A sigue `confirmed`): una 'Venta' en `operations` o una SELL viva del registro en las patas de A, del mismo activo, con `date >= fecha`, que no sea de este pase → 409. Textos: «Después de este pase vendiste {asset} en {A} el {dd/mm}. Para deshacerlo, primero borrá esa venta.» o, si es un pase posterior: «Después de este pase pasaste {asset} de {A} a {C} el {dd/mm}. Deshacé primero ese pase.»
4. **B tal como llegó** (sólo si el lote B sigue `confirmed`). Para cada BUY viva del lote B, el `position_id` actual de su vínculo en `import_op_links` (`batch_id`, `raw_row_id`) tiene que existir con `|quantity − fila.quantity| ≤ 1e-6`. Si no:
   - si hay un pase posterior vivo desde las patas de B del mismo activo con `fecha >=` → «Los {asset} que llegaron a {B} los pasaste a {C} el {dd/mm}. Deshacé primero ese pase.»;
   - si no, si hay una 'Venta' o una SELL en B → «Los {asset} que llegaron a {B} ya no están como llegaron: vendiste {q} de los {n}. Para deshacer el pase, primero borrá esa venta.»;
   - si no → «Los {asset} que llegaron a {B} ya no están como llegaron: los editaste. Volvé a dejarlos como llegaron ({n} a {costo}) para poder deshacer el pase.»

**Pasos para un pase vivo (los dos lotes `confirmed`):**
1. `UPDATE import_batches SET status='reverted', reverted_at=datetime('now') WHERE user_id=? AND id IN (?,?) AND status='confirmed'`. Tiene que tocar 2 filas; si no, 409 «ya se deshizo».
2. **B:** borrar las posiciones vinculadas a las BUY del lote B (`DELETE … WHERE id=? AND user_id=?`) y sus vínculos (`DELETE FROM import_op_links WHERE batch_id=?`). B no se rebuildea: la validación 4 garantiza que nadie consumió esos lotes, y los lotes propios de B quedan como estaban.
3. **A, lotes importados** [D, en este orden]:
   - (a) si `_is_safe_to_rebuild(conn, uid, patas_A, asset)` da verdadero → `rebuild_pair_asset(conn, uid, raíz_A, asset, tc_blue=…)`. Rearma A desde el registro, que ya no tiene la SELL, y repone exactos los lotes importados movidos. Si falla, `PaseInvalido(500)`;
   - (b) si no está a salvo: para cada lote importado de la receta, buscar el lote vivo por `import_op_links(batch_id, raw_row_id)` de `fila_origen` y, si existe, sumarle cantidad, inversión y comisiones. Si no existe, reinsertarlo con su foto, con el mismo id si está libre, y dejar el vínculo apuntando a ese id (`INSERT` o `UPDATE` de `import_op_links`).

   [V] Un rebuild de A posterior al pase cambia los ids y deja lápidas (`rebuild.py:975-978`, `:757-779`); por eso no se busca por `lote_id`.
4. **A, lotes que eran cargados a mano**, al final, con la función compartida `_devolver_al_lote` (D.10.12): si el `lote_id` sigue vivo, le suma; si no, lo reinserta con su foto, con el mismo id si está libre.
5. `price_override`: si la receta tiene `precio_cargado_en_destino` y los lotes de B de ese activo siguen con el valor `puesto` → se ponen en `antes`.
6. Gasto: si la receta tiene `gasto` → `_adjust_broker_cash(conn, uid, gasto.broker, +monto)` (`efectivo.mover`, la única puerta de la caja).
7. `UPDATE traspasos_a_mano SET deshecho_at=datetime('now') WHERE id=? AND user_id=?`.
8. El endpoint corre `_cascade_after_movement_delete(conn, uid, fecha, patas_A ∪ patas_B, antes=antes)`.

**Pase incompleto (se borró uno de los dos brokers):**
- **Sobrevive A** (B fue borrado): pasos 1 (sólo el lote A), 3, 4, 6, 7 y 8. Mensaje: «Listo: {B} ya no existe, así que los {q} {asset} volvieron a {A}.»
- **Sobrevive B** (A fue borrado): validación 4, después pasos 1 (sólo el lote B), 2, 5, 7 y 8. La vista previa del botón avisa antes: «{A} ya no existe: al deshacer el pase, los {q} {asset} salen de {B} y no vuelven a ningún lado.» Mensaje: «Listo: los {q} {asset} salieron de {B}.»
- [D] Con esto ningún estado queda sin salida: las guardas de D.10 siguen protegiendo las filas del pase mientras `deshecho_at IS NULL`, y siempre apuntan a este botón, que ahora funciona en los dos casos.

**«B · USD» creada por el pase:** queda, vacía. [D] Borrar un broker tiene su propio flujo, y la pata pudo haber recibido otras cosas mientras tanto.

**No se usa `revert_batch`**, porque borra fotos medidas (`persister.py:1974-1989`). Tampoco se ponen lápidas (H9). Los lotes `reverted` dejan de contar en `confirmed_fingerprint_counts` (`pipeline.py:391`).

### C.9 Firma

`sha256(json.dumps([lotes (lote_id, take, entry_date, mov_inv, mov_com, pata_B)], fecha, moneda, raíz_B, gasto], sort_keys=True))[:16]`.

[D] **Sin precio ni dólar.** [V] `asset_last_price` se reescribe cada 60 segundos con precios en vivo (`main.py:11982-12004`). Con el precio adentro, en horario de mercado el confirmar daba «Tu cartera cambió» sin que nada cambiara. El precio viaja aparte, en `valuacion` (B.3). La firma sigue frenando el doble envío: después del primer pase, los lotes de A cambian.

### C.10 Revaluar las patas cuando la cuenta pasa del dólar vivo al histórico

[V] Cada import puede disparar `_auto_migrar_fx_post_import` (`main.py:48235`, llamado en `:49013`). Esa función pasa la cuenta de v1 a v2 con `migrate_user_fx` (`fx_migrate.py:263`, `set_fx_version` en `:394`, rebuild de todos los lotes en `:397-410`). Las patas guardan V y C calculados con la regla v1. Después de migrar, la identidad por broker quedaría corrida en C_v1 − C_v2.

[D] Función nueva `traspaso_a_mano.revaluar_patas(conn, uid)`. Para cada pase con `deshecho_at IS NULL` recalcula, desde la receta (precio, moneda, lotes con inversión, comisiones, `entry_date`, `tc_compra` y moneda) y con la regla de C.4–C.5 de la versión actual:
- `tc_venta`, `tc_pase`, `V_usd` y `C` de cada par;
- el `valor_usd` de la FEE.

Después hace `UPDATE` de las filas del pase (los mismos números en las dos patas) y de `receta.fx_version`. La llama `migrate_user_fx` justo después del rebuild, en la misma transacción. Es el único lugar donde cambia `fx_version` (grep: `set_fx_version` sólo en `fx_migrate.py:394`) [V].

### C.11 Una sola regla para lo que cambia la historia anterior a un pase

[D] Función `traspaso_a_mano.pase_que_cambia(conn, uid, filas, *, excluir=None) -> Optional[dict]`. `filas` son dicts `{broker, asset, op, date, fecha_compra, traspaso_id}` que una puerta está por agregar, sacar o reescribir en el registro. Para cada pase con `deshecho_at IS NULL`:
- **Lado A** (el lote A sigue `confirmed`, `broker` entre las patas actuales de A, el mismo activo canónico, fila que no es del pase):
  - una BUY con `date <= fecha_del_pase` y `COALESCE(fecha_compra, date) <= máx(fecha_compra de los lotes movidos)`: cambia los lotes que consumió el pase;
  - una SELL con `date <= fecha_del_pase`.
- **Lado B** (el lote B sigue `confirmed`, `broker` entre las patas de B, el mismo activo): una SELL con `date < fecha_del_pase`. El replay de B fabricaría un lote semilla y dejaría los movidos enteros, con títulos de más.

Devuelve el pase afectado, con lado, fecha y contraparte, para el mensaje. Si no, None.

Mensajes:
- `MSG_CAMBIA_UN_PASE` = «Esto cambia la historia de {asset} en {broker} antes de tu pase del {dd/mm/aaaa} {a\|desde} {contraparte}, y el pase quedaría con otros lotes. Primero deshacé el pase (Movimientos → la fila «Pase» → Deshacer), hacé este cambio y después volvé a moverlos.»
- `MSG_IMPORT_CAMBIA_UN_PASE` = «Este archivo trae {compras\|ventas} de {asset} en {broker} del {dd/mm/aaaa}, anteriores a tu pase del {dd/mm/aaaa} {a\|desde} {contraparte}. Si lo confirmamos, el pase quedaría con otros lotes. Deshacé el pase (Movimientos → la fila «Pase» → Deshacer), importá el archivo y volvé a moverlos.»

Las puertas que la llaman están en D.10. Las ediciones de `positions` de lotes cargados a mano no la llaman: no reescriben el registro, y `positions` manda mientras A no esté a salvo (C.2.7).

---

## D. Cambios por archivo y función

### D.1 `importing/schema.py`
1. Constantes y `OPERATION_TYPES_INTERNOS` (A.5).
2. Los 6 campos de `NormalizedTx`.

### D.2 `importing/pipeline.py`
1. `store_preview_txs` (`:1713-1762`): las 6 columnas (A.8).
2. `load_session_for_confirm` (`:1765-1834`): rehidratarlas.
3. **Deduplicación única.** Función nueva `filas_repetidas(conn, uid, txs, *, counts, anteriores, already_skipped=(), incluir_huella=True) -> set`:
   - si `incluir_huella`, devuelve `duplicate_row_indices_by_count(...) | traspaso_a_mano.filas_ya_traspasadas(conn, uid, txs).indices`;
   - si no, sólo lo segundo.

   La usan:
   - `run_preview`, gancho del traspaso (`:1325-1331`), como `repetidas=`. Además se pasa `ya_traspasadas=<índices del pase>` (D.6);
   - `run_preview`, la lista para la pantalla (`:1422-1423`);
   - `already_imported_row_indices` (`:445-457`), que usa el confirm.
   - **Confirm, `include_duplicates`:** [V] con ese flag el confirm no llama al antiduplicado (`main.py:48774-48779`). Fuera de ese `if`, siempre se aplica `filas_ya_traspasadas` (`incluir_huella=False`): forzar los repetidos por huella no tiene que forzar un doble conteo del pase.
   - Wallbit (`main.py:49469`): sin cambio (Wallbit no puede ser A ni B).
4. `preview_payload["ya_traspasados"]` (al lado de `:1479-1485`): `[{fecha, activo, cantidad, broker, lado}]`.
5. `preview_payload["cambian_un_pase"]`: el resultado de `pase_que_cambia` sobre las filas que quedan después de deduplicar. La pantalla lo muestra como bloqueante (E.7).
6. `list_batches` (`:1980-1990`): para `parser_format='traspaso_a_mano'`, agregar `traspaso: {id, asset, cantidad, lado, contraparte, estado}`.

### D.3 `importing/persister.py`
1. Despacho de `persist_batch` (`:479-523`), antes del `else`:
   ```python
   elif op in OPERATION_TYPES_INTERNOS:
       if not getattr(tx, "traspaso_id", None):
           raise PersistError(tx.row_index, "Fila interna de pase sin pase.")
       pass          # no mueve caja ni posiciones: la leen el recálculo y los aportes
   ```
2. `_persist_buy` (`:707-742`):
   ```python
   fecha_compra = getattr(tx, "fecha_compra", None)
   entry_date = fecha_compra or tx.date
   en_broker_desde = tx.date if fecha_compra else None
   # _tc: si falta y el lote es ARS → _tc_for_date(conn, entry_date)   (antes: tx.date)
   # INSERT … entry_date=entry_date, + columna en_broker_desde
   if cost_total > 0 and not getattr(tx, "traspaso_id", None):     # :738-740
       helpers._adjust_broker_cash(...)
   ```
3. `_persist_sell_fifo` (`:745-1044`), cuando `getattr(tx, "traspaso_id", None)`:
   - (a) si `qty_to_sell > total_avail + 1e-9` (`:839`) → `raise PersistError(tx.row_index, "No alcanzan los títulos para el pase.")`, sin lote semilla;
   - (b) no se hacen el `INSERT INTO operations` (`:1001-1013`), el `_link(... operation_id=…)` ni `_resultado_dual.guardar` (H21);
   - (c) no se llama a `_update_monthly_pnl_realized` (`:1037-1039`).

   El bucle pasa a usar `tramo.costo_y_resultado_del_tramo`.
4. `revert_batch` (`:1558`), después del chequeo de estado (`:1582-1583`):
   - si `batch["parser_format"] == "traspaso_a_mano"` → `raise PersistError(0, MSG_REVERT_ES_PASE)` = «Este lote es un pase de títulos entre tus brokers: no se revierte desde acá. Deshacé el pase entero desde Movimientos (la fila «Pase» → Deshacer).»;
   - si alguna fila del lote es `fila_origen` de un pase con `deshecho_at IS NULL` (`traspaso_a_mano.filas_origen_vivas`) → `PersistError(0, "Hay títulos de esta importación que pasaste a {B} el {dd/mm/aaaa}. Deshacé ese pase antes de revertir el archivo.")`;
   - si `pase_que_cambia(conn, uid, <filas BUY/SELL vivas del lote>)` → `PersistError(0, MSG_CAMBIA_UN_PASE)`.

   Al vivir en la primitiva, cubre el revert, «Editar y rehacer» (`main.py:50361`) y el deshacer de tandas del asesor (`_revert_batch_de`, `main.py:50333`).

### D.4 `importing/tramo.py` (nuevo)
`costo_y_resultado_del_tramo` (C.5). Lo usan `_persist_sell_fifo`, `_replay_asset` y `traspaso_a_mano`. **Sale en dos pasos** (G.1, E2a/E2b): primero las pruebas con los valores congelados del código actual, después la extracción.

### D.5 `importing/rebuild.py`
1. `_full_events` (`:554-580`): sumar `n.traspaso_id, n.fecha_compra` al SELECT.
2. `_replay_asset` (`:236-537`):
   - BUY (`:264-300`): `"entry_date": ev.get("fecha_compra") or ev["date"]`, `"en_broker_desde": ev["date"] if ev.get("fecha_compra") else None`, `"_seq": <contador de llegada>`;
   - SELL (**H2**, `:371-388`): `_same` y `_other` se ordenan por `(l["entry_date"] or "9999-12-31", l["_seq"])` antes de armar `_consume_from`. La semilla sigue yendo al final. Con los datos de hoy no cambia nada (`entry_date == date`);
   - SELL con `ev.get("traspaso_id")`: consume igual pero **sin** `operations.append` (`:495`). A cambio, agrega a `traspasos[traspaso_id]` el `{entry_date, qty, invested, commissions, currency, batch_id, raw_row_id}` de cada tramo;
   - salida: `{"operations", "open_lots", "traspasos", "llegadas_de_pases": {traspaso_id: date}, "semillas": [date, …]}`;
   - el cálculo del tramo pasa a `tramo.costo_y_resultado_del_tramo`.
3. `_cancel_conduit_pairs` (`:116-221`): excluir de `buys` y `sells` los eventos con `traspaso_id`.
4. `_write_rebuilt` (`:811-851`): el INSERT de `positions` lleva `en_broker_desde = lot.get("en_broker_desde")`.
5. `rebuild_fifo_after_import` (`:885`) y `rebuild_pair_asset` (`:1020`), después de `_write_rebuilt`: `traspaso_a_mano.marcar_desfasados(conn, uid, replay)`. `rebuild_pair_asset` también devuelve `"traspasos"`.

### D.6 `importing/traspasos.py` (el traspaso automático)
`cerrar_origen_de_traspasos` (`:231-251`): parámetro nuevo `ya_traspasadas=()`. Las `entradas` del lote excluyen `t.row_index in ya_traspasadas`.

### D.7 `importing/traspaso_a_mano.py` (nuevo): qué expone

- Constantes: `FORMATO = "traspaso_a_mano"`, `BASE_ROW_INDEX = -49999`, `DIAS_TRASPASO_TARDIO = 60`, las notas de A.6 y los mensajes de B.6, C.8 y C.11 (`MSG_DESHACE_EL_PASE`, `MSG_REVERT_ES_PASE`, `MSG_CARTERA_CAMBIO`, `MSG_NO_SE_GUARDO`, `MSG_CAMBIA_UN_PASE`, `MSG_IMPORT_CAMBIA_UN_PASE`).
- `class PaseInvalido(Exception)` con `status` y `detalle`.
- `precargar(conn, uid, pedido)`: todo lo que va a la red (splits, dólar cripto). Se llama fuera de la transacción.
- `cuentas_del_pedido(conn, uid, pedido) -> Cuentas`: validaciones 1–7, patas y familia.
- `armar_plan(conn, uid, pedido, *, hoy, helpers, para_confirmar, cuentas=None) -> Plan` (B.6, C.1–C.6, C.9). Sólo lee.
- `aplicar_plan(conn, uid, plan, *, helpers) -> dict` (C.7).
- `validar_deshacer(conn, uid, traspaso_id) -> Registro` y `deshacer(conn, uid, registro, *, helpers) -> dict` (C.8).
- `traspasos_vivos(conn, uid) -> list[dict]` (B.5).
- `filas_ya_traspasadas(conn, uid, txs) -> Resultado(indices: set, detalle: list, avisos: list, frenos: list)`. Es el antiduplicado semántico (decisión 7). Considera pases con `deshecho_at IS NULL`: del lado entrada con el lote B `confirmed`, del lado salida con el lote A `confirmed`.
  - **Entrada:** una `tx` BUY con `transfer_in` o `"IEB:DETR" in notes`, broker entre las patas de B, el mismo activo canónico, `tx.quantity ≤ presupuesto_entrada + 1e-6`, donde `presupuesto_entrada` = Σ de las BUY del pase en esas patas:
    - \|date − fecha\| ≤ `flujos.DIAS_CRUCE` (4, `flujos.py:20`) → se omite y se descuenta del presupuesto. Se omite también **su DEPÓSITO hermano**: misma pata, misma fecha, misma moneda, `notes` con «entrada de título» o «IEB:DETR», y \|monto − tx.gross_amount\| ≤ max(1 %, 1 unidad), uno por uno;
    - 4 < \|date − fecha\| ≤ 60 → va a `frenos`, y el confirm responde 409: «El archivo de {B} dice que los {asset} llegaron el {dd/mm} y el pase lo anotaste el {dd/mm}. Para no contarlos dos veces, deshacé el pase y hacelo de nuevo con fecha {dd/mm}; después importá el archivo.»;
    - más de 60 días → entra normal, con un aviso.
  - **Salida:** una `tx` SELL con `transfer_out`, que no sea de foto (`notes` que no empiece con «Tenencia»), broker entre las patas de A, el mismo activo, `tx.quantity ≤ presupuesto_salida + 1e-6`, donde `presupuesto_salida` = Σ de las **SELL del pase** en esas patas, o sea sólo la parte importada. Las mismas tres ventanas y el texto espejo.
    - Si un Débito supera el presupuesto (incluye lotes que eran cargados a mano y salieron por `positions`), no se omite: el mismo archivo trae las compras de esos lotes, y `pase_que_cambia` frena la importación entera (C.11).
  - Ante la duda, se omite de menos (PLAN §12.1).
  - Lo omitido se anota en `traspasos_a_mano.omitidas_json` (`[{batch_id, row_index, lado}]`) en la misma transacción del confirm.
- `pase_que_cambia(conn, uid, filas, *, excluir=None)` (C.11).
- `lotes_en_pases_vivos(conn, uid) -> set[int]`: los `lote_id` de las recetas con `deshecho_at IS NULL`.
- `filas_origen_vivas(conn, uid) -> dict[(batch_id, raw_row_id) -> (B, fecha)]`.
- `lotes_a_mano_que_salieron(conn, uid) -> list[{broker, asset, entry_date, fecha_pase, cantidad, invested, commissions, currency, tc_compra, traspaso_id, k}]`. Sólo de pases con `deshecho_at IS NULL` **y el lote A `confirmed`**. Si A se borró, esos lotes ya no son de ningún broker.
- `llegadas_por_lote(conn, uid) -> {(raíz, asset, fecha_compra): fecha_pase}`, desde las BUY vivas con `traspaso_id`.
- `marcar_desfasados(conn, uid, replay)`:
  - **origen:** para cada `traspaso_id` de `replay["traspasos"]`, compara el multiconjunto `(entry_date, qty, invested)` consumido contra las BUY vivas del lote B que en la receta son `origen='importado'`;
  - **destino:** si `replay["semillas"]` tiene una fecha anterior a algún `replay["llegadas_de_pases"][id]`, ese pase queda desfasado por destino;
  - si no coincide → `desfasado_at = datetime('now')` y `desfasado_motivo` (si estaba NULL);
  - si vuelve a coincidir y el motivo era el de ese lado → los dos a NULL.
- `entradas_y_salidas_del_periodo(conn, uid, brokers, desde, hasta, *, por_mes=False) -> {entrada_valor_usd, entrada_costo_usd, salida_valor_usd, salida_costo_usd, puente_usd, gasto_usd}`, o un dict por mes. Para `'global'` se calcula el neto por traspaso de las patas vivas: vale 0 si viven las dos.
- `revaluar_patas(conn, uid)` (C.10).
- Todas las lecturas del registro usan `TX_VIVAS`, salvo las anotadas en `LEEN_EL_LOG`.

### D.8 `main.py`: capital, aportes y recálculo

1. Fragmento SQL nuevo, al lado de `_FX_PATA_*` (`main.py:855-872`):
   ```python
   _TRASPASO_PATA_DONDE_SQL = """b.user_id=?
                      AND n.operation_type IN ('TRASPASO_SALIDA','TRASPASO_ENTRADA')
                      AND n.date IS NOT NULL AND n.date LIKE '____-__-__%'"""
   ```
2. `_traspaso_legs_for_period(conn, uid, broker, y, m) -> (dep_usd, wit_usd)`, nuevo, al lado de `_fx_transfer_legs_for_period` (`:875`):
   - **broker real:** `dep = Σ COALESCE(valor_usd,0)` de `TRASPASO_ENTRADA` con `n.broker=?`, y `wit` igual con `TRASPASO_SALIDA`;
   - **`'global'`:** `SELECT n.traspaso_id, SUM(CASE op WHEN 'TRASPASO_ENTRADA' THEN valor_usd ELSE -valor_usd END) neto … GROUP BY n.traspaso_id`. Después `dep = Σ max(neto,0)` y `wit = Σ max(−neto,0)`; un \|neto\| < 0,005 cuenta como 0;
   - `except ERR_OPERACIONAL: return 0.0, 0.0`.
3. `_resultado_de_traspasos_for_period(conn, uid, broker, y, m) -> dict`, nuevo, con tres valores:
   - `puente_salida` = Σ (valor_usd − costo_usd) de las SALIDA;
   - `puente_entrada` = Σ (valor_usd − costo_usd) de las ENTRADA;
   - `gasto` = Σ `valor_usd` de las FEE con `traspaso_id`.

   Lo que entra al resultado del broker es `puente_salida − puente_entrada − gasto`. En `'global'` se suma sin filtro de broker, y eso ya da el neto de las patas vivas. [D] El gasto cuenta como pérdida del broker que lo pagó. Si no, la FEE baja la caja sin ningún flujo (el recálculo cuenta sólo DEPOSIT/WITHDRAW, `main.py:859-860`) y la identidad «capital = costo + caja» se corre en el monto del gasto. El de las comisiones importadas comunes es un hueco que ya existía (H19) y no se toca acá.
4. `_import_flows_for_period` (`:943-979`): al final, `t_dep, t_wit = _traspaso_legs_for_period(...)` y `return dep + fx_dep + t_dep, wit + fx_wit + t_wit`. Lo heredan `_derive_manual_flows` (`:1249`), el formulario `/mensual` (H14) y `_backfill_manual_flows`.
5. `_import_flows_por_mes` (`:982-1045`): una consulta más, agrupada por `(n.broker, y, m, n.operation_type)` sobre `_TRASPASO_PATA_DONDE_SQL`: ENTRADA al índice 0 y SALIDA al 1. Hay que sumar el caso en `test_conversion_en_movimientos.py::FlujosImportadosPorMes`.
6. **Aportes en pesos, en campos aparte.** [D] [V: `capitalAportado.js:192-247`] En la tabla global, el frontend le resta a la fila 'global' los dólares de cada broker. Si las patas fueran dentro de `pesos_importados_*`, el resto daría negativo y taparía la regla del dólar de su día. Por eso:
   - `_aportes_en_pesos_por_mes` (`:1048-1143`) y `_aportes_en_dolares_con_dia` (`:1146+`) **no** incluyen las patas;
   - función nueva `_patas_de_traspaso_por_mes(conn, uid)`:
     - por (broker, y, m), las patas en pesos van como `traspaso_pesos_dep`/`_dep_usd` y `traspaso_pesos_ret`/`_ret_usd` (`valor_ars` y `valor_usd`, ENTRADA en dep y SALIDA en ret);
     - las patas en dólares van como `traspaso_usd_con_dia: {dep: [[fecha, valor_usd]], ret: […]}`;
     - para `'global'`, sólo el neto por traspaso de las patas vivas: `traspaso_neto_pesos` y `traspaso_neto_usd` (son 0 si viven las dos).
7. `_recalc_pnl_realized_from_ops` (`:17023-17305`):
   - (a) siembra, después del bloque FX (`:17093-17118`): `SELECT DISTINCT n.broker, y, m FROM {tx_vivas('n','ib')} WHERE ib.user_id=? AND (n.operation_type IN ('TRASPASO_SALIDA','TRASPASO_ENTRADA') OR (n.operation_type='FEE' AND n.traspaso_id IS NOT NULL)) …` → `_seed.add((b, y, m))` y `_seed.add(("global", y, m))`;
   - (b) `new_pnl = round(float(pnl_row["s"] or 0) + _r["puente_salida"] − _r["puente_entrada"] − _r["gasto"], 4)` (`:17172`), con `_r = _resultado_de_traspasos_for_period(...)`.

   La cadena cierra al costo con `ci + dep − wit + pnl_realized` (`:17363-17365`), y la identidad por broker se mantiene: A queda con C + 0 − V + (V−C) − g = −g = su caja; B queda con 0 + V − (V−C) = C = su costo.
8. `GET /api/monthly` (`main.py:20733`). Cada fila suma, sólo si son distintos de 0:
   - `puente_salida_usd`, `puente_entrada_usd`, `gasto_pase_usd`;
   - los campos de D.8.6;
   - **el puente en pesos.** [V] `realized_ars` sale sólo de las operaciones (`main.py:20759-20768`), y la pantalla pasa el resto al dólar del mes con un cartel (`realizadoEnPesos.js:37-45`). Para las patas en pesos de las filas de broker, `realized_ars += (valor_ars − costo_nativo)` de las SALIDA y `−(valor_ars − costo_nativo)` de las ENTRADA, y `realized_ars_cubre_usd += ±(valor_usd − costo_usd)`. En la fila global, el neto de las vivas. Así la pestaña en pesos muestra V_ars − C_ars exacto y sin cartel.
   - Lo mismo en `export_monthly_csv` (`main.py:~24420`, `pnl_realized_ars`).
9. `_import_helpers` (`main.py:46803`): sumar `_manual_flow_rate`, `_pata_de_la_moneda` y `_devolver_al_lote`.
10. `_plata_de_fila_importada` (`main.py:22065-22100`). [D] Es el espejo de lo que hizo el persister: una BUY con `traspaso_id` devuelve `(cuenta, 0.0)`. Las guardas impiden borrar esas filas, pero los journals viejos y cualquier lector futuro tienen que ver lo mismo que hizo el persister.

### D.9 `main.py`: Movimientos, CSV y comisiones

1. `_build_movements` (`:21512`), bucle de filas importadas (`:21722-21800`):
   - el SELECT agrega `t.traspaso_id, t.valor_usd, t.valor_ars`;
   - `if d.get("traspaso_id") and op_type in ("BUY", "SELL"): continue`. Saca la BUY de B (si no, su comisión se cuenta dos veces en el KPI y en `/api/insights/commissions`, H5) y la SELL de A con su «Reabrir»;
   - TRASPASO_* → fila con `type` igual al op, `amount_usd = valor_usd`, **`fx_to_usd = valor_ars / valor_usd`** (así la vista en pesos muestra `valor_ars` y no lo convierte al dólar del día), `fees_usd = 0`, `quantity`, `asset`, `broker`, `traspaso_id`, `borrable: False`, `contraparte` y `estado` (de un diccionario precargado `{traspaso_id: (raíz_A, raíz_B, estado)}`);
   - FEE con `traspaso_id`: igual que hoy, más `traspaso_id` y `borrable: False`.
2. `_build_movements`, después de los lotes cargados a mano (`:21863-21910`): por cada elemento de `lotes_a_mano_que_salieron`, una fila `type "BUY"` con:
   - `id f"trp-{traspaso_id}-{k}"`, `date = entry_date`, `broker` = la pata de A y la cantidad movida;
   - `amount_usd` y `fees_usd` calculados como en `:21876-21885`;
   - `source "traspaso"` y `borrable: False`.

   Así la compra original de un lote cargado a mano no desaparece de Movimientos, y el KPI de comisiones no cambia.
3. `export_transactions_csv` (`:24134`), bucle del registro (`:24160-24183`):
   - se saltean las BUY y SELL con `traspaso_id`;
   - TRASPASO_* → `tipo = _humanize_tx_type(op)`, `monto = valor_ars` si la moneda es ARS o `valor_usd` si no, `notas = "pasaron a {contraparte} · costo original US$ {costo_usd}"`;
   - las compras cargadas a mano del punto 2, como COMPRA, en la sección de posiciones manuales (`:24277-24304`).
4. `_humanize_tx_type` (`:24371`): `"TRASPASO_SALIDA": "TRASPASO (SALE)"` y `"TRASPASO_ENTRADA": "TRASPASO (ENTRA)"`.
5. Diagnóstico de admin «Total EXACTO como get_commissions_total» (`main.py:~29417`): excluir `n.traspaso_id IS NOT NULL AND op='BUY'`.

### D.10 `main.py`: guardas de borrado, deshacer y escritura

En toda esta sección, «pase vivo» = `deshecho_at IS NULL`.

| # | Lugar | Cambio |
|---|---|---|
| 1 | `_route_tx_delete` (`:23724`) | El SELECT agrega `n.traspaso_id`. Si no es NULL → `HTTPException(409, MSG_DESHACE_EL_PASE)`. Si es NULL y `pase_que_cambia(conn, uid, [esa fila])` → 409 `MSG_CAMBIA_UN_PASE`. `MSG_DESHACE_EL_PASE` = «Esto es parte de un pase de títulos entre tus brokers. Para sacarlo, deshacé el pase entero: Movimientos → la fila «Pase» → Deshacer.» |
| 2 | `_delete_position_cascade` (`:26192`), después de leer `src` | si `src["traspaso_id"]` → 409 `MSG_DESHACE_EL_PASE`; si `(batch_id, raw_row_id) in filas_origen_vivas` → 409 «Parte de esta compra se pasó a {B} el {dd/mm}. Para borrarla, primero deshacé ese pase.»; si `pase_que_cambia(conn, uid, [src])` → 409 `MSG_CAMBIA_UN_PASE` |
| 3 | `_borrar_posicion` (`:26134`) | si `pid in lotes_en_pases_vivos` → 409 «Parte de este lote se pasó a otro broker. Para borrarlo, primero deshacé ese pase.» |
| 4 | `_delete_asset_history_cascade` (`:26425`) y `_borrar_activo_cargado_a_mano` (`:26168`) | si hay un pase vivo de ese activo → 409 «Este activo tiene un pase entre brokers. Deshacelo primero (Movimientos → la fila «Pase» → Deshacer).» |
| 5 | `import_redo` (`:50361`), después de leer `batch_row` | si `parser_format == "traspaso_a_mano"` → 400 `MSG_REVERT_ES_PASE`. El revert del lote original y las otras puertas las cubre D.3.4 |
| 6 | deshacer grupal del asesor (`main.py:~57195-57262`), dentro del bucle | si `it["position_id"] in lotes_en_pases_vivos(conn, cid)` → `skipped.append({"client_uid": cid, "reason": "se pasó a otro broker: deshacé primero ese pase"}); left_ok += 1; continue` |
| 7 | `_wipe_broker_data` (`main.py:34431`) | si alguna pata del broker está en un pase vivo → 409 «Este broker tiene títulos que pasaste a otro broker (o que llegaron desde otro). Deshacé esos pases antes de limpiarlo; si no, al reimportar vas a ver los títulos en los dos lados.» |
| 8 | `_contar_datos_de_brokers` (`:7247`) | sumar `"traspasos"`: COUNT de pases vivos cuyo `lote_salida` o `lote_entrada` sea un lote confirmado con `broker IN (nombres)` |
| 9 | `update_position` (`:15623`), en `:15641` | si `_actual and p.broker != _actual["broker"]` → 409 «Para pasar este lote a otro broker usá «Mover a otro broker» (en el menú ⋯ de la fila). Si lo cargaste en el broker equivocado, borralo y cargalo de nuevo en el correcto.» Reemplaza a `_exigir_broker_existente` en ese caso. Ver D.19 |
| 10 | `delete_broker` (`:7605`) | sin cambio de código además del punto 8 |
| 11 | `undo_delete_operation` (`:26342`) | para los borrados de filas importadas, antes de restaurar: `pase_que_cambia(conn, uid, <filas que vuelven>)` → 409 `MSG_CAMBIA_UN_PASE`. [V] No vence y hace `rebuild_pair_asset` (`:26342-26410`) |
| 12 | **Extracción:** `_devolver_al_lote(conn, uid, foto, cantidad, inv, com, *, link=None) -> dict` | sale del bloque de restauración de la venta manual (`main.py:25330-25372`). La venta manual pasa a llamarla, y el deshacer del pase también |
| 13 | foto de la venta manual (`main.py:20049-20066`) y su restauración | sumar `en_broker_desde` y `split_adjusted_through` a `"lot"` y al INSERT de `_devolver_al_lote` |
| 14 | `edit_position_group` (`:15524`, `_edit_position_group` `:15377`) | si cambia el ticker o el tipo y el (par, activo) está en un pase vivo → 409 «Este activo tiene un pase entre brokers. Deshacé primero el pase y después editalo.» [V] La edición se copia sólo a las BUY vinculadas (`main.py:15357-15376`); la SELL del pase y `traspasos_a_mano.asset` quedarían con el valor viejo |
| 15 | `_undo_edit_position_group` (`:15540`) | si el (par, activo) está en un pase vivo creado después de la edición que se deshace → 409, con el mismo texto |
| 16 | `import_confirm` (después del antiduplicado, `main.py:~48797`) | `pase_que_cambia(conn, uid, <txs que quedan>)` → 409 `MSG_IMPORT_CAMBIA_UN_PASE`; `filas_ya_traspasadas(...).frenos` → 409 con su texto. Va dentro de la transacción del confirm |

### D.11 `main.py`: splits
`_corporate_zero_dates` (`:16019-16038`):
- la fecha pasa a ser `COALESCE(n.fecha_compra, n.date)`;
- se agrega `AND NOT (n.operation_type='SELL' AND n.traspaso_id IS NOT NULL)`. La salida del pase no es un evento societario.

### D.12 `ledger_replay.py`
`cash_en` (`:97-162`): el SELECT agrega `n.traspaso_id`. En el bucle, `if r["traspaso_id"] and op == "BUY": continue`. La FEE del gasto sí cuenta. `tenencia_en` (`:38-85`) no cambia.

### D.13 `scripts/backfill_historical_mtm.py` (la historia a mercado)

1. **`_holdings_asof`** (`:524-570`). [V] Hoy agrupa por `n.broker, n.asset_symbol, n.asset_type` (`:550`), y una venta con otro tipo que sus compras cae en otro grupo, da cantidad negativa y se descarta (`:556-558`). Pasa entre lectores: Bull Market, PPI e IEB dejan el tipo en OTHER; Cocos y Balanz mandan CEDEAR o STOCK. Cambios:
   - (a) `GROUP BY n.broker, n.asset_symbol`, con `asset_type = MAX(CASE WHEN op='BUY' THEN n.asset_type END)`, igual que ya hace con la moneda (comentario `:560-566`);
   - (b) las SELL con `traspaso_id` restan `costo_nativo` de `buy_amt` y su cantidad de `buy_qty`. Así el costo promedio de lo que queda en A no hereda el de los lotes que se fueron;
   - (c) **ventas manuales de lotes del registro.** [D] Se resta, por `(lot.broker, lot.asset)` y con fecha ≤ `date_iso`, `lot.consumed` (y `lot.invested × consumed/quantity` de `buy_amt`) de cada 'Venta' en `operations` sin vínculo (`NOT EXISTS import_op_links.operation_id`), con `undo_meta_json.src='fifo_sell'`, cuyo `lot.id` figure como `position_id` en `import_op_links` de un lote `confirmed`. [V] `sell_position_fifo` no escribe el registro, y hoy esa compra queda en la historia para siempre. Le pasa ya a quien vende a mano un lote importado, y con el pase le pasaría a todo lote que era cargado a mano en A y se vende a mano en B.
2. `_tenencia_no_vista` (`:307-413`), H4:
   - (a) bucle de `positions`: el SELECT agrega `en_broker_desde`; `desde = r["en_broker_desde"] or r["entry_date"]`; `if desde and str(desde)[:10] > date_iso: continue`;
   - (b) **bucle nuevo** sobre `lotes_a_mano_que_salieron` (que ya filtra el lote A confirmado): si `entry_date <= date_iso < fecha_pase`, el lote estaba en A sin que el registro lo viera. Se cuenta con la misma regla de visto parcial (`vistos.get((broker_A, asset))`) y `_a_usd`;
   - (c) bucle de `operations`: `raiz` = {nombre: raíz} desde `brokers`; `llegada = llegadas_por_lote.get((raiz[r.broker], r.asset, ed))`; `if llegada and llegada > ed: ed = llegada`.
3. `huella_de_entrada` (`:728-829`):
   - sumar `en_broker_desde` al agregado de `positions`;
   - sumar un agregado de `traspasos_a_mano (id, deshecho_at)`;
   - sumar `n.traspaso_id, n.costo_nativo` al de BUY/SELL;
   - **subir `MOTOR_VERSION` de 3 a 4** (`:592`), porque cambia cómo se valúa (punto 1). Cada cuenta se rearma una vez al publicar.
4. `has_import` (`:909-918`): `… AND status='confirmed' AND COALESCE(parser_format,'') <> 'traspaso_a_mano'`. [D] Una cuenta 100 % cargada a mano no pasa a «reconstruible» por un pase. Al deshacerlo tampoco se borran fotos reconstruidas que habían reemplazado a las sintéticas.
5. `_cajas_explicadas` (`:432-482`): sin cambio. Hereda D.12.

### D.14 `resultado_dual.py`
`_compras_importadas` (`:381-398`): `AND COALESCE(n.fecha_compra, n.date)=?` (H18).

### D.15 `reporting/` y la IA

1. **Rendimiento con las patas al costo.** [V] Con filtro de broker, `bordes_mercado_periodo` devuelve None (`builder.py:906-907`), y el mes se mide con la contabilidad: Dietz de `start, end, dep−wit` (`:2609-2612`, fórmula `:1578-1589`) y la composición del año (`:2249-2270`). Con C = 1.000 y V = 1.200, A publicaba +50 % y B −33 %, y `leg_dudoso` no corta ninguno de los dos.

   [D] Para todo cálculo de **rendimiento**:
   `flujos_ret = (dep − wit) − (entrada_valor − entrada_costo) + (salida_valor − salida_costo)`, con los valores de `entradas_y_salidas_del_periodo` (por mes en la composición). Se usa en `_modified_dietz_pct`, en `leg_dudoso` y en el bucle del año, y `delta_usd = end − start − flujos_ret`. Con eso A da 0 − 1.000 + 1.000 = 0 y B da 1.000 − 0 − 1.000 = 0. El gasto no se saca: es una pérdida real. Las cifras brutas de Depósitos y Retiros quedan como están.
2. **Frases.** Las patas salen de `net_flow` en las frases «Aportaste/Retiraste» (`builder.py:3312-3315`, `:3366-3372`). Se agrega la frase «Pasaste títulos por US$ {V} {a\|desde} otro broker tuyo (costaron US$ {C}).» Como el «realizado» del reporte sale de las operaciones (`:1651-1652`) y no incluye el puente, la frase va junto a los flujos y no debajo del realizado.
3. `detectors.py:115` `detect_deposits_vs_gains`: `deps = report.metrics.deposits − (getattr(report.metrics, "traspaso_entrada_usd", 0) or 0)`.
4. `ai/builders/reports.py:157`: `realized_pnl_year_usd` resta el puente del año (`puente_salida − puente_entrada`, el gasto queda), y se agrega `traspasos_puente_year_usd`, documentado en `_field_docs`: «Diferencia entre el valor y el costo de los títulos pasados entre brokers del usuario. No es un trade cerrado.» [V] Hoy el campo se presenta como «Solo trades cerrados».

### D.16 `renombre_broker.py`
Sumar `("traspasos_a_mano", "receta_json")` a `COLUMNAS_JSON`.

### D.17 `importing/fx_migrate.py`
`migrate_user_fx` (`:263`): después del bucle de rebuild (`:397-410`) y antes de `recalc`, llamar a `traspaso_a_mano.revaluar_patas(conn, uid)` (C.10).

### D.18 Lugares revisados que no cambian, con el motivo (regla de propagación)

| Lugar | Motivo |
|---|---|
| `_fx_transfer_legs_for_period` | es otra fuente; la del pase va en su propio helper, sumado en el mismo lugar |
| `_is_safe_to_rebuild` (`rebuild.py:583`) | los lotes de B quedan vinculados y la SELL no crea 'Venta' |
| `_clear_old_state` (`rebuild.py:719`) | borra sólo 'Venta'. Por eso no se inventa un tipo 'Traspaso' en `operations`: se duplicaría en cada rebuild (H21) |
| `recompute_backfill.recompute_user` | rearma con el mismo rebuild, que ya entiende `traspaso_id`. Las patas tienen `gross_amount` NULL |
| `cobros_bonos.reparto_de_amortizacion` (`:285-291`) y `utils/pendingCashflows.js` (`:296`, `:454`) | sólo bonos [V: `generateSchedule`/`isBondTicker`], y los bonos están excluidos. **Si en la v1.1 se habilitan bonos**, hay que pasarlos a `COALESCE(en_broker_desde, entry_date)` |
| `sweep_matured_letras`, `sweep_bond_amortizations`, `_bond_genuine_net`, `nominales_originales` | bonos y letras excluidos |
| `proyeccion.proyectar` | el registro fechado al pase ya lo respeta (H13); la excepción está en G.2 |
| `proyeccion` (`:104`, `GROUP BY asset, asset_type` sobre `positions`) | después junta por clave comparable; no depende del tipo del registro |
| `cartera_hoy._lote_comprado_hoy`, `twr.py:394`, `behavioral.py:88` | quieren la fecha de compra original, que se conserva |
| `snapshots_job.take_snapshot_for_user` | misma familia y misma moneda de cuenta (C.1.4), así que misma valuación |
| Wallbit `_wallbit_apply_batch` | bloqueado (#6) |
| `realized_pnl.closed_filter_sql` y las exclusiones del frontend (`tradeStats.js:31`…) | no hay filas en `operations` |
| `_cambiar_tipo_del_lote` desde el `PUT` | con D.13.1 el tipo ya no parte la historia, y el replay no usa el tipo para consumir |

### D.19 Las dos decisiones del borrador, justificadas

**`PUT /api/positions/{pid}` con otro broker: se bloquea para todos los lotes, importados y cargados a mano.** [D]
- **Importados:** el próximo rebuild lo deshace o lo duplica (`rebuild.py:583-616, 734-741`).
- **Cargados a mano:** se rompe la receta (`_delete_manual_position_cascade` responde 409 para siempre si `meta.broker != broker`, `main.py:25570-25573`) y se rompe la identidad por broker.
- La corrección limpia ya existe: borrar el lote y cargarlo de nuevo.
- Hay que cambiar el contrato de `tests/test_borrar_broker_sueltos.py:509-510, 574-597`: mover a un broker existente o inexistente pasa a dar 409, con el mismo texto.

**`delete_broker` de A o B después del pase: se permite, con el 409 + `force` de siempre y el conteo «traspasos».** [D]
- La política `import_batches: revertir` revierte sólo el lote de ese lado, porque `import_batches.broker` es la raíz.
- El global ve el neto de las patas vivas:
  - si se borra A, B queda como si hubiera arrancado con esos títulos al valor del día;
  - si se borra B, A queda como si los hubiera vendido a V y retirado la plata.
- El pase queda «incompleto» y se puede deshacer lo que queda (C.8).
- «Limpiar broker» sí se frena (D.10.7).

---

## E. Frontend

Todo lo nuevo cumple `frontend/CLAUDE.md`:
- cero `font-mono`, `rounded-md`, colores hex y bifurcaciones por ancho;
- `Modal` para las dos anchuras;
- números con `tabular`;
- tokens `bg-bg-*`, `text-ink-*`, `border-line`.

`Positions.jsx` está congelado en el baseline: ninguna línea nueva con esas clases.

### E.1 Entrada

- `utils/positionActions.js:47` `buildPositionActions`: handler nuevo `onMove` e ítem `{ id: 'move', label: 'Mover a otro broker', icon: ArrowRightLeft, tone: 'accent', onClick: () => onMove(p) }`.
  - Va en la fila agregada (`:96-104`), en la fusionada (`:80-89`) y en la normal (`:138-146`).
  - Sólo si `puedeMoverse(p)`: no es efectivo, ni bono (`isBond`, **también en la rama agregada**), ni `FCI:`, ni Wallbit. [V] Hoy la rama agregada no mira `isBond` (`positionActions.js:62-104`).
- Cableado:
  - **compu:** los dos `buildPositionMenu` (`Positions.jsx:2753` y `:3004`) pasan `openMove`;
  - **celular:** `PositionRow` (`PositionsMobile.jsx:2891`) recibe `onMove` en sus dos montajes (`:1830`; `BrokerSection` `:2380`, pasado desde `:1801` y `:2503`).
- `openMove(p)` repite `openSell` (`Positions.jsx:910-928`) [V]:
  - `opciones = opcionesDeVenta(p._lots || [p], brokers)`: **los lotes de la fila tocada**, no todos los del activo;
  - si hay más de una → `setModal('move-selector')` con «¿Cuáles querés mover?» y `etiquetaDeVenta(o)`;
  - si hay una → calcula `destinosPosibles(opcion, brokers)`. Si viene vacío, no abre el modal: muestra `toast.push('No tenés otro broker donde pasar estos {asset}. Creá uno en Brokers y volvé a intentar.', { actionLabel: 'Crear broker', onAction: abrirAltaDeBroker })`. Si no, abre el modal.
  - En el celular, el selector `pataPara` (`PositionsMobile.jsx:3194-3240`) se extiende a «mover», con el mismo `p._lots || [p]`.

### E.2 Modal `components/cartera/MoverDeBrokerModal.jsx` (contenedor) + `VistaPreviaDelPase.jsx` (sólo dibuja)

[D] `renderToStaticMarkup` no corre efectos [V]. Por eso todo lo que se dibuja vive en `VistaPreviaDelPase({ plan, hidden, error, opcion })` y en `SelectorDeDestino({ destinos, valor, onCambio })`, que son puros. El contenedor sólo maneja el formulario y los pedidos.

Props del contenedor: `{ opcion, brokers, onClose, onHecho, onCrearBroker }`. Usa `Modal`, `useEnVuelo`, `DateInput max={hoyISO()}` y `usePrivacy`.

**Textos exactos:**
- Título: «Mover {asset} a otro broker». Bajada: «Desde {etiquetaDeVenta(opcion)}».
- «¿A qué broker?»: `<select>` con `destinosPosibles`; la última opción es «+ Crear un broker nuevo», que cierra el modal y llama a `onCrearBroker`. Ese callback abre el alta de siempre (`BrokerManager`, `Positions.jsx:1895, 2146`; `showAddBroker`, `PositionsMobile.jsx:1858`) con el toast «Creá el broker y volvé a «Mover a otro broker».».
- «¿Qué día llegaron a {B}?»: **sin valor por defecto**, con un botón «Hoy». La vista previa no se pide hasta que haya fecha. Ayuda: «Usá la fecha que figura en tu broker. Si después importás su archivo, Rendi la usa para no contar los títulos dos veces.»
- «Cantidad»: input `type="text" inputMode="decimal"` + botón «Todo». Ayuda: «Tenés {cantidad_disponible} que ya estaban en {A} ese día».
- Bloque plegado «Gasto del trámite (opcional)»: monto, y moneda sólo si A admite las dos. Ayuda: «Sale de la caja de {A}.»
- Vista previa: se pide 400 ms después del último cambio válido, y cancela el pedido anterior.
  - «Se mueven estos lotes (primero los más viejos):».
  - Por lote: «{cantidad} {asset} · comprados el {dd/mm/aaaa} · costo {fmtMoney(costo, moneda)}», más « · parte de un lote de {de_un_lote_de}» o « · cargado a mano» cuando corresponda.
  - «Valían {fmtMoney(valor_nativo, moneda_precio)} ({fmtUsd(valor_usd)}) el {dd/mm/aaaa} · {textoDeFuente}».
  - «Te costaron {fmtUsd(costo_usd)}.» y después:
    - si `puente_usd >= 0`: «En {A} va a figurar una ganancia de {fmtUsd(puente_usd)} hasta el pase, y en {B} arrancan valiendo {fmtUsd(valor_usd)}.»;
    - si es negativo: «En {A} va a figurar una pérdida de {fmtUsd(−puente_usd)} hasta el pase, y en {B} arrancan valiendo {fmtUsd(valor_usd)}.»;
    - siempre: «No es una venta: no cuenta en tus operaciones cerradas ni en los impuestos.»
  - Los `avisos`, uno por renglón, en `text-rendi-warn`.
- Con `hidden` del ojito se tapan los montos. Quedan a la vista cantidades, fechas y precio unitario.
- Si viene `codigo: 'sin_precio'`: campo «Precio de {asset} el {dd/mm/aaaa} (en {pesos|dólares})», y se vuelve a pedir con `precio_manual`.
- Errores: `errorMessage(e)` (`utils/api.js:619`) en rojo, arriba de los botones.
- Botones: «Cancelar» y «Mover {cantidad} {asset}». El segundo queda deshabilitado sin vista previa válida; mientras guarda dice «Moviendo…» y corre en `enVuelo.correr(...)`. Al confirmar manda el mismo cuerpo más `firma` y `valuacion`, tal como vinieron de la vista previa.

### E.3 Lógica pura

`utils/moverDeBroker.js`, nuevo, con su test:
- `destinosPosibles(opcion, brokers)`: cuentas raíz con `brokersParaElegir`, sin la de origen (`cuentaDe`, `utils/pataDeLaMoneda.js:28/45`), sin las de otra familia (la regla de C.1) y sin Wallbit;
- `cuerpoDeMover(form, opcion) -> {body} | {error}`, con `parseNum`;
- `textoDeFuente(fuente, fecha_precio, fecha_pase)`:
  - «cierre de ese día»;
  - «cierre del {día de la semana} {dd/mm}» cuando la vela es de otro día;
  - «último precio que tenemos»;
  - «precio que escribiste»;
  - «precio que cargaste a mano»;
- `lineaDeLote(l, fmt)` y `lineaDelPuente(plan, A, B, fmt)`.

[D] No se crea `utils/crearBroker.js` ni se migran las cuatro copias de `POST /brokers`. La decisión dice «con el flujo normal», y no se agrega una quinta copia.

### E.4 Después de confirmar

1. `onHecho(res)` → `loadAll()` (`Positions.jsx:511` / `PositionsMobile.jsx:785`), que recarga `/brokers`.
2. `toast.push('Listo: pasaste {q} {asset} de {A} a {B}.', { type: 'success', duration: 12000, actionLabel: 'Deshacer', onAction })`. `onAction` → `api.post(\`/positions/traspaso/${res.traspaso_id}/deshacer\`)` → `loadAll()` → `toast.push(res.mensaje)`. Si falla → `toast.push(errorMessage(e), { type: 'error' })`.
3. Analítica: `track('position_move_started', {source})`, `track('position_moved', {source})`, `track('position_move_undone')`.

### E.5 Dónde se ve y se deshace después

- **Movimientos** (`components/operations/shared.js`):
  - `TYPE_META` (`:33`): `TRASPASO_SALIDA: {label: 'Pase (salió)'}` y `TRASPASO_ENTRADA: {label: 'Pase (entró)'}`, con ícono `ArrowRightLeft` y tono neutro;
  - `MOVEMENT_TYPES` (`:80-92`): filtro nuevo «Pases»;
  - `puedeBorrarMovimiento` (`:73`) da `false` si `m.traspaso_id`;
  - en la fila: «{q} {asset} → {contraparte}» o «← {contraparte}». Si `estado === 'desfasado'`, un renglón en `text-rendi-warn`: «Cambió la historia de {A} y este pase quedó desactualizado: deshacelo y hacelo de nuevo.» Si `estado === 'incompleto'`: «{broker borrado} ya no existe.»;
  - en las filas TRASPASO_*, un botón «Deshacer pase» en lugar del tacho. Pide `GET /api/positions/traspasos`; si `puede_deshacer` es falso, muestra `motivo`. Si es verdadero: `await confirmar('¿Deshacer el pase de {q} {asset} de {A} a {B}?\n\n{texto según estado}', { si: 'Deshacer', no: 'Cancelar' })` → POST → recarga. Texto vivo: «Los títulos vuelven a {A} con su costo original, y si cargaste el gasto del trámite, vuelve a la caja.» Los textos de los incompletos están en C.8;
  - el KPI «Aportado neto» (`Operations.jsx:1788+`) no cambia.
- **Importaciones** (`pages/Imports.jsx:87-121, 525-549`): si `batch.traspaso`, el título es «Pase de {cantidad} {asset} {a|desde} {contraparte}», **sin** «Revertir», «Forzar revert» ni «Editar y rehacer», y con el rótulo «Para deshacerlo, usá Movimientos → la fila «Pase».». No lleva botón propio.

### E.6 Edición de lote

`PositionFormModal` (`Positions.jsx:4161`) lo usan las dos pantallas (`PositionsMobile.jsx:2071, 2089`) [V]:
- prop nueva `onMove`;
- en modo edición, el `<select>` de broker (`:4402-4409`) se reemplaza por texto `{form.broker}` y un botón link «Mover a otro broker», que cierra la edición y llama a `onMove`;
- sin `rounded-md` ni `font-mono`;
- los dos montajes pasan `onMove`;
- el `PUT` sigue mandando el mismo broker.

### E.7 Bandejas, /mensual, aportado, importar y borrar broker

- `utils/dividendosPendientes.js:177`: `!(p.en_broker_desde || p.entry_date) || (p.en_broker_desde || p.entry_date).slice(0,10) < exDate`.
- `utils/resultadoDelMes.js`, nuevo: `resultadoSinPuente(m) = (m.pnl_realized||0) − ((m.puente_salida_usd||0) − (m.puente_entrada_usd||0))`. Lo usa todo cálculo de **rendimiento** sobre filas de /api/monthly:
  - `components/MonthlySummary.jsx` `:460-461` (totales y compuesto) y `:648-649` (fila);
  - antes de cerrar la etapa, revisar con grep los demás lectores de `capital_inicio` que calculan rendimiento (`utils/insightsModel.js`, `hooks/useMonthlyData.js`, `pages/Insights.jsx`, `utils/benchmarkSim.js`, `pages/Dashboard.jsx`) y listar cuáles se cambiaron y por qué. En el caso común (las dos patas vivas) la fila global trae 0.
- `components/MonthlySummary.jsx`, debajo del realizado de la fila (`:757` y la tarjeta `:843`), en `text-ink-3`, una línea por concepto distinto de 0:
  - salida: «Incluye una {ganancia|pérdida} de {fmtUsd(|x|)} de los títulos que pasaste a otro broker (no es una venta).»;
  - entrada con V > C: «Descuenta {fmtUsd(x)}: los títulos que llegaron desde otro broker ya traían esa ganancia (no es una pérdida).»;
  - entrada con V < C: «Suma {fmtUsd(|x|)}: los títulos que llegaron desde otro broker ya traían esa pérdida.»;
  - gasto: «Incluye {fmtUsd(g)} del costo del pase.»

  En la pestaña en pesos, los montos salen de `realized_ars` (D.8.8).
- `utils/capitalAportado.js` (`:192-247`): en la tabla de un broker, `traspaso_pesos_*` y `traspaso_usd_con_dia` se suman como `pesos_importados_*` y `usd_con_dia.importado`. En la global se ignoran los campos de broker y se usan sólo `traspaso_neto_pesos`/`traspaso_neto_usd` de la fila global.
- Reportes: la frase de D.15.2, en la tarjeta del período.
- `utils/avisoBorrarBroker.js` `partesDelBorrado`: `if (n('traspasos') > 0) partes.push(\`${plural(n('traspasos'), 'pase', 'pases')} de títulos con otro broker tuyo (los títulos que llegaron al otro broker se quedan allá; si después reimportás este broker, van a aparecer en los dos lados)\`)`.
- ImportWizard:
  - si `preview.ya_traspasados` tiene filas: «Estas filas ya las cargaste con «Mover a otro broker»: no se cuentan de nuevo.» y la lista;
  - si `preview.cambian_un_pase` tiene algo: un bloque rojo con el texto de `MSG_IMPORT_CAMBIA_UN_PASE` y el botón confirmar deshabilitado.

### E.8 Modo demo

- `utils/demo.js:4245` `_BASES_DEL_VISITANTE`: sumar `'/positions/traspaso'`. Por prefijo bloquea el confirmar, la vista previa y el deshacer (`_esEscrituraDelVisitante`, `:4258-4263`).
- GET explícito, al lado de `:3398`: `if (basePath === '/positions/traspasos') return { habilitado: true, traspasos: [] }`.
- `utils/demoPlomeria.test.js:103-120`: sumar las tres rutas POST al `it.each` de bloqueadas.
- `__guards__/demo-contesta-todo.test.js`: no hay que anotar nada. [V] `laContesta` acepta cualquier respuesta no nula (`:82-89`), y `blocked()` devuelve un objeto.
- Los brokers del demo son de familias distintas, así que `destinosPosibles` viene vacío y el ítem muestra el toast de E.1, no un modal vacío.
- Si para entonces entró la guardia de escrituras `9bd6e23d` (`LISTO_MUDO`/`RUTA_ARMADA_APARTE`), anotar la llamada con `${id}` en `RUTA_ARMADA_APARTE`.

### E.9 `utils/api.js`
`LECTURAS_POR_POST` (`:513`): sumar `'/positions/traspaso/vista-previa'`.

### E.10 Tests de frontend

| Archivo | Qué prueba |
|---|---|
| `utils/positionActions.test.js` | el ítem aparece en las filas normal, agregada y fusionada; no en efectivo, bono (incluida la agregada), FCI ni Wallbit. Guardia de texto: las dos pantallas pasan `onMove` |
| `utils/moverDeBroker.test.js` | destinos (excluye la misma cuenta, otra familia y Wallbit); `cuerpoDeMover` con «1.000,5»; textos de fuente, incluido «cierre del viernes 20/11» |
| `components/cartera/VistaPreviaDelPase.render.test.jsx` | con `renderToStaticMarkup` y un `plan` armado: una línea por lote; con `hidden` los montos tapados y las cantidades visibles; error visible; texto de ganancia y de pérdida según el signo |
| `utils/resultadoDelMes.test.js` | `resultadoSinPuente` con salida, entrada y gasto |
| `utils/capitalAportado.test.js` | pase + aporte en dólares con día en el mismo mes: el global en pesos da lo mismo que sin el pase |
| `utils/dividendosPendientes.test.js` | un lote con `en_broker_desde` posterior al corte no se propone |
| `__guards__/envios-con-dueno.test.js` | sumar a `LIBRES`: `'components/cartera/MoverDeBrokerModal.jsx\|/positions/traspaso/vista-previa': 'es una lectura: arma la vista previa del pase; el servidor no guarda nada'` [V: la guardia exige que todo `api.post` dentro de un efecto o `setTimeout` esté clasificado, `:3-46`] |
| `utils/demoPlomeria.test.js` | E.8 |
| `__design__/design-contract.test.js` | los archivos nuevos en 0; si `Positions.jsx` cambia sus totales, regenerar el baseline (no pueden subir) |
| `__guards__/ocultar-saldos-censo.test.js` | `VistaPreviaDelPase` usa `usePrivacy` (o recibe `hidden` del contenedor, que la usa) |
| `reglaDeLosHooks.test.js`, `fecha.test.js`, `try-catch-scope`, `nombres-sin-definir` | que sigan en verde |

---

## F. Plan de pruebas del backend

### F.1 Arnés, por el mismo camino que producción

Archivo nuevo `backend/tests/test_mover_entre_brokers.py`, con un `_Cuenta` copiado de `tests/test_reconstruccion_aportado_canonico.py:72-160`:
- usuario con email `uuid4` e `is_admin=1`;
- **token real** `main.create_token(uid)`. Nunca `dependency_overrides`: saltea `_contabilidad_tocada` (`main.py:5074-5075`);
- imports por HTTP (`POST /api/imports/preview` + `/confirm`, `rendi_generic`) o con los archivos de prueba de `test_traspaso_entre_brokers.py` (Bull Market y Balanz «Transferencia Externa (Crédito)»);
- lotes cargados a mano con `POST /api/positions`;
- precios sembrados en `asset_last_price` y `velas_diarias`; el dólar sembrado en `fx_rates_daily` o con `mock.patch.object(fx, "fx_for_date", …)`; para la historia, `bf._fetch_monthly_close = …` y `mock.patch.object(main, "_fetch_data912_bonds", return_value={})`; splits sembrados (sin red);
- después de cada POST, esperar `main._MTM_RUNNING`;
- interruptor `mover_entre_brokers` prendido en el `setUp`;
- limpieza con `tests/_limpieza.vaciar`.

`estado()`, extensión del de `test_operaciones_con_receta.py:164`:
- caja por broker;
- lotes por broker (`asset, quantity, invested, commissions, entry_date, en_broker_desde, tc_compra, currency, asset_type`, ordenados sin ids);
- cantidad de 'Venta';
- `monthly_entries` (broker y global: `deposits, withdrawals, pnl_realized, capital_final`);
- aportado global `snapshots_job.compute_net_deposited_db` y por broker;
- `GET /api/insights/commissions`;
- tipos de `GET /api/movements`;
- filas de `GET /api/export/transactions.csv`;
- **fotos medidas**: `total_value` y `net_deposited` de las no sintéticas, excluida la de hoy.

**«Después del rebuild» quiere decir esto:** `importing.recompute_backfill.recompute_user(conn, uid, recalc=main._recalc_pnl_realized_from_ops)` y commit, o `POST /api/admin/backfill-recompute?apply=true&safe_only=false`. [V] Sin `apply=true` ese endpoint corre sobre una copia y no toca la base (`main.py:27652-27662`), y en Postgres da 501.

### F.2 Tests nuevos

| # | Nombre | Qué mide |
|---|---|---|
| 1 | `test_pase_total_importado_lleva_costo_y_fecha_original` | A importado con 2 compras (d1 < d2), B vacío, pase de todo con fecha hoy. A sin NVDA; B con 2 lotes `entry_date` d1/d2, `en_broker_desde` = hoy, y `invested`/`commissions`/`tc_compra` idénticos; 0 'Venta' nuevas; cajas iguales. Después del rebuild real (F.1): `estado()` idéntico. Además `POST /api/imports/{lote original de A}/redo` da 400 y el pase queda intacto |
| 2 | `test_pase_parcial_parte_el_ultimo_lote_en_proporcion` | 3 lotes, mover 1,5 lotes: proporciones exactas (1e-6) y A+B = antes; un lote cargado a mano sin `invested` usa `costo_del_lote` |
| 3 | `test_mezcla_a_mano_e_importados_y_fifo_posterior_en_b` | A con un lote cargado a mano viejo + importados; el cargado a mano sale de `positions` y queda en la receta. Después se importa una venta en B: el persister **y** el rebuild consumen primero el de fecha más vieja (H2) |
| 4 | `test_aportado_y_puente_por_broker_y_global` | V ≠ C. A: `withdrawals` = V, `pnl_realized` = V−C. B: `deposits` = V, `pnl_realized` = −(V−C). Global: igual que antes. `capital_final` de A baja C y el de B sube C |
| 5 | `test_recalculo_y_mensual_no_lo_vuelven_manual` | `GET /api/monthly` igual antes y después de `POST /api/imports/recalc-pnl`; no aparece «Depósito manual»; un `PUT /api/monthly` sobre ese mes conserva las patas (H14) |
| 6 | `test_sin_ventas_ni_estadisticas` | `GET /api/operations`, % de acierto y `operations.csv` iguales; `transactions.csv` con «TRASPASO (SALE)/(ENTRA)» y sin COMPRA/VENTA de más |
| 7 | `test_kpi_comisiones_igual_antes_y_despues` | `/api/insights/commissions` igual, también con un lote cargado a mano movido (fila `trp-`) |
| 8 | `test_caja_intacta_y_gasto_como_perdida_de_a` | sin gasto, cajas iguales; con gasto ARS 5.000 → caja de A −5.000, `pnl_realized` de A incluye −gasto_usd, y la identidad «capital = costo + caja» de A se cumple; deshacer → todo vuelve |
| 9 | `test_par_padre_y_usd` | Cocos + «Cocos · USD» (lote USD cargado a mano en la hija y CEDEAR USD importado en el padre, el de la hija más viejo) → Balanz sin hija. Se crea «Balanz · USD»; las SELL salen por tramo y cada una consume su pata; `_holdings_asof` de cada pata da bien. Cocos → «Cocos · USD» da 400. Un lote ARS en «Cocos · USD» va a la raíz de Balanz |
| 10 | `test_bloqueos_de_familia_tipo_y_wallbit` | ARS → USD, exchange, Wallbit, bono, FCI, efectivo y código de ticker viejo dan su status y su texto |
| 11 | `test_fecha_pasada` | (a) venta en A posterior → 409; (b) venta en B posterior → 409; (c) sin ventas: OK, meses de A y B sembrados, y la `mtm_coverage` de los meses entre la compra y el pase **no baja**. Se lee de la base (`SELECT mtm_coverage FROM snapshots …`, como `test_reconstruccion_sigue_a_la_contabilidad.py:525-536`) y no de `GET /api/snapshots`, que la saca (`main.py:8670`) [V]. Exige que antes haya al menos un mes con cobertura > 0, e incluye un lote cargado a mano movido (D.13.2b) |
| 12 | `test_deshacer_deja_la_cuenta_identica` | Fecha de pase de un mes anterior y fotos medidas plantadas (con `fx_to_usd_blue` y `holdings_json`) a mitad y a fin de mes entre la fecha y ayer, como `test_borrar_conserva_el_dia.py:163`. `estado()` antes del pase == después del deshacer, salvo la lista de brokers si se creó «· USD»; dos lotes `reverted`; `deshecho_at` puesto. Variantes: lote cargado a mano parcial; **importados y cargados a mano juntos con un importado parcial**; con un rebuild de A en el medio (una venta posterior de otro activo) |
| 13 | `test_deshacer_bloqueado_si_b_vendio_o_lo_paso` | venta en B → 409 «vendiste»; borrar la venta → OK. Pase B→C → deshacer A→B da 409 «los pasaste a C» |
| 14 | `test_deshacer_bloqueado_si_a_vendio_despues` | venta en A posterior al pase → 409; borrarla → OK. Pase posterior A→C → 409 «deshacé primero ese pase» |
| 15 | `test_import_de_b_despues_del_pase_no_duplica` | pase VIST Bull Market → Balanz; importar el archivo de Balanz con «Transferencia Externa (Crédito)» a ±4 días: misma cantidad en B, mismo aportado global, `preview.ya_traspasados` con la fila; también por `main.import_confirm(...)` y **con `include_duplicates=True`**; `omitidas_json` anotado |
| 16 | `test_import_de_b_con_otra_fecha_frena` | el mismo archivo con la llegada a 20 días: 409 con el texto de la fecha; a 90 días: entra con aviso |
| 17 | `test_import_de_a_despues_del_pase_no_duplica_la_salida` | archivo de A con Débito a +2 días: omitido, sin lote semilla ni 'Venta' de más. Si el pase incluyó un lote cargado a mano y el archivo trae su compra: 409 `MSG_IMPORT_CAMBIA_UN_PASE` |
| 18 | `test_import_de_b_antes_del_pase_frena_con_instrucciones` | importar B con la entrada → pase 409 (#13); borrar Compra y Depósito con `DELETE /api/movements/tx-…` → pase OK, sin doble conteo |
| 19 | `test_traspaso_automatico_ya_cerrado_frena` | cruce automático aprobado → pase del mismo activo 409 |
| 20 | `test_no_se_desarma_por_otras_puertas` | `/imports/{sid}/revert` 400, `/redo` 400, `DELETE /api/movements/tx-{venta del pase}` 409, `DELETE /api/positions/{lote B}` 409, historial del activo 409, revertir el import ORIGINAL de A 400, deshacer grupal del asesor salteado, editar en grupo el ticker 409 |
| 21 | `test_cambios_anteriores_al_pase_frenan` | importar en A una compra más vieja que los lotes movidos → 409; importar en B una venta anterior al pase → 409; borrar una fila vieja de A → 409; deshacer el borrado de una compra vieja de A → 409; importar en A una compra posterior → entra |
| 22 | `test_borrar_a_y_deshacer_lo_que_queda` | `DELETE /api/brokers/{A}` → 409 con `counts.traspasos`; con `?force=true` → global del mes `deposits` = V, `pnl_realized` = −(V−C); `GET /traspasos` dice `incompleto`; deshacer → B sin los títulos, global sin la pata, `deshecho_at` puesto |
| 23 | `test_borrar_b_y_deshacer_lo_que_queda` | el caso simétrico: los títulos vuelven a A con su costo |
| 24 | `test_limpiar_broker_con_pase_vivo_frena` | `POST /api/imports/wipe-broker` → 409 |
| 25 | `test_renombrar_a_y_b_y_deshacer` | `PUT /api/brokers/{id}` en los dos → deshacer devuelve a la A renombrada; la receta (incluida `brokers_usd_creados`) quedó con los nombres nuevos |
| 26 | `test_put_con_otro_broker_bloqueado` | 409 para importados y cargados a mano; editar sin cambiar el broker sigue en 200 |
| 27 | `test_vista_previa_no_escribe` (E5) | dos vistas previas: mismas cantidades de filas en `import_batches`/`positions`/`traspasos_a_mano`/`brokers`; misma firma |
| 28 | `test_firma_y_valuacion` (E6) | vista previa → cambiar `asset_last_price` → confirmar da 200 con el precio de la vista previa; confirmar con la firma vieja después de una compra nueva → 409; dólar corrido más de 3 % → 409 |
| 29 | `test_atomico` | tres fallas, cada una deja sin lote, sin posición, sin registro, sin «B · USD» y sin cambio de caja: (a) `mock.patch` de `_persist_buy` que levanta en las filas del pase → 500; (b) `PersistError` del freno de pesos → 409; (c) `_ensure_usd_sibling` con 409 → 409 |
| 30 | `test_idor` | usuario 2 con nombres de brokers del usuario 1 → 404 en vista previa y confirmar; deshacer el pase del usuario 1 → 404 |
| 31 | `test_cadena_y_meses_sembrados_en_broker_nuevo` | B creado ese mes sin otra actividad: tiene fila mensual y la cadena sigue |
| 32 | `test_rebuild_ordena_por_fecha_de_compra` (unitario `_replay_asset`) | una BUY con `fecha_compra` vieja que llega tarde se consume primero; sin `fecha_compra`, salida idéntica a la congelada |
| 33 | `test_conducto_no_se_come_la_salida` (unitario) | `_cancel_conduit_pairs` con una SELL de pase + una BUY en otra moneda de la misma cantidad: no se cancelan |
| 34 | `test_desfasado_visible_y_deshacer_lo_arregla` | forzar el desfase con una fila sembrada directo (saltando las puertas): `GET` dice `desfasado` y Movimientos trae el `estado`; deshacer deja `estado()` igual al de antes del pase |
| 35 | `test_split_pendiente_o_que_no_viaja_frena` | split sembrado y lote sin ajustar → 409 #20; lote con marca de split corporativo en A → 409 #21 |
| 36 | `test_lote_importado_editado_frena` | `PUT` de cantidad o costo a un lote importado de A, en una A a salvo → pase 409 #23 con el campo que cambió |
| 37 | `test_un_tramo_dos_motores` (unitario `importing/tramo.py`, **escrito en E2a con el código actual**) | mismos resultados para ARS v1, ARS v2, USD, `transfer_out` y comisión en otra moneda |
| 38 | `test_cripto_en_pesos` | BTC en Cocos (lote ARS) → otro broker AR, con fecha hoy: V = spot × factor del dólar cripto, C con `tc_venta` en pesos (no 1). Con fecha pasada → `sin_precio` en pesos |
| 39 | `test_pase_encadenado_usa_en_broker_desde` | C→A el 10/06 con lotes de 2023; A→B con fecha 01/05 → 400 #17; con 15/06 → OK, y después del rebuild de A no queda nada |
| 40 | `test_migracion_v1_a_v2_revalua_patas` | cuenta v1 → pase → `migrate_user_fx` → `valor_usd`/`costo_usd` recalculados y la identidad por broker de A y B se cumple |
| 41 | `test_rendimiento_por_broker_del_mes_del_pase` | reporte mensual de A y de B (`compute_metrics_for_period` con filtro de broker) da 0 %; el del año no compone el puente |
| 42 | `test_puente_en_pesos` | `GET /api/monthly` pestaña de A en pesos: `realized_ars` = V_ars − C_ars exacto; el CSV mensual igual |
| 43 | `test_fecha_antes_del_capital_declarado_frena` | primer renglón de A con `capital_inicio` declarado → pase con fecha anterior → 409 #14 |
| 44 | `test_omitidas_frenan_el_deshacer` | después de #15, deshacer → 409 con las instrucciones; revertir el import de B → deshacer OK |
| 45 | `test_holdings_asof_tipo_mezclado_y_venta_manual` (E3) | compra OTHER + venta STOCK en el mismo broker: la tenencia baja; venta manual de un lote importado: la historia lo saca desde la fecha de la venta |
| 46 | `test_cuenta_manual_no_se_vuelve_reconstruible` | cuenta sólo con lotes cargados a mano → pase → `has_import` falso; deshacer no borra fotos |

### F.3 Guardianes que hay que actualizar

| Archivo | Qué |
|---|---|
| `test_renombre_broker_recetas.py:887` `ESCENARIOS` | escenario «pase entre brokers»: armar, mover, renombrar A y B, deshacer; se compara con la corrida sin renombre |
| `test_borrar_broker_sueltos.py` | `puertas` (`:505`): sumar «mover a otro broker»; cambiar `:509-510, 574-597` (D.19) |
| `test_columna_nueva_llega_a_la_base_vieja.py` | censo de A.3 |
| `test_schema_pg_del_generador.py` / `test_schema_pg_al_dia.py` / `test_esquema_pg_reaplicable.py` | mkschema |
| `test_reset_censo.py` / `test_reset_data.py` | `_RESET_PORTFOLIO_TABLES` |
| `test_tx_vivas.py` | `LEEN_EL_LOG` si hace falta (A.4) |
| `test_conversion_en_movimientos.py::FlujosImportadosPorMes` | sumar el caso de patas de pase |
| `test_asesor_solo_lectura_post.py:125-135` | sumar `("POST", "/api/positions/traspaso/vista-previa")` a la lista exacta |
| `test_borrar_conserva_el_dia.py` | sumar el pase y su deshacer a las puertas: no borran fotos reales |
| `test_turno_en_todas_las_puertas.py` | los endpoints nuevos piden turno |

### F.4 Tests existentes a correr

Por etapa (segundos cada uno):
- **Traspasos y patas:** `test_traspaso_entre_brokers`, `test_pata_de_la_moneda`, `test_xbroker_mep_netting`, `test_reportes_broker_par`.
- **Rebuild y FIFO:** `test_rebuild_fifo` y los 8 archivos que heredan `_Base`, `test_position_group_edit`, `test_operaciones_con_receta`, `test_orden_mismodia`, `test_orden_filas_pool`.
- **Brokers:** `test_broker_rename`, `test_borrar_broker_sueltos`, `test_renombre_broker_recetas`.
- **Mes, flujos, caja y comisiones:** `test_puertas_dejan_el_mes_al_dia`, `test_flujos_a_mano`, `test_efectivo_una_puerta`, `test_monto_venta_ars::MetricasYMovimientosCoinciden`, `test_conversion_en_movimientos`.
- **Reconstrucción MTM:** `test_reconstruccion_aportado_canonico`, `test_reconstruccion_sigue_a_la_contabilidad`, `test_compra_borrada_fuera_de_la_curva`, `test_borrar_conserva_el_dia`.
- **Migración FX:** los tests de `fx_migrate`.
- **Guardias de código:** `test_turno_en_todas_las_puertas`, `test_tx_vivas`, `test_orden_con_desempate`, `test_un_solo_calendario`, `test_rutas_tapadas`, `test_endpoints_no_bloquean`, `test_conexiones_cerradas`, `test_plan_b_tiene_punto_de_guardado`.
- **Esquema y reset:** `test_schema_pg_*`, `test_columna_nueva…`, `test_referencias_con_indice`, `test_reset_censo`.

Al cierre de cada publicación:
- **suite completa SQLite:** `cd backend && python3 -m pytest tests -q -p no:cacheprovider; echo EXIT=$?`. La base de hoy es 8625 passed en unos 10 minutos, con `tests/fallas_conocidas.txt` vacía;
- **suite en Postgres** con `scripts/pg_de_prueba.py`, y al terminar matar el `postgres` que queda huérfano.

---

## G. Orden de implementación, publicación y fuera de la v1

### G.1 Etapas y tres publicaciones

| Etapa | Contenido | Cómo se verifica |
|---|---|---|
| E0 | Copia en `.claude/worktrees/…` desde `origin/main`; suite base | EXIT=0 de base |
| E1 | Esquema: columnas, tabla, mkschema, censo, listas (A.1–A.5), ida y vuelta (A.8) | guardias de esquema y reset + test de ida y vuelta de `store_preview_txs`/`load_session_for_confirm` |
| **E2a** | **Sólo pruebas:** #37 con los valores congelados de `_persist_sell_fifo` y `_replay_asset` actuales, y la expectativa congelada de #32 | se commitean en verde **antes** de mover código |
| E2b | Motores neutros: extracción de `tramo.py` (D.4), rebuild D.5.1–4, persister D.3.1–3, `_corporate_zero_dates` D.11, `cash_en` D.12, `_plata_de_fila_importada` D.8.10, `_compras_importadas` D.14, foto de la venta manual D.10.13, `_devolver_al_lote` D.10.12 | **suite completa en verde sin tocar ningún test existente**, más #32, #33 y #37 |
| E3 | Lectores de la historia: D.13 completo (`_holdings_asof`, `_tenencia_no_vista`, huella, `MOTOR_VERSION` 4, `has_import`) | #45 y #46. **Medición sobre una copia de la base de producción** (el respaldo nocturno de R2): cuántos (usuario, broker, activo) tienen más de un `asset_type` entre sus BUY vivas y cuántas 'Venta' manuales de lotes importados hay. Si aparecen casos que no son esos dos, revisarlos uno por uno antes de publicar |
| **Publicación 1** | E1 + E2 + E3, sin endpoints ni pantalla | sobre la copia de producción, `recompute_user` para todos los usuarios con el código de antes y el de después: **0 diferencias en `positions` y `operations`**. [V] En Postgres el dry-run del endpoint da 501, por eso es sobre la copia. Fuera de 23:59–01:15: cada cuenta se rearma una vez |
| E4 | Lectores de capital D.8, `/api/monthly` (D.8.8), reportes y la IA (D.15) | tests unitarios con filas sintéticas escritas con `store_preview_txs` + `persist_batch` y pasadas por el **recálculo real**; #41 y #42 |
| E5 | `armar_plan` + vista previa | #10, #27, #35, #36, #38, #39, #43 y validaciones de B.6 por HTTP |
| E6 | Confirmar (C.7 + B.3) | #1–#9, #11, #28, #29, #30, #31 |
| E7 | Deshacer + `GET` + guardas D.3.4 y D.10 + D.19 | #12, #13, #14, #20, #22–#26 |
| E8 | Antiduplicado (D.2.3–5, D.6, D.7), freno de imports (C.11, D.10.16) y omitidas | #15–#19, #21, #44 |
| E9 | Movimientos, CSV y comisiones (D.9) | #6, #7 |
| E10 | Detector de desfase (D.5.5) y su texto | #34 |
| E11 | Revaluación en la migración FX (C.10, D.17) | #40 |
| **Publicación 2** | E4–E11 con el interruptor **apagado** | suite completa en las dos bases. En producción: prender el interruptor, probar con la cuenta de prueba del dueño un pase y su deshacer, mirar /mensual y Movimientos, y dejarlo prendido |
| E12 | Frontend E.1–E.10 | tests de frontend + prueba en la app (memoria `feedback_preview_no_lee_documents`: copiar el backend y `dist` al scratchpad) |
| **Publicación 3** | E12 | prueba de comportamiento en producción: el ítem aparece, mover y deshacer desde la pantalla |

### G.2 Fuera de la v1, a propósito

1. **Bonos, letras y FCI** (#9, #10). Cuando entren: D.18 dice qué hay que cambiar.
2. **Pases entre familias** (#7) y **Wallbit** (#6).
3. **Adopción automática** de la entrada que ya trajo el archivo de B: por ahora se frena con instrucciones (#13). Para la v1.1, reusar las puertas del tacho y la rama `imported` de `undo_delete_operation` (`main.py:26342`).
4. **Costo rederivado de A (opción C del informe crítico):** la v1 lo previene con las puertas (C.11) y, si algo se escapa, lo detecta (D.5.5).
5. **Foto de tenencia de A con fecha anterior a un pase que sacó lotes cargados a mano:** `proyeccion.proyectar` no conoce la receta y los va a ver como faltantes.
6. **Las «posiciones transferidas» del asistente** (`cost_basis_pending` → «Estado inicial») no se cruzan con los pases hechos a mano.
7. **Dividendos o cupones que A cobró antes del pase y no se anotaron:** después del pase ya no se proponen en ningún broker.
8. Gasto cobrado por B (hoy se carga como cualquier comisión de B), «cerrar cuenta» sin borrar la historia, editar un pase hecho, deshacer parcial y marcar IEB DETR con `transfer_in` en el lector.
9. **Cripto entre exchanges:** entra en la v1 si hay vela o último precio; si no, con precio a mano. La cripto de una cuenta en pesos, con fecha pasada, sólo con precio a mano en pesos.

### G.3 Dudas que no bloquean la implementación

- No verifiqué de punta a punta `_cambio_de_aportado` (`main.py:23256+`). En un pase normal el aportado global no cambia, y el test #12 compara las fotos medidas antes y después.
- **Volver atrás el deploy con pases hechos:** el código viejo emitiría 'Venta' en cada rebuild de A, no leería las patas, tomaría la BUY de B como salida de caja y dejaría revertir el lote B fabricando caja. Antes de volver atrás: apagar el interruptor y deshacer los pases vivos. Lo leés con `SELECT id FROM traspasos_a_mano WHERE deshecho_at IS NULL`.
- Dos lotes del mismo día con costos distintos, si el orden por id de `positions` y el de llegada del registro difieren, pueden hacer saltar el #23 sin que nada esté mal. Es raro, y el mensaje genérico lo cubre.

---

## H. Qué cambió respecto de la versión revisada

C = revisor contable, T = revisor de tubería, R = revisor de alcance. Todos verificados en el código salvo que diga lo contrario.

| Ítem | Dónde quedó |
|---|---|
| C1 % y frases falsas por broker | D.15.1–2, D.8.8, E.7 (`resultadoSinPuente`) |
| C2 cripto en pesos: costo tomado como dólares y V corto | C.4.1–3, C.5, #38 |
| C3 elegibles por `en_broker_desde` | C.2.2, #17, #39 |
| C4 / T15 migración v1→v2 | C.10, D.17, #40 |
| C5a tipo de activo en `_holdings_asof` | D.13.1a, #45 |
| C5b venta a mano en B | D.13.1c (arreglo general), #45 |
| C5c cuenta 100 % manual | D.13.4, #46 |
| C6 / T6 / R13 historia de A que cambia | C.11, D.10, D.5.5, E.5, #21, #34 |
| C7 / R4 puente en pesos | A.1 `costo_nativo`, D.8.8, #42 |
| C8 aportado global en pesos | D.8.6, E.7 |
| C9 costo promedio en la historia | A.6 (`costo_nativo` en la SELL), D.13.1b |
| C10 / T10 ratio pendiente y split por la fuente única | B.6 #20–#21, C.2.5, B.3 paso 0 |
| C11 / T20 lotes de un A borrado | D.7 `lotes_a_mano_que_salieron` |
| C12 realizado de la IA | D.15.4 |
| C13 / T17 gasto | D.8.3 (pérdida del broker), aviso de caja negativa |
| C14 lotes sin `invested` | C.3 |
| T1 lotes editados contra el registro | C.2.6, B.6 #23, #36 |
| T2 / R2 firma con precio | C.9, B.3 (valuación), #28 |
| T3 pase incompleto sin salida | C.8 (deshacer lo que queda), #22, #23 |
| T4 / R15 deshacer sin mirar A | C.8 validación 3, #14 |
| T5 ids cambiados por el rebuild | C.7.7 (sin rebuild), C.8 paso 3 |
| T7 fecha por defecto y ventana | D.7 (ventanas 4/60), E.2 (fecha obligatoria), #16 |
| T8 presupuesto de salida | D.7, C.11, #17 |
| T9 deshacer después de omitir | A.2 `omitidas_json`, C.8 validación 2, #44 |
| T11 fecha antes del capital declarado | B.6 #14, #43 |
| T12 concurrencia SQLite | B.3 (`_tomar_lotes`) |
| T13 creación en `armar_plan` | C.1.3 |
| T14 `PersistError` crudo | C.1.3, B.6 #25, B.3 |
| T16 clave que no se renombraba | A.2 `brokers_usd_creados` |
| T18 `price_override` | C.7.8, C.8 paso 5 |
| T19 familias con dos hijos | C.7.7, C.8 (`rebuild_pair_asset` de la raíz), nota 1 de A.6 |
| T20 huella de la reconstrucción | D.13.3 |
| T21 edición en grupo | D.10.14–15 |
| T22 `include_duplicates` | D.2.3, #15 |
| T23 ticker viejo | B.6 #11 |
| T24 volver atrás el deploy | B (interruptor), G.3 |
| R1 prueba de rebuild vacía | F.1, #1 |
| R3 banda del precio manual | B.6, avisos (en dólares y sin frenar) |
| R5 signo del puente | D.8.8, E.2, E.7 |
| R6 `openMove` | E.1 |
| R7 prueba de dibujo | E.2, E.10 |
| R8 guardia `envios-con-dueno` | E.10 |
| R9 `mtm_coverage` | #11 |
| R10 fotos reales | #12 |
| R11 extracción en dos pasos | G.1 E2a/E2b |
| R12 crear broker en el modal | E.2, E.3 |
| R14 texto del #15 viejo | B.6 #17 |
| R16 publicación por tandas | G.1 |
| R17 modal de edición compartido | E.6 |
| R18 archivo de /mensual | E.7 |
| R19 lugar de la nota de Reportes | D.15.2 |
| R20 demo | E.8 |
| R21 callejones en el demo y en filas agregadas | E.1 |
| R22 lista exacta del asesor | B.2, F.3 |
| R23 «B · USD» al deshacer | C.8 |
| R24 textos por causa | B.6 #15, #20, #21, C.8, avisos |
| R25 orden de la prueba #24 | F.2 #27/#28 en E5/E6 |
| R26 Movimientos en pesos y filtro | D.9.1, E.5 |
| R27 recortes | D.18 (`cobros_bonos`, `pendingCashflows`), gasto sólo de A, Importaciones sin botón propio |
| R28 casos del atómico | #29 |
| R29 lo que no se recorta | todo sigue en la v1 |

---

## I. Problemas de revisores descartados o adaptados, y por qué

1. **T1, «armar la cola con el replay en seco».** Adaptado. La cola sigue saliendo de `positions`, que es lo que el usuario ve y lo que consume el persister. El replay en seco se usa para comprobar que el registro consumiría exactamente esos lotes, y si no, frena (#23). Si se armara la cola desde el registro, el pase movería en silencio una versión del lote distinta de la que muestra la pantalla, y borraría las correcciones a mano de los lotes que quedan en A.
2. **T1 / T5, «rebuildear A en el pase y después comparar».** Descartado. Con la comprobación previa, el rebuild del pase no agrega nada y le cambiaba los ids a los lotes de A, que es justo lo que complicaba el deshacer (T5).
3. **T3, «liberar las guardas en un pase incompleto».** Adaptado. Liberarlas dejaba la pata de capital viva sin títulos. En su lugar, el deshacer funciona en los dos estados incompletos (C.8) y las guardas siguen apuntando a él.
4. **T7, «reconocer la fila del archivo sin tope de días».** Adaptado a dos ventanas: hasta 4 días se omite, de 5 a 60 se frena con instrucciones, y desde 61 entra con un aviso. Sin tope, un traspaso real y viejo del mismo activo desde un tercer broker se omitiría por error. Además la fecha del pase ahora se elige siempre (E.2).
5. **T9, «guardar las filas omitidas con una lápida y reactivarlas al deshacer».** Descartado por costo: sería una máquina de estados nueva sobre `import_normalized_tx`. Se anota lo omitido y el deshacer se frena con el camino exacto (revertir el archivo, deshacer, volver a subirlo).
6. **C4 / T15, «guardar los valores en moneda original y pasar a dólares al leer».** Descartado a favor de revaluar en la migración (C.10). La regla cambia en un solo momento y en un solo lugar (`set_fx_version`), mientras que pasar a dólares al leer obligaba a repetir la regla del tramo en cada lector de capital y en cada mes del recálculo.
7. **R16, «verificar la publicación 1 con `backfill-recompute` en dry-run en vivo».** La idea se mantiene, pero no se puede hacer así: en Postgres ese ensayo da 501 (`EnsayoPorClonNoDisponible`, `main.py:27699`), y producción está en Postgres. Se hace con `recompute_user` sobre una copia de la base de producción.
8. **R3, «aviso con confirmación explícita» para el precio fuera de banda.** Queda como aviso sin casilla extra: el usuario ya ve el valor calculado y aprieta «Mover».
9. **C5c, alternativa «probarlo explícitamente».** Se eligió excluir los lotes de pase del control `has_import`, porque probarlo sólo documentaba un cambio de comportamiento no buscado.
10. **R13, opción (a) «sacar el detector de la v1».** Adaptado: se pone el freno donde nace el problema, en todas las puertas (C.11), y se conserva el detector como red barata, ahora visible.
11. **T12, alternativa «`_tomar_turno` antes del plan».** Se usa `_tomar_lotes` sobre A y B, que traba sólo esos lotes en Postgres y no pone en fila al resto de la cuenta.
12. **Del borrador, recortado a propósito:** el gasto que sale de B, la unificación de las cuatro copias del alta de broker, D.15 viejo (`cobros_bonos`), los cambios a `pendingCashflows.js` y el botón «Deshacer el pase» en Importaciones (siguen disponibles en Movimientos y en el aviso).

No encontré ningún problema de los revisores que fuera falso. Todos los que miré en el código son reales; los de esta lista se resolvieron de otra forma.

## J. Decisiones que quedaron abiertas para el dueño

Ninguna. Todo se resolvió con las decisiones ya tomadas. Dos cosas que el dueño tiene que **saber**, aunque no hace falta que decida:
- la publicación 1 rearma una vez la historia a mercado de todas las cuentas, y corrige la curva de quien vendió a mano lotes importados o tiene ventas con otro tipo que sus compras (D.13.1);
- antes de volver atrás un deploy con pases hechos, hay que deshacerlos (G.3).
