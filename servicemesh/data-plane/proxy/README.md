# Proxy Container — Traffic Handler

각 서비스 Pod에 사이드카로 붙어 나가는 트래픽을 검사하고 **Relay / Drop / Forward**를
결정한다. 논문 *Lightweight Service Mesh for Intrusion Detection using KD-CNN in
Cloud-Native Environments*의 Algorithm 1 구현이다.

Proxy Container는 세 모듈로 이루어진다. 이 디렉터리는 그중 **Traffic Handler**다.

| 모듈 | 담당 | 상태 |
|---|---|---|
| Traffic Handler | 트래픽 가로채기, 세션 구성, 판정 집행 | 이 디렉터리 |
| Traffic Converter | 세션 이미지(20×5) 생성 | `../detection/` |
| Anomaly Detector | KD-CNN + OCSVM 판정 | `../detection/` |

두 모듈은 `../detection/`에 vendoring돼 있고, `detection_binding.py`가 아래 규약에
맞춰 잇는다. 다만 **사이드카 이미지에 아직 torch가 없어서 기본값은 여전히 탐지 없는
Forward 전용**이다 — 배포 배선이 끝나야 실제로 판정한다.

## 동작

### 세 가지 처리

| 동작 | 조건 |
|---|---|
| **Forward** | 정상 판정이거나 판정이 아직 없을 때 |
| **Drop** | outbound 요청이 이상 판정 + Request Verifier가 미관측이라 답할 때 |
| **Relay** | outbound 응답이 이상 판정 + 형제 Pod의 참조 응답과 내용이 다를 때 |

검사 대상은 **나가는 트래픽뿐**이다. 위협 모델이 lateral movement이므로 침해된 Pod에서
확장되는 트래픽을 막는 것이 목적이고, 외부에서 들어오는 요청은 검사 없이 메인 컨테이너로
전달한다.

### 두 경로로 나뉜다

논문 Algorithm 1은 패킷 하나가 탐지를 거쳐 그 자리에서 전달되는 것처럼 쓰여 있지만,
그대로 구현할 수 없다. `Preprocess`가 요구하는 19바이트 헤더는 IP/TCP 헤더에서 뽑는데,
트래픽을 전달하는 프록시는 일반 TCP 소켓을 쓰고 거기엔 L2/L3/L4 헤더가 없다. 커널이 이미
벗겨냈기 때문이다.

헤더를 합성하면 학습 데이터(pcap)와 추론 입력의 형식이 어긋나 모델이 무의미해진다.
그래서 탐지용 프레임을 따로 캡처하고, 두 경로를 세션 id로 잇는다.

```
              ┌──────────────── Pod ────────────────┐
 메인 컨테이너 ─┼─> (lo) ──> 프록시 ──> 목적지        │
              │     │          │                    │
              │     ▼          │ ② 집행 경로         │
              │ ① 탐지 경로     │   proxy.py         │
              │   detection.py │   HTTP 메시지 단위   │
              │   프레임 단위    │   Relay/Drop/Forward
              │     │          ▲                    │
              │     ▼          │                    │
              │ 종단 어댑터 ──> VerdictStore ─────────┘
              │  adapter.py     session_id → Detection
              └─────────────────────────────────────┘
```

- **① 탐지 경로** — loopback을 `AF_PACKET`으로 캡처한다. iptables가 ingress·egress를
  모두 프록시로 돌리므로 메인 컨테이너의 모든 트래픽이 이 구간을 지난다. 정확히 논문의
  `T_main`이고, 프록시가 외부로 내보내기 **전에** 잡히므로 Relay·Drop을 걸 시간이 남는다.
- **② 집행 경로** — 연결을 종단하는 프록시. Relay는 응답 본문을 형제 Pod 응답과 비교해야
  하고 Drop은 요청 본문으로 시그니처를 만들어야 해서, HTTP 메시지 단위로 다룬다.

두 경로가 공유하는 것은 `session_id` 하나뿐이다.

```
session_id = (src_ip ^ dst_ip ^ src_port ^ dst_port ^ proto) % max_sessions
```

XOR이라 방향에 무관하다 — 요청과 응답이 같은 세션으로 묶인다. `max_sessions`는 Traffic
Converter가 세션을 나누는 기준과 같아야 하므로 어댑터에게서 받아 쓴다.

자세한 배경과 이 분리가 낳는 성질은 `docs/traffic-handler-two-paths.md` 참고.

## 구조

```
traffic_handler/
  adapter.py        ★ 탐지 모듈과의 유일한 접점
  detection_binding.py  ../detection/ 을 그 접점에 맞추는 래퍼
  ports.py          SessionKey, Detection, Protocol 정의
  detection.py      탐지 경로 (Algorithm 1 line 1~8)
  packet_source.py  AF_PACKET 캡처
  proxy.py          집행 경로 (Algorithm 1 line 9~26)
  http_message.py   HTTP/1.1 파서
  signature.py      Request Verifier 질의용 시그니처 (생성 규칙 v1)
  relay.py          형제 Pod 참조 응답 획득
  control_plane.py  POST /verify/request 클라이언트
  peers.py          Pod Info Provider가 push한 주소록
  verdicts.py       세션별 판정 보관 (TTL)
  session.py        프레임 파싱, T_main 판별
  config.py         환경변수
  stubs.py          테스트용 대역
main.py             엔트리포인트

../iptables.sh        initContainer가 실행하는 리다이렉트 규칙 (data-plane/)
../Dockerfile         프록시 컨테이너 이미지 (data-plane/)
../requirements.txt   런타임 의존성 (data-plane/)
../detection/         vendoring한 Traffic Converter·Anomaly Detector (data-plane/)
../model/             배포용 학습 모델 (.pt/.pkl). 저장소에 없고 PVC를 마운트한다
```

