#!/usr/bin/env bash
# Build the GitHub Pages site into OUT (default _site). Used by .github/workflows/pages.yml and locally.
#   /       the design document         /try/   the evidence sandbox      /ask/   Ask the corpus
#   /help/  DITA help (HTML5, strict), csh.json and the PDF user guide       /dev/   developer docs (MyST, Sphinx)
# Needs DITA_HOME and the [docs] extra.
set -euo pipefail
OUT="${1:-_site}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
rm -rf "$OUT" && mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
cp index.html "$OUT/index.html"
cp -r site/try site/ask site/assets "$OUT/"
echo "Help: DITA-OT HTML5 and PDF, strict"
"$DITA_HOME/bin/dita" -i help/aegis-help.ditamap -f html5 -o "$OUT/help" --processing-mode=strict
"$DITA_HOME/bin/dita" -i help/aegis-user-guide.bookmap -f pdf -o "$OUT/help" --processing-mode=strict
python help/tools/build_csh.py "$OUT/help"
echo "Developer docs: Sphinx, warnings are errors"
python -m sphinx -q -W -b html docs "$OUT/dev"
touch "$OUT/.nojekyll"
echo "Built $OUT"
