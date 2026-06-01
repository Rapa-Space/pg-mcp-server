# PRD — MCP 트랜스포트 SSE → Streamable HTTP 전환

**유형:** 일반 기능 변경
**대상:** pg-mcp-server (PostgreSQL MCP 서버, Python/FastMCP)
**작성:** 2026-06-01

## 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 목적 | 레거시 SSE 트랜스포트를 Streamable HTTP로 교체해 노트북→studio pg-mcp 접속의 간헐 끊김·타임아웃 제거 |
| 대상 사용자 | pg-mcp에 붙는 MCP 클라이언트(노트북 Claude Code, studio 로컬) |
| 배경 | SSE 롱-리브 스트림이 간헐적으로 단절(anyio TaskGroup ExceptionGroup + `http.disconnect` 5012건, 컨테이너 가동 4일·로그 보존분 기준) → 클라이언트 응답 미수신·타임아웃. PG 권한/인증 거부는 무관(로그 0건 확인) |
| 클라이언트 인벤토리 | 2개 — (1) 노트북 Claude Code (별도 머신, `~/.claude.json`이 `192.168.0.31:38000/sse` 참조) (2) studio 로컬 세션. 둘 다 운영자 1인 소유 → 일괄 `/mcp` 재설정 비용 낮음(대안 A 근거) |

## 핵심 시나리오 + 실패 모드

| # | 코드경로 | 시나리오 | 감지 | 대응 |
|---|---------|---------|------|------|
| S1 | `app.py` streamable_http_app + lifespan | 노트북이 `/mcp`로 연결·인증·pg_query 반복 | MCP 클라 status connected + 쿼리 응답 | 정상 |
| F1 | `mcp.session_manager.run()` 미배선/순서 오류 | streamable 요청 시 session manager 미기동 → 500/행. **`mcp.session_manager`는 lazy 속성** — `streamable_http_app()` 선행 호출 없이 접근하면 `RuntimeError` | 컨테이너 부팅 시 `RuntimeError`, `/mcp` POST 500 | **순서 고정**: `http_app = mcp.streamable_http_app()`을 lifespan 진입 전 1회 호출 → 그 인스턴스를 Mount, 부모 lifespan에서 `async with mcp.session_manager.run()` 진입 (게이트) |
| F6 | streamable 자체 `/mcp` 라우트 ↔ `Mount('/')` 경로 충돌 또는 oauth 프로브 우선순위 역전 | well-known/`/mcp` 라우팅 오작동 | 부팅 후 `/mcp` POST·well-known GET 응답 코드 확인 | oauth 프로브 라우트를 `Mount('/')` **앞에 prepend** 유지(F-03), 부팅 검증으로 경로 응답 확인 |
| F2 | uv.lock 미갱신 | Dockerfile `uv sync --frozen` 빌드 실패 | docker build 에러 | uv.lock 선갱신 후 빌드 |
| F3 | 클라 config 미갱신 | `~/.claude.json`이 `/sse` 잔존 → 연결 실패 | MCP status disconnected | URL `/sse`→`/mcp` + transport type 동시 갱신 |
| F4 | 재배포 중 단절 | 컨테이너 교체 동안 pg-mcp 미응답 | 일시 connection refused | 단일 dev 툴링 컨테이너, 재기동 수초 — 수용 |
| F5 | oauth 프로브 경로 회귀 | well-known 404 JSON 핸들러 누락 시 SDK auth 중단 | `SDK auth failed: HTTP 404` | `make_oauth_probe_routes()` 유지 |

## 대안 탐색

| 대안 | 내용 | 장점 | 단점 | 공수 |
|------|------|------|------|------|
| A ★ | SSE 완전 제거 → Streamable HTTP 교체 | 끊김 원인 제거 확실·코드 단순 | 모든 클라 `/mcp` 재설정 | 중 |
| B | SSE + Streamable 병행 마운트 | 무중단 점진 전환 | 코드·유지보수 2배 | 중상 |
| C | SSE 유지 + 재연결 로직만 보강 | 클라 변경 0 | 근본 원인 미해결, SDK 한계 | 하 |
| D | 현상 유지 | 작업 0 | 간헐 타임아웃 지속 | 0 |

**선택: A** — 판단 근거 유형: 엔지니어 선호(전송 계층 근본 교체) + 운영 가설(붙는 클라가 노트북·studio 소수라 일괄 재설정 비용 낮음). MCP 최신 권장 트랜스포트가 Streamable HTTP.

## 톤·정체성

해당 없음 (UI·카피 없는 백엔드 인프라 변경). 로그·주석 문체는 기존 코드 컨벤션(한국어 주석) 유지.

