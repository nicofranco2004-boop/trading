# Plan — arreglar lo que queda raro en cripto

Estado al 2026-09-09, después de deployar `ed40e73e` (el premium dólar-cripto
pasó a decidirse por la moneda de la cuenta, no por si el broker es un exchange).

**Todo lo de abajo es preexistente.** Lo verifiqué en `665b8b67`, el commit que
estuvo en producción hasta hoy, y da idéntico. Una cosa sí es reprochable al
cambio de hoy y está marcada como tal en B-2.

Cada punto dice cómo lo comprobé:

- **MEDIDO** — lo corrí y tengo los números.
- **LEÍDO** — seguí el camino de ejecución en el código, sin ejecutarlo.
- **A CONFIRMAR** — depende de datos de producción que no puedo consultar.

---

# Tanda A · Plata que se registra mal

Va primero porque deja rastro permanente en el historial del usuario: se
escribe una operación, no se muestra un número feo.

## A-1 · Vender cripto desde el celular en una cuenta en pesos registra resultado cero

**MEDIDO.** Para una cripto en un broker en pesos, el precio se pide con la
clave `BTC.BA`; para un exchange se pide `BTC`. Lo corrí:

```
keys que el fetch pide: ["BTC.BA", "BTC"]
```

El modal de venta del celular lee la clave `BTC` (`PositionsMobile.jsx:308`).
Para quien tiene la cripto sólo en un broker en pesos, esa clave no existe, el
precio queda vacío y el modal cae al **precio de compra**. Confirmar sin editar
registra una venta con resultado exactamente cero.

Dos agravantes leídos: el envío del celular no manda la moneda, mientras el de
la computadora sí (`Positions.jsx:869`), y la computadora prefillea bien porque
usa otro camino. La misma venta se sugiere distinta según el aparato.

El comentario que documenta esa rama dice lo contrario de lo que pasa: afirma
que la clave que ya no se pide es `BTC.BA`, cuando es justo la que sí se pide.

**Arreglo**: que el prefill lea la misma clave que la valuación, no una fija.
Hay una función que ya decide esa clave y es la que hay que usar.

## A-2 · Un retiro de cripto puede quedar registrado como pérdida total

**LEÍDO**, alcance **A CONFIRMAR**. `backend/importing/rebuild.py:456`:

```python
transfer_out = ((is_exchange or bool(ev.get("transfer_out")))
                and not exit_price and not _num(ev["gross_amount"]))
```

Sacar monedas a una billetera propia llega como una venta a precio cero. Si la
condición se cumple, el lote se cierra a costo y el resultado es cero, que es lo
correcto. Si no se cumple, cae a la rama de abajo y calcula
`0 × cantidad − costo`, o sea **la pérdida completa del lote**.

La condición se cumple por dos vías: que el broker esté en la lista de catorce
exchanges, o que la fila traiga una marca explícita. Los parsers que ponen esa
marca están cubiertos. Queda expuesto un retiro importado desde una billetera
que no está en la lista y por un parser que no la marca.

**Antes de arreglar hay que medir** si existen operaciones así en producción. Si
existen, es lo más urgente de todo el plan.

---

# Tanda B · El mismo activo con dos números distintos

## B-1 · El costo de la cripto en pesos se divide dos veces por el dólar

**MEDIDO.** `backend/snapshots_job.py:288`, la multiplicación queda fuera del
paréntesis y alcanza también a la rama en pesos, que ya pasó a dólares:

| motor | costo | resultado |
|---|---|---|
| informes e inteligencia artificial | USD 700,00 | **ganancia** de USD 0,60 |
| foto diaria guardada | USD 725,68 | **pérdida** de USD 25,08 |

El valor coincide en los dos. Difiere el costo, y alcanza para invertir el
signo. El otro motor lo hace bien y su comentario explica por qué no hay que
hacerlo. Se dispara con cualquier cripto en un broker en pesos, con o sin la
moneda anotada en la fila.

**Hasta dónde llega**: se guarda en la foto diaria. El motor de rendimiento la
trae pero no la usa. Sí la usa el gráfico de evolución como respaldo cuando la
foto no tiene depósitos netos (`evolution.js:194` y `:269`).

## B-2 · Doble recargo en la variación del día de la sección en pesos

**LEÍDO**, mecanismo confirmado línea por línea. En la sección en pesos el monto
de variación se calcula con el precio en pesos, que **ya trae el recargo
adentro**, y después se vuelve a multiplicar por el recargo
(`Positions.jsx:1547`). El valor de la misma fila no lo multiplica. Dos celdas
vecinas en escalas distintas.

**Esto es lo único reprochable al cambio de hoy.** No lo introduje: en el commit
anterior el recargo se aplicaba ahí igual. Pero al pasar la moneda lo dejé
encendido justo en la rama donde está mal y lo apagué en la que estaba bien.
Tuve la línea delante y no vi que ese camino ya venía con el recargo puesto.

**Arreglo**: en ese punto el recargo nunca corresponde, porque el precio ya lo
trae. Va fijo en dólares, como el resto de los llamados de esa pantalla.

