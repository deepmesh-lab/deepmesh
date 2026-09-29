# DeepMesh 대시보드 프론트엔드

`DeepMesh_대시보드_API_명세.md`의 REST 9종 + SSE 스트림을 소비하는 모니터링 대시보드.

## 실행

```bash
npm install
npm run dev     # http://localhost:3110
```

기본값은 **목 데이터 모드**다. 백엔드 없이 바로 뜬다.

## 목 → 실제 백엔드 전환

```bash
# .env
VITE_USE_MOCK=false
DASHBOARD_BACKEND_ORIGIN=http://localhost:8080
```

이 두 값만 바꾸면 된다. 컴포넌트 코드는 손대지 않는다.

앱은 `VITE_DASHBOARD_API_URL`이 비어 있으면 **같은 오리진**(`/dashboard/...`)으로 요청하고,
개발 서버의 프록시가 `DASHBOARD_BACKEND_ORIGIN`으로 넘긴다. 백엔드에 CORS 설정이 필요 없다.

## 컬러 시스템

색 값은 [`src/styles/tokens.css`](src/styles/tokens.css) 한 곳에만 있다. 3단 구조다.

| 단계 | 토큰 | 역할 |
|---|---|---|
| 1 | `--brand-*` · `--palette-*` | 실제 hex가 있는 유일한 층 |
| 2 | `--color-primary` `--color-secondary` `--color-success` `--color-warning` `--color-danger` `--color-info` … | 역할 이름 |
| 3 | `--verdict-benign` `--verdict-cleared` `--verdict-drop` `--verdict-relay` | 이 화면 고유의 의미 |

**브랜드를 갈아끼우려면 1단의 `--brand-primary-*` / `--brand-secondary-*` 값만 바꾼다.**
2·3단과 컴포넌트 CSS는 손대지 않는다.

현재 적용된 값은 ETRI CI다 — Blue `#0066A5`(R0 G102 B165), Orange `#F15A22`(R241 G90 B34).

SVG 차트는 `fill="var(--x)"`를 해석하지 못하므로
[`src/dashboard/internal/theme.ts`](src/dashboard/internal/theme.ts)가 계산된 토큰 값을 읽어 넘긴다.
색 값을 TS에 따로 적어두지 않는다.

## 네임스페이스

기본값은 **`deepmesh`**다. 명세의 API 기본값은 `default`지만 이 프로젝트의 k8s 매니페스트는
전부 `deepmesh`에 배포되므로(`k8s/namespace.yaml`), 그대로 두면 실제 클러스터에서 빈 화면이 나온다.
다른 네임스페이스를 보려면 `VITE_DASHBOARD_NAMESPACE`로 덮어쓴다.

`VITE_DASHBOARD_API_URL`을 채우면 앱이 그 절대 URL로 직접 호출하므로 프록시를 타지 않는다.
이 경우 백엔드가 `Access-Control-Allow-Origin`을 내려줘야 하며, `EventSource`도 마찬가지다.

전환 지점은 [`src/dashboard/internal/client.ts`](src/dashboard/internal/client.ts) 한 곳이다.
실제 구현(`dashboardApi.ts` / `dashboardStream.ts`)과 목 구현(`mock/`)이 모두
`types.ts`의 `DashboardApi` · `DashboardStreamFactory` 타입을 구현하므로,
백엔드 응답 스키마가 명세와 어긋나면 `npm run typecheck`에서 드러난다.

## 구조

```
src/
├── api/restClient.ts                 fetch 래퍼 (msa/frontend와 동일 규약)
├── dashboard/
│   ├── internal/
│   │   ├── types.ts                  명세 스키마 전체
│   │   ├── dashboardApi.ts           실제 REST 호출
│   │   ├── dashboardStream.ts        실제 EventSource 래퍼
│   │   ├── client.ts                 ★ 실제 / 목 선택 지점
│   │   ├── time.ts                   KST ISO-8601 유틸
│   │   ├── verdict.ts                판정 분류 공통 계산
│   │   ├── hooks/                    화면별 데이터 훅
│   │   └── mock/                     목 상태 저장소 · 목 API · 목 스트림 · 시나리오
│   ├── components/
│   └── pages/
└── routes/AppRoutes.tsx
```

## 화면

| 경로 | 내용 |
|---|---|
| `/` | 실시간 모니터. 요약 카드 · 토폴로지(React Flow) · 판정 추이(Recharts) · 탐지 피드 · 서비스별 분포 |
| `/logs` | 이력 조회. `GET /dashboard/events`의 필터 + 커서 페이지네이션 |

목 모드에서는 상단에 **시나리오 1·2 재생** 버튼이 보인다. 백엔드 모드에서는 숨겨진다
(명세상 대시보드 API는 GET 전용이라 서버에 재생을 요청할 수단이 없다).
