# PRD — 멀티 DB: 이름으로 선택 (list_databases + connect-by-name)

**유형:** 일반 기능 변경
**대상:** pg-mcp-server
**작성:** 2026-06-01

## 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 목적 | 클라이언트가 자격증명 없이 **DB 이름만으로** 서버의 임의 DB에 ad-hoc 연결. 현재는 기본 DSN(`museum_finder`) 단일 DB만 사용 |
| 대상 사용자 | pg-mcp MCP 클라이언트 (노트북·studio) |
| 배경 | 같은 PG 클러스터에 앱 DB 다수(`clock_points`·`museum_finder`·`senior_meal_map`). `rp_readonly`가 전부 CONNECT 가능·mTLS 적용 확인됨. 막힌 건 편의성 — connect에 매번 자격증명 든 full DSN을 넘겨야 함 |

## 핵심 시나리오 + 실패 모드

| # | 코드경로 | 시나리오 | 감지 | 대응 |
|---|---------|---------|------|------|
| S1 | `list_databases` | 클라가 선택 가능한 DB 목록 조회 | 목록에 앱 DB 노출, 시스템·템플릿 미포함 | 정상 |
| S2 | `connect(database="clock_points")` | 이름만 주면 서버가 base DSN의 dbname 치환해 연결 | conn_id 반환 → pg_query 성공 | 정상 |
| F1 | `connect(database="postgres")` | 시스템 DB 선택 시도 | ValueError | 시스템/템플릿 denylist 거부 |
| F2 | `DEFAULT_DSN` 미설정 | `database=` 사용 시 base DSN 없음 | ValueError | 명시적 에러 메시지 |
| F3 | base DSN dbname 치환 오류 | 쿼리스트링(sslmode 등) 유실·경로 깨짐 | 연결 실패 | `urlsplit/urlunsplit`로 path만 교체, query 보존 |
| F4 | 존재하지 않는 dbname | 오타 등 | asyncpg 연결 에러 | 에러 전파(클라가 list_databases로 확인) |

## 대안 탐색

| 대안 | 내용 | 장점 | 단점 |
|------|------|------|------|
| A ★ | `list_databases` + `connect(database=)` (동적 나열, 시스템 제외) | 자격증명 0, 미래 DB 자동 포함, "그때그때"에 최적 | connect 시그니처 확장 |
| B | 부팅 시 전 DB auto-register | 연결 단계 생략 | DB 추가 시 재기동 필요 |
| C | full DSN 직접 전달(현행) | 코드 0 | 매번 자격증명 |

**선택: A** — 판단 근거: 제품 가설(ad-hoc 전환이 주 사용 패턴) + 운영(서비스 DB 증가 시 자동 반영). 사용자 Q1/Q2 명시 선택.

## 톤·정체성

해당 없음 (백엔드 툴). 기존 한국어 주석·로그 컨벤션 유지.

## 기능 요구사항

