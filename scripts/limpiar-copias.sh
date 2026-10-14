#!/bin/bash
# Limpia las copias del código (worktrees) que ya no hacen falta.
#
# Por qué existe: cada sesión saca su propia copia para no pisarse con las otras,
# y nadie la borraba al publicar. El 09/10/2026 había 74 copias en cuatro lugares
# distintos y la carpeta principal se había quedado un mes atrás.
#
# Una copia se borra SÓLO si se cumplen las tres:
#   1. ningún programa la está usando (una sesión de Claude, un servidor de prueba);
#   2. todo su trabajo ya está publicado en origin/main;
#   3. no tiene archivos modificados ni archivos nuevos sin guardar.
# Si falta alguna, la copia se saltea y se dice por qué.
#
# Lo que el control de versiones ignora a propósito (bases de prueba, capturas)
# no se pierde: se mueve a ~/Documents/rendi-archivo/copias/<nombre>/ antes de borrar.
# Se descarta sólo lo que se regenera solo (node_modules, dist, cachés) y los .env,
# que son copias de las claves de la carpeta principal.
#
# Uso:
#   scripts/limpiar-copias.sh            → muestra qué haría, no toca nada
#   scripts/limpiar-copias.sh --borrar   → lo hace

set -u
BORRAR=0; [ "${1:-}" = "--borrar" ] && BORRAR=1
ARCHIVO="${RENDI_ARCHIVO:-$HOME/Documents/rendi-archivo/copias}"
REGENERABLE='(^|/)(node_modules|__pycache__|\.pytest_cache|\.vite|dist)(/|$)|\.pyc$|\.DS_Store$|\.egg-info|\.coverage'
CLAVES='(^|/)\.env'

cd "$(git rev-parse --path-format=absolute --git-common-dir)/.." || exit 1
PRINCIPAL="$PWD"
git fetch origin --quiet || { echo "No pude traer origin/main: freno."; exit 1; }

borradas=0; salteadas=0
while IFS= read -r w; do
  [ "$w" = "$PRINCIPAL" ] && continue
  [ -d "$w" ] || continue
  n=$(basename "$w")

  # 1. ¿la usa alguien? Una terminal abierta sin nada corriendo no cuenta.
  uso=$(lsof -d cwd 2>/dev/null | awk -v p="$w" '$NF==p || index($NF, p"/")==1 {print $1}' \
        | grep -v -x -E 'zsh|bash|sh' | sort -u | tr '\n' ' ')
  if [ -n "$uso" ]; then echo "SALTEO $n — en uso por: $uso"; salteadas=$((salteadas+1)); continue; fi

  # 2. ¿tiene commits que no están en lo publicado?
  h=$(git -C "$w" rev-parse HEAD)
  sin_publicar=$(git cherry origin/main "$h" | grep -c '^+')
  if [ "$sin_publicar" != 0 ]; then echo "SALTEO $n — $sin_publicar commit(s) sin publicar"; salteadas=$((salteadas+1)); continue; fi

  # 3. ¿tiene cambios sin guardar? (el symlink de node_modules aparece como nuevo: no cuenta)
  sueltos=$(git -C "$w" status --porcelain -uall | grep -v -E "$REGENERABLE" | wc -l | tr -d ' ')
  if [ "$sueltos" != 0 ]; then echo "SALTEO $n — $sueltos archivo(s) sin guardar"; salteadas=$((salteadas+1)); continue; fi

  # Lo ignorado que vale la pena (bases de prueba, capturas) va al archivo.
  guardar=$(git -C "$w" status --porcelain --ignored -uall | grep '^!!' | cut -c4- \
            | grep -v -E "$REGENERABLE" | grep -v -E "$CLAVES")
  cant=$(printf '%s' "$guardar" | grep -c . )
  if [ $BORRAR = 0 ]; then echo "BORRARÍA $n (archivaría $cant archivo(s) locales)"; continue; fi

  if [ "$cant" != 0 ]; then
    mkdir -p "$ARCHIVO/$n"
    printf '%s\n' "$guardar" | while IFS= read -r f; do
      mkdir -p "$ARCHIVO/$n/$(dirname "$f")" && mv "$w/$f" "$ARCHIVO/$n/$f"
    done
  fi
  if git worktree remove --force --force "$w" && [ ! -e "$w" ]; then
    echo "BORRADA $n (archivados: $cant)"; borradas=$((borradas+1))
  else
    echo "NO PUDE BORRAR $n"
  fi
done < <(git worktree list --porcelain | awk '/^worktree /{print substr($0,10)}')

[ $BORRAR = 1 ] && git worktree prune
echo "---"; [ $BORRAR = 1 ] && echo "borradas: $borradas  salteadas: $salteadas" \
                        || echo "salteadas: $salteadas — para borrar las demás: scripts/limpiar-copias.sh --borrar"
