## 1. Stack, estructura e infraestructura

Todo lo de esta sección se leyó contra la copia de `origin/main` en el commit `b74f450f` (2026-09-05), o sea producción. Las rutas van relativas a la raíz del repo.

Convención: `[V]` = verificado leyendo el código, con cita. `[I]` = inferencia mía, digo de qué me agarré.

---

### 1.1 El resumen en una pantalla

| Capa | Qué es | Dónde se declara |
|---|---|---|
| Backend | Python 3.11 + FastAPI 0.115.0, servido por uvicorn 0.30.6 | `backend/requirements.txt:1,3`, `nixpacks.toml:12,31` |
| ORM | **No hay.** SQL crudo con `?` en todos lados | `backend/pgshim.py:3-4` (*"3.293 placeholders `?` en ~1.400 llamadas con SQL crudo y CERO ORM"*); grep de `sqlalchemy\|alembic\|peewee\|tortoise` en `backend/` da **cero** resultados |
| Cliente de base | `sqlite3` de la stdlib (motor actual) + `psycopg[binary]==3.2.13` (motor dormido) | `backend/main.py:9,431`, `backend/requirements.txt:36` |
| Frontend | React 18.3.1 + react-router-dom 6.30.3, SPA | `frontend/package.json:15-18`, `frontend/src/main.jsx:3` |
| Bundler | Vite 5.4.21 con `@vitejs/plugin-react` 4.7.0 | `frontend/vite.config.js:1-2`, lockfile |
| Estilos | Tailwind 3.4.19 (`darkMode: 'class'`) + PostCSS 8.5.10 + autoprefixer | `frontend/tailwind.config.js:20-21`, `frontend/postcss.config.js` |
| Gráficos | Recharts 2.15.4 | `frontend/package.json:19` |
| Íconos | lucide-react 0.441.0 | `frontend/package.json:14` |
| SEO/head | react-helmet-async 3.0.0 | `frontend/package.json:17`, `frontend/src/main.jsx:4` |
| Tests back | pytest (241 archivos en `backend/tests/`) | `backend/pytest.ini:29-31` |
| Tests front | vitest 4.1.5, `environment: 'node'`, 55 archivos `*.test.js(x)` | `frontend/package.json:10-11,27`, `frontend/vite.config.js:68-70` |
| IA | SDK `anthropic>=0.97.0`; modelos `claude-haiku-4-5` (Free) y `claude-sonnet-4-6` (Pro) | `backend/requirements.txt:10`, `backend/ai/llm.py:45-46` |
| Deploy back | Railway (nixpacks) | `railway.toml:4-8`, `nixpacks.toml` |
| Deploy front | Vercel | `frontend/vercel.json:1-8` |

**Tamaño del sistema [V]:** `backend/main.py` tiene **38.029 líneas** (`wc -l`). `backend/twr.py` 2.213, `backend/behavioral.py` 1.880, `backend/snapshots_job.py` 1.049, `backend/schema_pg.sql` 2.035. En backend hay 149 archivos `.py` fuera de tests, y 239 dentro de `backend/tests/`. El frontend tiene 350 archivos `.js/.jsx` en `src/` sumando ~100.953 líneas.

---

### 1.2 Versiones exactas

#### Backend — `backend/requirements.txt`

| Paquete | Pin | Línea |
|---|---|---|
| fastapi | `==0.115.0` | :1 |
| python-multipart | `==0.0.12` | :2 |
| uvicorn | `==0.30.6` | :3 |
| yfinance | `>=1.2.0` | :4 |
| requests | `==2.32.3` | :5 |
| pydantic | `==2.9.2` | :6 |
| passlib[bcrypt] | `==1.7.4` | :7 |
| bcrypt | `==4.0.1` | :8 |
| python-jose[cryptography] | `==3.3.0` | :9 |
| anthropic | `>=0.97.0` | :10 |
| httpx | `>=0.27,<1.0` | :22 |
| python-dotenv | `>=1.0.0` | :23 |
| pywebpush | `>=2.0.0` | :24 |
| apscheduler | `==3.10.4` | :25 |
| psycopg[binary] | `==3.2.13` | :36 |
| defusedxml | `==0.7.1` | :37 |
| boto3 | `>=1.34.0` | :38 |
| openpyxl | `>=3.1.0` | :39 |
| pdfplumber | `>=0.11.0` | :41 |

**Nota rara verificada [V]:** el propio `requirements.txt:12-21` documenta que `httpx` estuvo **importado en producción sin estar declarado**, colándose como dependencia transitiva de `anthropic`. Está arreglado (línea 22), pero el comentario deja escrito el patrón: "código de producción apoyado en un paquete que nadie declaró".

**Contradicción entre dos archivos [V]:** `backend/dberrors.py:14-16` dice textualmente que *"`psycopg` NO está en requirements.txt todavía —la migración es un spike—"*, y `backend/requirements.txt:36` lo tiene pinneado en `3.2.13`. El comentario quedó viejo; el `try/except ImportError` de `dberrors.py:34-44` que dependía de eso ahora siempre entra por la rama `else` en Railway. No es un bug (la rama `else` es la correcta), pero es un comentario que miente sobre el estado del sistema.

#### Frontend — `frontend/package.json` + `package-lock.json` (lockfileVersion 3)

| Paquete | Rango en package.json | Resuelto en el lock |
|---|---|---|
| react / react-dom | `^18.3.1` | 18.3.1 |
| react-router-dom | `^6.26.2` | **6.30.3** |
| recharts | `^2.12.7` | **2.15.4** |
| lucide-react | `^0.441.0` | 0.441.0 |
| react-helmet-async | `^3.0.0` | 3.0.0 |
| vite | `^5.4.3` | **5.4.21** |
| tailwindcss | `^3.4.10` | **3.4.19** |
| postcss | `^8.4.47` | 8.5.10 |
| autoprefixer | `^10.4.20` | 10.5.0 |
| @vitejs/plugin-react | `^4.3.1` | 4.7.0 |
| vitest | `^4.1.5` | 4.1.5 |

No hay TypeScript, ni ESLint config, ni Prettier en el repo [V]: `frontend/package.json:21-28` sólo lista esas seis devDependencies, y no hay `tsconfig.json` ni `.eslintrc*` en el árbol.

---

### 1.3 Cómo se levanta en dev

Hay **tres** scripts de arranque en la raíz, con solapamiento y uno de ellos roto.

**`dev.sh` — el que anda y el que parece el vigente [V].** `dev.sh:39` lanza `python3 -m uvicorn main:app --reload --port 8000` con `nohup` desde `backend/`, y `dev.sh:44` lanza `npm run dev` desde `frontend/`. Subcomandos `start|stop|status|logs` (`dev.sh:30-78`), logs en `/tmp/rendi-backend.log` y `/tmp/rendi-frontend.log` (`dev.sh:11-12`). El "stop" es un `lsof -t | xargs kill -9` sobre los puertos 8000 y 5173 (`dev.sh:16-19`) — mata *cualquier* proceso en esos puertos, no sólo los suyos.

**`start.sh` — ESTÁ ROTO [V].** `start.sh:11-26` corre un `python3 -c` que, si `trading.db` no existe o `positions` está vacía, hace `import seed; seed.seed()`. Pero `backend/seed.py:7-10` hace `print(...)` + `sys.exit(1)` **a nivel de módulo**: el sólo `import seed` termina el proceso con código 1. Como `start.sh:2` tiene `set -e`, el script muere ahí. O sea: `start.sh` funciona únicamente en el caso en que la base ya existe y tiene posiciones (la rama `else` del `if`, que sólo imprime "✅ Base de datos ya inicializada"). El propio `seed.py:1-5` se declara DEPRECATED, y `backend/pgshim.py` lo llama "código muerto" en su docstring.

**`start-rendi.sh` — el "doble click" [V].** Hace lo mismo que `dev.sh` pero en foreground con colores y trap de limpieza (`start-rendi.sh:62-89`). Dos cosas que valen la pena marcar:
- **`start-rendi.sh:7-8` hace `source ~/.zshrc` y `~/.bashrc`** dentro del script, para heredar `ANTHROPIC_API_KEY`. Es decir, el arranque de la app ejecuta el rc del usuario.
- 🔴 **`start-rendi.sh:43` tiene una `SECRET_KEY` hardcodeada y commiteada al repo** (`export SECRET_KEY=c248...`). Es la clave de firma de los JWT. Está pensada para dev (que los tokens sobrevivan reinicios), pero está en el repo, en texto plano, y cualquiera que corra este script en una máquina que después sirva tráfico firma tokens con una clave pública. Ver §1.9.

