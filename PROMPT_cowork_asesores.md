# PROMPT para Claude Cowork — Qué le falta al Plan Asesor de Rendi

> Pegar tal cual en Cowork. Requiere acceso a web. No requiere acceso al repo.

---

## Quién sos y qué te pido

Sos analista de producto de fintech. Te voy a describir **exactamente qué es Rendi y qué tiene hoy el Plan Asesor**. Tu trabajo tiene dos partes, en este orden:

1. **Investigar** (web, fuentes verificables) qué funcionalidades tienen las plataformas para asesores financieros / wealth management del mundo y de LatAm, y cuáles de ésas tendría sentido traer a Rendi.
2. **Devolverme una lista priorizada de oportunidades**, cada una atada a **datos que Rendi YA tiene** (te los enumero abajo) y con el sesgo puesto en lo que **la IA de Rendi habilita** y una plataforma tradicional no.

No me devuelvas un listado genérico de "features de PMS". Quiero cosas que **este** producto, con **estos** datos, con **este** mercado, puede construir.

---

## 1. Qué es Rendi

- **Producto retail (B2C, lo original):** un tracker de cartera **multi-broker** para inversores argentinos. El usuario sube los exports/PDFs de sus brokers (Cocos, IOL, Balanz, Bull Market, PPI, IEB, inviu, Binance, Schwab, Wallbit, etc. — 18 parsers) o carga a mano, y Rendi reconstruye el historial completo: lotes FIFO, P&L realizado y no realizado, costo en pesos y en dólares, cash por broker, cupones de bonos, splits, conversiones ARS↔USD al MEP.
- **El diferencial real:** Rendi es el único que ve **todos los brokers juntos**. Ningún broker argentino puede decirte "vendiste tus ganadoras 3,5× más rápido que tus perdedoras" porque ninguno ve el historial completo. Rendi sí.
- **Mercado:** Argentina. Todo está atravesado por el problema de la moneda (pesos vs dólar MEP/CCL/blue, inflación, CEDEARs, bonos soberanos, ONs, FCIs, cauciones).
- **Equipo:** fundador solo + IA. No hay equipo de 20 ingenieros. Un feature "grande" tiene que valer mucho para entrar.
- **Regla de venta que es también restricción legal:** **"Rendi registra, no opera."** No ejecuta órdenes, no guarda claves de broker para tradear, no toca la plata. El Agente Productor (AP) argentino tiene **prohibido** recibir fondos, gestionar órdenes y administrar carteras. Nada de lo que propongas puede violar esto.

## 2. Qué es el Plan Asesor (B2B2C) y qué ya está construido

El asesor financiero paga un plan flat (~ARS 120.000/mes hasta 40 clientes). Ve el "libro" (el conjunto de las carteras de sus clientes) y puede entrar a la cuenta de cada cliente con visión completa. El cliente entra a su propia cuenta y ve la versión Free (doble monetización: el asesor le hace el onboarding gratis y el cliente se convierte solo).

**Todo esto YA ESTÁ CONSTRUIDO Y DEPLOYADO — no me lo propongas de nuevo:**

**Estructura y acceso**
- Multi-cliente real: el asesor cambia de contexto y toda la app sirve la cuenta del cliente (roster, drill-down, escritura gateada por permiso, tests de IDOR).
- Invitación por email → el cliente reclama la cuenta y se queda con ella; puede revocar al asesor desde su config.
- Nav propio del asesor (Dashboard del libro / Clientes / Novedades / Rendi AI / Alertas).

**El libro**
- **Dashboard del libro:** capital total administrado, delta semanal, aportes − retiros del mes, efecto mercado, y gráfico de **evolución del capital administrado** con la descomposición mercado-vs-flujos.
- **"Motor estrella":** P&L por activo **cross-cliente** — qué activo le está haciendo ganar o perder a la mayoría de sus clientes.
- **Composición del libro** y drill-down "quiénes tienen este activo".
- **Colas "clientes que necesitan tu atención":** drawdown ajustado por flujos, exceso de cash en pesos, cliente inactivo >90 días, cliente sin datos cargados.
- **TWR del libro** (time-weighted return, sellado append-only, con semáforo de calidad de datos: si no hay historia medible no publica un porcentaje, publica el motivo). Benchmark contra plazo fijo UVA medido en dólar MEP.

