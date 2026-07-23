#!/usr/bin/env bash
# Deploy the proxy to Google Cloud Run.
# Prerequisites: gcloud installed + logged in, billing enabled on the project,
# Atlas Network Access allows 0.0.0.0/0 (Cloud Run has no fixed home IP).
#
# Usage:
#   export MONGODB_URI='mongodb+srv://...'
#   ./deploy-cloudrun.sh [PROJECT_ID] [REGION]
set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
REGION="${2:-${CLOUD_RUN_REGION:-us-east1}}"
SERVICE="${CLOUD_RUN_SERVICE:-cashshaver-proxy}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Usage: ./deploy-cloudrun.sh PROJECT_ID [REGION]"
  echo "Or set GOOGLE_CLOUD_PROJECT."
  exit 1
fi

if [[ -z "${MONGODB_URI:-}" ]]; then
  if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
  fi
fi

if [[ -z "${MONGODB_URI:-}" ]]; then
  echo "Set MONGODB_URI (or put it in .env) before deploying."
  exit 1
fi

MONGODB_DB="${MONGODB_DB:-llm_cost_proxy}"
MONGODB_COLLECTION="${MONGODB_COLLECTION:-requests}"

# YAML env file avoids --set-env-vars splitting on special characters in the URI.
ENV_FILE="$(mktemp -t cashshaver-env.XXXXXX.yaml)"
trap 'rm -f "$ENV_FILE"' EXIT

PYTHON=".venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" MONGODB_COLLECTION="$MONGODB_COLLECTION" \
"$PYTHON" - <<'PY' >"$ENV_FILE"
import os
uri = os.environ["MONGODB_URI"]
db = os.environ.get("MONGODB_DB", "llm_cost_proxy")
coll = os.environ.get("MONGODB_COLLECTION", "requests")
try:
    import yaml
    print(yaml.safe_dump({
        "MONGODB_URI": uri,
        "MONGODB_DB": db,
        "MONGODB_COLLECTION": coll,
    }, default_flow_style=False))
except ImportError:
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    print(f"MONGODB_URI: {q(uri)}")
    print(f"MONGODB_DB: {q(db)}")
    print(f"MONGODB_COLLECTION: {q(coll)}")
PY

echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Service:  ${SERVICE}"
echo "Mongo DB: ${MONGODB_DB}.${MONGODB_COLLECTION}"

gcloud config set project "${PROJECT_ID}"

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "${PROJECT_ID}"

gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8000 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --cpu-boost \
  --min-instances 0 \
  --max-instances 3 \
  --env-vars-file "$ENV_FILE" \
  --project "${PROJECT_ID}"

URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --project "${PROJECT_ID}" --format='value(status.url)')"
echo
echo "Deployed: ${URL}"
echo "Point Claude Code at it (append your username):"
echo "  export ANTHROPIC_BASE_URL=${URL}/alice"
echo
echo "If Mongo logging fails, open Atlas → Network Access and allow 0.0.0.0/0."
