from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Path
from beanie import PydanticObjectId

from app.api.v1.deps.auth import get_current_user
from app.models.alert import Alert

router = APIRouter(prefix="/student/alerts", tags=["student-alerts"])

@router.get("/", response_model=List[Alert])
async def get_my_alerts(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all alerts for the currently logged-in student.
    Sorted by newest first.
    """
    student_id = current_user.get("user_id")
    if not student_id:
        raise HTTPException(status_code=400, detail="User ID not found")
        
    # Fetch alerts for this student, sorted by creation time descending
    alerts = await Alert.find(
        Alert.student_id == student_id
    ).sort("-created_at").to_list()
    
    return alerts

@router.delete("/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: PydanticObjectId,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Delete a specific alert.
    Verifies that the alert belongs to the requesting student.
    """
    student_id = current_user.get("user_id")
    
    # 1. Find the alert
    alert = await Alert.get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # 2. Verify ownership (Security)
    if alert.student_id != student_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this alert")
        
    # 3. Delete
    await alert.delete()
    return None
