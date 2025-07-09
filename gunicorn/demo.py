import os
import time
from logging import getLogger
from pathlib import Path
from fastapi import FastAPI, APIRouter, Request, Response
import shlex
import subprocess
import signal

log = getLogger(__name__)


def run():
    mlflowserving_path = os.environ.get("MODEL_PATH")
    try:
        file_names = os.listdir(mlflowserving_path)
        log.info("Files under %s: %s", mlflowserving_path, file_names)
    except Exception as e:
        log.warning("Could not list files under %s: %s", mlflowserving_path, e)

    model_uri = os.path.join(os.environ.get("PWD"), mlflowserving_path)
    log_model_path = os.path.join(model_uri, os.environ.get("MODEL_ARTIFACT_PATH", "model"))

    if not os.path.exists(log_model_path):
        log_model_path = model_uri

    cmd = f"vllm serve {log_model_path} "

    host = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_IP")
    port = os.environ.get("MODEL_SERVING_CONTAINER_EXPOSED_PORT")
    vllm_ops = os.environ.get("VLLM_OPS")

    args = []
    if host:
        args.append(f"--host={shlex.quote(host)}")

    if port:
        args.append(f"--port={port}")

    if vllm_ops:
        args.append(vllm_ops)

    cmd += ' '.join(args)

    cmd_env = os.environ.copy()

    command = "exec " + cmd
    log.info("=== Running command '%s'", command)
    command = ["bash", "-c", command]

    child_proc = subprocess.Popen(
        command,
        env=cmd_env,
        stdout=None,
        stderr=None,
    )

    def _terminate():
        child_proc.terminate()
        if child_proc.poll() is None:
            try:
                child_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child_proc.kill()

    signal.signal(signal.SIGTERM, _terminate)


async def lifespan(context):
    run()
    yield
    log.info("shuted down!")


app = FastAPI(lifespan=lifespan)

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
