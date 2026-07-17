# K8s 침입탐지 트래픽 수집 가이드

> 목적: 로컬 디렉토리에서 benign/attack locust 파일을 정리·수정한 뒤, 실제 Kubernetes 클러스터로 옮겨
> 정상/공격 트래픽을 수집(pcap)하기 위한 실행 가이드. (Claude Code 작업 기준 문서)
> 선행연구: scratch_grad.txt, grad.pdf

---

## 0. 현재 상태 요약 (한 눈에)

- **목표**: 선행연구의 KD-CNN + OCSVM 서비스별 침입탐지를 우리 게시판 MSA에서 재현. 지금은 **K8s 환경에서
  정상/공격 트래픽을 수집**하는 단계.
- **모델 방향**: 표현 학습(KD-CNN) + 이상 점수화(OCSVM) 분리 결합. teacher(NT-Xent) → student(1x8부터 2x16까지 다양) 증류 →
  student 임베딩으로 OCSVM(정상만) 생성, 최적의 모델을 **서비스별**(정상 분포가 서비스마다 구별됨 — 교차-서비스 FPR로 확인)로 생성.
- **이번 단계 초점**: 제안서의 **K8s 특화 공격**(정보열거·리소스조작·브루트포스) 트래픽 수집. 웹앱 계층 구조
  공격(auth/post/comment 열거·스캔·삭제 등)은 이전 Docker 단계에서 검증한 트랙으로, 여기서는 요약만 둔다.
- **이미지화/학습 위치**: 학습용 데이터 이미지화·학습·평가는 **로컬(GPU)**. 런타임 실시간 이미지화는 배포 시
  사이드카가 pod에서 수행(둘은 동일 C 파서 `.so` 공유 → train=serve 정합). 지금은 pcap만 수집한다.
- **전제**: 세 공격 시나리오 모두 "공격자가 이미 컨테이너 접근권한을 확보한 상태"를 전제(침해 후 east-west 트래픽 탐지).

---

## 1. 디렉토리 구조 (locust / result 분리, 각 폴더 benign/attack 하위 분리) 설명

```
project-root/
├── k8s/
│   ├── auth-service/comment-service/post-service/frontend/mysql 각각에 포함된 파일들
│   │   └── deployment.yaml  
│   │   └── deployment-with-sidecar.yaml  
│   │   └── model-pvc.yaml  
│   │   └── service.yaml  
│   ├── control-plane
│   │   └── deployment.yaml  
│   │   └── rbac.yaml  
│   │   └── service.yaml  
│   ├── configmap.yaml
│   ├── ingress.yaml
│   ├── namespace.yaml
│   ├── secret.example.yaml
├── msa/
│   ├── backend/
│   │   └── 각각 별도로 배포된 auth-service/comment-service/post-service 디렉토리 등
│   ├── db/
│   │   └── init.sql  
│   ├── frontend/
│   │   └── 관련파일들 (react, nginx기반)
│   ├── docker-compose.yml
├── local_files/ # 쿠버네티스에는 올리지 않고, locust 디렉토리와 result 디렉토리를 생성할 때 참고
│   ├── common/
│   │   └── harness.py                     # benign locust 공통 베이스(pacing·헤더). ★ benign이 import
│   ├── benign/
│   │   ├── auth_locustfile.py
│   │   ├── post_locustfile.py
│   │   ├── comment_locustfile.py
│   │   └── benign_frontend_locustfile.py 
│   ├── attack/
│   │   ├── k8s_enum_locustfile.py          # 시나리오1: 정보열거 (T1613)
│   │   ├── k8s_manipulate_locustfile.py    # 시나리오2: 리소스조작 (T1609, dryRun)
│   │   └──k8s_bruteforce_locustfile.py    # 시나리오3: 스캐닝+브루트포스 (T1595/T1110)
│   └── study_kubernetes_attack		# 참고 : 논문 리포지토리에서 공개한 pcap파일들이 들어있는 폴더
├── locust/ <새로 생성될 예정, 이후 쿠버네티스 서버에도 올림>
│   ├── common/
│   │   └── harness.py                     # benign locust 공통 베이스(pacing·헤더). ★ benign이 import
│   ├── benign/
│   │   ├── auth_locustfile.py
│   │   ├── post_locustfile.py
│   │   ├── comment_locustfile.py
│   │   └── benign_frontend_locustfile.py # frontend_locustfile.py로 수정 필요
│   │   ├── db_locustfile.py # Question : 새로 생성해야하는지?
│   └── attack/
│       ├── k8s_enum_locustfile.py
│       ├── k8s_manipulate_locustfile.py
│       └── k8s_bruteforce_locustfile.py
├── result/ <쿠버네티스 서버에 폴더 생성 예정>
│   ├── benign/                            # benign_<svc>.pcap 저장, 학습에 사용
│   ├── attack/                             # attack_<enum|manipulate|brute>.pcap 저장, CNN 모델 학습에 사용하진 않지만 지도학습으로 상한을 결정할 때 사용됨
│   └── test/					# 학습이 아니라, 모델 성능을 테스트할 트래픽 데이터 저장소
│       ├── benign/
│       └── attack/
├── benign_packet.png			# 논문에서 공개한 packet size - 수집 규모를 이정도는 아니지만 비슷하게 구현, 우리 서비스(backend끼리는 동질적인 부분 존재, frontend와 db는 별개)에 맞게 트래픽 수집 정책을 짜야함
├── attack_packet.png		
```

