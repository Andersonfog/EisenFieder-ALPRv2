"""Camera registration and management (owner console) + config pull (edge)."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Camera, User
from ..schemas import (
    CameraCreate, CameraOut, CameraRegistered, CameraSettings, CameraSettingsUpdate,
)
from ..security import get_current_user, require_camera_auth

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


def _env_snippet(serial: str, token: str) -> str:
    return (
        f"EISENFIEDER_CAMERA__ID={serial}\n"
        f"BACKEND_URL=http://YOUR-BACKEND-HOST:8000\n"
        f"BACKEND_API_TOKEN={token}\n"
    )


@router.post("", response_model=CameraRegistered, status_code=status.HTTP_201_CREATED)
def register_camera(
    body: CameraCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CameraRegistered:
    serial = body.serial_number.strip()
    if db.get(Camera, serial) is not None:
        raise HTTPException(status_code=409, detail="A camera with that serial already exists")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    camera = Camera(
        id=serial,
        name=(body.name or serial).strip(),
        location=(body.location or "").strip(),
        api_token=token_hash,   # store hash; raw token shown once only
        status="registered",
    )
    db.add(camera)
    db.commit()
    return CameraRegistered(
        id=serial, name=camera.name, api_token=token, env_snippet=_env_snippet(serial, token)
    )


@router.get("", response_model=list[CameraOut])
def list_cameras(
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Camera]:
    cameras = db.query(Camera).order_by(Camera.created_at.desc()).all()
    for c in cameras:
        c.has_token = bool(c.api_token)  # type: ignore[attr-defined]
    return cameras


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(
    camera_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.has_token = bool(camera.api_token)  # type: ignore[attr-defined]
    return camera


@router.put("/{camera_id}/settings", response_model=CameraOut)
def update_settings(
    camera_id: str,
    body: CameraSettingsUpdate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Camera:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.settings = body.model_dump()
    db.commit()
    db.refresh(camera)
    camera.has_token = bool(camera.api_token)  # type: ignore[attr-defined]
    return camera


@router.post("/{camera_id}/regenerate-token", response_model=CameraRegistered)
def regenerate_token(
    camera_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CameraRegistered:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    token = secrets.token_urlsafe(32)
    camera.api_token = hashlib.sha256(token.encode()).hexdigest()
    db.commit()
    return CameraRegistered(
        id=camera.id, name=camera.name, api_token=token,
        env_snippet=_env_snippet(camera.id, token),
    )


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: str,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(camera)
    db.commit()


@router.get("/{camera_id}/config", response_model=CameraSettings)
def get_camera_config(
    camera_id: str = Depends(require_camera_auth),
    db: Session = Depends(get_db),
) -> CameraSettings:
    """The edge unit pulls its own settings here (camera-authenticated)."""
    camera = db.get(Camera, camera_id)
    if camera is None or not camera.settings:
        return CameraSettings()
    return CameraSettings(**camera.settings)
