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

## A-1 · Vender cripto desde el celular en una cuenta en pesos registra resultado cero — ✅ ARREGLADO

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

**✅ Arreglado.** El prefill dejó de tener lógica propia: las dos pantallas usan
`sellPriceSuggestion` y `sellCurrency`, en `valuation.js`, al lado de la
valuación.

⚠️ **Arreglar sólo la clave no alcanzaba: destapaba un segundo error.** El
precio de venta va en la moneda del broker, y la rama de cripto devolvía
spot × recargo, que está en DÓLARES. Con la clave corregida, un broker en pesos
habría prefilleado ~78.000 para un bitcoin que en pesos vale ~119.000.000. El
mismatch de claves venía tapando eso. Por eso la conversión de moneda quedó
adentro del helper y no en la pantalla.

De paso se unificaron tres cosas que estaban duplicadas y distintas entre
aparatos: la moneda en que se registra la venta (mobile miraba el broker,
desktop el lote), el respeto al precio manual (sólo desktop) y el guard
anti-distorsión (uno en cada pantalla, con comparaciones distintas).

**Verificado por mutación**, tres veces: volver a la clave cruda pone 7 pruebas
en rojo, sacar la conversión de moneda 1, y sacar el guard 1. Hay una prueba del
invariante que se rompió: la clave con la que se PIDEN los precios y la que el
prefill LEE tienen que ser la misma.

### A-1b · Y el mismo modal tenía un segundo defecto, en el envío — ✅ ARREGLADO

`confirmSell` de mobile no mandaba la moneda de la venta. El backend la declara
opcional y sin ella cae a la moneda del BROKER por compatibilidad hacia atrás,
así que un lote comprado EN PESOS alojado en una cuenta en dólares se vendía
contra los lotes de la otra moneda: el FIFO cierra lo que no es. Desktop la
mandaba desde siempre. Ahora sale del mismo helper que el prefill, y el cuerpo
de la venta quedó idéntico campo por campo entre las dos pantallas.

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

# Las mediciones · HECHAS y deployadas (`c17ce94a`)

Son cuatro consultas más del botón que ya existía, no un script aparte. Se
corren desde el panel de admin, en la tarjeta **"Alcance real de la auditoría"**,
con el botón **"Medir alcance"**. Sólo lectura, sólo agregados, y el guard se
niega a ejecutar si alguna consulta no es un SELECT limpio.

| consulta | qué contesta | para qué punto |
|---|---|---|
| Q9 | retiros de cripto registrados como pérdida total | A-2 |
| Q10 | usuarios con cripto en una cuenta en pesos | B-1 |
| Q11 | brokers que son exchange y están en pesos a la vez | B-3 |
| Q12 | tenencias con un código que es cripto y acción | C-1 |

Q9 busca el **daño ya ocurrido**, no el riesgo: ventas de cripto a precio cero
con resultado negativo, en brokers que la lista no reconoce.

⚠️ Las consultas llevan **copiadas** en SQL dos constantes de Python (los ~100
símbolos de cripto y los 14 exchanges), porque no hay forma de leer un conjunto
de Python desde SQL. La copia está atada por `TestLasListasDeCriptoNoDriftean`,
verificado por mutación: agregar un símbolo de un lado y no del otro pone los
tests en rojo. Importa el sentido de la falla, porque una consulta que quedó
corta no explota: mide de menos y publica un número tranquilizador.

Sin esos números, A-2, B-3 y C-1 se deciden a ciegas.

---

# Resultados de la medición · 2026-09-09, producción

| pregunta | número | veredicto |
|---|---|---|
| Retiros de cripto registrados como pérdida total (A-2) | **0** | sin caso |
| Usuarios con costo de cripto inflado (B-1) | **6** | 16 posiciones, 5 brokers |
| Cuentas de exchange marcadas en pesos (B-3) | **4** | 4 usuarios |
| Tenencias con código cripto-y-acción (C-1) | **6** | 2 usuarios, 2 códigos |

**A-2 era teórico.** Cero retiros quedaron como pérdida. Baja de "lo más urgente
de todo el plan" a guard preventivo: el mecanismo sigue estando, sólo que nadie
lo pisó todavía. Vale cerrarlo cuando se toque la lista de exchanges (C-2), no
antes y no solo.

**B-1 es real pero chico en plata.** Con el costo nominal declarado de
11.153.037,8 y la brecha de hoy, el costo fantasma ronda los 296 dólares
repartidos en 6 personas, unos 49 cada una. Lo que lo mantiene arriba no es el
monto: es que **da vuelta el signo** de una ganancia chica, y que se escribe en
la foto diaria todos los días.

⚠️ **Ese monto es una cota floja, y el defecto es de mi consulta**: Q10 suma
`invested + commissions` de todas las posiciones del broker en pesos, y esas
filas pueden estar en pesos o en dólares. El SUM mezcla monedas. Los números que
sí son firmes son los tres conteos: 6 usuarios, 16 posiciones, 5 brokers.

**B-3 NO es gratis.** Esperaba cero. Son 4 cuentas de 4 usuarios distintos. O
sea que sacar el flag de exchange del cálculo les cambia el valor de la cripto
hacia arriba un 3,67 %. Deja de ser una simplificación silenciosa y pasa a ser
una decisión con consecuencia visible.

**C-1 es revisable a mano.** Sólo 2 códigos distintos en 2 usuarios. Falta saber
CUÁLES: Q12 devuelve el conteo pero no los códigos, porque se escribió para no
publicar nada identificable. Un código de activo no identifica a nadie, así que
se puede agregar una consulta que los liste.

**Lo que quedó sin medir es A-1**, la venta desde el celular que se prefillea al
precio de compra. Se puede: la firma es una venta de cripto cuyo precio de salida
coincide exactamente con el de compra, en un broker en pesos. No es prueba
concluyente —alguien pudo vender justo a ese precio— pero acota el universo.

---

# Orden recomendado · revisado con los números

1. **A-1**, la venta desde el celular. Sigue primera: registra plata mal a un
   toque de distancia y contradice a la computadora. Medirla en el mismo
   movimiento (ventas de cripto con precio de salida igual al de compra).
2. **B-1**, el costo duplicado. 6 usuarios con el signo del resultado dado
   vuelta todos los días.
3. **B-2**, el doble recargo en la variación del día. Es el que quedó a medias
   del cambio de hoy y es una línea.
4. **B-3**, cuando esté decidido cuál condición manda. Ya no es gratis: toca a 4
   usuarios.
5. **C-1**, primero listar los 2 códigos y mirarlos a mano.
6. **C-2 y C-3**, la deuda de las listas, con chequeo automático. Ahí adentro se
   cierra A-2 de paso.

Sobre B-1: el arreglo mínimo es mover un paréntesis, y **no es el correcto**.
Hay cuatro motores que valúan cripto y ninguno es el bueno al que volver. Los
dos del backend que divergen tienen 99 y 206 líneas, con 10 y 20 de cripto. Vale
extraer una sola función que reciba el lote, el precio y la moneda de la cuenta
y devuelva valor y costo, y que la llamen los tres del backend. El frontend
llega al mismo número por el precio en pesos; ese camino se deja, pero la
igualdad numérica contra la función nueva pasa a ser una prueba.
