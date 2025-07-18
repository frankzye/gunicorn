import os
import time
import httpx
from logging import getLogger
from pathlib import Path
import flask
import shlex
import subprocess
import signal
from concurrent.futures import ThreadPoolExecutor

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
    port = os.environ.get("GUNICORN_EXTRA_PORT", 8001)
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
    child_proc.wait()
    
readness_pool = ThreadPoolExecutor(1)
readness_pool.submit(run)

signal.signal(signal.SIGTERM, lambda signum, frame: readness_pool.shutdown(wait=False))


app = flask.Flask(__name__)



@app.get("/")
def root():
    return {"message": ""}


@app.route("/ping", methods=["GET", "POST"])
def ping():
    """Ping check. Endpoint required for SageMaker"""
    return flask.Response(status=200, response="\n", mimetype="application/json")


@app.route("/v2/health/live")
def live():
    """Ping check. Endpoint required for SageMaker"""
    return flask.Response(status=200, response="\n", mimetype="application/json")


@app.route("/v2/health/ready")
def ready():
    """Ping check. Endpoint required for SageMaker"""
    return flask.Response(status=200, response="\n", mimetype="application/json")


@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/invocations", methods=["POST"])
def invocations():
    raw_request = flask.request
    timeout = os.environ.get("REQUEST_TIMEOUT", 6000)
    url = f'http://localhost:{os.environ.get("GUNICORN_EXTRA_PORT", 8001)}/invocations'
    payload = {}
    content_type = raw_request.content_type
    headers = {
        "Content-Type": content_type
    }
    if raw_request.is_json:
        payload = raw_request.json

    try:
        if str(payload.get("stream", "false")).lower() == "true":
            
            @flask.stream_with_context
            def stream_response():
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", url, headers=headers, content=payload) as response:
                        for chunk in response.iter_bytes():
                            yield chunk

            return flask.Response(stream_response(), status=200, media_type="text/event-stream;charset=UTF-8")

        else:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(url, headers=headers, content=raw_request.get_data())
                return flask.Response(status=res.status_code, headers=res.headers, response=res.content)
    except Exception as e:
        return flask.Response(status=500, response=str(e))


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
