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
  "peerStats": [
    { "dstIp": "10.108.4.9", "benign": 126 },
    { "dstIp": "10.96.0.10", "benign": 2 }
  ],
  "peerCount": 2,
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
      "windowSize": 5,
      "packets": [
        {
          "seq": 1,
          "capturedAt": "2026-08-06T13:21:06.109+09:00",
          "length": 1460,
          "payloadLength": 1406,
          "flags": "PSH,ACK",
          "dstIp": "10.96.0.1",
          "dstPort": 443
        }
      ]
    }
  ]
}
```

## 두 채널을 나눈 이유

| 채널 | 무엇 | 주기 | 백엔드가 여기서 만드는 것 |
|---|---|---|---|
| `windowStats` | benign 포함 4분류 **집계** | 1s | `/dashboard/stats/*` |
| `peerStats` | **목적지별 benign** | 1s | 평시 엣지와 그 굵기 |
| `events` | `benign`·`cleared`·`drop`·`relay` **개별** | 발생 즉시 큐 | `/dashboard/events` 행, 공격 엣지 |

**네 분류의 단위는 같다 — HTTP 메시지 1건당 1이다.** 집계 지점이 `TelemetryClient.emit()`
하나뿐이라서, `windowStats`의 숫자와 `events`의 행 수가 정확히 같은 것을 센다.

예전에는 benign만 탐지 경로에서 셌다. 판정은 윈도우가 찬 뒤 **프레임마다** 나오므로
(Algorithm 1 line 24의 sliding) 요청 한 번이 benign 수십 건이 됐고, cleared/drop/relay는
집행 경로라 1건이었다. 그래서 대시보드의 정상 건수가 로그 행 수보다 10배 넘게 컸고
이상 판정률도 실제보다 훨씬 작게 나왔다. 지금은 그렇지 않다.

`EMIT_FORWARD_EVENTS=false`로 끄면 benign **이벤트**만 빠지고 집계는 그대로 오른다.
집계까지 빼면 `peerStats`가 비어 토폴로지의 평시 경로가 통째로 사라진다.

## `packets` — 판정이 본 그 윈도우

`packets`는 **모델에 들어간 바로 그 윈도우**다. 컨버터가 특징 벡터를 쌓는 자리에서 메타를
짝으로 같이 쌓기 때문에, 컨버터가 `extract()`로 걸러낸 프레임은 여기에도 없다. 탐지 경로에서
따로 세면 걸러진 프레임이 섞여 판정과 무관한 패킷이 화면에 나온다.

`seq`는 판정 시점에 윈도우에 남아 있는 순서대로 1부터 붙는다. 링버퍼라 오래된 것이 밀려나므로
프레임 도착 순번과는 다르다.

**페이로드 본문은 담지 않는다.** `payloadLength`만 남긴다 — 대시보드로 나가는 값이라 요청·응답
본문이 그대로 흘러나가면 안 된다.

이상 판정에만 붙는다. 정상 시퀀스는 개별 이벤트로 나가지 않아 실을 곳이 없고, 트래픽 대부분이
정상이라 그만큼이 순수 낭비다. 그래서 `packets`가 없는 이벤트는 원래 없다 — 키가 아예 빠져 있으면
탐지 모듈이 `window_meta`를 제공하지 않는 구성이라는 뜻이다.

## `peerStats` — benign만 목적지를 나른다

토폴로지 엣지는 "관측된 통신"이다. `cleared`·`drop`·`relay`는 `events`가 `dstIp`와 함께
나르므로 엣지를 만들 수 있다. benign도 `emit()`이 `dstIp`로 목적지별 집계를 올리므로
`peerStats`가 채워진다. `EMIT_FORWARD_EVENTS`를 꺼도 이 집계는 유지된다. 없으면
평시 통신 경로(`post → mysql` 등)가 토폴로지에 한 줄도 그려지지 않는다 — 노드만 있고
선이 없는 그래프가 되고, "평소 없던 `post → kubernetes` 엣지가 공격 시점에 생긴다"는
대비 효과도 배경이 없어 사라진다.

`peerStats`는 그 빈칸만 메운다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `peerStats[].dstIp` | string | 목적지 IP. 상한에 걸려 접힌 몫은 `"other"` |
| `peerStats[].benign` | int | 그 목적지로 간 benign 시퀀스 수 |
| `peerCount` | int | 이번 창에서 관측한 서로 다른 목적지 수. **접힌 것도 센다** |

`benign` 합은 `windowStats.benign`과 항상 같다. 상한에 걸려도 `other`로 접힐 뿐
유실되지 않는다.

**benign 외의 분류는 여기에 담지 않는다.** `events`가 이미 목적지와 함께 나르므로 같은
사실이 두 경로로 갈라지고, 어긋났을 때 어느 쪽이 맞는지 판단할 근거가 없어진다.

### 상한과 `peerCount`

슬롯은 창당 64개(`telemetry.MAX_PEERS`)다. 평시 목적지는 형제 서비스·mysql·DNS 정도라
10개 안쪽이고, 포트 스캔은 benign이 아니라 attack 판정을 만들어 이쪽으로 오지 않는다.
그래도 모델이 스캔을 **놓쳐** benign으로 흘리면 키가 퍼질 수 있어 안전망을 둔다. 슬롯이
차면 새 목적지는 `other` 한 칸으로 접는다.

접으면 "목적지가 많다"는 신호가 사라지므로 `peerCount`를 따로 보낸다. 카디널리티와 무관한
값 하나이고, 평시 10에서 갑자기 수천이 되는 것 자체가 스캔 지표다.

엣지 수 자체의 상한은 백엔드 집계 단계가 담당한다 — 공격 이벤트도 스캔 시 수천 개의
서로 다른 목적지를 만들기 때문에, 두 출처가 합쳐지는 그쪽에 두어야 한 번으로 덮인다.

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
| `detectionLatencyMs` | **채움** — 어댑터가 classify 호출 전후로 측정 |
| `packets[]`·`windowSize` | **채움** — Converter가 벡터를 쌓는 자리에서 메타도 같이 쌓고(`ModelConverter.window_meta`), 어댑터가 이상 판정에만 실어 보낸다. 정상 판정에는 붙이지 않는다 |
| `modelId` | Anomaly Detector 결합 시 확정 |

## 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `DASHBOARD_URL` | (없음) | 비면 텔레메트리 비활성 |
| `TELEMETRY_INTERVAL` | `1.0` | 배치 전송 주기(초) |
| `TELEMETRY_QUEUE_MAX` | `10000` | 큐 상한. 초과 시 오래된 것부터 폐기 |
| `EMIT_FORWARD_EVENTS` | `true` | benign을 개별 이벤트로도 보낼지. 꺼도 집계는 오른다 |
| `TELEMETRY_TIMEOUT` | `2.0` | POST 타임아웃(초) |
