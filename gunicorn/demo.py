import os
import time
from pathlib import Path
from fastapi import FastAPI, APIRouter, Request, Response
app = FastAPI()

router = APIRouter()


@app.get("/")
async def root():
    return {"message": ""}


@router.api_route("/ping", methods=["GET", "POST"])
async def ping(raw_request: Request) -> Response:
    """Ping check. Endpoint required for SageMaker"""
    return Response(status_code=200, content="\n")


@router.api_route("/v2/health/live")
async def live(raw_request: Request) -> Response:
    """Ping check. Endpoint required for SageMaker"""
    return Response(status_code=200, content="\n")


@router.api_route("/v2/health/ready")
async def ready(raw_request: Request) -> Response:
    """Ping check. Endpoint required for SageMaker"""
    return Response(status_code=200, content="\n")

app.include_router(router)

# write
dir = os.environ.get("READINESS_PROBE_DIR", "/databricks/readiness-probe")
os.makedirs(dir, exist_ok=True)
marker_file_path = Path(f"{dir}/{os.getpid()}")
marker_file_path.touch()
retry_times = 0

while not marker_file_path.exists() and retry_times < 1000:
    marker_file_path.touch()
    time.sleep(1)
    retry_times += 1

if not marker_file_path.exists():
    raise Exception("fail to mark ready")
