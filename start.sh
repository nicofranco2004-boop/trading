#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Backend setup
echo "📦 Instalando dependencias del backend..."
pip3 install -r "$ROOT/backend/requirements.txt" -q

# Seed DB if empty
python3 -c "
import sqlite3, os
db = '$ROOT/backend/trading.db'
if not os.path.exists(db):
    import sys; sys.path.insert(0, '$ROOT/backend')
    import seed; seed.seed()
else:
    conn = sqlite3.connect(db)
    count = conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
    conn.close()
    if count == 0:
        import sys; sys.path.insert(0, '$ROOT/backend')
        import seed; seed.seed()
    else:
        print('✅ Base de datos ya inicializada')
"

# Frontend setup
echo "📦 Instalando dependencias del frontend..."
cd "$ROOT/frontend" && npm install -s

echo ""
echo "🚀 Iniciando servidores..."
echo "   Backend:  http://localhost:8000"
echo "   Frontend: http://localhost:5173"
echo ""

# Start backend
cd "$ROOT/backend" && uvicorn main:app --port 8000 --reload &
BACKEND_PID=$!

# Start frontend
cd "$ROOT/frontend" && npm run dev &
FRONTEND_PID=$!

# Open browser after a short wait
sleep 3 && open http://localhost:5173 &

wait $BACKEND_PID $FRONTEND_PID
