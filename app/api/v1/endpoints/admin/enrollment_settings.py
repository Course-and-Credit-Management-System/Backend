from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.deps.auth import require_admin
from app.core.time_utils import normalize_to_app_timezone, now_in_app_timezone
from app.models.enrollment_setting import EnrollmentSetting
from app.schemas.enrollment_setting import (
    EnrollmentSettingCreate,
    EnrollmentSettingResponse,
    EnrollmentSettingStatusPatch,
    EnrollmentSettingUpdate,
)

router = APIRouter(prefix="/admin/enrollment-settings", tags=["admin-enrollment-settings"])


def _to_response(doc: EnrollmentSetting) -> EnrollmentSettingResponse:
    payload = doc.model_dump(by_alias=True)
    payload["_id"] = str(doc.id)
    payload["enrollment_open_at"] = normalize_to_app_timezone(payload.get("enrollment_open_at"))
    payload["enrollment_close_at"] = normalize_to_app_timezone(payload.get("enrollment_close_at"))
    payload["created_at"] = normalize_to_app_timezone(payload.get("created_at"))
    payload["updated_at"] = normalize_to_app_timezone(payload.get("updated_at"))
    return EnrollmentSettingResponse(**payload)


async def _get_single_setting() -> EnrollmentSetting | None:
    docs = await EnrollmentSetting.find_all().sort("-updated_at").limit(1).to_list()
    return docs[0] if docs else None


@router.post("", response_model=EnrollmentSettingResponse, status_code=201)
async def create_enrollment_setting(
    payload: EnrollmentSettingCreate,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    # Singleton behavior: POST replaces existing setting.
    await EnrollmentSetting.find_all().delete()

    now = now_in_app_timezone()
    create_data = payload.model_dump(exclude_none=True)
    window_minutes = create_data.pop("window_minutes", None)
    window_days = create_data.pop("window_days", None)
    create_data["enrollment_open_at"] = now
    if window_minutes is not None:
        create_data["enrollment_close_at"] = now + timedelta(minutes=int(window_minutes))
    elif window_days is not None:
        create_data["enrollment_close_at"] = now + timedelta(days=int(window_days))
    else:
        raise HTTPException(status_code=400, detail="Provide one: window_minutes or window_days")
    doc = EnrollmentSetting(
        **create_data,
        created_at=now,
        updated_at=now,
        updated_by=str(current_user.get("user_id") or ""),
    )
    await doc.insert()
    return _to_response(doc)


@router.get("", response_model=EnrollmentSettingResponse)
async def get_enrollment_setting(
    current_user: Dict[str, Any] = Depends(require_admin),
):
    doc = await _get_single_setting()
    if not doc:
        raise HTTPException(status_code=404, detail="Enrollment setting not found.")
    return _to_response(doc)


@router.put("", response_model=EnrollmentSettingResponse)
async def upsert_enrollment_setting(
    payload: EnrollmentSettingUpdate,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    doc = await _get_single_setting()

    update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
    window_minutes = update_data.pop("window_minutes", None)
    window_days = update_data.pop("window_days", None)
    now = now_in_app_timezone()
    update_data["enrollment_open_at"] = now
    if window_minutes is not None:
        update_data["enrollment_close_at"] = now + timedelta(minutes=int(window_minutes))
    elif window_days is not None:
        update_data["enrollment_close_at"] = now + timedelta(days=int(window_days))
    else:
        raise HTTPException(status_code=400, detail="Provide one: window_minutes or window_days")
    update_data["updated_at"] = now
    update_data["updated_by"] = str(current_user.get("user_id") or "")

    if not doc:
        create_data = dict(update_data)
        create_data["created_at"] = now
        doc = EnrollmentSetting(**create_data)
        await doc.insert()
        return _to_response(doc)

    await doc.update({"$set": update_data})
    for key, value in update_data.items():
        setattr(doc, key, value)
    return _to_response(doc)


@router.patch("/status", response_model=EnrollmentSettingResponse)
async def patch_enrollment_setting_status(
    payload: EnrollmentSettingStatusPatch,
    current_user: Dict[str, Any] = Depends(require_admin),
):
    doc = await _get_single_setting()
    if not doc:
        raise HTTPException(status_code=404, detail="Enrollment setting not found.")

    set_active = payload.status == "open"
    update_data = {
        "is_active": set_active,
        "updated_at": now_in_app_timezone(),
        "updated_by": str(current_user.get("user_id") or ""),
    }
    await doc.update({"$set": update_data})
    doc.is_active = set_active
    doc.updated_at = update_data["updated_at"]
    doc.updated_by = update_data["updated_by"]
    return _to_response(doc)
