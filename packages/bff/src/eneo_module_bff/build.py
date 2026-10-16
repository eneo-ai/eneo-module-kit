from __future__ import annotations

import os
import re
from datetime import datetime

# The tags the template's release workflow takes (template/.github/workflows/release.yml): only such a tag is a release.
RELEASE_TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
# The repository becomes a link on the page: an https address, with nothing that could leave an attribute.
_SOURCE = re.compile(r"https://[^\s\"'<>?#]+")
_BUILD_DATE = "%Y-%m-%dT%H:%M:%SZ"


def _is_build_date(value: str) -> bool:
    # strptime reads "1" as a month; the time is written back and compared, so only the one spelling passes.
    try:
        return datetime.strptime(value, _BUILD_DATE).strftime(_BUILD_DATE) == value
    except ValueError:
        return False


def read_build() -> dict[str, str | None]:
    """Which build runs, as /health answers it. Each value is None when it is not known, and nothing stands in for it.

    The image says what it was built from: SOURCE_REVISION (the commit), BUILD_DATE (UTC) and SOURCE_URL (the
    repository), which the template's Dockerfile sets from CI's build arguments; a development build has none. The
    deployment says the release: MODULE_VERSION, the tag of the image it runs, because a release gives a tested image
    its version without building it again. Only a version tag (vX.Y.Z) is a release: ``latest`` and a commit's tag say
    which image was pulled, not which release it is.
    """
    revision = os.environ.get("SOURCE_REVISION", "")
    build_date = os.environ.get("BUILD_DATE", "")
    release = os.environ.get("MODULE_VERSION", "")
    source = os.environ.get("SOURCE_URL", "")
    return {
        "revision": revision if _COMMIT.fullmatch(revision) else None,
        "build_date": build_date if _is_build_date(build_date) else None,
        "release": release if RELEASE_TAG.fullmatch(release) else None,
        "source": source if _SOURCE.fullmatch(source) else None,
    }
