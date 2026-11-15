#!/usr/bin/env bash
# No reset, stash automático, limpieza ni force: conservar trabajo local.
set -euo pipefail
cd "$(dirname "$0")/.."
git fetch origin main
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Hay cambios locales: conservados; integrar manualmente antes de sincronizar main." >&2
  exit 1
fi
branch=$(git symbolic-ref --quiet --short HEAD) || {
  echo "HEAD separado: conservado; revisar antes de cambiar a main." >&2
  exit 1
}
if [[ "$branch" != main ]]; then
  git merge-base --is-ancestor HEAD origin/main || {
    echo "La rama actual tiene commits fuera de origin/main: conservados; revisar integración." >&2
    exit 1
  }
  if git show-ref --verify --quiet refs/heads/main; then
    git merge-base --is-ancestor main origin/main || {
      echo "main tiene commits locales o divergencia: conservados; revisar integración." >&2
      exit 1
    }
    git switch main
  else
    git switch --create main --track origin/main
  fi
fi
git merge-base --is-ancestor HEAD origin/main || {
  echo "main tiene commits locales o divergencia: conservados; revisar integración." >&2
  exit 1
}
git merge --ff-only origin/main