**Operación**
- **Operación grupal (block trade):** una compra/venta que se registra en N clientes a la vez, con broker y precio editable por fila, batch deshacible.
- **Grupos dinámicos de clientes:** reglas combinables ("todos los que tengan Amazon", "más de USD 20.000", "más de 30% en liquidez", "más de 30% en acciones argentinas") que se recalculan solas. Los grupos enganchan con operación grupal, informes, alertas y WhatsApp.
- Notas privadas por cliente, teléfono, botón de WhatsApp en el roster y en las colas.

**Comunicación**
- **Informe del período brandeado:** con logo y matrícula CNV del asesor, link público `/i/<token>`, versión lista para pegar en WhatsApp, generación en lote, pantalla de "informes enviados", revocación de links.
- **Brief diario ×2 por email**, anclado a la rueda argentina: uno a la **apertura** (~11:00 ART, el PLAN del día: a quién llamar, eventos de hoy de activos que tienen sus clientes, invitaciones por vencer) y uno al **cierre** (~17:15, el RESULTADO: delta del libro valuado en vivo, mejor y peor cliente del día, qué activos mandaron).
- **Alertas a nivel libro:** "avisame si la cartera de algún cliente se mueve más de X%", acotable a un grupo.
- **Novedades cross-cliente:** eventos corporativos y noticias del universo de tickers de todos sus clientes, con atribución ("afecta a 15 clientes: Juan P, Ana G +13").

**IA (esto es central para lo que te pido)**
- **Rendi AI en modo libro:** el asesor chatea con un modelo que tiene, server-side, los agregados de su libro completo — AUM, colas, exposición cross-cliente por activo con peso por cliente, top-5 tenencias por cliente, cash por cliente, notas privadas. Puede **registrar operaciones grupales por chat** ("registrale a Juan $300k y a Ana $400k del CEDEAR de Tesla a 58.900"), con confirmación en turno separado y deshacer.
- **Rendi AI dentro de un cliente:** el mismo chat pero hablándole al asesor sobre ese cliente puntual.
- Toda la app tiene lecturas de IA por pantalla (dashboard, insights, composición, eventos, noticias, posición, operaciones, reportes...) construidas por "builders" que arman contexto numérico verificado antes de llamar al modelo.

## 3. Qué datos tiene Rendi (la materia prima de lo que propongas)

Esto es lo que hay en la base **hoy**, sin construir nada nuevo:

- **Historial de operaciones a nivel LOTE** (FIFO abierto/cerrado): fecha, activo, broker, cantidad, precio de entrada y salida, comisiones, moneda, P&L realizado y no realizado, en pesos y en dólares.
- **Snapshots diarios por cuenta** (cron nocturno + intradiario): valor total, capital neto aportado, tenencias, firma de origen del dato ('cron'|'browser'|'import') para saber qué medición es real y cuál sintética.
- **Cash por broker y moneda**, flujos (depósitos/retiros/conversiones), cauciones, plazos fijos, cupones y amortizaciones de bonos.
- **Precios**: histórico y último precio por activo, FX diario (MEP compra/venta/medio, blue, CCL), índices de bonos.
- **Clasificación de activos**: tipo (acción AR, CEDEAR, bono, ON, letra, FCI, cripto, acción US) y sector.
- **Detectores de sesgos comportamentales** ya implementados sobre el historial: efecto disposición (vender ganadoras y aguantar perdedoras), sobre-operación, concentración, timing. Con severidad, evidencia numérica y citas académicas.
- **Eventos corporativos y noticias** por ticker, cacheados.
- **Datos del vínculo asesor-cliente**: roster, notas privadas, teléfono, grupos, historial de operaciones grupales con su lote, informes enviados, alertas configuradas, TWR sellado por mes.
- **Memoria de la IA sobre el usuario** (`ai_user_facts`) y uso de IA por día/herramienta.
- **Metas y diagnóstico de objetivos** del lado retail.
- Login history, plan/billing, importaciones con su trazabilidad fila por fila.

