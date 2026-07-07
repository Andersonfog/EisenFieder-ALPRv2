"""Captured-still storage.

Stills are written under MEDIA_DIR and referenced by an opaque *key* (never an
absolute path). They are served only through the authenticated /api/v1/media
endpoint — there is no public folder — so footage can't be read without the
owner's login.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.media_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _contained_target(self, key: str) -> Path | None:
        """Resolve ``key`` under the media root, or None if it escapes the root.

        This is the single choke point that keeps a caller-supplied key (which
        includes the ingest-supplied event_uuid) from escaping MEDIA_DIR via
        ``..`` or an absolute path. Used on BOTH write and read.
        """
        root = self.root.resolve()
        target = (root / key).resolve()
        if root != target and root not in target.parents:
            return None
        return target

    def save(self, key: str, data: bytes) -> str:
        """Persist bytes under ``key`` (relative path) and return the key.

        Refuses path-traversal escapes: a key like ``cam/../../../x.jpg`` that
        resolves outside MEDIA_DIR raises instead of writing an arbitrary file.
        """
        target = self._contained_target(key)
        if target is None:
            raise ValueError("Unsafe storage key (path traversal)")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def path_for(self, key: str) -> Path | None:
        """Resolve a key to a real file path, refusing path-traversal escapes."""
        target = self._contained_target(key)
        if target is None:
            return None
        return target if target.is_file() else None


_storage: LocalStorage | None = None


def storage_singleton() -> LocalStorage:
    """Process-wide storage instance used by the routers."""
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings())
    return _storage
