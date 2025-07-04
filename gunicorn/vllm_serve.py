from starlette.requests import Request
from starlette.responses import Response


async def vllm_extra_serve(request: Request, call_next):
    if request.url.path in ("/v2/health/live", "/v2/health/ready"):
        return Response(content="\n", status_code=200, media_type="application/json")
    return await call_next(request)