> **import 규칙 주의**: benign locust는 `from common.harness import BaseUser`를 하고 `sys.path`에
> `dirname(dirname(__file__))`(= `locust/`)를 추가한다. 따라서 **`common/`은 반드시 `locust/common/`에 위치**해야
> 코드 수정 없이 import가 된다. (K8s 공격 3종은 harness를 쓰지 않는 standalone `HttpUser`라 common 불필요.)

## 2. 정상(benign) 시나리오 (요약)

모든 benign locust는 `common/harness.py`를 상속(혼합 pacing·공통 헤더). 실제 게시판 사용을 재현하고, 정상에도
자연스러운 4xx(오타 로그인·없는 자원)를 소량 섞어 "4xx=공격" 지름길을 차단한다.

| 서비스 | 정상 태스크(핵심) | 자연 4xx |
|---|---|---|
| auth | 로그인, 가입, 로그아웃, 유효 토큰으로 internal validate | 오타 로그인 → 401 |
| post | 목록/상세 조회 위주, 본인 글만 작성/수정/삭제 | 없는 id 조회 → 404 |
| comment | 댓글 조회 위주, 본인 댓글만 조작; post 호출로 서비스 간 흐름 | 없는 글 댓글 조회 → 404 |
| frontend | index/자산 다발, SPA 라우트, favicon | 없는 자산 → 404 |
| mysql | (locust 없음) 백엔드 3종 구동 시 유발되는 JPA 파라미터 쿼리 부산물 | — |

---

## 3. K8s 특화 공격 시나리오 (상세)

세 시나리오 모두 침해된 pod에서 실행하는 것을 전제로, pod에 마운트된 **서비스어카운트 토큰**으로 K8s API 서버와
내부 서비스를 HTTP로 때린다. **K8s API 서버가 REST/HTTP라 셋 다 locust로 표현된다**(별도 익스플로잇 도구 불필요).
컨테이너 탈출·tmate 같은 비-HTTP 공격만 제외되며, 이는 제안서 범위 밖이다.

| 파일 | 시나리오 | MITRE | 동작 | 안전장치 |
|---|---|---|---|---|
| `k8s_enum_locustfile.py` | 클러스터 정보 열거 | T1589, T1528, T1613 | API 서버에 pods/services/secrets/deployments/networkpolicies/nodes 조회, SelfSubjectRulesReview로 권한 정찰 | read-only GET |
| `k8s_manipulate_locustfile.py` | 리소스 조작 | T1609 | 네트워크정책 생성, 특권 pod 배포, 디플로이 스케일 변경 **시도** | 전부 `?dryRun=All` → 실제 변경 없음 |
| `k8s_bruteforce_locustfile.py` | 스캐닝 + 브루트포스 | T1595, T1110 | 내부 서비스 민감 경로 스캔(404 버스트) + auth 로그인 사전 브루트포스(실패 로그인) | 파괴 동작 없음 |

- **라벨**: 서버가 막아 403/401/404가 나도 시도 자체가 악성(의도 기준). 캡처 시간창 전체를 공격으로 라벨.
- **RBAC**: `deepmesh` 기본 SA에 권한이 없으면 enum/manipulate가 403. 그래도 트래픽은 유효. 논문의 "과도한 권한"
  상황을 재현하려면 해당 SA에 read/create 롤을 바인딩하면 실제 열거·조작이 성공한다.

---

## 4. Claude Code 작업: 파일 배치 + 수정 포인트

### 4-0. 쿠버네티스 환경에서 바로 올리면 트래픽 수집이 가능하도록, 현재 코드에서 잘못된 부분이 없는지 검증
k8s 디렉토리에도 잘못된 내용이 없는지 검증을 먼저 수행한다.
local_files 안의 코드들을 수정하여 로컬 디렉토리를 §1 디렉토리 구조 와 같이 변경한다.

