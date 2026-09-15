from fastapi import APIRouter

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("/status")
def customers_status():
    return {
        "status": "ok",
        "service": "customers",
    }
