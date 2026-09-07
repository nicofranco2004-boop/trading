# Audit sección Asesores — 2026-07-31

3 auditores paralelos sobre origin/main (`d46c23d`): copy+invitación+WhatsApp · cálculos · IA.
Excluido el backlog conocido del audit del 27/07. ~70 hallazgos nuevos.

## 🔴 LO MÁS GRAVE (arreglar antes de vender el plan)

1. **La etiqueta privada del asesor se filtra al cliente** — el label "¿Cómo lo identificás?" (ej. "Juan P — el que se asusta") sale en el email de invitación, el informe público y el texto de WhatsApp. Riesgo reputacional directo. Fix: precedencia `users.name → label` en superficies de cara al cliente. (`emails.py:994`, `ReportPublic.jsx:112`, `main.py:27444`)
2. **"Invitación enviada" aunque el email falló** — el send está en try/except que solo loguea; el asesor espera a un cliente que nunca recibió nada. (`main.py:26728`)
3. **Registro grupal: un cliente ambiguo se cae del lote sin aviso garantizado** — "registrale a Juan, Ana y Pedro" con dos Juanes → Juan excluido → el "sí" ejecuta 2 de 3 y el mensaje de éxito dice "0 filas afuera". (`main.py:28059`, `22448`)
4. **"vendile a Juan…" fuerza la tool de COMPRA grupal** — `_TRADE_INTENT_RE` matchea "vendile" y `tool_choice` fuerza `register_group_op` (solo compras) → draft de COMPRA donde el asesor dictó una venta. (`main.py:21660`, `22505`)
5. **Δ7d del libro sin piso de antigüedad en la base** — un cliente con snapshots frenados 60 días mete su delta de 2 meses en "Últimos 7 días". `flows_month` tiene el guard (`_stale_floor`); el Δ7d no. (`main.py:28353`)
6. **`tc_mep` cae al blue si la fila más nueva de fx_rates_daily tiene mep NULL** — el cron nocturno inserta solo blue → fin de semana sin logins = todo el libro valuado ~5% abajo y contradiciendo al AUM en la misma pantalla. `fx.py:50` documenta la trampa; el libro no la aplica. (`main.py:28346`, `27090`, `27525`)
7. **"Efecto mercado" contaminado por cargas de datos** — Δnet_deposited es un acumulado mutable hacia atrás: importar un broker viejo o un seed → "el mercado ganó US$ X" en el informe con matrícula CNV al pie. (`main.py:28384`, `27283`)
8. **La IA dentro de un cliente le habla al asesor como si fuera el dueño** — prompt retail puro: "tu cartera", contención emocional, preguntas-coach. Falta addendum "hablás con el ASESOR sobre la cartera de {label}". (`main.py:22213`)
9. **`/api/ai/analyze` sin lente Pro del asesor** — dentro de un cliente Free, los botones ✦ devuelven prompts descriptivos y el follow-up muestra upsell "pasate a Pro" AL ASESOR (el chat ya lo arregló; analyze no). (`main.py:19977`)
10. **3 tools de la IA consultan la cuenta VACÍA del asesor** — get_asset_operations/monthly_detail/realized_vs en book-mode responden "0 operaciones" con confianza sobre el libro. (`main.py:19278`)
11. **Chip + ejemplo del prompt piden "cash por cliente", dato que el contexto NO tiene** → el modelo lo inventa. (`main.py:14783`, `AICoach.jsx:57`)
12. **Informes públicos irrecuperables** — no hay GET /advisor/reports; los links viven en el useState del modal. Cerraste el modal = links perdidos (y públicos para siempre). (`AdvisorDashboard.jsx:726`)

## 📞 WHATSAPP (la pregunta de Nico): HOY NO SE PUEDE — y es la mayor oportunidad

- **No existe campo teléfono** en advisor_clients (solo label/notes/consent_ref).
- La CallQueue se llama "a quién llamar hoy" y **no se puede llamar desde ahí** (único botón: "Entrar →").
- "Texto WhatsApp" del informe = copiar al portapapeles; con 40 clientes son 40 ciclos manuales.
- El patrón ya existe: `utils/support.js whatsappUrl()` + `WhatsAppIcon` exportado — generalizar `whatsappUrl(msg, phone)` y listo.
- **Fix propuesto (chico, alto impacto):** columna `phone` + input en alta/edición + botón WhatsApp en cada card del roster, cada fila de la CallQueue (con mensaje pre-armado por motivo de cola, ya existen los `detail` en criollo) y en el envío del informe (`wa.me/<tel>?text=<wa_text>`).

## 🟡 MEDIAS destacadas (selección)

