#!/usr/bin/env bash
# Build a clean zip of this project for handover.
#
# Only committed files ship: the zip comes from a fresh `git clone --no-local`,
# so .env.local, .neon, .venv, node_modules, exports and uncommitted work stay
# behind. .git is kept so the owner can pull updates.
#
# Usage: scripts/package_for_client.sh [--out DIR] [--origin URL] [--allow-dirty]
set -euo pipefail

repo="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"
name="nightlife-license-monitor"
out_dir=""
origin=""
allow_dirty=0

while [ $# -gt 0 ]; do
  case "$1" in
    --out) out_dir="$2"; shift 2 ;;
    --origin) origin="$2"; shift 2 ;;
    --allow-dirty) allow_dirty=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v zip >/dev/null || { echo "zip is not installed" >&2; exit 1; }

if [ -z "$out_dir" ]; then
  if [ -d "$HOME/Desktop" ]; then out_dir="$HOME/Desktop"; else out_dir="$HOME"; fi
fi
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"
case "$out_dir/" in
  "$repo"/*) echo "refusing to write the zip inside the repo" >&2; exit 1 ;;
esac

if [ -n "$(git -C "$repo" status --porcelain)" ]; then
  if [ "$allow_dirty" -ne 1 ]; then
    echo "working tree has uncommitted changes; commit them or pass --allow-dirty" >&2
    echo "(only committed files are ever packaged)" >&2
    exit 1
  fi
  echo "warning: uncommitted changes are NOT included" >&2
fi

if [ -z "$origin" ]; then
  origin="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
fi

work=""
trap 'if [ -n "$work" ]; then rm -rf "$work"; fi' EXIT
work="$(mktemp -d "${TMPDIR:-/tmp}/licmon-pkg.XXXXXX")"
git clone --quiet --no-local "$repo" "$work/$name"
cd "$work/$name"
if [ -n "$origin" ]; then
  git remote set-url origin "$origin"
else
  git remote remove origin
fi

# Safety checks on what would ship.
bad=0
while IFS= read -r f; do
  case "$f" in
    .env|.env.*|*/.env|*/.env.*|.neon|.neon/*) echo "BLOCKED: $f" >&2; bad=1 ;;
    tests/fixtures/*) ;;
    *.csv|*.xlsx|*.xls|*.sqlite|*.db|*.eml) echo "BLOCKED (data file): $f" >&2; bad=1 ;;
  esac
done < <(git ls-files)
# A real connection string has a password; only the local test DB is allowed.
if git grep -nIE 'postgres(ql)?://[^:/@[:space:]]+:[^@[:space:]]+@' -- . \
    | grep -vE 'postgres:test@(127\.0\.0\.1|localhost)[:/]' >&2; then
  echo "BLOCKED: possible connection string with a password (see above)" >&2
  bad=1
fi
[ "$bad" -eq 0 ] || { echo "package aborted" >&2; exit 1; }

stamp="$(date +%F)"
zip_path="$out_dir/$name-$stamp.zip"
rm -f "$zip_path"
(cd "$work" && zip -qr "$zip_path" "$name")

files="$(git ls-files | wc -l | tr -d ' ')"
size="$(du -h "$zip_path" | cut -f1)"
echo "packaged $files tracked files ($(git rev-parse --short HEAD)) -> $zip_path ($size)"
echo "origin in zip: ${origin:-none}"
