# Deploying

The MVP deploys with one script, run from your own machine or Cloud Shell. It builds what the image needs, then has Cloud
Build make the container and deploy one public Cloud Run service that serves the page and the API.

```bash
PROJECT=my-gcp-project ./scripts/deploy.sh
```

## Prerequisites

| Need | Why |
|---|---|
| A Google Cloud project with billing | Cloud Run, Cloud Build and Artifact Registry are enabled by the script |
| `gcloud`, logged in (`gcloud auth login`) | deploys the service |
| `git`, Java 17 or later, Python 3.11 or later | submodule, DITA-OT, the approval index |
| bash 4 or later | `scripts/build_packs.sh` uses associative arrays; macOS ships bash 3.2 |
| `GITHUB_TOKEN` (optional) | raises the GitHub rate limit for the approval index |
| `GEMINI_API_KEY` (optional) | enables the sandbox's "propose a link" and Ask. The generate page doesn't need it. |

On macOS with Homebrew:

```bash
brew install git python@3.12 openjdk@21 bash gh
brew install --cask google-cloud-sdk
export PATH="$(brew --prefix)/bin:$PATH"
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"; export PATH="$JAVA_HOME/bin:$PATH"
git clone --recurse-submodules -b main https://github.com/siddharthraop/AEGIS.git && cd AEGIS
python3.12 -m venv .venv && source .venv/bin/activate
export GITHUB_TOKEN="$(gh auth token)"
```

Activate the virtual environment first: Homebrew's Python refuses a global `pip install`, and the script installs two
packages.

## What the script does

1. Updates the `corpus` submodule to dita-corpus `main` and records its commit.
2. Downloads DITA-OT 4.4 if `DITA_HOME` isn't set, then builds the three packs in strict mode (`scripts/build_packs.sh`).
3. Builds the approval index (`scripts/approval_index.py`) into `data/approvals.json`.
4. Enables the Google APIs it needs.
5. If `GEMINI_API_KEY` is set, stores it in Secret Manager as `gemini-api-key` and grants the runtime account access.
6. Runs `gcloud run deploy --source .`: Cloud Build uses the `Dockerfile`, which bakes in the packs, the approval index,
   the Gemma evidence set and the site. The service runs with 0 to 1 instances, 1 CPU, 512 MiB, and allows unauthenticated
   calls.
7. Prints the live URL and the health response.

`.gcloudignore` keeps `build/` and `data/` in the upload even though git ignores them.

## Updating

Run the script again. Do this after every merge in dita-corpus that changes an approval, because the approval index is read
at deploy time and baked into the image (see [ADR 0003](../adr/0003-approval-index-at-build-time.md)).
`/api/health` shows `approvals.approved_files` and the corpus commit the service is running.

## Cost and teardown

Request-based billing with no minimum instance, so an idle service costs close to nothing. The first request after a quiet
period takes about 15 seconds. To remove it:

```bash
gcloud run services delete aegis-api --project my-gcp-project --region us-central1
gcloud secrets delete gemini-api-key --project my-gcp-project
```

## GitHub Actions

The workflows under `.github/workflows` are from the first build and need Workload Identity Federation variables
(`GCP_PROJECT`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_RUNTIME_SA`) that the MVP doesn't use.

| Workflow | State |
|---|---|
| `tests` | Runs on every push. |
| `pages` | Publishes the design document, help, these docs and the Pages copies of the sandbox and Ask. |
| `deploy-api` | Manual only. Needs the variables above. |
| `refresh-approvals` | Manual only. Compares the live approval count with Git, and redeploys through `deploy-api`. |
| `live-check` | Runs after `pages` or `deploy-api`. |
| `evidence-request` | Issue opened → checks and report; `/release` by a code owner → seal in Cloud Storage. Needs a bucket and the variables above. |

The Pages copies of `/try/` and `/ask/` call the service named in `site/assets/config.js`. Keep that URL current when you
deploy to a new project.