**Copy:** "AUM · snapshot {fecha}" en el roster (el dashboard ya dice "Total administrado" bien) · "fills" en la op grupal · "visión Free/Pro" como lenguaje de UI · "Idóneo registrado CNV" afirmado desde un campo de texto libre sin verificar · email de invitación dice "te está siguiendo" (vigilancia) y "no se crea nada sin este link" (falso: la cuenta ya existe) · error con `≠` y repr Python `'IOL'` · "Cliente 412: sin vínculo" (ID interno en vez del nombre).

**Invitación:** invitación vencida vuelve a "shadow" sin badge ni aviso · no se ve a qué email se invitó (reenviar = re-tipear de memoria) · no se puede cancelar una invitación · claim sin logo/matrícula del asesor ni explicación de qué es Rendi · aterrizaje post-claim ciego (navigate('/')) · el asesor no se entera cuando el cliente reclama.

**Cálculos:** off-by-one del corte de mes (la base incluye el día 1 → depósito del 1/8 invisible) · cortes UTC vs snapshots ART (la captación del mes desaparece las últimas 3h del mes; POST /snapshots del browser fecha "mañana") · AUM suma snapshots de cualquier antigüedad y el "datos al" muestra el máximo (stale tapado) · informe: tenencias de HOY con denominador del cierre del período, sin fecha · modo costo: weight_pct mezcla costo/valor · gráfico AUM se reescribe hacia atrás (cliente revocado desaparece de la historia; "+N clientes" nunca negativo) · cada KPI del hero cubre un subconjunto distinto sin decirlo · cripto USD en broker ARS: valor ÷MEP (~1450× hundido) en exposure/informe · auto-depósito del block trade cuenta como "captación del mes" · distribución excluye en silencio a los sin base.

**IA:** dos definiciones de retorno (chat nd actual vs libro max nd) → +20% vs +20.000% del mismo cliente · 88% del system prompt es material retail (glosario obligatorio "drawdown (la caída desde el pico)" a un matriculado; secciones de métricas que el libro no tiene → alucinación) · rutas del prompt base (/alertas, /analisis) llevan al asesor a SUS pantallas vacías · registro grupal sin card de confirmación con botón (el personal la tiene) ni total del lote · undo grupal sin short-circuit determinístico · notas privadas del asesor NO llegan al contexto de la IA · sin dimensión temporal por cliente (¿quién cayó esta semana? irrespondible) · exposure[] (la joya) sin ningún chip que la descubra · remember_user_fact del asesor escribe en la memoria del CLIENTE.

## 💡 OPORTUNIDADES DE PRODUCTO (consolidadas, rankeadas)

1. **WhatsApp end-to-end** (phone + botones + mensajes pre-armados por motivo + informe directo). El desbloqueo de mayor palanca.
2. **Brief matinal del libro** — queues+star+flows ya calculados; push 8:30 "3 clientes para llamar hoy · el libro cayó 1,8% (AL30 explica 60%)".
3. **Borrador de mensaje al cliente por IA** (bloque draft_message con Copiar/WhatsApp): "explicale a Marcos por qué cayó" → texto listo para reenviar, registro cliente-final sin jerga.
4. **Pantalla "Informes enviados"** (GET /advisor/reports + revocar + ¿lo abrió?) — cierra también el hueco de seguridad de links eternos.
5. **Estado de invitación de primera clase** (email invitado visible, badge vencida, cancelar, aviso al reclamar, recordatorio día 5).
6. **TWR/MWR por cliente + benchmark del libro** (MERVAL USD/S&P) — hoy hay 3 retornos distintos y ninguno time-weighted; es el número que justifica el fee.
7. **Fee estimado sobre AUM** (bps configurables) → "tu ingreso del período": convierte el libro en el P&L del asesor.
8. **Captación desagregada + churn** (altas, aportes, retiros, bajas, AUM perdido — hoy todo colapsa en un neto contaminado).
9. **Onboarding post-claim de 3 pasos** + marca del asesor en la pantalla de claim.
10. **Alertas del libro** ("avisame si un cliente cae >15%") — reusa el motor de alertas nuevo, por cliente.
11. **Chips dinámicos** data-driven del libro + chip que enseñe el registro grupal por chat (la feature killer no tiene discovery).
12. **Cobertura de datos como KPI** (cuántos clientes con snapshot fresco, posiciones sin precio, FX stale) — hoy el asesor no puede saber qué tan confiable es su número.

## Lotes de fix sugeridos
- **Lote 1 (pre-venta, seguridad/confianza):** #1 label filtrado · #2 email fallido · #3 excluidos del lote · #4 vendile · #12 informes.
- **Lote 2 (números):** #5 Δ7d piso · #6 MEP NULL · #7 efecto mercado/import · off-by-one mes · UTC/ART · retorno unificado chat/libro.
- **Lote 3 (IA):** addendum asesor-en-cliente · lente Pro en analyze · tools de cuenta vacía · cash por cliente al contexto · notas al contexto.
- **Lote 4 (producto):** WhatsApp end-to-end + pantalla de informes + estado de invitación.
