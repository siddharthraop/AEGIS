# Local development

```bash
git clone --recurse-submodules https://github.com/siddharthraop/AEGIS && cd AEGIS
pip install -e '.[api,test]'
python scripts/approval_index.py            # needs network; set GITHUB_TOKEN to avoid rate limits
DITA_HOME=~/dita-ot-4.4 scripts/build_packs.sh   # optional: documentation for the pack zip
uvicorn api.main:app --port 8080
cd site && python -m http.server 8000      # open http://localhost:8000/try/?api=http://localhost:8080
```

Without `GOOGLE_API_KEY`, `propose_mapping` is off (the API answers 503) and Ask answers extractively. Without
`AEGIS_FIRESTORE=1`, sandboxes, quota and the register live in memory.

| Variable | Default | Meaning |
|---|---|---|
| `AEGIS_CORPUS` | `corpus` | dita-corpus checkout |
| `AEGIS_APPROVALS` | `data/approvals.json` | approval index |
| `AEGIS_BUILDS` | `build/packs` | DITA-OT output per reader |
| `AEGIS_MODEL` | `gemini-3.8-flash` | model id |
| `AEGIS_PROPOSALS_PER_DAY` | `20` | public proposal cap |
| `AEGIS_ASKS_PER_DAY` | `150` | model answers per day on Ask; then extractive |
