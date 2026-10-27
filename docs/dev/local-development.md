# Local development

Prerequisites: Python 3.11 or later, Java 17 or later for DITA-OT, and bash 4 or later (on macOS, `brew install bash`).
Use a virtual environment.

```bash
git clone --recurse-submodules https://github.com/siddharthraop/AEGIS && cd AEGIS
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[api,test]'
python scripts/approval_index.py                 # needs network; set GITHUB_TOKEN to avoid rate limits
DITA_HOME=~/dita-ot-4.4 scripts/build_packs.sh   # documentation for the pack zips and the leak scan
python -m pytest -q
uvicorn api.main:app --port 8080                 # the page and the API: http://localhost:8080/
```

The API serves the site, so one process gives you the generate page at `/`, the sandbox at `/try/` and Ask at `/ask/`,
all same-origin.

Without `data/approvals.json` the approval metrics read 0 and the page says so. For a run with approvals, set
`AEGIS_APPROVALS=tests/fixtures/approvals.json`. Without `build/packs` the zips hold the manifest and report only, and the
leak metric reads `not measured`. Without `GOOGLE_API_KEY`, `propose_mapping` is off (the API answers 503) and Ask answers
extractively. Without `AEGIS_FIRESTORE=1`, sandboxes, quota and the register live in memory.

| Variable | Default | Meaning |
|---|---|---|
| `AEGIS_CORPUS` | `corpus` | dita-corpus checkout |
| `AEGIS_APPROVALS` | `data/approvals.json` | approval index |
| `AEGIS_BUILDS` | `build/packs` | DITA-OT output per reader |
| `AEGIS_SITE` | `site` | folder the service serves at `/` |
| `AEGIS_MODEL` | `gemini-3.8-flash` | model id |
| `AEGIS_PROPOSALS_PER_DAY` | `20` | public proposal cap |
| `AEGIS_ASKS_PER_DAY` | `150` | model answers per day on Ask; then extractive |