**El proxy de dev [V]:** `frontend/vite.config.js:46-50` proxea `/api` a `http://localhost:8000`. El frontend nunca arma una URL absoluta: `frontend/src/utils/api.js:106,228,265,304` hace `fetch('/api' + path, ...)`. Misma forma en dev (proxy de Vite) y en prod (rewrite de Vercel).

**Config de preview de Claude Code [V]:** `.claude/launch.json` define dos configuraciones alternativas — `backend-csv` en el puerto **8001** y `frontend-csv` en el **5174** — para levantar una segunda instancia sin pisar la de `dev.sh`.

---

### 1.4 Cómo se buildea y deploya en prod

**Sí: backend a Railway, frontend a Vercel. Verificado, no asumido.**

**Backend → Railway [V]:**
- `railway.toml:4-5` declara `builder = "nixpacks"`; `:7-8` pone `restartPolicyType = "on_failure"`.
- `nixpacks.toml:11-16` instala `python311` y `gcc` como nixPkgs, y agrega `stdenv.cc.cc.lib` a `nixLibs` (el comentario explica que sin eso numpy — que viene con yfinance — crashea con `libstdc++.so.6: cannot open shared object file`).
- `nixpacks.toml:23-28`: crea un venv en `/opt/venv`, **pinea `pip<26`** (el comentario dice que pip 26.1.1 rompe el resolver con `fastapi==0.115.0`), e instala `backend/requirements.txt`.
- `nixpacks.toml:30-31`: el comando de arranque es `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`. **Un solo proceso, sin `--workers`.**
- Confirmación desde el otro lado: `backend/main.py:34293` lee `RAILWAY_GIT_COMMIT_SHA` para reportar el commit vivo en `/api/health`, y `backend/billing/rebill.py:107` lee `RAILWAY_ENVIRONMENT` para decidir si está en producción.
- El host concreto está escrito en el frontend: `frontend/vercel.json:6` y `frontend/index.html:88` nombran `https://trading-production-143b.up.railway.app`.

**Frontend → Vercel [V]:**
- `frontend/vercel.json:2-4`: `buildCommand: npm run build`, `outputDirectory: dist`, `framework: vite`.
- `frontend/vercel.json:6` reescribe `/api/(.*)` → `https://trading-production-143b.up.railway.app/api/$1`. **Server-side**, así que el browser nunca cruza origin (por eso `backend/main.py:240-243` dice que CORS "casi no entra en juego" y queda como defensa en profundidad).
- `frontend/vercel.json:7` es el fallback SPA: todo lo demás → `/index.html`.
- `frontend/vite.config.js:11-18` toma `VERCEL_GIT_COMMIT_SHA` (o `COMMIT_REF`, o un timestamp) como identidad del build.

