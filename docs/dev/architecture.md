# Architecture

## The ten tools in the design, and where they live

| Design tool | Code | Model? |
|---|---|---|
| `load_requirements` | `aegis.engine.Engine.requirements` (reltable rows that survive the reader's DITAVAL; `packs/model-card-sections.yaml` for the public pack) | no |
| `read_evidence_map` | `aegis.corpus.Corpus` (topics, prolog, keys, reltable with file and line) and `aegis.approvals.Approvals` (Git and pull-request record) | no |
| `check_coverage` | `aegis.checks.check_coverage` | no |
| `check_currency` | `aegis.checks.check_currency` | no |
| `check_approval` | `aegis.checks.check_approval` | no |
| `check_consistency` | `aegis.checks.check_consistency` | no |
| `propose_mapping` | `aegis.model.propose_mapping` | **yes**, Gemini structured output |
| `build_pack` | `scripts/build_packs.sh` (DITA-OT 4.4 per reader, in CI) and `aegis.engine.Engine.build_zip` (manifest, report, CSV, hashes) | no |
| `open_review` | `.github/workflows/evidence-request.yml` (report on the request issue) | no |
| `seal_pack` | `.github/workflows/evidence-request.yml` release job (Cloud Storage with retention, register row) | no |

## One service

`api/main.py` serves the API under `/api` and the site (`site/`) at `/`. The generate page, the sandbox and Ask are
same-origin with the API. See [ADR 0004](../adr/0004-serve-the-site-from-the-api.md) and [the MVP flow](mvp-flow.md).

## Data flow

1. CI builds the approval index (`scripts/approval_index.py`): for every file in `corpus/gemma`, the last commit, the
   merged pull request, its author and its approving reviews. It also reads `CODEOWNERS` from the corpus.
2. CI builds the three packs' documentation with DITA-OT (`scripts/build_packs.sh`) and bakes both into the image.
3. At request time, `Engine.run(reader, overlay)` evaluates the reader's DITAVAL in Python (`aegis.ditaval`, the same
   rule DITA-OT applies), applies the visitor's sandbox overlay and runs the four checks.
4. The API (`api/main.py`) stores overlays in Firestore (`aegis_sandbox`, TTL on `expires_at`), counts model calls in
   `aegis_quota`, and reads released packs from `aegis_register`.

## The sandbox overlay

```json
{"links": [{"requirement": "aia.xi-2d", "topic": "gemma4-training-data", "status": "pending|approved|rejected", "proposal": {}}],
 "decisions": {"coverage:aia.xi-2e": {"choice": "release-with-gap|hold", "reason": "...", "by": "...", "date": "..."}},
 "leak": {"topic": "gemma4-training-data", "key": "gemma-4-train-compute"},
 "model_update": "2026-08-15",
 "gap_notes": {"aia.xi-1c": {}}}
```

Only `approved` links count. A finding id names what it is about (`coverage:<req>`, `currency:<topic>`,
`approval:<topic>`, `conflict:<topic>`, `literal:<topic>:<key>`, `leak:<topic>:<key>`), so a decision stays attached
when the checks run again.

## Ask

`aegis.ask.Asker` indexes requirement and evidence topics (keys resolved, trace facts added to requirement topics) in
SQLite FTS5 and ranks with BM25. A requirement named in the question ("Annex XII 1(e)") is pinned first. Gemini writes
1–4 points; a point survives only if its quote is in the cited topic word for word and every number in it is too.