### 4-1. benign locust 수정 (호스트만 — 파일 로직은 대개 그대로) : 규모 변경, 필요하다면 시나리오 구체화, /result/test/benign에 저장될 트래픽들을 적절한 규모로 분리
benign 파일들은 host가 **환경변수**라 파일 자체는 수정 없이 env로 넘기면 된다. 다만 K8s 포트/주소가 Docker와
다르므로 실행 시 아래 값을 지정한다. (아래 §5 클러스터 정보 참조)

| 서비스 | 필요한 env |
|---|---|
| auth | `HOST` |
| post | `HOST`, `AUTH_HOST` |
| comment | `HOST`, `AUTH_HOST`, `POST_HOST` |
| frontend | `HOST` |

### 4-2. K8s 공격 locust 수정 : 규모 변경, 필요하다면 시나리오 구체화, /result/test/attack에 저장될 트래픽들을 적절한 규모로 분리
- `k8s_enum`, `k8s_manipulate`: `HOST` 기본값 `https://kubernetes.default.svc`(인클러스터 API). **수정 불필요**
  (토큰·CA는 pod 마운트 경로에서 자동 로드). `TARGET_NS` 기본 `deepmesh`.
- `k8s_bruteforce`: `AUTH_HOST` 기본 `http://auth-service.deepmesh.svc:8080`. 필요 시 `VICTIM_USER` 지정.

---

## 5. K8s 클러스터에서 트래픽 수집 절차

### 5-1. 클러스터 정보 (namespace: `deepmesh`) - 실제 수집 전에 정확한 값을 질문할 것

| 서비스 | 타입 | ClusterIP:포트 | pod(예시) / 노드 |
|---|---|---|---|
| auth-service | ClusterIP | 10.109.47.68:8080 | worker1(10.244.194.87), worker3 |
| post-service | ClusterIP | 10.100.234.122:8080 | worker1(10.244.194.89), worker2 |
| comment-service | ClusterIP | 10.102.52.160:8080 | worker1(10.244.194.90), worker2 |
| frontend-service | NodePort | 10.108.184.241:80 (30080) | worker3(10.244.100.215), worker2 |
| mysql-service | Headless(StatefulSet) | :3306 | mysql-0 / worker1(10.244.194.79) |
| (K8s API) | ClusterIP | 10.96.0.1:443 | — |

> 실행 전 `kubectl get svc,pods -n deepmesh -o wide`로 최신 IP/노드 재확인.

### 5-2. 공통 준비
```bash
# 캡처 저장 폴더(노드에서 호스트로 동기화되는 위치)
mkdir -p /vagrant/result/benign /vagrant/result/attack
# locust 실행 환경(노드 또는 attacker pod)
pip3 install locust requests
```

### 5-3. 정상(benign) 수집 — 서비스별
서비스 pod 하나에 트래픽을 몰기 위해 **pod IP로 고정**하고, 그 pod가 뜬 노드에서 netns eth0을 캡처한다.
예: post-service (worker1, pod IP 10.244.194.89)

```bash
# (터미널 A, worker1) 대상 pod netns eth0 캡처
vagrant ssh k8s-worker1
CID=$(sudo crictl ps --name post-service -q | head -1)
PID=$(sudo crictl inspect --output go-template --template '{{.info.pid}}' "$CID")
sudo timeout 300 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/benign/benign_post.pcap tcp &

# (터미널 B, 같은 노드) 부하: 그 pod IP로 고정
cd /vagrant/locust
export AUTH_HOST=http://10.244.194.87:8080
locust -f benign/post_locustfile.py --host http://10.244.194.89:8080 --headless -u 20 -r 4 -t 300s
```
- auth/comment/frontend도 동일 방식(각 pod IP + 필요한 env). comment는 `AUTH_HOST`+`POST_HOST`도 지정.
- **mysql**: 별도 부하 없이 위 백엔드 locust를 돌리는 동안 `mysql-0`(worker1) netns eth0을 함께 캡처 →
  `/vagrant/result/benign/benign_mysql.pcap`.

### 5-4. 공격(attack) 수집 — 침해 pod에서
enum/manipulate는 pod 안에서만 토큰·API 접근이 되므로 **attacker pod**를 띄운다.