## 4. Qué se decidió NO hacer (y por qué) — no me lo re-propongas sin un argumento nuevo

- Ejecutar órdenes o guardar claves de broker para operar → **prohibido** para un AP.
- Track record público del asesor → riesgo publicitario CNV.
- Export regulatorio AGE_007 / AML-UIF → obligación del ALyC, no del asesor.
- CRM completo y compliance completo → scope creep; a lo sumo "CRM-lite" sobre las colas.
- Cobrar por AUM → mala óptica regulatoria; el plan es flat.

## 5. Lo que YA está identificado como pendiente (partí de acá, no lo redescubras)

Un research previo dejó esta lista de pendientes conocidos. **No me los repitas como hallazgo tuyo.** Si tu investigación los confirma, decime qué le agregarías o cómo lo harías distinto; si tu investigación los contradice, decímelo con fuente:

1. **Carteras modelo + drift + rebalanceo precargado** (corazón de la categoría PMS).
2. **Pack de suitability**: perfil de riesgo visible en el roster, cola de "desvío de perfil", revisión anual, consentimiento por operación fuera de perfil (obligación CNV literal).
3. **Alta masiva del libro**: CSV de roster + tenencias en batch (hoy el día 1 son 2-3 horas de clicks).
4. **Módulo "Mi negocio"**: fee por cliente (%AUM / fijo / retrocesión), devengado del mes, success fee con high-water mark.
5. **CRM-lite sobre las colas**: contactado / posponer / próximo contacto.
6. **Audit trail** inmutable de quién hizo qué en la cuenta de un cliente (RG 1015/2024, 5 años).
7. **Carpeta fiscal del libro** (batch para el contador).
8. **Modo prospecto**: importar la tenencia de un candidato sin cuenta real y darle un diagnóstico brandeado.
9. **Capa cliente-facing brandeada** (co-branding del portal del cliente).

## 6. Contexto competitivo que ya sé (verificalo, no lo asumas)

- En Argentina, Rendi es hoy el único self-serve con precio publicado para el **asesor independiente multi-broker**. Docta es enterprise demo-gated (back-office de ALyCs y family offices). Los portales de brokers (IOL Asesores, Bull Advisors, Cocos AFI, PPI EAMs) son **mono-silo**: cada uno ve solo sus propios comitentes.
- **El incumbente real es Excel.**
- Economía del asesor argentino: ~100 clientes / USD 3M de AUM al 1% ≈ USD 2.500/mes. El ingreso real se compone de retrocesiones (0,5-1%), fee y success fee (15-20%).

---

## 7. TU TRABAJO

### Parte A — Investigación (con fuentes)

Investigá qué funcionalidades ofrecen hoy las plataformas para asesores. Cubrí como mínimo estas familias (los nombres son puntos de partida, **verificá cada uno, no los des por buenos, y agregá los que falten**):

