#!/bin/bash
# ─── Rendi — iniciar backend + frontend ───────────────────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Cargar variables de entorno del shell del usuario (incluye ANTHROPIC_API_KEY)
# shellcheck disable=SC1090
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null || true
[ -f "$HOME/.bashrc" ] && source "$HOME/.bashrc" 2>/dev/null || true

# ── Colores ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${GREEN}  rendi — iniciando...${RESET}"
echo "──────────────────────────────────────"

# ── Verificar Python ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo -e "${RED}✗ python3 no encontrado. Instalá Python 3.${RESET}"
  exit 1
fi

# ── Verificar Node ─────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo -e "${RED}✗ node no encontrado. Instalá Node.js.${RESET}"
  exit 1
fi

# ── Instalar dependencias si faltan ───────────────────────────────────────────
echo -e "${CYAN}▸ Verificando dependencias del backend...${RESET}"
pip3 install -r "$ROOT/backend/requirements.txt" -q --disable-pip-version-check 2>&1 | grep -v "already satisfied" || true

echo -e "${CYAN}▸ Verificando dependencias del frontend...${RESET}"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  cd "$ROOT/frontend" && npm install -s
fi

# ── SECRET_KEY fija (para que los tokens sobrevivan reinicios del backend) ────
export SECRET_KEY=c24828dc66d55a3f1e35980cacc611d7f9e9e27cbf300c22786e992f282ac1da

# ── Verificar API key ─────────────────────────────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo -e "${YELLOW}⚠  ANTHROPIC_API_KEY no está definida. El Coach IA no va a funcionar.${RESET}"
  echo -e "   Agregala a ~/.zshrc con: export ANTHROPIC_API_KEY=sk-ant-..."
else
  echo -e "${GREEN}✓  ANTHROPIC_API_KEY cargada.${RESET}"
fi

echo ""
echo -e "  ${CYAN}Backend: ${RESET}http://localhost:8000"
echo -e "  ${CYAN}Frontend:${RESET} http://localhost:5173"
echo ""
echo -e "  Presioná ${YELLOW}Ctrl+C${RESET} para detener todo."
echo "──────────────────────────────────────"
echo ""

# ── Función de limpieza al salir ──────────────────────────────────────────────
cleanup() {
  echo ""
  echo -e "${YELLOW}⏹  Deteniendo servidores...${RESET}"
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo -e "${GREEN}✓  Todo detenido.${RESET}"
  exit 0
}
trap cleanup INT TERM

# ── Iniciar backend ────────────────────────────────────────────────────────────
cd "$ROOT/backend"
python3 -m uvicorn main:app --port 8000 --reload 2>&1 | \
  sed "s/^/  ${CYAN}[backend]${RESET} /" &
BACKEND_PID=$!

# ── Iniciar frontend ───────────────────────────────────────────────────────────
cd "$ROOT/frontend"
npm run dev 2>&1 | \
  sed "s/^/  ${GREEN}[frontend]${RESET} /" &
FRONTEND_PID=$!

# Abrir el browser después de 2 segundos
(sleep 2 && open http://localhost:5173 2>/dev/null || true) &

# Esperar a que ambos procesos terminen
wait $BACKEND_PID $FRONTEND_PID
