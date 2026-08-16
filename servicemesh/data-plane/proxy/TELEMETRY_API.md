# Telemetry Ingestion API (Proxy → Dashboard Backend)

프록시 사이드카가 판정 결과를 대시보드 백엔드로 보내는 **단방향 수집 계약**이다.
백엔드→프론트 조회 API(`backend-frontend-api.md`)와는 방향이 반대이며, 그 API가 프론트에
서빙하는 필드의 **원천**이 이 수집이다.

## 방향과 방식

```
프록시(생산자) ──HTTP POST 배치──> 백엔드(소비자) ──STOMP──> 프론트
     └ 이 문서 ─────────────────────┘  └ backend-frontend-api.md ┘
```

- **HTTP POST**를 쓴다. WebSocket이 아니다. 프록시는 데이터를 밀어내기만 하고 백엔드로부터
  받을 게 없다. WebSocket(STOMP)은 백엔드↔프론트 구간 전용이다.
- 발신은 **데이터 경로와 분리된 별도 태스크**다. 판정은 즉시 큐에 넣고, 1초 주기로 배치
  전송한다. 백엔드가 죽어도, 느려도 트래픽 중계는 멈추지 않는다. 큐가 가득 차면 **가장
  오래된 항목부터 폐기**한다(최신 관측 우선).
- `DASHBOARD_URL`이 설정되지 않으면 발신기는 통째로 비활성이다. 프록시는 텔레메트리 없이
  정상 동작한다.

## 엔드포인트

```
POST {DASHBOARD_URL}/ingest/events
Content-Type: application/json
```

**Response**: `200`(또는 `202`). 바디는 무시한다. 2xx 아니면 로그만 남기고 다음 주기에
재시도하지 않는다(해당 배치는 폐기). 신선도가 중요한 관측 데이터라 재전송으로 순서가
꼬이는 것보다 버리는 편이 낫다.

## 페이로드

```json
{
  "proxy": {
    "serviceName": "post",
    "podName": "post-6d4f8b9c7d-a1b2c",
    "podIp": "10.244.1.37",
    "nodeName": "worker-1",
    "namespace": "default"
  },
  "windowStats": {
    "from": "2026-08-06T13:21:05.000+09:00",
    "to":   "2026-08-06T13:21:06.000+09:00",
    "benign":  128,
    "cleared": 0,
    "drop":    2,
    "relay":   1
  },
  "events": [
    {
      "occurredAt": "2026-08-06T13:21:06.115+09:00",
      "direction": "REQUEST",
      "sessionId": "s-9f2a41c7",
      "srcIp": "10.244.1.37", "srcPort": 48812,
      "dstIp": "10.96.0.1",   "dstPort": 443,
      "protocol": "TCP",
      "modelVerdict": "ATTACK",
      "ocsvmScore": -0.4127,
      "verdict": "DROP",
      "category": "drop",
      "verificationStage": "REQUEST_VERIFIER",
      "verificationPassed": false,
      "detectionLatencyMs": 0.61,
      "signature": "GET|kubernetes:443|/api/v1/secrets|q:|b:",
      "packets": [
        { "seq": 1, "capturedAt": "2026-08-06T13:21:06.109+09:00", "length": 1460, "flags": "PSH,ACK" }
      ]
    }
  ]
}
```

## 두 채널을 나눈 이유

| 채널 | 무엇 | 주기 | 백엔드가 여기서 만드는 것 |
|---|---|---|---|
| `windowStats` | benign 포함 4분류 **집계** | 1s | `/dashboard/stats/*`, 엣지 굵기 |
| `events` | `cleared`·`drop`·`relay` **개별** | 발생 즉시 큐 | `/dashboard/events` 행 |

평상시 대량 benign을 개별 이벤트로 보내면 부하가 초당 수천 건이 된다. benign은 집계
숫자로만 보내고, 개별 저장 대상(`cleared/drop/relay`)만 `events`에 담는다.
`backend-frontend-api.md`의 "benign은 개별 저장하지 않는다"와 일치한다.

## 필드 담당 경계

프록시가 **아는 것만** 보낸다. 나머지는 백엔드가 채운다.

| 프록시가 보냄 | 백엔드가 채움 | 근거 |
|---|---|---|
| `srcIp`, `dstIp`, 포트 | `peerServiceName` | 백엔드가 K8s watch로 IP→서비스 역매핑. **프록시는 IP만** 보내 추가 트래픽·재귀 탐지를 피한다 |
| `serviceName`, `podName` | — | downward API(env)로 주입받아 그대로 |
| `ocsvmScore`, `verdict`, `category` | `eventId` | 백엔드가 BIGINT 채번 |
| `signature` | `summary` | 백엔드가 category+signature로 한국어 문장 생성 |
| `direction` | `modelId`(협의) | 아래 참고 |

## 방향(엣지)의 확정성

그래프의 화살표는 **항상 "관측한 프록시 → 목적지"**다. egress만 탐지하므로 애매함이 없다
(`backend-frontend-api.md` 탐지 관측 방향 규칙 2).

```
srcIp = 내 Pod (관측 주체, serviceName 확실)
dstIp = 목적지 (peerServiceName 역매핑)
→ 프론트: [내 서비스] ──> [상대 서비스]
```

- `post → kubernetes` 엣지는 반드시 post 프록시가 만든 것. K8s API Server는 프록시가
  없어 자기 통계는 `null`이지만, 이 엣지로 위험이 드러난다.
- **응답(Relay) 이벤트**: `srcIp`=내 Pod, `dstIp`=요청했던 외부 클라이언트. 그래프에서
  이 엣지를 어떻게 그릴지(요청 방향 유지 vs 응답 방향 표기)는 프론트 표현 규칙에 따른다.

## 판정 조합 (Algorithm 1 대응, backend-frontend-api.md와 동일)

| direction | verificationStage | verificationPassed | verdict | category |
|---|---|---|---|---|
| `REQUEST` | `REQUEST_VERIFIER` | `true` | `FORWARD` | `cleared` |
| `REQUEST` | `REQUEST_VERIFIER` | `false` | `DROP` | `drop` |
| `RESPONSE` | `RESPONSE_CONSISTENCY` | `true` | `FORWARD` | `cleared` |
| `RESPONSE` | `RESPONSE_CONSISTENCY` | `false` | `RELAY` | `relay` |

## 현재 프록시가 채울 수 있는 필드 / 대기 중

| 필드 | 상태 |
|---|---|
| `direction`, 5-tuple, `sessionId`, `ocsvmScore`, `verdict`, `category`, `signature`, `verification*` | **지금 가능** — 프레임 파싱 + 집행 결과로 채움 |
| `detectionLatencyMs` | 어댑터 호출 시간 측정으로 채움 |
| `packets[]` (5패킷 메타) | **Traffic Converter 결합 대기** — 윈도우를 Converter가 들고 있어 판정과 함께 반환받아야 함 |
| `modelId` | Anomaly Detector 결합 시 확정 |

## 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `DASHBOARD_URL` | (없음) | 비면 텔레메트리 비활성 |
| `TELEMETRY_INTERVAL` | `1.0` | 배치 전송 주기(초) |
| `TELEMETRY_QUEUE_MAX` | `10000` | 큐 상한. 초과 시 오래된 것부터 폐기 |
| `TELEMETRY_TIMEOUT` | `2.0` | POST 타임아웃(초) |
