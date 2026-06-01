# server/oauth_compat.py
"""
MCP 인증 스펙(2025-06-18) 호환용 OAuth 프로브 경로 핸들러.

배경: MCP 클라이언트 SDK 가 트랜스포트 연결 전에 OAuth Resource Server 메타데이터를
프로브한다 (`/.well-known/oauth-protected-resource[/{path}]`,
`/.well-known/oauth-authorization-server`, `/.well-known/openid-configuration`,
`POST /register`). pg-mcp 는 OAuth 미지원이며, 스펙상 이 경로들이 부재(404)면
클라이언트는 anonymous 로 fallback 해야 한다.

그러나 Starlette 의 기본 404 본문은 평문 "Not Found" 라 일부 SDK 가
"OAuth 에러 응답"으로 오해해 JSON 파싱에 실패 → 연결 자체를 중단한다
(증상: `SDK auth failed: HTTP 404: Invalid OAuth error response`).

본 모듈은 같은 경로에 대해 **JSON 본문 `{}` + 상태 404 + content-type
application/json** 으로 응답해 SDK 의 회복 경로를 활성화한다. pg-mcp 가
실제로 OAuth 를 도입하면 핸들러를 교체하면 된다.
"""

from starlette.responses import JSONResponse
from starlette.routing import Route


async def _oauth_not_configured(request):
    return JSONResponse({}, status_code=404)


# RFC 9728 (Protected Resource Metadata) + MCP 2025-06-18 프로브 대상 경로.
# resource-specific 변형(`/mcp` 접미 등)은 path:path catch-all 로 흡수.
_OAUTH_PROBE_GET_PATHS = (
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/{path:path}",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
)


def make_oauth_probe_routes():
    """OAuth 프로브 인터셉트용 Starlette Route 리스트.

    호출처(server/app.py) 에서 Mount('/') 앞에 prepend 해 매칭 우선순위를 확보.
    """
    routes = [
        Route(path, _oauth_not_configured, methods=["GET"])
        for path in _OAUTH_PROBE_GET_PATHS
    ]
    routes.append(Route("/register", _oauth_not_configured, methods=["POST"]))
    return routes