## 탐지 모듈 붙이기

Traffic Handler가 아는 것은 메서드 하나다.

```python
analyze(session_id: int, frame: bytes) -> Detection | None
```

`frame`은 `AF_PACKET`으로 잡은 **완전한 Ethernet 프레임 원본**이다. tcpdump로 뜬 pcap과
같은 형태라 학습 때 쓴 전처리를 그대로 쓸 수 있다. 19B 헤더 추출·1460B 절단·이미지 조립은
전부 어댑터 너머의 일이다. 윈도우가 아직 안 찼으면 `None`을 반환한다.

구현은 둘 중 편한 쪽으로 하면 된다.

```python
# 분리형
class TrafficConverter:
    max_sessions = 65536
    def push(self, session_id, frame): ...    # 이미지 또는 None

class AnomalyDetector:
    def classify(self, session_id, image): ...

# 융합형 — 세션 버퍼를 직접 들고 있는 경우
class DetectionEngine:
    max_sessions = 65536
    def analyze(self, session_id, frame): ...
```

주입은 환경변수로 한다.

```bash
CONVERTER_FACTORY=모듈:팩토리  DETECTOR_FACTORY=모듈:팩토리    # 분리형
DETECTION_ENGINE_FACTORY=모듈:팩토리                          # 융합형
```

`../detection/`의 모듈을 쓸 때는 이렇게 준다.

```bash
CONVERTER_FACTORY=traffic_handler.detection_binding:build_converter
DETECTOR_FACTORY=traffic_handler.detection_binding:build_detector
MODEL_ROOT=/app/model          # 가중치 PVC 마운트 지점
DETECTION_SERVICE=auth         # 생략하면 SERVICE_NAME에서 "-service"를 뗀 값
```

어댑터는 탐지 모듈의 예외를 흡수해 `None`으로 만든다. 탐지가 고장 나도 트래픽 중계는
멈추지 않는다 — 바꿔 말하면 **탐지가 조용히 죽어도 서비스는 정상으로 보이므로 로그를
확인해야 한다.**

## 실행

```bash
cd servicemesh/data-plane/proxy
python main.py
```

주요 환경변수 (전체는 `traffic_handler/config.py`).

| 변수 | 기본값 | 용도 |
|---|---|---|
| `TARGET_PORT` | `8080` | 메인 컨테이너 포트 |
| `PROXY_PORT` | `9011` | 프록시 리스닝 포트 (주소록 수신도 겸함) |
| `POD_IP` | `127.0.0.1` | fieldRef로 주입 |
| `SERVICE_NAME` | `unknown` | 로그 식별용 |
| `CONTROL_PLANE_URL` | — | Request Verifier 주소 |
| `SNIFF_IFACE` | `lo` | 캡처 인터페이스 |
| `VERDICT_TTL` | `10` | 세션 판정 유효 기간(초) |
| `VERIFY_FAIL_OPEN` | `false` | Control Plane 장애 시 허용 여부 |

## 테스트

```bash
cd servicemesh/data-plane/proxy && python -m pytest tests -q
```

Relay·Drop 분기는 실제 loopback 소켓 위에서 가짜 메인 컨테이너·형제 Pod·Control Plane을
띄워 검증한다. 모델 파일이나 torch 없이 돌아간다.

## 배포

```bash
docker build -t <레지스트리>/reverse-proxy:<태그> servicemesh/data-plane
docker push <레지스트리>/reverse-proxy:<태그>
kubectl -n deepmesh apply -f k8s/post-service/deployment-with-sidecar.yaml
```

매니페스트에서 지켜야 할 것.

- 사이드카 컨테이너 이름은 **`reverse-proxy`** 를 유지한다. Control Plane의 Pod
  디스커버리 기준이다. 바꾸면 주소록 push가 끊기고 검증 API가 전부 400이 된다.
- 사이드카는 `runAsUser: 1337`. `iptables.sh`의 `--uid-owner`와 짝이다. 어긋나면
  프록시가 전달하는 트래픽이 자기 자신에게 다시 리다이렉트되어 루프에 빠진다.
- 사이드카에 `NET_RAW`가 필요하다. 이미지의 python 바이너리에 파일 capability가 붙어
  있어서, drop하면 탐지가 꺼지는 게 아니라 **컨테이너가 아예 기동하지 못한다.**
- Service의 `targetPort`는 `8080` 그대로 둔다. PREROUTING이 9011로 돌린다.

기동 확인.

```bash
kubectl -n deepmesh logs -l app=post-service -c reverse-proxy --tail=20
```

`패킷 캡처 시작: iface=lo`가 보이면 정상이다. 그 줄이 없으면 capability가 안 먹은 것이고,
그 상태에서도 서비스는 동작하므로 로그로만 알 수 있다.

## 알려진 한계

- 세션 윈도우가 차기 전(첫 w개 패킷)에는 판정이 없어 Forward된다. 논문 Algorithm 1
  line 6도 같은 성질이다.
- 집행 시점에 쓰는 판정은 그 세션에서 가장 최근에 완성된 윈도우의 것이다. 논문의 "최신
  패킷에 대한 판정"과 엄밀히 같지 않다.
- Relay는 GET·HEAD·OPTIONS에만 건다. POST를 형제 Pod에 재실행하면 리소스가 중복
  생성된다.
- 형제 Pod 비교는 응답한 첫 번째 Pod과 1:1이다(논문 방식). replica 3개 이상에서 다수결로
  비교하는 개선은 아직 반영하지 않았다.
- HTTP 메시지를 파싱했다 재직렬화하므로 chunked 응답이 `Content-Length`로 정규화된다.
  본문은 같지만 바이트 단위로 원본과 동일하지는 않다.
