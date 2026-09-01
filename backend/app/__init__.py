"""tvtimes API package."""

import os

# Set at image-build time from the release tag (Dockerfile ARG -> ENV, wired by
# .github/workflows/release.yml). "dev" for a source / local run.
__version__ = os.environ.get("TVTIMES_VERSION") or "dev"