```bash
# 공격 locust를 configmap으로
kubectl -n deepmesh create configmap k8s-attacks --from-file=locust/attack/

# attacker pod (locust 이미지 + 기본 SA 토큰 자동 마운트)
kubectl -n deepmesh run attacker --image=locustio/locust:2.29.1 --restart=Never \
  --overrides='{"spec":{"containers":[{"name":"attacker","image":"locustio/locust:2.29.1","command":["sleep","infinity"],"volumeMounts":[{"name":"f","mountPath":"/mnt"}]}],"volumes":[{"name":"f","configMap":{"name":"k8s-attacks"}}]}}'

# (터미널 A) attacker pod의 egress 캡처 = 공격 트래픽 (논문 pcap과 같은 방향)
kubectl -n deepmesh get pod attacker -o wide          # NODE 확인
vagrant ssh k8s-worker<N>
CID=$(sudo crictl ps --name attacker -q | head -1)
PID=$(sudo crictl inspect --output go-template --template '{{.info.pid}}' "$CID")
sudo nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/attack/attack_enum.pcap tcp &

# (터미널 B) 시나리오별 실행 — 캡처 파일명을 시나리오마다 바꿔가며
kubectl -n deepmesh exec -it attacker -- locust -f /mnt/k8s_enum_locustfile.py       --headless -u 5  -r 1 -t 120s
kubectl -n deepmesh exec -it attacker -- locust -f /mnt/k8s_manipulate_locustfile.py  --headless -u 3  -r 1 -t 120s
kubectl -n deepmesh exec -it attacker -- locust -f /mnt/k8s_bruteforce_locustfile.py  --headless -u 10 -r 5 -t 120s
```
- 시나리오마다 `attack_enum.pcap` / `attack_manipulate.pcap` / `attack_brute.pcap`로 따로 저장.
- 정리: `kubectl -n deepmesh delete pod attacker; kubectl -n deepmesh delete configmap k8s-attacks`.

### 5-5. pcap → 로컬 → 학습
- 노드 `/vagrant/result/*`는 Vagrant 동기화로 호스트의 `k8s-cluster/result/`에 함께 저장된다.
- 호스트에서 로컬로 내려받아(scp 등), 로컬 전처리 파이프라인으로 이미지화 → 지도학습 분리 상한 확인 →
  지식증류(teacher → student → OCSVM) 학습·확정 → held-out 평가.

---

## 6. 설계 참고 노트 (수집 전 반드시 인지)

- **benign 기준선(중요)**: 위 benign은 각 **서비스 pod의 ingress 정상**(사용자 → 서비스)이다. 반면 K8s API
  공격(enum/manipulate)은 **attacker pod의 egress**(pod → API 서버)다. 즉 방향·기준선이 다르다. 앱 pod는 평소
  K8s API를 거의 호출하지 않으므로 "정상 API-egress" 자체가 희박하다 → K8s API 공격의 정확한 매칭 기준선 확보는
  별도 설계가 필요하다(예: 정상적으로 API를 쓰는 컴포넌트의 egress를 benign으로 수집하거나, "앱 pod의 API 호출 =
  이탈"로 규정). **이번 수집에서는 웹앱 benign만 확보하고 이 한계를 명시**한다.
- **cross-environment skew**: 선행연구가 공개한 attack pcap은 다른 클러스터에서 나온 것이라, 우리 클러스터 benign과
  섞으면 TTL/MSS/window 차이로 오분리가 생긴다. 검증은 **정상·공격을 모두 우리 클러스터에서** 수집해 맞춘다.
- **캡처 지점 정합**: 반드시 pod netns eth0(Ethernet 프레임)에서 캡처(-i any/SLL 금지) — C 파서 오프셋과 정합.
- **이미지화 이원화**: 학습용 데이터 이미지화는 로컬(오프라인), 실시간 탐지 이미지화는 배포 시 사이드카(pod). 둘은
  동일 `.so`를 공유한다. 현재 pod는 1/1(사이드카 미배포)이므로 지금은 pcap 수집만 한다.

---

## 7. 체크리스트 (실행 순서)

1. [ ] `locust/`(common·benign·attack), `result/`(benign·attack) 구조 정리.
2. [ ] `kubectl get svc,pods -n deepmesh -o wide`로 IP/노드 최신화.
3. [ ] benign 5종 수집 → `result/benign/benign_<svc>.pcap`.
4. [ ] attacker pod 배포 → enum/manipulate/bruteforce 수집 → `result/attack/attack_<scn>.pcap`.
5. [ ] attacker pod·configmap 정리.
6. [ ] pcap 로컬 이전 → 이미지화 → 지도학습 분리 상한 → 지식증류 학습 → held-out 평가.
