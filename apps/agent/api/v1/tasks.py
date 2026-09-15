from fastapi import APIRouter

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/status")
def tasks_status():
    return {
        "status": "ok",
        "service": "tasks",
    }
