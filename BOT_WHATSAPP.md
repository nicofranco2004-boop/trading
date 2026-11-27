# El bot de WhatsApp — cómo se da de alta en Meta y se prende

> Para quien lo va a configurar (Nico). El código está en `backend/whatsapp.py`
> (lo propio de WhatsApp) y en `backend/main.py`, sección «WhatsApp: el bot».
> Qué hace: es otra puerta al mismo Mervall-E AI de la app. Sólo plan Pro.

## Cómo funciona, en una línea cada paso

1. El usuario Pro entra a **Configuración → WhatsApp → «Conectar mi WhatsApp»**. Ve un
   código (`RENDI ABC123`, dura 15 minutos) y un botón que abre WhatsApp con el código ya
   escrito.
2. Lo manda. Meta le avisa al servidor de Rendi. El servidor une ese teléfono a esa cuenta.
3. Desde ahí, cada mensaje entra al mismo chat que la app: lee la cartera, anota compras,
   ventas y depósitos pidiendo confirmación (con botones Sí / No), y «deshacé» deshace.
4. Descuenta del **mismo cupo semanal** de consultas que la app. Audios, fotos y archivos
   todavía no se leen: el bot lo dice y pide texto.

## Lo que hay que hacer en Meta (una sola vez)

Se puede construir y probar todo con el **número de prueba gratis** de Meta, sin chip. El
número real hace falta recién para abrírselo a los usuarios.

1. **Cuenta de empresa:** [business.facebook.com](https://business.facebook.com) → crear una
   cuenta comercial para Rendi (si no existe). Después, **Configuración del negocio →
   Centro de seguridad → Verificación del negocio**: pide documentación (CUIT, un servicio
   a nombre del negocio). Tarda de días a dos semanas. **Arrancarla primero.**
2. **La app:** [developers.facebook.com](https://developers.facebook.com) → Mis apps → Crear
   app → tipo «Empresa» → agregarle el producto **WhatsApp**.
3. **WhatsApp → Configuración de la API.** Ahí están:
   - el **número de prueba** (ya viene) y su **Identificador de número de teléfono** → va en
     `WHATSAPP_PHONE_NUMBER_ID`;
   - la lista «Para» de hasta 5 teléfonos que pueden escribirle al número de prueba: agregá
     el tuyo.
4. **Token permanente** (el de la pantalla vence a las 24 h): Configuración del negocio →
   **Usuarios del sistema** → crear uno (rol administrador) → **Agregar activos** → la app →
   control total → **Generar token** con los permisos `whatsapp_business_messaging` y
   `whatsapp_business_management` → va en `WHATSAPP_TOKEN`.
5. **Clave secreta de la app:** la app → Configuración → **Básica** → «Clave secreta de la
   app» (botón Mostrar) → va en `WHATSAPP_APP_SECRET`. Con esto el servidor comprueba que
   cada aviso vino de Meta.
6. **El webhook:** la app → WhatsApp → **Configuración** → Webhook → Editar:
   - URL de devolución de llamada: `https://<el servidor de Rendi>/api/whatsapp/webhook`
   - Token de verificación: inventá una palabra larga
     (`python3 -c "import secrets; print(secrets.token_urlsafe(24))"`) y ponela también en
     `WHATSAPP_VERIFY_TOKEN` **antes** de apretar «Verificar y guardar» (Meta llama al
     servidor en ese momento y el servidor tiene que conocer la palabra).
   - Campos del webhook: suscribirse a **`messages`**.
7. `WHATSAPP_NUMERO` = el número del bot con código de país y sólo dígitos (el de prueba
   también sirve): arma el link que abre WhatsApp desde la app.

Las cinco variables van en **Railway → servicio del servidor → Variables**. El servidor se
reinicia solo al guardarlas.

Hay una sexta, opcional: `WHATSAPP_GRAPH_VERSION`. Meta apaga cada versión de su API a los
~2 años (la v21.0 muere el 21/01/2027); el código usa la v26.0 y con esta variable se cambia
sin publicar nada si alguna vez hace falta.

Lo que se guarda: el número de cada cuenta mientras esté conectada y la conversación de los
últimos 30 días (lo anterior se borra solo; al desconectar se borra todo). Está dicho así en
`/privacidad`.

## Prender

1. Entrar a `/admin` → panel **«Bot de WhatsApp»**. El renglón de abajo dice si falta
   alguna variable.
2. **Prender.** Hasta ahí, Configuración → WhatsApp decía «todavía no está disponible».
3. Probar desde tu celular (tiene que estar en la lista «Para» del número de prueba):
   Configuración → WhatsApp → Conectar → mandar el código → preguntar «cómo vengo».

## Cuando se pase al número real

- Chip **con abono** (un prepago sin recarga se da de baja y la compañía lo reasigna).
  **Nunca** instalarle WhatsApp a ese número en ningún teléfono: lo sacaría del bot.
- En la app de Meta → WhatsApp → Configuración de la API → **Agregar número de teléfono**:
  Meta manda un SMS o llama con un código. Se elige una clave de 6 números (segundo
  candado del número: **guardarla**).
- Cambian `WHATSAPP_PHONE_NUMBER_ID` y `WHATSAPP_NUMERO`. El token y el webhook son los
  mismos.
- Para mandar mensajes que no sean respuesta (p. ej. un resumen los viernes) hacen falta
  plantillas aprobadas por Meta y se pagan (~US$ 0,03 en Argentina). Todavía no está
  construido.

## Reglas de Meta que importan

- **Contestar es gratis** dentro de las 24 horas de que la persona escribió.
- Desde el 15/01/2026 Meta **prohíbe los bots de IA «de uso general»**. El de Rendi habla
  sólo de la cartera y del mercado, y las instrucciones del chat lo dicen
  (`whatsapp.SISTEMA_WHATSAPP`). No hay que ampliarle el tema.
- Los mensajes pasan por Meta: está dicho en `/privacidad` (sección 5 y el resumen).

## Si algo no anda

| Qué se ve | Qué es | Qué hacer |
|---|---|---|
| Meta no deja guardar el webhook | el servidor no reconoce la palabra | `WHATSAPP_VERIFY_TOKEN` igual en Railway y en Meta; guardar y reintentar |
| En los logs: «aviso con firma inválida» | `WHATSAPP_APP_SECRET` no es la clave de ESA app | copiarla de nuevo de Configuración → Básica |
| El código dice «no me sirve» | pasaron 15 minutos o se tipeó mal | generar otro desde la app |
| El bot no contesta y los logs dicen «Meta rechazó el envío 401» | token vencido o sin permisos | generar el token permanente del usuario del sistema (paso 4) |
| «Meta rechazó el envío 131030» | con el número de prueba, el teléfono no está en la lista «Para» | agregarlo en Configuración de la API |
