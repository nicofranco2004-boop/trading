# Prueba de la API de IOL para Rendi (para el tester)

Gracias por darnos una mano. Esto es una prueba de **solo lectura** contra la API de IOL
para saber qué datos expone y cuánto dura el acceso. Corre en **tu** computadora: Rendi
nunca ve tu contraseña.

## Opción A (la fácil): desde Rendi, sin instalar nada

1. Pedile a IOL la activación de la API (ver "Antes de empezar", abajo). Es obligatorio.
2. Entrá a **rendi.finance/lab/iol** con tu cuenta de Rendi (te tenemos que habilitar el email antes).
3. Poné tu usuario y contraseña de IOL y apretá "Iniciar prueba". Tarda un minuto. Listo: el resultado nos llega solo.
4. Dejá marcada la casilla "Medir cuánto dura el acceso": guarda solo el refresh token, cifrado, y lo renueva cada hora. Cuando IOL lo rechace, la página lo muestra. Podés borrarlo cuando quieras con "Desconectar".

La contraseña se usa una vez para pedir el token y se descarta; no se guarda ni se loguea. Rendi no puede operar: el cliente no tiene ninguna función de compra, venta ni extracción.

## Opción B: script en tu máquina (si preferís que tu contraseña no pase por Rendi)

## Qué garantiza el script

- La contraseña se pide por consola sin mostrarla, se usa una sola vez para pedir el token y se descarta. No queda en ningún archivo.
- El script **no puede operar**: solo hace consultas (GET) a una lista fija de direcciones. Cualquier otra dirección se bloquea antes de salir a internet. Podés abrir `iol_spike.py` y verificarlo: buscá `ALLOWED_GET`.
- Lo que se envía a Rendi está anonimizado: nombre, apellido, DNI, CUIT, email y números de cuenta salen como `***`. Quedan tickers, cantidades y montos, que es lo que necesitamos analizar.

## Antes de empezar (una sola vez)

IOL exige activar la API por cuenta:

1. Entrá a invertironline.com.
2. Sección **Mensajes** → mandá uno pidiendo **"activación de APIs"**.
3. Cuando te confirmen, andá a **Mi Cuenta → Personalización → APIs** y aceptá los términos.

Sin esto, el login del script falla. Anotá cuántos días tardó IOL en activarla: nos sirve.

## Paso 1: prueba rápida (5 a 10 minutos)

Necesitás Python 3 (en Mac ya viene; en Windows, python.org).

```bash
python3 iol_spike.py probe
```

Te pide usuario y contraseña. Al terminar imprime la ruta de un `.zip` dentro de `iol_spike_out/`. **Mandanos ese zip.**

Si podés, sumá también el export **"Movimientos históricos"** (.xls) de IOL: Mi Cuenta → Movimientos → Detalle de Movimientos → fecha desde que abriste la cuenta → "Descargar movimientos históricos". Es el mismo archivo que se sube hoy a Rendi y nos deja cruzar los dos caminos.

## Paso 2: cuánto dura el acceso (corre solo, varios días)

```bash
python3 iol_spike.py watch
```

Renueva el token cada hora y anota en `iol_spike_watch.log` cuándo deja de funcionar. Dejalo corriendo en una terminal abierta (o con `nohup python3 iol_spike.py watch &`). Si se corta la máquina, volvé a correr el mismo comando: retoma solo. Cuando el log diga `FIN`, mandanos `iol_spike_watch.log`.

Para esta parte el script guarda **solo el refresh token** en `iol_spike_state.json` (permisos solo para tu usuario). Ese token permite entrar a tu cuenta mientras dure, así que:

## Al terminar

```bash
rm iol_spike_state.json
```

Y si querés estar 100% tranquilo, cambiá tu contraseña de IOL. Eso invalida cualquier token que haya existido.

## Si algo falla

- `Login falló: HTTP 400`: casi seguro la API no está activada o falta aceptar los TyC.
- `HTTP 401` en el medio: el token venció, volvé a correr.
- Cualquier otra cosa: mandanos el mensaje de error tal cual.
