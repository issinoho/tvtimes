#!/bin/sh
# tvtimes container entrypoint.
#
#   entrypoint web       -> run DB migrations, then the API + web app (default)
#   entrypoint worker    -> run the arq background worker
#   entrypoint <cmd...>  -> exec it verbatim (e.g. `alembic`, `sh`)
#
# On first boot it generates the two required secrets into the /data volume and
# never touches them again, so sessions and encrypted credentials survive a
# restart or image upgrade without any manual key management.
set -eu

DATA_DIR="${TVTIMES_DATA_DIR:-/data}"
JWT_FILE="$DATA_DIR/jwt_ed25519.pem"
ENC_FILE="$DATA_DIR/encryption.key"

mkdir -p "$DATA_DIR"

if [ ! -f "$JWT_FILE" ]; then
    echo "tvtimes: generating signing key -> $JWT_FILE (first run)"
    python - "$JWT_FILE" <<'PY'
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

pem = Ed25519PrivateKey.generate().private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
open(sys.argv[1], "wb").write(pem)
PY
fi

if [ ! -f "$ENC_FILE" ]; then
    echo "tvtimes: generating encryption key -> $ENC_FILE (first run)"
    python - "$ENC_FILE" <<'PY'
import base64, os, sys
open(sys.argv[1], "w").write(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
fi

# Only export if the operator hasn't supplied their own (env wins).
: "${TVTIMES_JWT_PRIVATE_KEY_PEM:=$(cat "$JWT_FILE")}"
: "${TVTIMES_ENCRYPTION_KEY:=$(cat "$ENC_FILE")}"
export TVTIMES_JWT_PRIVATE_KEY_PEM TVTIMES_ENCRYPTION_KEY

case "${1:-web}" in
    web)
        echo "tvtimes: applying database migrations"
        alembic upgrade head
        exec uvicorn app.main:app --host 0.0.0.0 --port "${TVTIMES_PORT:-8000}" \
            --proxy-headers --forwarded-allow-ips '*'
        ;;
    worker)
        exec arq app.worker.WorkerSettings
        ;;
    *)
        exec "$@"
        ;;
esac