## B-3 · "Es exchange" y "la cuenta está en pesos" se contradicen

**MEDIDO.** Una cripto en un broker marcado exchange con la cuenta en pesos:

| superficie | valor |
|---|---|
| Cartera | USD 700,60 |
| Foto diaria | USD 675,80 |

Después del cambio de hoy hay dos condiciones que contestan la misma pregunta y
no coinciden. Es **decisión de producto**: si la pregunta que manda es la
moneda, el flag de exchange sobra para este cálculo. Sacarlo subiría 3,67% el
valor de la cripto que hoy está en un exchange con cuenta en pesos.

**Medir primero** cuántos brokers cumplen las dos cosas. Si son cero, el cambio
es gratis y cierra la contradicción para siempre.

## B-4 · La prueba que debería cazar B-1 y B-3 mira el único caso que funciona

`backend/tests/test_crypto_premium.py:178` compara los dos motores usando una
cuenta en dólares, que es exactamente donde coinciden.

---

# Tanda C · Las listas

## C-1 · Símbolos de cripto que también son acciones reales

La lista de unas cien monedas se usa para decidir cómo se pide el precio. Ya se
sacaron dos por colisión, con el comentario que lo explica. Quedan varias que
son tickers vivos en Estados Unidos. El barrido señala entre otras `STX`, que es
Stacks y también Seagate, una empresa del índice S&P 500 y una tenencia
perfectamente plausible en una cuenta de Schwab.

**A CONFIRMAR uno por uno**: son tickers externos, no los puedo validar desde el
repo. Pero el mecanismo es el mismo que ya obligó a sacar dos.

Cuando la diferencia de precio es enorme el guard anti-distorsión lo tira a
costo y el activo queda congelado sin aviso. Cuando es moderada, no lo atrapa y
muestra el precio de la otra cosa.

Falta además toda la camada nueva de monedas. Una que no está en la lista y vive
en un broker en pesos termina pidiendo un símbolo de la bolsa argentina que no
existe, y queda congelada al costo.

**Arreglo**: no curar la lista a mano otra vez. Un chequeo automático que falle
si un símbolo de la lista aparece también en las listas de acciones del repo.

## C-2 · La lista de exchanges compara el nombre entero

`is_exchange_broker` compara igualdad exacta contra catorce nombres. No matchean
`Binance · USD`, `Binance Spot` ni `Coinbase Pro`. El propio sistema fabrica el
primero cuando crea la pata en dólares de un broker.

Faltan además las billeteras argentinas grandes. Para una cripto en Lemon eso
encadena cuatro comportamientos: recargo activo, ruteo a un símbolo de la bolsa
argentina, la protección de retiros apagada y la protección de conductos
apagada.

## C-3 · Cuatro listas de monedas estables y tres de cripto, todas distintas

Ningún par coincide. Consolidarlas en una sola fuente.

---

# Paso 0 · La prueba primero, y tiene que fallar

**No tocar código antes de esto.** Para B-1 y B-3, extender la prueba de
consistencia entre motores al caso en pesos y verificar que se pone en rojo. Un
arreglo cuya prueba nunca estuvo en rojo no demuestra nada.

Para A-1, la prueba tiene que pasar por la misma función que decide la clave del
precio en producción, no por una clave escrita a mano en el test.

---

# Lo que hay que medir antes de empezar

Cuatro consultas de sólo lectura, para el botón de alcance del panel de admin:

1. Operaciones de venta a precio cero en brokers que no están en la lista de
   exchanges → si A-2 es real.
2. Posiciones de cripto en brokers con moneda en pesos → cuánta gente toca B-1.
3. Brokers marcados exchange y con moneda en pesos a la vez → si B-3 es real.
4. Tenencias cuyo símbolo esté en la lista de cripto y a la vez en las listas de
   acciones → si C-1 tiene víctimas hoy.

Sin esos números, A-2, B-3 y C-1 se deciden a ciegas.

---

# Orden recomendado

1. Las cuatro mediciones.
2. Paso 0, las pruebas en rojo.
3. **A-1**, que es plata mal registrada a un toque de distancia y contradice a
   la computadora.
4. **A-2** si la medición dice que existe.
5. **B-1 y B-2**, que son el mismo defecto de fondo: el recargo aplicado sobre
   un número que ya lo tenía.
6. **B-3** cuando esté decidido cuál de las dos condiciones manda.
7. **C-1 a C-3**, deuda estructural, con chequeo automático en lugar de listas
   curadas a mano.

Sobre B-1: el arreglo mínimo es mover un paréntesis, y **no es el correcto**.
Hay cuatro motores que valúan cripto y ninguno es el bueno al que volver. Los
dos del backend que divergen tienen 99 y 206 líneas, con 10 y 20 de cripto. Vale
extraer una sola función que reciba el lote, el precio y la moneda de la cuenta
y devuelva valor y costo, y que la llamen los tres del backend. El frontend
llega al mismo número por el precio en pesos; ese camino se deja, pero la
igualdad numérica contra la función nueva pasa a ser una prueba.
