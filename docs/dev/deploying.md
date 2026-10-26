# Deploying

Same pattern as KnowledgeFlow and AlignR: GitHub Actions to Google Cloud through Workload Identity Federation, no keys
in the repository.

| Workflow | Does |
|---|---|
| `tests` | pytest on every push |
| `deploy-api` | approval index → DITA-OT packs → image → container smoke test → push → Cloud Run `aegis-api` (0–1 instance) → live check |
| `pages` | design document at `/`, sandbox at `/try/`, Ask at `/ask/`, DITA help and PDF at `/help/`, these docs at `/dev/` |
| `evidence-request` | issue opened → checks and report on the issue; `/release` by a code owner → seal in Cloud Storage and register |
| `live-check` | after a deploy: page, CORS, the three readers and the Ask samples |
| `refresh-approvals` | daily and on demand: rebuild the approval index and redeploy when it changed |

Cloud Run runs with `--min-instances=0 --max-instances=1`, request-based billing, the shared runtime service account
and the `gemini-api-key` secret. The evidence bucket uses a 1-day retention policy, not locked: a locked policy can't
be removed or shortened.
