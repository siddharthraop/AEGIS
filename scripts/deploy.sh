#!/usr/bin/env bash
# One-command deploy to Cloud Run, from Cloud Shell or any machine with gcloud, git, Java 17+ and Python 3.11+.
# It builds the DITA-OT packs and the approval index, then deploys one public service that serves the page and the API.
#   PROJECT=my-project ./scripts/deploy.sh
# Optional: GEMINI_API_KEY=... turns on the sandbox's "propose a link" and Ask (the MVP page doesn't need it).
#           GITHUB_TOKEN=...   raises the GitHub rate limit for the approval index.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-aegis-api}"
[ -n "$PROJECT" ] || { echo "Set PROJECT=<gcp project id>"; exit 1; }

echo "== corpus submodule (full history, for the approval index)"
git submodule update --init corpus
git -C corpus fetch -q origin main && git -C corpus checkout -q FETCH_HEAD
COMMIT="$(git -C corpus rev-parse --short=12 HEAD)"

echo "== DITA-OT 4.4"
if [ -z "${DITA_HOME:-}" ]; then
  DITA_HOME="$HOME/dita-ot-4.4"
  [ -d "$DITA_HOME" ] || { curl -sSL -o /tmp/dita.zip https://github.com/dita-ot/dita-ot/releases/download/4.4/dita-ot-4.4.zip && unzip -q /tmp/dita.zip -d "$HOME"; }
fi
export DITA_HOME
./scripts/build_packs.sh

echo "== approval index"
pip install -q lxml pyyaml
python scripts/approval_index.py

echo "== deploy $SERVICE to $PROJECT ($REGION)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT"
ENVS="AEGIS_CORPUS_COMMIT=$COMMIT"
SECRETS=()
if [ -n "${GEMINI_API_KEY:-}" ]; then
  gcloud services enable secretmanager.googleapis.com firestore.googleapis.com --project "$PROJECT"
  gcloud secrets describe gemini-api-key --project "$PROJECT" >/dev/null 2>&1 || gcloud secrets create gemini-api-key --project "$PROJECT" --replication-policy=automatic
  printf %s "$GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --project "$PROJECT" --data-file=-
  NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  gcloud secrets add-iam-policy-binding gemini-api-key --project "$PROJECT" \
    --member="serviceAccount:$NUM-compute@developer.gserviceaccount.com" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  SECRETS=(--set-secrets="GOOGLE_API_KEY=gemini-api-key:latest")
  ENVS="$ENVS,AEGIS_MODEL=gemini-3.8-flash"
fi
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source . \
  --allow-unauthenticated --min-instances=0 --max-instances=1 --cpu=1 --memory=512Mi --port=8080 \
  --set-env-vars="$ENVS" "${SECRETS[@]}" --quiet
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo; echo "Live: $URL"; curl -s "$URL/api/health" | head -c 300; echo
