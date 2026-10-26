#!/usr/bin/env bash
# build_pack, documentation part: DITA-OT 4.4 builds the Gemma evidence map once per reader with that reader's
# DITAVAL profile, as HTML5 and PDF, into build/packs/<reader>/. The API puts these files in every pack it builds.
# Needs DITA_HOME. Strict mode: a broken key, link or unknown audience value fails the build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/packs}"
MAP="$ROOT/corpus/gemma/gemma.ditamap"
declare -A PROFILE=(
  [authority]="$ROOT/corpus/gemma/filters/authority.ditaval"
  [downstream]="$ROOT/corpus/gemma/filters/downstream.ditaval"
  [public]="$ROOT/packs/public.ditaval"
)
for reader in authority downstream public; do
  dest="$OUT/$reader"
  rm -rf "$dest" && mkdir -p "$dest"
  echo "== $reader: $(basename "${PROFILE[$reader]}")"
  "$DITA_HOME/bin/dita" -i "$MAP" --filter="${PROFILE[$reader]}" -f html5 -o "$dest/html" --processing-mode=strict
  "$DITA_HOME/bin/dita" -i "$MAP" --filter="${PROFILE[$reader]}" -f pdf -o "$dest" --processing-mode=strict
  mv "$dest/gemma.pdf" "$dest/gemma4-$reader-pack.pdf"
  ls -la "$dest" | tail -n +2
done
