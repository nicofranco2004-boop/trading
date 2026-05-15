#!/usr/bin/env bash
# Rendi — levanta backend (uvicorn :8000) + frontend (vite :5173) en background.
# Uso:
#   ./dev.sh        # arranca ambos
#   ./dev.sh stop   # mata ambos
#   ./dev.sh logs   # tail de logs de ambos
#   ./dev.sh status # muestra si están corriendo
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_LOG=/tmp/rendi-backend.log
FRONTEND_LOG=/tmp/rendi-frontend.log

action="${1:-start}"

free_port() {
  local port="$1"
  lsof -i ":$port" -t 2>/dev/null | xargs -r kill -9 2>/dev/null || true
}

port_status() {
  local port="$1"
  if lsof -i ":$port" -t >/dev/null 2>&1; then
    echo "✅ :$port (PID $(lsof -i ":$port" -t | head -1))"
  else
    echo "❌ :$port"
  fi
}

case "$action" in
  start)
    echo "🚀 Iniciando Rendi…"
    free_port 8000
    free_port 5173
    sleep 1

    echo "→ Backend (uvicorn)…"
    cd "$REPO_DIR/backend"
    nohup python3 -m uvicorn main:app --reload --port 8000 > "$BACKEND_LOG" 2>&1 &
    disown

    echo "→ Frontend (vite)…"
    cd "$REPO_DIR/frontend"
    nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
    disown

    sleep 4
    echo ""
    echo "Backend:  $(port_status 8000)"
    echo "Frontend: $(port_status 5173)"
    echo ""
    echo "📋 Logs:  ./dev.sh logs"
    echo "🛑 Stop:  ./dev.sh stop"
    ;;

  stop)
    echo "🛑 Deteniendo Rendi…"
    free_port 8000
    free_port 5173
    sleep 1
    echo "Backend:  $(port_status 8000)"
    echo "Frontend: $(port_status 5173)"
    ;;

  status)
    echo "Backend:  $(port_status 8000)"
    echo "Frontend: $(port_status 5173)"
    ;;

  logs)
    echo "📋 Tailing logs (Ctrl+C para salir)…"
    tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
    ;;

  *)
    echo "Uso: $0 {start|stop|status|logs}"
    exit 1
    ;;
esac
