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
APP_USER="${TVTIMES_USER:-tvtimes}"
JWT_FILE="$DATA_DIR/jwt_ed25519.pem"
ENC_FILE="$DATA_DIR/encryption.key"

# The app runs unprivileged, but /data is almost always an operator-supplied
# bind mount or a volume created before this image went rootless, so it lands
# owned by root. Take ownership while we're still root, then drop to APP_USER
# and re-exec. Without this the secret bootstrap below dies with a bare
# PermissionError that `restart:` hides in a crash loop.
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R "$APP_USER" "$DATA_DIR"
    exec gosu "$APP_USER" "$0" "$@"
fi

mkdir -p "$DATA_DIR"

if [ ! -w "$DATA_DIR" ]; then
    echo "tvtimes: $DATA_DIR is not writable by $(id -un) (uid $(id -u))." >&2
    echo "tvtimes: fix its ownership on the host (chown to this uid), or drop the" >&2
    echo "tvtimes: 'user:' override so the entrypoint can take ownership itself." >&2
    exit 1
fi

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
        # No --proxy-headers: tvtimes resolves the client IP itself and only
        # trusts X-Forwarded-For from TVTIMES_TRUSTED_PROXIES. Letting uvicorn
        # rewrite request.client from XFF sent by anyone (which
        # --forwarded-allow-ips '*' did) let a direct client spoof its address.
        exec uvicorn app.main:app --host 0.0.0.0 --port "${TVTIMES_PORT:-8000}"
        ;;
    worker)
        exec arq app.worker.WorkerSettings
        ;;
    *)
        exec "$@"
        ;;
esac