## 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|---------|---------|
| F-01 | `pyproject.toml` `mcp[cli]` 의존성을 **`>=1.8,<2`로 상한 핀**(미래 메이저 회귀 차단)하고 검증한 정확 버전으로 `uv lock` 갱신. pyproject 하한·uv.lock 동시 갱신 | Must |
| F-02 | `server/app.py`: `mcp.sse_app()` → `mcp.streamable_http_app()` 교체. **검증 대상 패턴**: ① `http_app = mcp.streamable_http_app()`을 모듈 레벨(lifespan 진입 전)에서 1회 호출 ② 커스텀 Starlette lifespan에서 `async with mcp.session_manager.run():` 진입 후 기존 DB lifespan(`global_db`) 병합 ③ oauth 프로브 라우트 + `http_app`을 결합. `session_manager` lazy 제약(F1)으로 ①→②→③ 순서 고정. **H-1**: `streamable_http_app()` 반환 Starlette는 내부 `/mcp` 라우트 보유 → `Mount('/', http_app)`은 prefix-strip 의존이라 1순위로 **streamable Starlette를 최상위 app으로 채택 + oauth 라우트를 그 `.routes`에 prepend** 검토, 차선으로 Mount. 실제 노출 경로는 F-07(b)로 확인. **H-2**: sub-app 내장 lifespan(`session_manager.run()`)은 Mount 시 **비전파** → 부모 lifespan의 수동 `session_manager.run()`이 단일 SSOT(이중 진입 금지) | Must |
| F-03 | OAuth 프로브 라우트(`make_oauth_probe_routes()`)를 `Mount('/')` **앞에 prepend** 유지 — well-known 경로는 트랜스포트 무관. `/sse` 언급 주석만 정리 | Must |
| F-04 | 컨테이너 포트 바인딩 38000:8000 유지, 엔드포인트만 `/sse`→`/mcp` | Must |
| F-05 | studio에서 이미지 재빌드 + docker-compose 재배포 | Must |
| F-06 | 클라이언트 `~/.claude.json` pg-mcp 항목 URL `/sse`→`/mcp` + transport type(`http`) 갱신 | Must |
| F-07 | 검증(다단계): (a) 컨테이너 부팅 성공·`RuntimeError` 0건 (b) well-known 프로브 GET 404 JSON / `/mcp` POST 정상 핸드셰이크 응답 (c) 클라 재설정 후 첫 핸드셰이크 connected·authenticated (d) 노트북 20회 연속 pg_query 무타임아웃 (e) 재배포 후 컨테이너 로그 anyio ExceptionGroup 0건. **표본 근거**: 기존 disconnect가 세션당 다발(5012건/4일)이라 20회 연속 무사 통과면 회귀 충분 반증 | Must |
| F-08 | **롤백 절차**: 전환 실패(F-07 게이트 미통과) 시 직전 이미지 태그 + 이전 `uv.lock`·`pyproject.toml` + 클라 config `/sse` 원복으로 복귀. 단일 컨테이너라 `git revert` + 재빌드·재배포 + config 되돌림으로 즉시 복구 | Must |

## AI 기능 검증

해당 없음 (LLM 추론·채점 기능 미포함. pg_query는 결정적 SQL 실행).

## 기술 스택

| 영역 | 내용 |
|------|------|
| 언어 | Python ≥3.13 |
| 프레임워크 | FastMCP (mcp[cli] ≥1.8), Starlette, uvicorn |
| 패키지 | uv (frozen lock) |
| 인프라 | Docker (studio 192.168.0.31:38000), LAN 192.168.0.0/24 + mTLS |

## 제약사항

| 영역 | 제약 |
|------|------|
| 성능 | 재배포 다운타임: 컨테이너 교체 수초(단일 dev 툴링, 라이브 고객 트래픽 무관) |
| 보안 | PG 접근 정책(LAN + mTLS) 불변. 트랜스포트만 변경, 인증 경로 동일. `/mcp` 신규 엔드포인트도 동일 mTLS/OAuth 프로브 경유 — F-07(b)(c)에서 검증 |
| 호환성 | `/sse` 폐기 — 기존 클라 전부 `/mcp` 재설정 필요. 미갱신 클라는 연결 실패(F3) |
| 운영 맹점 | docker-compose healthcheck가 **8000 TCP connect만** 확인 → `/mcp` 핸드셰이크가 깨져도 `healthy`로 표시될 수 있음. 본 전환 검증은 healthcheck에 의존하지 않고 F-07 실제 핸드셰이크/쿼리로 판정 |

## 공개 전환 시나리오

PRD·코드에 시크릿·인프라 식별자 신규 노출 없음. 단 `~/.claude.json`은 로컬 사용자 설정 파일(커밋 대상 아님)이며 studio IP(`192.168.0.31`)는 mac-mini-infra 평문 정책상 LAN 내부 IP로 이미 취급. pg-mcp-server 레포 커밋에는 IP·시크릿 미포함(엔드포인트 경로 변경만).

## Open Issues

| # | 내용 | 처리 |
|---|------|------|
| O-1 | `query.py:36` `SET TRANSACTION READ ONLY`가 asyncpg autocommit 밖 호출돼 read-only 실효성 의심 | 본 PRD **범위 제외**. 별도 핫픽스로 추적 |
| O-2 | pg-mcp-server 미초기화(CLAUDE.md 없음) — 상위 공통 규칙 참조 문구 부재 | 본 변경 범위 외. 차후 rp-init 보강 검토 |
| O-3 | SDK 메이저 업그레이드로 인한 다른 API 변경(resources/prompts 등록 시그니처) 가능성 | F-02 구현 시 빌드·부팅 검증으로 회귀 확인 |
