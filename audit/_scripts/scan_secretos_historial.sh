#!/bin/bash
# Escanea TODOS los blobs del historial de git buscando patrones de secreto.
# NUNCA imprime el valor: sólo el patrón y el blob. Después se resuelve el blob
# a commit+archivo con: git rev-list --all --objects | grep <sha>
# Uso: bash audit/_scripts/scan_secretos_historial.sh [repo]
set -u
cd "${1:-$(pwd)}" || exit 1
PAT='sk-ant-api|sk-ant-|sk_live_|sk_test_|rk_live_|AKIA[0-9A-Z]{16}|APP_USR-|xoxb-|ghp_|github_pat_|BEGIN [A-Z ]*PRIVATE KEY|re_[A-Za-z0-9]{24}|AIza[0-9A-Za-z_-]{30}'
git cat-file --batch-all-objects --batch --buffer 2>/dev/null \
 | awk -v pat="$PAT" '
     /^[0-9a-f]{40} blob [0-9]+$/ { sha=$1; next }
     { if (match($0, pat)) { m=substr($0, RSTART, RLENGTH); if (!(sha m in seen)) { seen[sha m]=1; print sha "|" m } } }
   '
