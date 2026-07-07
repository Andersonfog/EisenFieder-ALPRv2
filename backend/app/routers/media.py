"""Owner-only access to captured stills.

This is the core privacy guarantee: every image is served through here, behind
the owner's JWT. There is no public media folder, so footage cannot be read by
anyone without the business owner's login.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..models import User
from ..security import get_current_user
from ..storage import storage_singleton

router = APIRouter(prefix="/api/v1", tags=["media"])


@router.get("/media/{key:path}")
def get_media(key: str, _user: User = Depends(get_current_user)) -> FileResponse:
    path = storage_singleton().path_for(key)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    # A still never changes once written (keys are unique per event), so let the
    # owner's OWN browser cache it briefly — scrolling back through the vehicle
    # log doesn't refetch every image. "private" forbids shared/proxy caches.
    return FileResponse(
        str(path),
        headers={"Cache-Control": "private, max-age=3600, immutable"},
    )