**Cabeceras que pone Vercel [V]** (`frontend/vercel.json:9-56`): HSTS con `preload`, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` amplia, y una **CSP completa** (`:18`) que permite scripts de `googletagmanager`, `google-analytics` y `connect.facebook.net`, y `connect-src` al host de Railway. `/assets/*` va con `max-age=31536000, immutable`; `/`, `/index.html` y `/version.json` van con `no-store`.

**El mecanismo de auto-update [V]:** `frontend/vite.config.js:26-41` es un plugin propio que escribe `dist/version.json = { version: <buildId> }` al terminar el build, y `:44` inyecta `__BUILD_ID__` en el bundle. El cliente compara "lo que corro" contra "lo último publicado" (por eso `version.json` va `no-store` en `vercel.json:50-55`). Complementariamente, `frontend/src/main.jsx:20-40` documenta y maneja el caso de chunks viejos 404-eados por Safari con un reload one-shot y loop guard en `sessionStorage`.

**Code splitting [V]:** `frontend/vite.config.js:56-66` hace `manualChunks` de `recharts`, `lucide-react` y el trío react/react-dom/react-router-dom, con `chunkSizeWarningLimit: 700`. Además, `frontend/src/App.jsx:43-66` carga ~20+ páginas con `React.lazy`.

**No hay CI [V].** No existe `.github/`, ni `.gitlab-ci.yml`, ni Dockerfile, ni `Makefile`. El único contenido oculto en la raíz es `.claude/` (config de Claude Code), `.gitignore` y `backend/.env.example`. **Deploy = push a la rama** (no hay gate automático: nada corre `pytest` ni `vitest` antes de que Railway/Vercel construyan).

---

### 1.5 Árbol de carpetas (primer y segundo nivel)

```
/
├── backend/          FastAPI. Todo el negocio. 149 .py fuera de tests.
├── frontend/         SPA React+Vite.
├── .claude/          Config de Claude Code (settings.local.json, launch.json). No es infra de la app.
├── railway.toml      Deploy Railway (builder=nixpacks, restart on_failure).
├── nixpacks.toml     Build Railway: python311+gcc, venv, pip<26, uvicorn en $PORT.
├── dev.sh            Dev local: uvicorn:8000 + vite:5173 en background.
├── start.sh          Dev local "instalá todo y arrancá". ROTO (ver §1.3).
├── start-rendi.sh    Dev local en foreground, colores, SECRET_KEY hardcodeada.
├── .gitignore        Ignora *.db, backups y .env (ver §1.9).
└── *.md              5 documentos sueltos (ver §1.10).
```

#### `backend/` — segundo nivel

| Carpeta | Para qué sirve REALMENTE |
|---|---|
| `backend/ai/` | Todo lo de Claude: `llm.py` (cliente + modelos + tabla de precios, `:45-52`), `registry.py` (mapea `topic_id` → builder+prompt, `:1-8`), `prompts.py`, `quota.py`, `cache.py`, `schema.py`, `plan.py`, `trade_tickers.py`, `ar_bonds_metadata.py`. |
| `backend/ai/builders/` | 34 archivos, uno por pantalla o sub-componente (`dashboard.py`, `insights_*.py`, `reports.py`, `behavioral.py`…): arman el payload de contexto que se le manda al modelo. |
| `backend/billing/` | Suscripciones y plata: `rebill.py` (procesador ACTIVO), `mercadopago.py` (legacy, se mantiene "por si hay que revertir" según `backend/.env.example:71-74`), `subscriptions.py` (job diario de ciclo de vida, `:1-7`), `trial.py`, `credits.py`, `pricing.py`, `emails.py` (Resend). |
| `backend/home/` | La pantalla Home: `briefing.py` (arma 1-3 cards según los holdings del usuario, `:1-7`) y `market.py`. |
| `backend/importing/` | El importador de brokers, en etapas: `pipeline.py` orquesta parse → normalize → validate → preview (`:1-2`), y después `mapper.py`, `normalizer.py`, `validator.py`, `persister.py`, `rebuild.py`, `preview.py`, `sections.py`, `tenencia.py`, `cash_sim.py`, `invariantes.py`, `fx_migrate.py`, `recompute_backfill.py`, `excel.py`, `proyeccion.py`, `maturity.py`, `fci_map.py`, `tickers_cd.py`, `schema.py`, `seed.py`. |
| `backend/importing/parsers/` | 18 parsers, uno por broker/formato: balanz (×4), binance (×3), bullmarket, cocos, ieb, inviu, iol, ppi, schwab, generic + `base.py` y `registry.py`. |
| `backend/pricing/` | Precios que no vienen de yfinance: `fci.py` (FCIs vía ArgentinaDatos/CAFCI, con la trampa del `vcp` que es por 1000 cuotapartes, `:1-6`) y `bond_amortization.py`. |
| `backend/reporting/` | Los "reportes de período": `builder.py` (`build_period_report`, `:1-6`), `detectors.py`, `timeline.py`, `schema.py`. |
| `backend/scripts/` | 20 scripts de operación/migración, ninguno importado por la app: el copiador a Postgres, el verificador, `mkschema.py`, `backup_db.py`, backfills, `iol_spike.py`, y **tres archivos `test_*.py` que NO son tests** (ver §1.8). |
| `backend/tests/` | 241 archivos de test + `conftest.py`, `fixtures/`, `fallas_conocidas.txt`. |

Archivos sueltos de `backend/` que valen mención: `main.py` (38k líneas: rutas, auth, migraciones de esquema, scheduler, endpoints de admin), `twr.py` (121KB, motores de retorno), `behavioral.py` (82KB), `snapshots_job.py` (el cron diario), `pgshim.py`/`pgsesion.py`/`dberrors.py` (la capa Postgres, §1.7), `mantenimiento.py` (§1.8), `schema_pg.sql` (DDL generado), `iol_api.py`, `wallbit.py`, `fx.py`, `performance.py`, `realized_pnl.py`, `ledger_replay.py`, `alerts_engine.py`, `advisor_*.py` (4), `goals_diagnostic.py`, `price_history.py`, `wrapped.py`, `flujos.py`, `analysis_prep.py`, `sim_import.py`, `seed.py` (muerto).

#### `frontend/` — segundo nivel

| Carpeta | Para qué sirve REALMENTE |
|---|---|
| `frontend/src/pages/` | 51 archivos: una página por ruta. Incluye forks explícitos por viewport (`Home.jsx`/`HomeMobile.jsx`, `Positions.jsx`/`PositionsMobile.jsx`, `PositionDetailMobile.jsx`) y las 4 pantallas del plan asesor (`Advisor*.jsx`). |
| `frontend/src/components/` | 82 entradas: 65 componentes sueltos + 17 subcarpetas temáticas (`ai/`, `advisor/`, `alerts/`, `blog/`, `diagnostico/`, `fundamentals/`, `guide/`, `home/`, `import/`, `landing/`, `mobile/`, `onboarding/`, `operations/`, `plan/`, `profile/`, `reports/`). |
| `frontend/src/utils/` | 94 archivos, y acá vive **la mitad del cálculo del producto** (bonos, FIFO, FX, benchmark, composición, formato) junto con sus `.test.js` al lado. `api.js` es la única puerta HTTP. |
| `frontend/src/hooks/` | 18 hooks: moneda (`useCurrencyChoice`), FX histórico, datos mensuales, alertas, push, pull-to-refresh, `useIsMobile`. |
| `frontend/src/contexts/` | 7 contextos + 2 tests: `AuthContext`, `CurrencyContext` (el selector global USD/Pesos), `ThemeContext`, `AlertsContext`, `AdvisorContext`, `CoachDrawerContext`, `PrivacyContext`. |
| `frontend/src/data/` | Un solo archivo: `planCatalog.js` (el catálogo de planes; `backend/billing/emails.py:769` lo nombra como fuente). |
| `frontend/src/__design__/` | El guard del sistema visual: `design-baseline.json` (deuda congelada) + `design-contract.test.js`, que corre con `npm test` y falla ante violaciones NUEVAS (`:1-16`). |
| `frontend/scripts/` | Herramientas de build/mantenimiento fuera del bundle: `design-patterns.mjs` (walker compartido, vive acá **para no contarse a sí mismo**, `:9-14`), `gen-design-baseline.mjs`, `download-logos.mjs` (baja 315 logos a `public/logos/`), `generate-favicons.py`, `generate-og-image.py`. |
| `frontend/public/` | Estáticos servidos tal cual: `sw.js` (service worker de Web Push, `:1-11`), `site.webmanifest`, `robots.txt`, `sitemap.xml`, favicons, `og-image.png`, `founder.jpg`, `brand/` (11 archivos de logo) y `brand-kit/` (`manual.html`, `tokens.css`, `tokens.json`, `fonts.md`, `logos/`), `logos/` (315 PNG de tickers). |

Nota: `frontend/node_modules` en esta copia es un **symlink** al `node_modules` del working tree del usuario. No es parte del repo (`.gitignore:28`).

---

### 1.6 Inventario de variables de entorno

#### Backend (todas se leen con `os.environ.get` / `os.getenv`)

| Variable | Dónde se lee | Para qué | ¿Default? | ¿Secreto? |
|---|---|---|---|---|
| `SECRET_KEY` | `backend/main.py:100` | Firma de los JWT | **Sí, pero condicionado**: en `RENDI_ENV=prod` sin ella el proceso **no arranca** (`:105-109`); en dev genera una efímera (`:112-114`) | 🔴 Sí |
| `RENDI_ENV` | `main.py:105,148,248,278,371,2938,16001`; `billing/rebill.py:105` | Interruptor prod/dev: exige SECRET_KEY, cookie `Secure`, HSTS, origins default, confianza en `X-Forwarded-For` | `"dev"` | No |
| `DB_PATH` | `main.py:118`; `scripts/backup_db.py:314`; `scripts/mkschema.py:38`; `scripts/base_sintetica.py:105`; `scripts/copiar_a_postgres.py:722`; `sim_import.py:15` | Ruta del archivo SQLite | `backend/trading.db` (en Railway se apunta a `/data/trading.db`) | No |
| `DATABASE_URL` | `main.py:423`; `scripts/copiar_a_postgres.py:562` | **El interruptor SQLite↔Postgres** (§1.7) | `""` → SQLite | 🔴 Sí (DSN con password) |
| `ADMIN_EMAIL_HASH` | `main.py:128` | Hash SHA-256 del email admin | **Sí**: un hash hardcodeado en `main.py:126` | Parcial (es un hash, pero el email en claro está en el comentario `:124`) |
| `ALLOW_REGISTRATION` | `main.py:121` | Cierra el registro público | `"true"` | No |
| `ALLOWED_ORIGINS` | `main.py:255` | Lista CORS | Sí, environment-aware (`main.py:247-250`) | No |
| `ANTHROPIC_API_KEY` | `ai/llm.py:114`; `main.py:20363` | Coach IA. Sin ella los endpoints devuelven 503 (`main.py:25916,26196,28288`) | No (warning y AI apagada) | 🔴 Sí |
| `RESEND_API_KEY` | `billing/emails.py:41` | Email transaccional | No (modo no-op) | 🔴 Sí |
| `EMAIL_FROM` | `billing/emails.py:47` | Remitente default | `Rendi <no_reply@rendi.finance>` | No |
| `EMAIL_FROM_NOREPLY` | `billing/emails.py:54` | Remitente de transaccionales | `Rendi <no_reply@rendi.finance>` | No |
| `EMAIL_FROM_SUPPORT` | `billing/emails.py:63` | Remitente con reply útil | `Rendi Soporte <soporte@rendi.finance>` | No |
| `ADMIN_NOTIFY_EMAIL` | `main.py:2920`; `billing/emails.py:951,1012` | Destino de avisos de admin | No | No |
| `ADMIN_SIGNUP_ALERT_LIMIT` | `main.py:2921` | Corta el aviso de signup tras N altas | `"100"` | No |
| `REBILL_API_KEY` | `billing/rebill.py:39,109,243` | Cobro. **Levanta `RuntimeError` si falta** (`:41`) | No | 🔴 Sí |
| `REBILL_WEBHOOK_SECRET` | `billing/rebill.py:46,257` | Firma HMAC del webhook | `""` | 🔴 Sí |
| `REBILL_WEBHOOK_TOKEN` | `billing/rebill.py:65,258` | Token en el query string del webhook | `""` | 🔴 Sí |
| `REBILL_PLAN_ID_{PLAN}_{PERIOD}` (4) | `billing/rebill.py:72,282` (nombre armado) | Los 4 plan IDs de Rebill. **`RuntimeError` si falta** (`:74`) | No | No |
| `MP_ACCESS_TOKEN` | `billing/mercadopago.py:43` | Mercado Pago (legacy) | No | 🔴 Sí |
| `MP_WEBHOOK_SECRET` | `billing/mercadopago.py:81` | Firma webhook MP (legacy) | No | 🔴 Sí |
| `MP_ENV` | `billing/mercadopago.py:119` | sandbox/prod de MP | No | No |
| `MP_TEST_PAYER_EMAIL` | `billing/mercadopago.py:120` | Email de prueba en sandbox | No | No |
| `MP_FRONTEND_BASE_URL` | `main.py:2935`; `billing/rebill.py:80`; `billing/mercadopago.py:63,71` | Base de las return URLs. **Nombre histórico**: la usa Rebill, no MP | `https://rendi.finance` en rebill; `http://localhost:5173` en mercadopago | No |
| `MP_BACK_URL_BASE` | `billing/mercadopago.py:60` | Override de la anterior | No | No |
| `RAILWAY_ENVIRONMENT` | `billing/rebill.py:107` | Detecta prod para no aceptar webhooks sin firma | No | No |
| `RAILWAY_GIT_COMMIT_SHA` | `main.py:34293` | Commit que corre, en `/api/health` | cae a `GIT_COMMIT_SHA`, después `"unknown"` | No |
| `GIT_COMMIT_SHA` | `main.py:34294` | Idem, fallback | `"unknown"` | No |
| `VAPID_PUBLIC_KEY` | `main.py:34056,34125` | Web Push | No | No (es pública) |
| `VAPID_PRIVATE_KEY` | `main.py:34126` | Web Push | No | 🔴 Sí |
| `VAPID_SUBJECT` | `main.py:34127` | `mailto:` del spec WebPush | No | No |
| `SNAPSHOT_CRON_TOKEN` | `main.py:33665,33947` | Autoriza el cron externo de snapshots | No | 🔴 Sí |
| `ALERTS_CRON_TOKEN` | `main.py:33597` | Autoriza el cron de alertas | No | 🔴 Sí |
| `ADVISOR_BRIEF_TOKEN` | `main.py:33946` | Autoriza el cron del brief del asesor | No | 🔴 Sí |
| `IOL_LAB_CRON_TOKEN` | `main.py:31564` | Autoriza `/api/iol/lab/run-cron` | No | 🔴 Sí |
| `IOL_LAB_EMAILS` | `main.py:31339` | Allowlist de `/lab/iol` (vacío = sólo admins) | `""` | No |
| `RENDI_MANTENIMIENTO` | `mantenimiento.py:90` | `"1"` cierra, `"0"` abre, ausente = depende de `DATABASE_URL` | Sí (§1.8) | No |
| `RENDI_MANTENIMIENTO_TOKEN` | `mantenimiento.py:109` | Bypass del mantenimiento por header `x-rendi-bypass` | No (sin ella no hay bypass) | 🔴 Sí |
| `RENDI_PASAJE_COMPLETO` | `mantenimiento.py:99` | Marca "el pasaje a Postgres terminó" | No | No |
| `RENDI_TRUSTED_PROXY_HOPS` | `main.py:15998,16000` | Cuántos hops de `X-Forwarded-For` confiar | Sí (visible en el endpoint de diagnóstico) | No |
| `RENDI_RESET_DATA_ENABLED` | `main.py:3789` | Reactiva el "empezar de cero", desactivado a propósito | No → apagado | No |
| `RENDI_FORCE_SNAPSHOT_MIGRATION` | `main.py:32286` | Fuerza una migración de snapshots al boot | No | No |
| `TRIALS_ENABLED` | `billing/trial.py:48` | Prende el trial de 15 días | No | No |
| `TRIALS_MONTHLY_CAP` | `billing/trial.py:57` | Tope mensual de trials | `"0"` | No |
| `REPORTS_TTL_DAYS` | `main.py:36000` | Caducidad de los reportes compartidos | `"180"` | No |
| `YF_TZ_CACHE_LOCATION` | `main.py:58` | Dónde deja yfinance su TzCache | `/tmp/yf-cache` | No |
| `BACKUP_LOCAL_DIR` | `scripts/backup_db.py:317`; `main.py:18502` | Carpeta de backups locales | `./backups` | No |
| `BACKUP_LOCAL_KEEP_DAYS` | `scripts/backup_db.py:61` (vía `_env_int`) | Retención local | `30` | No |
| `BACKUP_REMOTE_KEEP_DAYS` | `scripts/backup_db.py:61` (vía `_env_int`) | Retención remota | `90` | No |
| `BACKUP_S3_BUCKET` | `scripts/backup_db.py:143,176,192,209` | Bucket S3-compatible | No → sin backup remoto | No |
| `BACKUP_S3_ENDPOINT` | `scripts/backup_db.py:159` | Endpoint (B2/R2/MinIO) | No | No |
| `BACKUP_S3_ACCESS_KEY` | `scripts/backup_db.py:144` | Credencial | No | 🔴 Sí |
| `BACKUP_S3_SECRET_KEY` | `scripts/backup_db.py:145` | Credencial | No | 🔴 Sí |
| `BACKUP_S3_REGION` | `scripts/backup_db.py:162` | Región | `us-east-1` | No |
| `BACKUP_S3_PREFIX` | `scripts/backup_db.py:320` | Prefijo de keys | `rendi/` | No |
| `PG_DSN_COPIA` | `scripts/copiar_a_postgres.py:724`; `scripts/vigilar_espacio.py:93` | DSN destino del copiador (sólo herramientas) | No | 🔴 Sí |
| `IOL_SPIKE_BASE` | `scripts/iol_spike.py:35` | Base URL del spike de IOL | No | No |
| `PYTEST_CURRENT_TEST` | `billing/emails.py:82` | Detecta que está corriendo bajo pytest (para no mandar mails) | — | No |
| `PORT` | `nixpacks.toml:31` (shell, no Python) | Puerto que Railway asigna a uvicorn | Lo pone la plataforma | No |

**Notas [V]:**
- `backend/.env.example` documenta 24 variables y **omite** 25+ de las que el código sí lee: `RENDI_ENV`, `ALLOW_REGISTRATION`, todos los `RENDI_MANTENIMIENTO*` y `RENDI_PASAJE_COMPLETO`, `SNAPSHOT_CRON_TOKEN`, `ALERTS_CRON_TOKEN`, `ADVISOR_BRIEF_TOKEN`, `REBILL_WEBHOOK_TOKEN`, `ADMIN_NOTIFY_EMAIL`, `TRIALS_*`, `REPORTS_TTL_DAYS`, todos los `BACKUP_*`, `RENDI_TRUSTED_PROXY_HOPS`. Y sobre todo **`DATABASE_URL` sólo aparece en un comentario** (`.env.example:29-31` habla de `DB_PATH` pero nunca menciona `DATABASE_URL`) — la variable que hoy define si la app corre sobre SQLite o Postgres **no está documentada en el `.env.example`**.
- `backend/main.py:25-30` hace `load_dotenv(_env_path, override=True)` — con `override=True` a propósito (`:19-24` explica el caso real de una key vieja heredada del shell). Consecuencia: **un `backend/.env` presente le gana a lo que setee el entorno**, incluido Railway. En Railway no hay `.env` así que es no-op, pero es una trampa si alguien alguna vez lo commitea.

#### Frontend

| Variable | Dónde se lee | Para qué | ¿Default? | ¿Secreto? |
|---|---|---|---|---|
| `import.meta.env.DEV` | `frontend/src/utils/valuationGuards.js:18-19` | Activar guardas de valuación sólo en dev/tests | — | No |
| `VERCEL_GIT_COMMIT_SHA` / `COMMIT_REF` | `frontend/vite.config.js:14-16` (Node, en build-time) | Identidad del build → `__BUILD_ID__` + `version.json` | `String(Date.now())` | No |

**Y nada más [V].** El frontend **no lee ninguna variable `VITE_*` en runtime**. Grep de `VITE_` en `frontend/src` devuelve sólo comentarios: `frontend/src/utils/analytics.js:3,52` y `frontend/src/main.jsx:12` **hablan** de `VITE_GA_MEASUREMENT_ID` como si fuera configurable, pero el ID está **hardcodeado** en `frontend/src/utils/analytics.js:37` (`const GA_ID = 'G-DQ8LV6YJPP'`). Lo mismo con el pixel: `frontend/src/utils/metaPixel.js:22` tiene el ID literal, y `frontend/index.html:203-205` lo repite hardcodeado en el snippet inline. `frontend/src/utils/metaPixel.js:12` deja escrito el motivo: *"porque Vercel no inyectaba bien los env var `VITE_`"*. Son IDs públicos, así que no es una fuga; pero los comentarios describen un mecanismo de configuración que **no existe**.

---

### 1.7 Base de datos: SQLite o Postgres — la pregunta clave

#### Respuesta corta

**Producción corre HOY sobre SQLite.** La migración a Postgres está **completamente escrita, mergeada a `main` y dormida**: se activa entera con una sola variable de entorno, `DATABASE_URL`. No está "a medias" en el sentido de código incompleto — está a medias en el sentido de que **nunca se prendió**, y quedaron piezas que no cruzan el shim (ver los agujeros abajo).

#### El interruptor, línea por línea [V]

```
backend/main.py:423   DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
backend/main.py:424   USANDO_PG = bool(DATABASE_URL)
backend/main.py:427   def get_db():
backend/main.py:428       if USANDO_PG:
backend/main.py:429           import pgshim
backend/main.py:430           return pgshim.connect(DATABASE_URL)
backend/main.py:431       conn = sqlite3.connect(DB_PATH)
```

`backend/main.py:416-422` explica por qué es un interruptor y no una bifurcación: *"durante la migración hay que poder correr LA MISMA suite de tests contra los dos motores y comparar. Si el código se bifurca, se testean dos cosas distintas"*.

**`USANDO_PG` se usa en exactamente DOS lugares de la app [V]** (grep en todo `backend/` fuera de tests): `main.py:428` (`get_db`) y `main.py:699` (`init_db`). Todo lo demás pasa por `get_db()` sin enterarse.

#### Rama SQLite: los PRAGMAs [V] (`backend/main.py:431-476`)

`journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=15000`, `synchronous=NORMAL`, `cache_size=-64000` (64 MB), `temp_store=MEMORY`, `mmap_size=268435456` (256 MB). Y un bloque de comentario largo (`:451-476`) que documenta que `journal_size_limit` **se puso el 12/08 y se sacó el 13/08** porque volvieron los `database is locked` masivos: *"recortar el -wal exige lock EXCLUSIVO sobre el WAL, y lo pide después de CADA checkpoint"*. Está desactivado a propósito.

#### Rama Postgres: `init_db` [V] (`backend/main.py:690-706`)

Con `USANDO_PG`, `init_db()` **no replica las 46 migraciones incrementales de SQLite**: aplica de una `backend/schema_pg.sql` vía `pgsesion.conectar(DATABASE_URL, autocommit=True)`, sentencia por sentencia, tragándose `psycopg.errors.DuplicateObject` (`:692-696`). El razonamiento está en `:700-705`: *"Postgres arranca de cero y sólo necesita el RESULTADO… Traducir 46 migraciones sería 46 oportunidades de equivocarse para llegar al mismo lugar"*.

#### El shim, en detalle [V] — `backend/pgshim.py` (49 KB)

Es una **emulación de la API de `sqlite3` sobre `psycopg`**, no un ORM y no una reescritura. Tres partes:

**(a) La clase `Row` (`:87-121`).** Emula `sqlite3.Row`: se accede por nombre **y** por posición, porque *"el código usa las dos formas —`r["email"]` y `r[0]`— muchas veces en el mismo archivo"* (`:88-90`). Implementa `keys()`, `__contains__`, `__iter__`, `__len__`.

**(b) El traductor `traducir(sql)` (`:605-687`).** Función pura, sin estado. Lo que traduce, en orden:

| De SQLite | A Postgres | Dónde |
|---|---|---|
| `PRAGMA table_info(t)` | un SELECT al catálogo (reemplaza la sentencia entera) | `:610-613` |
| `FROM sqlite_master` | equivalente del catálogo | `:617` |
| `strftime('%Y'/%m/%Y-%m', col)` | `substr(col,1,4)` / `substr(col,6,2)` / `substr(col,1,7)` | `:665-668` |
| `datetime('now')` / `date('now')` | `to_char(now() at time zone 'utc', …)` — **devuelve TEXTO**, para no romper las comparaciones de string | `:672-673` |
| `IFNULL` | `COALESCE` | `:674` |
| `MIN(a,b)` / `MAX(a,b)` | `LEAST` / `GREATEST` | `:675` |
| `printf('%04d-%02d',…)` | `lpad(…) \|\| '-' \|\| lpad(…)` (sólo enteros con ceros; cualquier otro formato **levanta error**) | `:676` |
| `round(x, n)` | `round(x::numeric, n)::double precision` (el casteo de vuelta evita que un `Decimal` explote lejos con `Decimal + float`) | `:677` |
| `INSERT OR IGNORE` | `INSERT … ON CONFLICT DO NOTHING` | `:681-685` |
| `rowid` **dentro de un DELETE** | `ctid` | `:644-645` |
| `?` | `%s`, y `%` → `%%` (respetando lo que está adentro de literales de string) | `:687` → `_escapar_y_placeholders` |
| `True/False` en params | `1/0` (las columnas booleanas quedaron `smallint`) | `_normalizar_params` `:757` |

**Lo que NO traduce, y levanta `NotImplementedError` a propósito** (`pgshim.py:50-73` lo documenta y el código lo implementa):
- `INSERT OR REPLACE` (`:618-622`): no se puede adivinar la columna del conflicto, y en SQLite **borra y reinserta** (pierde columnas no nombradas y dispara los `ON DELETE CASCADE`). Se convirtieron a mano; el guardarraíl queda puesto para el que escriba uno nuevo.
- `rowid` **fuera** de un DELETE (`:650-655`): el `ctid` no es estable entre updates/VACUUM.
- Referencias **peladas** dentro de `ON CONFLICT … DO UPDATE SET` (`:652-666`): en Postgres son ambiguas (tabla vs `excluded`) y el error suele quedar tragado por un `try/except`, apareciendo como "la alerta no se mandó".

**(c) La `Connection` (`:847-1053`) y los tres cachés de catálogo.** Emula `execute/executemany/executescript/commit/rollback/close` y `with conn:` (`:1045-1053`: commit al salir bien, rollback si hubo excepción).

Lo más delicado es la emulación de `lastrowid`, que el código usa en 38 lugares:
- `Connection.execute` (`:987-1010`) detecta un INSERT sin `RETURNING`, pide la PK de la tabla y reescribe la query como `… RETURNING "pk"`.
- `_pk_de` (`:864-930`) lee la PK del catálogo. El comentario documenta **dos versiones anteriores que rompieron de maneras opuestas**: la 1ª leía por la conexión del llamador y terminaba con `rollback()`, llevándose puesta la transacción ajena *sin error*; la 2ª no cerraba nada y dejaba `idle in transaction` reteniendo locks. La 3ª (la actual) abre **una conexión propia**.
- `_cargar_pks` (`:932-975`) usa `SELECT DISTINCT ON (c.relname) … ORDER BY c.relname, (a.attidentity = ''), a.attnum` porque **11 de las 58 tablas tienen PK compuesta** y la versión original tomaba "la primera que llegara", sin `ORDER BY`, o sea no determinística. Si el catálogo devuelve **cero** tablas con PK, **levanta `RuntimeError` y no cachea** (`:963-975`) — porque cachear ese estado haría que cada INSERT devolviera `lastrowid=None` en silencio y las FKs quedaran en NULL.
- `_invalidar_por_ddl` (`:506-522`) limpia los **tres** cachés (`_COLS_CACHE`, `_PKS_CACHE`, `_SIN_PK`) ante cualquier `ALTER|CREATE|DROP TABLE|VIEW` (`_RE_DDL`, `:503`). El comentario dice que **acá estaba el bug**: sólo limpiaba `_COLS_CACHE`, y una tabla creada en caliente después del primer INSERT quedaba marcada "sin PK" para siempre. La ventana existe en producción porque `pricing/fci.py` crea dos tablas en caliente.

#### `backend/pgsesion.py` — la única puerta a Postgres [V]

Todas las conexiones pasan por `pgsesion.conectar()` (`:66-80`), que aplica `SET extra_float_digits = 3` (`:48-51`). El motivo está medido, no razonado (`:1-26`): los poolers de Supabase traen `extra_float_digits = 0`, que imprime los `double precision` con 15 dígitos significativos — **no alcanzan** para reconstruir el double. Sobre 350 filas de `operations.pnl_usd`: **0 de 350 con bits distintos, 73 de 350 con LECTURA distinta**. Y el punto que importa: el rebuild hace leer→modificar→escribir, así que un valor mal leído se **persiste** y a partir de ahí la verificación no ve nada. Hay un test estructural (`tests/test_conexiones_pg_ajustadas.py`, citado en `:69-72`) que barre el backend con AST y falla si aparece un `psycopg.connect` que no pase por acá.

#### `backend/dberrors.py` — los `except` que sirven en los dos motores [V]

21 lugares del código capturan `sqlite3.IntegrityError` / `sqlite3.OperationalError`, y con psycopg esas excepciones **nunca se levantan** (`:3-7`). La solución son tuplas (`ERR_INTEGRIDAD`, `ERR_OPERACIONAL`, `ERR_BASE`, `:34-44`), no un `if USANDO_PG`. Detalle no obvio y bien documentado (`:18-30`): la equivalencia **no es uno a uno** — "no such table/column" y los errores de sintaxis son `OperationalError` en SQLite y `ProgrammingError` en psycopg, por eso `ERR_OPERACIONAL` incluye los dos. Además hay helpers que preguntan por el **hecho** en vez del **texto** del error: `es_unique` (`:53-58`), `es_columna_duplicada` (`:61-71`), `es_base_trabada` (`:74-82`).

Y una limitación explícita: `EnsayoPorClonNoDisponible` + `exigir_clon_soportado` (`:99-119`). Tres herramientas de admin simulan **clonando la base entera** con `sqlite3.Connection.backup()`; en Postgres esa fotocopia no existe. La decisión tomada es **no migrarlas** y avisar claro en vez de fallar con un error críptico.

#### Los scripts del pasaje [V]

- **`backend/scripts/mkschema.py`** — genera `backend/schema_pg.sql` corriendo `init_db()` sobre un SQLite **vacío** (`:34-42`) y traduciendo el schema resultante. Traducciones: `INTEGER PRIMARY KEY AUTOINCREMENT` → `GENERATED BY DEFAULT AS IDENTITY` (no `ALWAYS`: con `ALWAYS` Postgres rechaza los INSERT con id explícito, que es justo lo que hace la copia, `:68-72`); `INTEGER` → `bigint`; `REAL` → `double precision`; `BOOLEAN 0/1` → **`smallint`, no `boolean`**, porque el código hace `WHERE is_cash=1` en decenas de lugares (`:20-22`); las fechas quedan **TEXT** (`:23-26`). Regla declarada: *"la migración NO es el momento de mejorar el modelo de datos"* (`:28`).
  - 🔴 **Lo interesante está en `:44-52`**: `init_db()` crea 58 tablas y producción tiene 60. Las dos que faltaban las crea `pricing/fci.py:ensure_tables()` **en caliente**. Generar el esquema preguntándole sólo a `init_db()` era *"preguntarle a la fuente equivocada"*, y sin eso el copiador dejaba afuera los precios de los FCI. El script ahora importa `pricing.fci` y llama `ensure_tables(conn)` a mano (`:53-55`).
  - ⚠️ **Discrepancia que no cierra [V]:** `backend/schema_pg.sql` tiene **63** `CREATE TABLE` y 66 índices (`grep -c`), no 58 ni 60. `backend/scripts/copiar_a_postgres.py:10` habla de "las 60 tablas"; `backend/scripts/mkschema.py:46` de "58 + 2 = 60"; `backend/pgshim.py:480,907,935` de "las 58 tablas del esquema". Tres números en tres archivos y un cuarto en el artefacto generado. **No verifiqué cuál es el correcto** — el `.sql` es lo que de verdad se aplica, así que es el que manda.
- **`backend/scripts/copiar_a_postgres.py`** (37 KB) — el copiador de una sola pasada, con 4 subcomandos: `aplicar-esquema`, `preflight` (sólo lee), `preparar-destino` (vacía), `copiar` (`:9-13`). Las decisiones que sostienen el diseño están escritas (`:26-46`): psycopg crudo y nunca el shim; **nunca `with destino.transaction()`** (si no es la transacción más externa se degrada a SAVEPOINT y al cerrar la conexión el servidor rollbackea todo — *"la herramienta habría reportado éxito… sobre una base vacía"*); la verificación final corre en **una conexión nueva abierta después del commit**; qué copiar sale del **origen** y no hay parámetro para pedir otra cosa; **el origen se abre sólo lectura** (`:45-46`: *"Es la base de la que dependen 1.084 personas"*).
- **`backend/scripts/verificar_copia.py`** (29 KB) — la vara. `copiar_a_postgres.py:5-6` dice que *"la única forma de aceptar esto es que sus cuatro niveles den CERO hallazgos"*.
- **`backend/scripts/pg_type_audit.py`**, **`base_sintetica.py`**, **`vigilar_espacio.py`** — herramientas de apoyo.

#### Los agujeros de la migración que encontré leyendo el código

🔴 **(1) El cron diario de snapshots NO pasa por el shim [V].** `backend/main.py:34260` llama `run_daily_snapshot(db_path=DB_PATH, …)` y `backend/snapshots_job.py:966` hace `conn = sqlite3.connect(db_path)` directo, con sus propios PRAGMAs (`:969-970`). El parámetro se llama `db_path` y el docstring dice *"path al SQLite file"* (`:922`). Con `DATABASE_URL` puesta, `get_db()` iría a Postgres pero **el snapshot diario seguiría escribiendo en el archivo SQLite** — la foto de cierre de cada día quedaría en la base vieja, en silencio. Lo mismo con `/api/admin/snapshots/run-now` (`main.py:32040,34260`) y el disparador del cron externo.

🔴 **(2) `/api/admin/disk-usage` es SQLite-only [V].** `backend/main.py:18538-18560` corre `PRAGMA page_size`, `PRAGMA page_count`, `PRAGMA freelist_count`, mide `DB_PATH + "-wal"`/`-shm` y consulta la vtab `dbstat`. Todo eso está dentro de un `try/except` amplio (`:18565-18566`) así que degrada a un `{"error": ...}`, pero el diagnóstico de disco —justo el que se usa cuando algo va mal— dejaría de servir.

🟡 **(3) Los clones de `Connection.backup()` [V].** `backend/main.py:16935,16940,17263,17269` e `backend/importing/recompute_backfill.py:89` abren `sqlite3.connect(tmp.name)` para el "ensayo por clon". Esto **sí** está reconocido y protegido: `dberrors.exigir_clon_soportado` (`:103-119`) corta antes con un mensaje claro. Es la parte honesta.

#### Cómo se elige el motor, en una frase

**Con `DATABASE_URL` seteada en Railway, la app entera habla Postgres a través de `pgshim`; sin ella, SQLite.** No hay flag en la base, ni archivo de config, ni feature flag por usuario: es una variable de entorno leída una vez al importar `main.py` (`:423`).

#### Evidencia de que HOY corre SQLite

- **[V]** `nixpacks.toml` no setea `DATABASE_URL`, y `requirements.txt:32-35` deja escrito que psycopg se agregó *"ANTES y POR SEPARADO del pasaje, y sin `DATABASE_URL`: así el deploy sale verde sin cambiar nada para el usuario"*.
- **[V]** El job de backup diario del scheduler (`main.py:32560-32565`) hace backup **de la SQLite** con `sqlite3.backup` (`scripts/backup_db.py:14-15`), y sigue registrado en producción.
- **[V]** `MIGRACION_POSTGRES.md:24-25` dice *"Rama `spike/postgres`. **NO se deploya** — es un spike. Producción va por `main` y está estable"*. (Ese documento es del 18/08; el código del spike **sí** está hoy en `main`, o sea que se mergeó después. Lo que no hay es evidencia de que se haya prendido la variable.)
- **[I]** Inferencia fuerte, agarrada de `mantenimiento.py:99`: si `DATABASE_URL` estuviera puesta en Railway **sin** `RENDI_PASAJE_COMPLETO`, la app estaría devolviendo 503 a todo el mundo. Como la app está viva, o bien `DATABASE_URL` está vacía (SQLite) o bien el pasaje ya se declaró completo. Dado el resto de la evidencia, lo primero.
- **⚠️ Lo que NO puedo verificar desde el código:** el valor real de las variables en el dashboard de Railway. Eso sólo se ve entrando ahí, o pegándole a `/api/admin/disk-usage` (si devuelve `db_internals` con `page_size` y `file_mb`, es SQLite).

#### Sobre la copia local `backend/trading.db`

**[V]** Tiene **39 tablas** (`sqlite3 … "SELECT count(*) FROM sqlite_master WHERE type='table'"`), contra las 58/60/63 que menciona el código. Le faltan, entre otras, todo lo del plan asesor, alertas de precio, reportes de período, plazos fijos y las tablas de trial/créditos que sí están en `schema_pg.sql`. **Confirma la advertencia del brief: esa base viene de una rama vieja y no sirve como evidencia del esquema actual.** La usé sólo para eso.

---

### 1.8 Las piezas de operación

#### `backend/mantenimiento.py` — cerrar la app sin apagarla

Middleware de FastAPI que devuelve **503** a todo el mundo mientras dura una ventana de mantenimiento. Tres decisiones, todas escritas y todas implementadas [V]:

1. **No toca la base, ni para leer un flag** (`:15-18`): *"un modo mantenimiento que consulta una tabla se cae junto con la base de la que te protege"*. Todo sale de `os.environ` (`:80-82`).
2. **El default es CERRADO** (`:85-99`): `RENDI_MANTENIMIENTO=1` cierra, `=0` abre, y **si nadie dijo nada**, `en_mantenimiento()` devuelve `bool(DATABASE_URL) and not RENDI_PASAJE_COMPLETO`. O sea: **arrancar contra Postgres implica mantenimiento**. El razonamiento (`:27-38`) es que las dos fallas no cuestan lo mismo: trabado en mantenimiento es visible y se sale en 30 s; abierto de más es silencioso y cruza el punto de no retorno solo.
3. **503 y no 500, y el bypass va por header** (`:40-56`). El cuerpo va bajo `detail` (`:126-131`) porque el frontend lee `payload.detail` en `buildHttpError`. El comentario `:45-53` deja registrado un **error propio corregido**: se había escrito que "el frontend ya sabe mostrar este mensaje lindo" mirando el código de reintentos, cuando el que arma el mensaje es `buildHttpError` — *"Miré la fuente equivocada"*. El bypass es por header `x-rendi-bypass` (`:77`) y no por query param porque *"un token en la URL queda en los logs del proxy, en el historial del navegador y en el `Referer`"*; se compara con `hmac.compare_digest` (`:112`). **Sin `RENDI_MANTENIMIENTO_TOKEN` no hay bypass posible** (`:110-111`) — a propósito.

`RUTAS_LIBRES = ("/api/health",)` (`:75`) es la única excepción, *"o Railway mata el contenedor"*. `instalar()` (`:134-149`) se registra **último** para quedar **primero** en la cadena (`:137-140`), y `backend/main.py:290-301` repite la advertencia para que nadie mueva la llamada.

Y lo que **no** garantiza, escrito por el autor (`:58-64`): no frena los crons externos, no frena los requests en vuelo, y **no frena los seis escritores del arranque** ("un problema aparte y abierto").

#### `backend/scripts/vigilar_espacio.py` — cuánto disco necesita la copia *mientras* corre

Se corre en otra terminal mientras corre el copiador (`:24-27`) y muestrea cada 2 s: `pg_database_size(current_database())`, `pg_current_wal_lsn()` convertido a bytes (`_lsn_a_bytes`, `:39-43`), y cuántos `COPY` hay activos (`:53-55`). Al final imprime el **pico de datos, el pico de WAL y el TOTAL** (`:84-86,102-106`).

Existe por un incidente concreto y medido (`:1-18`): el **2026-08-15**, copiando 1 GB a un Supabase Free, la instancia se cayó con el disco al 100%: `DATABASE 553 MB · WAL 660 MB · SYSTEM 759 MB`. *"El cuaderno de borrador pesaba MÁS que los datos"* — consecuencia directa de que el copiador va en **una sola transacción**, así que el WAL no se recicla hasta el commit. Detalle útil: **no hace falta el destino real** (`:20-22`), porque cuánto WAL genera la copia depende de la copia. Lee el DSN de `--destino` o de `PG_DSN_COPIA` (`:93`).

#### `backend/scripts/backup_db.py` — el backup diario

Doble destino [V] (`:1-41`):
1. **Local siempre**: copia + gzip a `BACKUP_LOCAL_DIR` (default `./backups/`) *en el mismo disco de Railway*. Protege contra bugs propios, **no** contra pérdida del disco.
2. **Remoto opcional**: si están las `BACKUP_S3_*`, sube a un storage S3-compatible (B2/R2/S3/MinIO) vía `boto3` (`:143-162`).

Usa la API `.backup` de SQLite, **no un file copy**, así que la copia es consistente aunque haya writes en curso (`:16-17`). Retención: 30 días local, 90 remoto, y **el primer backup de cada mes se preserva 1 año** (`:19-22`). Corre desde el scheduler a las **03:45 UTC** (`backend/main.py:32558-32565`), después del snapshot (02:59) y del lifecycle (03:30). El setup paso a paso está en `backend/scripts/BACKUP_SETUP.md`.

🔴 **El problema conocido, documentado en dos lugares [V]:** `MIGRACION_POSTGRES.md:2290-2292` dice que **el 75% del volumen de Railway son backups en el mismo disco que la base**, y que sin tocar la retención vuelve al 97% "entre el 8 y el 28 de septiembre" — o sea, **ahora**. Y `MIGRACION_POSTGRES.md:42-77` documenta el bloqueante: el backup que produce este script **no pasa el guardián del `-wal`** del copiador, porque `src.backup(dst)` deja el header en modo WAL sin archivo `-wal`, y el copiador lo rechaza como "copia a medias" aunque esté completa.

#### El scheduler [V] — `backend/main.py:32095, 32524-32580`

`BackgroundScheduler(timezone='UTC')` de APScheduler 3.10.4, arrancado en `@app.on_event("startup")`. Cinco jobs:

| Job | Cron (UTC) | Qué hace |
|---|---|---|
| `daily_snapshot` | 02:59 | Foto diaria de cada cartera. El horario es 23:59 ART a propósito (`:32525-32533`) |
| `iol_lab_refresh` | cada hora, minuto 7 | Renueva los refresh tokens del IOL Lab (`:32540-32547`; el comentario lo llama *"respaldo del cron externo"*) |
| `subscription_lifecycle` | 03:30 | Baja a Free lo vencido, limpia pendings |
| `backup_db` | 03:45 | Backup de la SQLite |
| `fci_refresh` | 12:10 | Precios de cuotaparte (CAFCI publica T+1) |

Más un `_fci_bootstrap_async()` en un thread daemon al boot (`:32506-32521`). En `shutdown` (`:32586+`) baja el buffer de últimos precios "porque Railway redeploya seguido".

⚠️ **[V] + [I]:** el scheduler es **in-process**. Con `restartPolicyType = "on_failure"` y un solo proceso uvicorn (`nixpacks.toml:31`, sin `--workers`), hoy no hay duplicación; pero existen además **tokens de cron externo** (`SNAPSHOT_CRON_TOKEN`, `ALERTS_CRON_TOKEN`, `ADVISOR_BRIEF_TOKEN`, `IOL_LAB_CRON_TOKEN`), lo que sugiere que los mismos jobs también se disparan desde afuera. **No verifiqué** si el scheduler in-process y el cron externo pueden correr el mismo job dos veces el mismo día.

#### `backend/pytest.ini` — el archivo que existe para que `pytest` no mande un mail

[V] `:29-31` define `testpaths = tests` y `norecursedirs = scripts …`. El comentario (`:1-27`) explica por qué **hacen falta las dos líneas y no una**: `testpaths` gobierna `pytest` sin argumentos, `norecursedirs` cubre `pytest .` / `pytest -k algo` donde `testpaths` se ignora.

🔴 El motivo concreto: en `backend/scripts/` hay tres archivos que se llaman `test_*.py` y **no son tests**. `scripts/test_emails.py` **manda 3 mails reales por Resend**, y su import hace `load_dotenv(override=True)`: *"con sólo COLECTARLO, las credenciales de producción pisan el entorno de toda la corrida"*. `scripts/test_bot_profile_boundaries.py` (91 KB) hace `sys.exit(1)` en su helper `fail()`. Son 47 pseudo-tests, y durante **siete rondas** se dio por hecho que "la suite muere al 23-28%" cuando *"Nunca fue la suite: era la colección"*. Con el fix, la suite corre entera en ~52 s.

#### El guard del sistema visual [V]

`frontend/src/__design__/design-contract.test.js` corre con `npm test` y **congela la deuda actual** contra `design-baseline.json`, fallando ante cualquier violación NUEVA (`:9-15`). El walker vive en `frontend/scripts/design-patterns.mjs` y **no** en `src/` a propósito: *"un módulo con los literales 'font-mono', 'rounded-md' y 'uppercase' adentro de `src/` se contaría A SÍ MISMO"* (`:9-14`). El generador (`gen-design-baseline.mjs:7-11`) advierte que correrlo para "arreglar" un test que dice "SUBIÓ" es desarmar el guard.

---

### 1.9 Cosas que anoto y no corrijo

Todo esto es material de estructura/infra que salió mientras leía. Lo dejo listado sin narrarlo como si estuviera bien.

1. 🔴 **`start-rendi.sh:43` commitea una `SECRET_KEY` real al repo.** Es la clave de firma de los JWT. Está pensada para dev, pero está en el repo. Si algún día alguien levanta con este script una instancia que sirva tráfico, cualquiera que lea el repo puede firmar tokens.
2. 🔴 **`backend/main.py:124` deja el email del admin en claro** en un comentario, dos líneas arriba del hash que existe justamente para no guardarlo en claro (`:123`). El hash está hardcodeado en `:126`.
3. 🔴 **`start.sh` está roto** por el `sys.exit(1)` de `backend/seed.py:10` (§1.3). Es el script que un recién llegado va a correr primero.
4. 🔴 **El cron de snapshots no cruza el shim** (`snapshots_job.py:966`). Si se prende `DATABASE_URL`, el snapshot diario escribe en el archivo viejo sin dar error (§1.7).
5. 🔴 **`backend/dberrors.py:14-16` afirma que psycopg no está en requirements**, y `requirements.txt:36` lo tiene pinneado. Comentario que miente sobre el estado del sistema.
6. 🟡 **Tres conteos distintos de tablas**: 58 (`backend/pgshim.py:480,907,935`), 60 (`backend/scripts/copiar_a_postgres.py:10`, `backend/scripts/mkschema.py:46`) y 63 (`grep -c '^CREATE TABLE' backend/schema_pg.sql`).
7. 🟡 **`DATABASE_URL` no está en `backend/.env.example`.** La variable que decide sobre qué motor corre la app no aparece en el archivo que documenta las variables.
8. 🟡 **`load_dotenv(..., override=True)`** (`main.py:29`): un `backend/.env` presente le gana al entorno del proceso. En Railway es no-op, pero es una trampa cargada.
9. 🟡 **Los `VITE_*` son ficción.** `frontend/src/utils/analytics.js:3,52` y `frontend/src/main.jsx:12` documentan una configuración por env var que no existe: los IDs están hardcodeados (`frontend/src/utils/analytics.js:37`, `frontend/src/utils/metaPixel.js:22`, `frontend/index.html:204,214`).
10. 🟡 **No hay CI.** Ni GitHub Actions, ni pre-commit, ni gate de tests. Con 241 archivos de test back y 55 front, nada los corre antes de un deploy.
11. 🟡 **Un solo proceso uvicorn sin `--workers`** (`nixpacks.toml:31`). Es coherente con SQLite (un solo escritor) y con el scheduler in-process, pero es el techo de concurrencia del backend entero.
12. 🟡 **El backup vive en el mismo disco que la base** y es el 75% del volumen (`MIGRACION_POSTGRES.md:2290-2292`), con la proyección de volver al 97% en septiembre.
13. 🟡 **`dev.sh` mata por puerto, no por PID** (`:16-19`): un `kill -9` a lo que sea que esté en 8000/5173.
14. 🟡 **`start-rendi.sh:7-8` hace `source ~/.zshrc`** dentro del script de arranque.
15. 🟡 **`frontend/src/utils/` con 94 archivos concentra cálculo financiero del lado del cliente** (bonos, benchmark, FX, composición). Es estructura, no bug — pero significa que el número que ve el usuario no siempre lo calcula el backend.
16. 🔴 **`CORRECTNESS_AUDIT_2026-06-25.md` no existe en el repo y el código lo cita 11 veces en 9 archivos**, incluido `.gitignore:14` y el comentario que justifica el `raise RuntimeError` de `SECRET_KEY` (`backend/main.py:104`). Ver §1.10.
17. 🟡 **`backend/scripts/` tiene tres archivos `test_*.py` que no son tests** [V, `backend/pytest.ini:1-27`], y uno (`scripts/test_emails.py`) manda mails reales y pisa el entorno con credenciales de producción con sólo ser colectado. Está contenido por `backend/pytest.ini:29-31`. **[I]** Pero la contención depende del *cwd*: el `pytest.ini` vive en `backend/`, así que por el algoritmo de rootdir de pytest (que busca el ini desde el ancestro común de los args hacia **arriba**, nunca hacia abajo) correr `pytest` parado en la raíz del repo no lo levantaría. No lo ejecuté para comprobarlo — el brief prohíbe correr la suite.

---

### 1.10 Los `.md` sueltos de la raíz

| Archivo | Qué es | ¿Documentación viva o resto de sesión? |
|---|---|---|
| `README.md` | **9 bytes.** Literalmente `# trading` | **Resto.** No documenta nada. Ni el stack, ni cómo levantar, ni qué es Rendi |
| `MIGRACION_POSTGRES.md` | 134 KB, 26 secciones. Estado + prompt de continuación de la migración a Postgres. Última sesión anotada: **2026-08-14 (sesión 8)**, con actualizaciones hasta el 18/08 | **Híbrido, y el documento más valioso del repo.** Es un cuaderno de sesiones (con su bloque "pegá esto en una sesión nueva", `:3`), pero contiene la única especificación del pasaje, el bloqueante abierto del `-wal` (`:42-77`), los números de la suite en los dos motores (`:199-260`) y el contexto de producción (`:2287-2301`). **Está desactualizado en un punto clave**: dice *"Rama `spike/postgres`. NO se deploya"* (`:24-25`) y el código del spike **hoy está en `main`** |
| `AUDIT_REPORT_2026-05-25.md` | 20 KB. Auditoría en 6 dimensiones (security back/front, SEO, mobile, performance, code quality) con ~190 hallazgos, hecha con 6 agentes en paralelo | **Resto de sesión.** Sus fixes sí están implementados (los headers de `frontend/vercel.json:9-56`, los PRAGMAs de `backend/main.py:434-450`, el gate de `RENDI_ENV` en `:278`), pero **ningún archivo del repo lo cita por nombre**: `grep -rn "AUDIT_REPORT_2026-05-25"` en `backend/`, `frontend/` y `.gitignore` da **cero**. Congelado en mayo |
| `ONBOARDING_REPORT_2026-05-26.md` | 13 KB. Bitácora de una noche: wizard de bienvenida + checklist en Home, 5 commits | **Resto.** Es el parte de una sesión, con los SHAs. Sirve de arqueología (ahí se documenta el hardcode del GA_ID), no de documentación |
| `PLAN_iol_sync.md` | 15 KB. Plan de sync automático read-only con IOL: las 3 "verdades" (ningún MCP sirve, no hay token de sólo lectura, no hay push), fases, riesgos | **Vivo y parcialmente implementado.** El código lo referencia: `backend/main.py:31339` (`IOL_LAB_EMAILS`), `:31564` (`IOL_LAB_CRON_TOKEN`), el job `iol_lab_refresh` (`main.py:32541-32547`), `frontend/src/App.jsx:53` (`IolLab` en `/lab/iol`), `backend/scripts/iol_spike.py` + `IOL_SPIKE_README.md` |

**Fuera de la raíz, dos más que sí son documentación viva [V]:** `frontend/CLAUDE.md` (13 KB — el contrato del sistema visual, con las 7 reglas; lo **verifica un test**, `design-contract.test.js:15-16`) y `backend/scripts/BACKUP_SETUP.md` (el paso a paso para prender el backup remoto en B2/R2).

🔴 **El `.md` que el código cita 11 veces y NO ESTÁ en el repo [V]: `CORRECTNESS_AUDIT_2026-06-25.md`.** `find . -name "CORRECTNESS_AUDIT*"` no devuelve nada, y sin embargo hay **11 referencias en 9 archivos**: `backend/main.py:104` (*"Ver CORRECTNESS_AUDIT_2026-06-25.md (M-SEC1)"*, justo arriba del `raise RuntimeError` que exige `SECRET_KEY` en prod), `:4944`, `:7079`, `backend/analysis_prep.py`, `backend/reporting/timeline.py`, `backend/ai/builders/dashboard_top_holdings.py`, `backend/ai/builders/insights_attribution.py`, `backend/ai/builders/profile_card.py`, `backend/tests/test_snapshots_job.py`, `frontend/src/utils/profileMatch.js`, y **`.gitignore:14`** (*"contienen datos reales de usuarios (emails + hashes bcrypt). NUNCA deben commitearse. Ver CORRECTNESS_AUDIT_2026-06-25.md (C4)"*). O sea: la justificación de por qué esas reglas existen — y los IDs `C3`, `C4`, `M-SEC1`, `M-OPS2`, `M-7` que aparecen dispersos en los comentarios — apunta a un documento que **no está**. Si alguien quiere entender por qué el código hace lo que hace en esos 11 puntos, no tiene dónde leerlo. Espejo del anterior: el informe que **sí** está en la raíz (`AUDIT_REPORT_2026-05-25.md`) no lo cita nadie, y el que **todos** citan no está.

**Lo que NO existe [V]:** no hay documento que explique la arquitectura, ni el modelo de datos, ni las convenciones de precios/monedas, ni cómo correr los tests, ni qué variables hay que setear para un deploy nuevo. El `README.md` de 9 bytes es todo lo que hay como puerta de entrada.
