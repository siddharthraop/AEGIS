# The MVP flow

The generate page (`site/index.html`, `site/mvp.js`) is the front door. A visitor picks a system and gets the authority
pack and one downstream pack, with the design's metrics measured on that run. Nothing is stored: the flow is stateless,
so it needs no Firestore and no model key.

## Endpoints

| Route | Does |
|---|---|
| `GET /api/systems` | The systems the page offers. A system with no requirement map is listed with `available: false`. |
| `GET /api/mvp?system=gemma-4` | Runs `authority` and `downstream` with an empty overlay, builds both zips, and returns results, pack details and metrics. |
| `GET /api/mvp/pack?system=gemma-4&reader=authority\|downstream` | Returns that pack's zip. `409` when a leak blocks release, `400` for another reader, `404` for an unknown system. |

The code is `aegis/mvp.py` and the three routes in `api/main.py`. Both routes call the same `Engine.run` and
`Engine.build_zip` as the sandbox, so the checks, manifest and report are identical.

## Deterministic pack ids

`mvp_pack_id` is `<system>-<reader>-<corpus commit>`, for example `gemma4-downstream-a29b3d7`. The manifest holds no
timestamp, so the manifest hash is the same for the same corpus commit. The page shows the hash from `/api/mvp`. The
download from `/api/mvp/pack` carries it in `X-Aegis-Manifest-Sha256`, and the page compares the two. Zip bytes differ
between builds (zip timestamps) but the file hashes inside do not.

## The metrics

`mvp.metrics` returns seven rows. Each has `kind`: `measured`, `modeled` or `not-in-mvp`.

| id | Computed from | Target |
|---|---|---|
| `covered` | Requirements with evidence, where every evidence topic has an approval and no `check_currency` finding. Both packs together. | 100%, or a recorded decision per gap |
| `approvers` | Evidence items with `approval_ok` and a named approver. | 100% |
| `keys` | `check_consistency` passed over total, both packs. | 100% |
| `leak` | `mvp.leak_measurement`: a scan of the built downstream HTML. | 0 |
| `time` | Wall-clock seconds for both runs and both zip builds. | Under 1 working day |
| `hours` | Not computed. The design's modeled figure. | Under 4 |
| `sealed` | Fixed at 0 of 2. The page never seals. | 100% |

`status` is `pass`, `open`, `fail` or `info`. The page never shows a pass for a number it could not measure.

### The leak scan

`mvp.scan` searches `build/packs/<reader>/html` for authority-only content: the pattern `aia-xi-<digit>`, the text
`Annex XI` not followed by another `I`, the title of each topic whose audience is `authority`, and the value of each
authority-only key. It checks file paths as well as text.

`mvp.leak_measurement` also scans the authority pack with the same patterns. That is a positive control. If the control
finds nothing, the downstream result is reported as not measured, because a zero would only mean the scan can't see the
content. If no DITA-OT output exists, the metric is `not measured`.

The scan covers HTML only. It does not read the PDF.

## What the numbers depend on

- **Approvals** come from `data/approvals.json`, built by `scripts/approval_index.py` at deploy time. Until a change to
  each evidence topic merges through a pull request approved by a code owner, `covered` and `approvers` read 0. The page
  explains this with a note when the approval check passes 0 of a non-zero total.
- **Built output** comes from `build/packs`, built by `scripts/build_packs.sh` and copied into the image. Without it,
  the zip holds the manifest and report only and the leak metric can't run.

## Adding a system

Today the engine is built for one system: `engine.MODEL` is `gemma-4`, the readers' DITAVAL files live under
`corpus/gemma`, and `scripts/build_packs.sh` builds `gemma.ditamap`. To add a system, give it an evidence set and a
requirement map in dita-corpus, generalise those three places to take the system id, and set `available: true` in
`mvp.SYSTEMS`. The page and endpoints already take the id.
