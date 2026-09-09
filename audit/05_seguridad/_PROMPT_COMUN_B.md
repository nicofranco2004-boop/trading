# Tanda B — contexto adicional

Leé **primero** `audit/05_seguridad/_PROMPT_COMUN.md` entero: todas sus reglas te aplican
(dónde auditar, evidencia MEDIDO/DEDUCIDO/ESTRUCTURAL, no tocar producción, no modificar código,
escribir el archivo ANTES de responder, el mapa es hipótesis y gana el código).

## Lo que ya salió en la Tanda A — no lo repitas, construí encima

Está todo en `audit/05_seguridad/5a-resumen.md`. Lo que te sirve saber de entrada:

- **Cero IDOR en los 264 endpoints.** Los que reciben un id filtran por dueño en la sentencia que
  produce el efecto. 47/47 rutas `/api/admin` exigen `get_admin_user`. **No vuelvas a auditar
  autorización endpoint por endpoint.**
- **La causa raíz dominante es "el fix aplicado en 1 de N call sites"**, con 8 casos. En todos, el
  arreglo correcto YA está escrito en el repo y no se propagó. Buscá ese patrón en tu área: es
  donde más rinde.
- **`SECRET_KEY` ya fue rotada** (2026-09-08) y ya no es una API key de Anthropic. Cerrado, ver
  `5a-paso0-secret-key.md`. **No lo reportes de nuevo.**
- Hallazgos de la Tanda A que **cruzan** con áreas de la B, para que los profundices en vez de
  redescubrirlos:
  - Los 4 endpoints de cron comparan el token con `!=` (no `hmac.compare_digest`), lo aceptan por
    `?token=` y por GET. `mantenimiento.py:56-112` documenta el patrón correcto y hay 9 usos bien
    hechos en el repo.
  - `POST /api/billing/webhook` (Mercado Pago) es fail-open en el caller (`main.py:27554`) aunque
    el módulo sea fail-closed. Confirmado que **no existe ninguna variable `MP_` en Railway**, así
    que quedó calificado BAJO. Verificá si conviene borrar la ruta.
  - `_check_rate_limit` arma la clave como `f"{ip}|{suffix}"` (`main.py:397`): todo límite "por
    email" o "por uid" es en realidad por IP. **31 call sites**, incluidas las cuotas de IA y de
    billing.
  - `GET /api/monthly` escribe (vía `_rollover_all_brokers`), y `get_effective_user` sólo exige
    permiso `read_write` para métodos != GET.

## Dos filtraciones de material de claves, medidas hoy en logs reales de producción

Las dos son de la misma familia y las dos son tuyas si caen en tu área:

1. **`ALERTS_CRON_TOKEN` apareció en claro** en los logs de acceso, porque el cron lo manda en la
   query string (`GET /api/alerts/evaluate?token=...`). Ya está reportado; lo que falta es el
   barrido: **¿qué otros secretos viajan por query string y terminan en logs?**
2. **`REBILL_API_KEY` asoma en cada arranque**: `backend/billing/rebill.py` escribe sus primeros 8
   caracteres en un warning (`key prefix: sk_...`). Además ese warning dice que la key **no tiene
   prefijo `sk_test_` ni `sk_live_`**, que es de lo que el código deduce el ambiente. Los dos
   puntos son de la Tanda B.

## Confirmaciones de configuración de producción (del founder, sobre el dashboard de Railway)

- `RENDI_ENV=prod` **está seteada**.
- **No existe ninguna variable `MP_`** (Mercado Pago está muerto de verdad).
- Existen `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_SECRET_KEY`, `SNAPSHOT_CRON_TOKEN`,
  `REBILL_API_KEY`, `REBILL_WEBHOOK_TOKEN`, `RESEND_API_KEY`, `ALLOWED_ORIGINS`, `DB_PATH`.
- **No se puede consultar Railway ni producción desde la auditoría.** Si tu conclusión depende de
  un valor de configuración que no está en el código, decilo en "lo que no pude verificar" con la
  pregunta exacta que hay que hacerle al founder.

## Contexto de producto que cambia la severidad

Rendi tiene ~1.000 usuarios reales con sus carteras cargadas, planes pagos con Rebill, período de
prueba, y un plan para asesores financieros. **Una filtración de datos financieros personales no
es un problema técnico, es el fin del producto.** Pero un plan pago regalado o una cuota de IA
quemada son plata real, no teoría: pesalos como tales y no los infles ni los minimices.