| ID | 요구사항 | 우선순위 |
|----|---------|---------|
| F-01 | `list_databases` 툴 신설: **`DEFAULT_CONN_ID`(기본 연결)** 풀로 `SELECT datname FROM pg_database WHERE datistemplate=false` 실행 후 **시스템 denylist(`postgres`,`template0`,`template1`) 제외**한 이름 배열 반환. 동적이라 신규 서비스 DB 자동 포함. **`DEFAULT_CONN_ID`/`DEFAULT_DSN` 미설정 시 ValueError**(F2와 동일 가드) | Must |
| F-02 | `connect` 툴에 `database: str = ""` 인자 추가. **인자 우선순위**: `connection_string` 우선 — 비어있지 않으면 그대로 사용하고 `database`는 무시. `connection_string`이 비고 `database` 지정 시에만 `DEFAULT_DSN`의 dbname을 치환해 연결. 둘 다 비면 기존대로 `DEFAULT_DSN`. **기존 빈 호출·full DSN 경로 하위호환 유지** | Must |
| F-03 | `database=`가 시스템 denylist면 ValueError 거부 (F1). `DEFAULT_DSN` 미설정인데 `database=` 지정 시 ValueError (F2) | Must |
| F-04 | dbname 치환은 `urllib.parse.urlsplit/urlunsplit`로 **path만 교체, query(sslmode 등)·netloc·scheme 보존** (F3) | Must |
| F-05 | 정규화 일관성: 치환은 **`DEFAULT_DSN` 원문에 `urlsplit`→path만 교체→`urlunsplit`** 왕복으로 생성하고 그 문자열을 `register_connection`에 전달. dbname이 기본과 동일하면 동일 왕복이 **DEFAULT_DSN 원문과 바이트 동일**을 보장 → conn_id == `DEFAULT_CONN_ID`(중복 풀·`disconnect` 가드 우회 방지). 사후 보정이 아닌 사전 보장 | Must |
| F-06 | `disconnect` 동작 불변: 이름연결로 만든 conn_id도 일반 conn_id와 동일 처리. `DEFAULT_CONN_ID` 보호 가드는 그대로 유지 | Must |
| F-07 | 검증: (a) `list_databases` = **`pg_database`(template 제외)에서 denylist 뺀 전체와 일치**(현재 앱 3개, 불변식 — 미래 DB 자동 반영) (b) `connect(database=각각)` → `current_database()` 일치 (c) 시스템 DB 지정 → 거부, **대소문자 변형(`Postgres`)도 거부** (d) query string(sslmode 등) 포함 DSN 치환 시 query 보존 (e) 기본 dbname 재지정 → conn_id == `DEFAULT_CONN_ID` (f) **비기본 dbname → conn_id ≠ `DEFAULT_CONN_ID` 이고 disconnect 성공** | Must |
| F-08 | 풀 생명주기 운영 제약 **명시**: 활성 풀 개수 자동 상한 미도입 — `disconnect`(클라 자율) 의존. 안전 근거로 **여유 계산 기재**: 앱 DB 수 × `max_size`(10) + 기본 풀 ≤ PG `max_connections`. 현재 앱 DB 3~4개 × 10 ≈ 40 ≤ 기본 100 → 여유 확보. 향후 DB 급증 시 `max_size` 하향 또는 유휴 풀 정리 도입 검토 | Should |

## AI 기능 검증

해당 없음.

## 기술 스택

Python ≥3.13, FastMCP(mcp 1.27.2), asyncpg. PG mTLS(env 인증서, 모든 pool 적용).

## 제약사항

| 영역 | 제약 |
|------|------|
| 보안 | 노출 범위는 `rp_readonly` 권한 내 DB로 한정(롤 권한이 실질 게이트). **앱 DB 간 데이터 격리는 제공하지 않음** — 시스템/템플릿 DB만 denylist로 추가 차단, 앱 DB는 권한 경계가 유일한 게이트(의도된 설계) |
| 호환성 | `connect` 시그니처 확장은 **하위호환**(신규 optional 인자, `connection_string` 우선). 기존 빈 호출·full DSN 경로 불변 |
| 성능 | list_databases는 단일 카탈로그 쿼리. 풀은 **conn_id(=DSN 해시, netloc+path)별** — 동일 DSN 재호출 시 재사용, dbname 상이 시 풀 신설. 다수 DB 동시 연결 시 백엔드 커넥션이 DB 수×(min 2~max 10)으로 증가 |

## 공개 전환 시나리오

코드에 시크릿·내부 IP·호스트 미포함(자격증명은 env DSN, 인증서는 env 경로). DB 이름(`clock_points` 등)은 서비스 식별자지 시크릿 아님. 레포 노출 리스크 없음.

## Open Issues

| # | 내용 | 처리 |
|---|------|------|
| O-1 | `query.py:36` read-only 가드 실효성(이전 PRD에서 이월) | 범위 외, 별도 추적 |
| O-2 | DNS rebinding 보호 비활성(PR #4) — LAN 신뢰 전제. 멀티 DB로 노출 표면 증가(임의 LAN Host가 모든 앱 DB 조회 가능) | 위협 모델(LAN 전용+NAT) 동일 적용. 외부 노출 전환 시 재검토 |