- **Portfolio management / reporting**: Orion, Addepar, SS&C Black Diamond, Envestnet | Tamarac, Advyzon, Panoramix.
- **Planificación financiera**: eMoney, RightCapital, MoneyGuidePro, Conquest.
- **Riesgo y suitability**: Nitrogen (ex-Riskalyze), Andes Wealth.
- **Research y propuesta comercial**: YCharts, Morningstar Advisor Workstation (ojo: Morningstar Office se discontinúa).
- **Fiscal y operativa**: Holistiplan, FP Alpha.
- **CRM del asesor**: Wealthbox, Redtail, Practifi.
- **Custodios/plataformas de nueva generación**: Altruist, Betterment for Advisors.
- **LatAm / Argentina / Brasil**: Docta, Vale.money, Fintual, y lo que encuentres del mercado brasileño de asesores (que está mucho más desarrollado: mirá qué usan los escritórios de agentes autónomos vinculados a XP/BTG).
- **IA aplicada al asesor**: qué está saliendo en 2025-2026 — notetakers de reuniones, generación de propuestas, asistentes de compliance, resúmenes de cliente. Acá quiero especialmente que busques **qué se está construyendo ahora**, no qué había en 2023.

Para cada plataforma anotá **qué hace que valga la pena copiar**, no el catálogo entero.

### Parte B — Oportunidades para Rendi

Devolveme **entre 12 y 18 oportunidades priorizadas**. Para cada una:

| Campo | Qué quiero |
|---|---|
| **Nombre** | Cómo se llamaría en Rendi, en criollo (nada de jerga de mesa de dinero) |
| **Qué es** | 2-3 frases. Qué ve el asesor en pantalla |
| **Quién lo tiene** | Plataforma(s) + link + qué versión de la idea tienen |
| **El trabajo que resuelve** | Qué hace hoy el asesor argentino a mano/en Excel que esto le saca de encima |
| **Datos que lo habilitan** | Nombrá los datos concretos de la sección 3. Si necesita un dato que Rendi NO tiene, decilo explícitamente y decí de dónde saldría |
| **Rol de la IA** | Si aplica: qué parte la hace el modelo y qué parte tiene que ser determinística. Sé duro acá — un número inventado por un LLM en la cara de un cliente mata el producto |
| **Esfuerzo** | chico / medio / grande, con una línea de por qué |
| **Riesgo regulatorio** | CNV, protección de datos (Ley 25.326), o ninguno |
| **Qué lo mataría** | La razón más fuerte para NO hacerlo |

Ordenalas por **(valor para el asesor × probabilidad de que lo use todas las semanas) ÷ esfuerzo**. Decime explícitamente cuáles son **las 3 que harías primero** y por qué.

### Parte C — Lo que nadie tiene

Aparte del ranking, dame **3 a 5 ideas que ninguna plataforma que encontraste tiene**, y que sólo son posibles porque Rendi tiene el historial multi-broker completo, los detectores de sesgos y una IA con el libro entero en contexto. Acá quiero que te la juegues. Marcalas claramente como especulativas.

### Parte D — Descartes

Cerrá con las funcionalidades que encontraste en la investigación y que **descartás para Rendi**, con el motivo en una línea cada una (mercado equivocado, ilegal para un AP, requiere custodia, requiere un equipo que no existe, el dato no está).

---

## 8. Reglas de la entrega

- **Todo hallazgo de la Parte A lleva fuente con URL y fecha de consulta.** Si algo no lo pudiste verificar, escribí "no verificado" al lado. Prefiero un hallazgo menos que uno inventado.
- **Nada de features fantasma:** si decís que una plataforma hace X, tiene que estar en su documentación, changelog, pricing page o en una review con fecha.
- **Escribí en español rioplatense.** El copy de Rendi no usa jerga: no es "drawdown ajustado por flujos", es "cuánto perdió sin contar lo que sacó". Cada número que propongas mostrar tiene que poder explicarse en una frase en criollo.
- **No propongas nada que implique ejecutar órdenes, mover plata o guardar claves de trading.**
- **Distinguí siempre "esto ya lo tiene Rendi" de "esto es nuevo".** Si dudás si algo ya existe, mirá la sección 2 antes de escribirlo.
- Formato: un documento con las cuatro partes (A investigación, B ranking, C ideas propias, D descartes). La Parte B como tabla o como fichas, lo que quede más legible.
- Si en algún momento te falta un dato mío para decidir, no adivines: dejalo anotado en una sección final de "preguntas para Nico".
