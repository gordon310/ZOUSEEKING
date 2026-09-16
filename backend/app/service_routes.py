from uuid import UUID

from fastapi import APIRouter, Depends

from .auth import AuthUser, require_user
from . import service_tasks

router = APIRouter(prefix="/api/service", tags=["service-tasks"])


@router.get("/tasks")
async def list_creator_tasks(user: AuthUser = Depends(require_user)) -> dict:
    return await service_tasks.list_for_creator(user.user_id)


@router.post("/tasks/{task_id}/consent")
async def grant_creator_consent(task_id: UUID, user: AuthUser = Depends(require_user)) -> dict:
    return await service_tasks.grant_creator_consent(user.user_id, task_id)


@router.post("/tasks/{task_id}/confirm-completion")
async def confirm_completion(task_id: UUID, user: AuthUser = Depends(require_user)) -> dict:
    return await service_tasks.confirm_completion(user.user_id, task_id)
