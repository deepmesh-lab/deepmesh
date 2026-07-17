# K8s 트래픽 수집 실행 계획 (traffic_collect.md)

> `K8s_트래픽_수집_가이드.md`를 근거로 현재 디렉토리 상태를 검증하고, 실제 쿠버네티스 클러스터
> (`namespace: deepmesh`)에서 benign/attack pcap을 수집하기 위한 실행 계획을 정리한다.
> 작성 기준일: 2026-07-11 / 대상 브랜치: `feat/traffic`

---

## 0. 결론 요약 (TL;DR)

- **locust 코드(`local_files/`)와 k8s 매니페스트(`k8s/`)는 대체로 정합**하며, 그대로 클러스터에 올려도
  트래픽 수집이 가능한 상태다. 코드 로직 수정은 거의 불필요하고 **host/포트는 전부 환경변수로 주입** 가능하다.
- 실제 실행 전에 필요한 작업은 **① 디렉토리 재구성(`local_files/` → `locust/`, `result/` 생성)**,
  **② frontend benign 파일명 정리**, **③ 클러스터 최신 IP/노드 재확인**, **④ 공격 SA 권한(RBAC) 정책 결정** 4가지다.
- 코드를 고쳐야 하는 필수 항목은 **없다.** 아래 §3의 재구성만 하면 §5 절차대로 수집 진입 가능.

---

## 배경: 논문(grad.pdf)에서 수집·전처리에 직결되는 사실

> 논문: *Lightweight Service Mesh for Intrusion Detection using KD-CNN in Cloud-Native Environments* (CCSW '25, PNU).
> 우리 프로젝트는 **구체적 서비스만 다를 뿐**(게시판 MSA: auth/post/comment/frontend/mysql) 방향성은 동일하다:
> **정상/공격 트래픽 수집 → 이미지화 → KD-CNN+OCSVM 학습 → 학생 모델을 사이드카 프록시에 붙여 실시간 평가.**
> 목표 정확도·예측시간도 논문 수치와 동일하게 파인튜닝할 예정이므로, 아래 스펙을 **수집 단계에서부터** 맞춰야 한다.

### 아키텍처 매핑 (논문 → 우리 매니페스트)
- **Control Plane** = `k8s/control-plane/` : Pod Info Provider(ReplicaSet pod IP 배포) + Request Verifier(요청 재현 검증).
  RBAC의 `pods get/list/watch`가 곧 Pod Info Provider 권한 — 우리 매니페스트와 정합 ✅.
- **Data Plane** = 사이드카 프록시(`deployment-with-sidecar.yaml`의 `reverse-proxy` 컨테이너, port 9011).
  `iptables-init` initContainer(NET_ADMIN)가 pod의 ingress+egress를 프록시로 리다이렉트 → 논문의 iptables 방식과 정합 ✅.
  프록시는 `MODEL_DIR=/app/model`(PVC `*-model-pvc`)에서 학생 모델을 로드 → **로컬 학습 산출물(.so 파서 + 모델)을 이 PVC에 넣는 구조**.
- **두 단계 탐지(Relay/Drop/Forward)** 는 **ReplicaSet 복제본 일관성**에 의존(같은 요청/응답이 다른 pod에도 있는지 대조).
  → 각 서비스 **replicas ≥ 2 필수**. auth/post/comment/frontend 전부 `replicas: 2` ✅ (control-plane만 1, 정상).

### 클러스터 물리 배치 (실측 — 2026-07-11 `kubectl get pods,svc -n deepmesh -o wide` 확인)
> ✅ 아래는 **라이브 확인값**이다(설계도 `structure_predict.png`와 달랐음 — 특히 **mysql-0은 worker1**, 설계도는 worker3로 그렸음).
> **무엇이 언제 바뀌나**: 노드명(`k8s-worker1~3`)·ClusterIP·NodePort(30080)는 **고정**(재접속·재부팅해도 유지). 반면 **Pod의 노드/Pod IP는 재접속으로는 안 바뀌고, Pod가 재생성·재스케줄될 때만** 바뀐다(rollout·`delete pod`·노드 장애 등). 매니페스트에 `nodeSelector`/`affinity`가 없어 재스케줄 시 다른 노드로 갈 수 있으므로 → **매 수집 직전 `kubectl get pods -o wide`로 Pod 노드/IP만 재확인**(그사이 재스케줄됐을 수 있어서).
> ⚠️ 아래 Pod IP·ClusterIP는 **클러스터 내부 주소**다. 노트북에서 직접 접속 불가(프론트만 NodePort `노드IP:30080`, 백엔드/DB는 `kubectl port-forward`/`exec` 또는 인클러스터).
- **노드**: master 3 vCPU / 8 GB, worker1~3 각 5 vCPU / 16 GB (alloc 4,500m / 14,746Mi).
- **제어 데몬(설계도)**: `structure_predict.png`는 Control Plane을 master의 `masterNode.py`로 그렸으나, **실측상 control-plane은 `deepmesh` 네임스페이스 Deployment pod(worker1, 10.244.194.82)** — 우리 매니페스트와 일치. 설계도의 master-node 데몬 묘사는 설계 단계 표현.
- **pod 배치(실측)** — 캡처는 대상 replica가 뜬 worker로 SSH:

| 서비스 | replica → 노드 (Pod IP) | ClusterIP | 캡처 위치 |
|---|---|---|---|
| frontend (NodePort 30080) | worker3 (10.244.100.215) / worker2 (10.244.126.26) | 10.108.184.241:80 | 대상 replica 노드 netns eth0 |
| auth-service | **worker1 (10.244.194.87)** / worker3 (10.244.100.213) | 10.109.47.68:8080 | 〃 |
| post-service | **worker1 (10.244.194.89)** / worker2 (10.244.126.25) | 10.100.234.122:8080 | 〃 |
| comment-service | **worker1 (10.244.194.90)** / worker2 (10.244.126.24) | 10.102.52.160:8080 | 〃 |
| mysql-0 (StatefulSet) | **worker1 (10.244.194.79)** | Headless(None):3306 | worker1 netns eth0 |
| control-plane | worker1 (10.244.194.82) | 10.106.18.227:8080 | 수집 대상 아님 |
| Attacker Pod (실험 시) | nodeSelector로 지정(예: worker3) | — | 지정 노드 egress |

- 💡 **worker1에 auth·post·comment 각 1개 replica + mysql-0 + control-plane이 모두 모여 있음** → 백엔드 3종 + mysql benign 캡처를 **worker1 한 노드에서** 처리 가능(편의). frontend는 worker2/worker3.
- **리소스 스펙(설계도 기준)**: 사이드카 **proxy = req 250m / limit 1,000m / 512Mi** ← 논문의 "단일 vCPU"가 곧 limit 1 core. backend main 250m/512Mi · frontend main 100m/64Mi · mysql main 250m/512Mi. Attacker req 200m/256Mi·limit 500m(지정 노드에 가산).
- ⚠️ **proxy CPU limit(1,000m)은 설계도엔 있으나 `deployment-with-sidecar.yaml` 매니페스트엔 미반영** → 지연/처리량 재현하려면 매니페스트에 추가 필요(§2-3).

### 전처리 스펙 = 캡처가 반드시 만족해야 하는 조건
- 패킷 1개 → **1479B 벡터 = 19B 헤더(프로토콜 필드) + 1460B 페이로드**. **IP·포트 등 가변 필드는 제외**(train=serve 정합용).
- 세션 = 5-tuple(src/dst IP·port) 그룹핑, **슬라이딩 윈도우 w=5** 패킷을 시간순 stack → **5×1479 grayscale 이미지**.
  (단일 패킷 39×39 이미지는 benign/attack 분리 성능이 낮음 → **5-패킷 시퀀스가 표준**.)
- 따라서 캡처 요건:
  1. **`-s 0`** — 페이로드 1460B까지 온전히 저장(스냅 길이 절단 금지).
  2. **pod netns의 eth0** — Ethernet 프레임 기준. `-i any`/SLL 캡처 **금지**(C 파서 바이트 오프셋과 어긋남).
  3. **요청·응답 양방향** 모두 캡처(세션 단위 분석이므로).
  4. **세션당 ≥ 5 패킷** 이라야 이미지 1장 생성 → 짧은 세션(<5패킷)은 버려짐. locust가 다중 요청 세션을 만들도록 이미 설계됨(frontend `load_page` 등).
- 기존 §5 캡처 명령(`tcpdump -i eth0 -s 0 ... tcp`)은 위 4개 요건과 **모두 정합** ✅.
- 학습 이미지화(로컬 GPU, 오프라인)와 실시간 이미지화(사이드카)는 **동일 C `.so`** 를 공유해야 정합 — 로컬 파이프라인과 프록시가 같은 파서를 쓰도록 관리.

### 파인튜닝 목표 수치 (동일 재현 대상 = 수집 데이터의 성공 기준)
> 수집한 데이터셋이 아래 수치를 낼 만큼 **충분·정합**해야 한다. 미달 시 규모/세션 길이/서비스 분리를 재점검.

| 항목 | 논문 값 (Kubernetes-specific) | 비고 |
|---|---|---|
| CNN+OCSVM 베이스라인 | Precision 91.5% / Recall 94.3% / ROC-AUC 98.3% | teacher 계열, 상한 |
| **배포용 학생 CNN-2x8** | Precision 87.4% / Recall 89.9% / ROC-AUC 95.7% | 사이드카 채택 모델 (5.69K params, 0.579M FLOPs) |
| 대안 학생 CNN-2x16 | Precision 95.5% / Recall 87.0% / ROC-AUC 96.6% | 13.87K params |
| 추론 지연(단일 vCPU, 이미지 1장) | teacher 3.612 ms → CNN-2x8 0.518 ms → CNN-1x8 0.406 ms(-88.74%) | std < 0.2 ms |
| **E2E 오버헤드(탐지 ON, CNN-2x8, w=5)** | **지연 ≤ 14 ms(13.23), 처리량 ≥ 600 req/s(0.60k)** | 전처리 ~0.16 ms/packet |

> ⚠️ **지연·처리량 재현 조건**: 논문은 프록시를 **단일 vCPU**로 제한하고 측정했다. 현재 `reverse-proxy` 사이드카에는
> `resources.limits.cpu`가 **설정되어 있지 않다** → 지연/처리량 수치를 논문과 맞추려면 사이드카에 `cpu: "1"` 제한을 추가해야 한다.
> (수집 자체에는 영향 없음. 평가·파인튜닝 단계 재현성 이슈로 §6에 질문으로 둔다.)

---

## 1. 현재 디렉토리 상태 (실측)

```
C:\k8s-msa\
├── k8s/                         # ✅ 배포 매니페스트 (검증 완료)
│   ├── auth-service/            # deployment, deployment-with-sidecar, model-pvc, service
│   ├── post-service/            # (동일 4종)
│   ├── comment-service/         # (동일 4종)
│   ├── frontend/                # deployment, service
│   ├── mysql/                   # pvc, service, statefulset
│   ├── control-plane/           # deployment, rbac, service
│   ├── configmap.yaml / ingress.yaml / namespace.yaml / secret.example.yaml
├── local_files/                 # ⚠️ 아직 locust/로 재구성 필요
│   ├── common/harness.py
│   ├── benign/  auth / post / comment / benign_frontend  (4개)
│   ├── attack/  k8s_enum / k8s_manipulate / k8s_bruteforce (3개)
│   └── study_kubernetes_attack/ # 논문 공개 pcap 5종 (참고용, 업로드 X)
├── locust/                      # ❌ 아직 없음 — 생성 대상
├── result/                      # ❌ 아직 없음 — 생성 대상
├── benign_packet.png / attack_packet.png   # 논문 패킷 규모 참고 이미지
└── K8s_트래픽_수집_가이드.md
```

가이드 §1 구조와 비교한 차이:
- `locust/`, `result/` 디렉토리가 **아직 생성되지 않음** (수집 전 반드시 생성).
- benign frontend 파일이 `benign_frontend_locustfile.py` → 가이드는 `frontend_locustfile.py`로 정리 권고.
- `db_locustfile.py`는 **생성 불필요** (§2 표: mysql은 locust 없음. 백엔드 locust 구동 중 부산물로만 캡처).

---

## 2. 검증 결과 (§4-0: 잘못된 부분 점검)

### 2-1. k8s 매니페스트 — 가이드 §5-1 클러스터 정보와 정합 ✅

| 서비스 | 매니페스트 실측 | 가이드 §5-1 | 판정 |
|---|---|---|---|
| auth-service | ClusterIP, port 8080 | 10.109.47.68:8080 | ✅ 포트 일치 |
| post-service | ClusterIP, port 8080 | 10.100.234.122:8080 | ✅ |
| comment-service | ClusterIP, port 8080 | 10.102.52.160:8080 | ✅ |
| frontend-service | NodePort 30080, port 80 | 10.108.184.241:80 (30080) | ✅ |
| mysql-service | Headless(`clusterIP: None`), 3306 | Headless, mysql-0 | ✅ |
| K8s API | (클러스터 기본) | 10.96.0.1:443 | ✅ |

- ConfigMap의 서비스 DNS(`http://auth-service:8080` 등)와 서비스명이 일치. 서비스 간 흐름 정상.
- **IP는 클러스터 재배포 시 변동됨** → 수집 직전 `kubectl get svc,pods -n deepmesh -o wide`로 반드시 재확인.

### 2-2. locust 코드 — 로직 이상 없음 ✅

- **benign 4종**: 전부 `common.harness.BaseUser` 상속, `sys.path`에 상위(`locust/`) 추가 →
  `common/`이 `locust/common/`에 있으면 코드 수정 없이 import됨. host는 전부 `os.environ["HOST"]` 오버라이드 가능.
  - `auth`: HOST만 필요 / `post`: HOST + AUTH_HOST / `comment`: HOST + AUTH_HOST + POST_HOST / `frontend`: HOST.
  - 자연 4xx 태스크가 각 파일에 포함되어 "4xx=공격" 지름길 차단 설계 반영됨.
- **attack 3종**: standalone `HttpUser`(harness 미사용) — `common/` 의존 없음, 그대로 configmap 업로드 가능.
  - `k8s_enum`, `k8s_manipulate`: HOST 기본 `https://kubernetes.default.svc`, 토큰·CA는 pod 마운트 자동 로드. **수정 불필요**.
  - `k8s_bruteforce`: AUTH_HOST 기본 `http://auth-service.deepmesh.svc:8080` (유효 in-cluster DNS). VICTIM_USER 기본 `admin`.

### 2-3. 유의사항 (버그는 아니나 수집 결과에 영향)

1. **frontend benign 기본 host가 `:3000`** (Docker 기준). K8s frontend는 port 80/NodePort 30080.
   → 실행 시 `HOST` env로 pod IP:80을 반드시 지정하면 됨 (파일 수정 불필요).
2. **enum/manipulate는 기본 SA(`default`) 권한이 없어 전부 403 예상.**
   현재 RBAC(`control-plane/rbac.yaml`)은 `control-plane-sa`에만 `pods get/list/watch`를 부여.
   attacker pod가 `default` SA면 열거·조작이 **모두 403** → 트래픽은 유효하나 "성공한 열거"는 못 만듦.
   논문의 "과도한 권한(성공하는 열거/조작)"을 재현하려면 **attacker SA에 read/create 롤 바인딩이 필요**(§5-4 옵션, 아래 §4에서 결정).
3. `study_kubernetes_attack/`의 `kubernetes_escape.pcap`, `remote_access.pcap`은 **제안서 범위 밖**(컨테이너 탈출/비-HTTP).
   수집 대상은 enum/manipulate/bruteforce 3종뿐. escape/remote는 참고만.
4. **사이드카 CPU limit 누락(설계도와 불일치)**: 설계도(structure_predict.png)는 proxy를 **req 250m / limit 1,000m / 512Mi**로 규정하지만,
   `deployment-with-sidecar.yaml`의 `reverse-proxy`엔 `resources` 블록이 아예 없음. 수집엔 무관하나, 논문/설계도의 지연·처리량(≤14ms, ≥600req/s)을
   재현하려면 매니페스트에 `resources: {requests: {cpu: 250m, memory: 512Mi}, limits: {cpu: "1000m", memory: 512Mi}}` 추가 필요(배경 §·§6).
5. **replicas ≥ 2 확인**: 두 단계 탐지가 복제본 일관성에 의존 → 수집 시점에도 각 백엔드/프론트가 2 replica로 떠 있어야 함(현재 매니페스트 OK).
6. **attacker pod 이미지 불일치**: 설계도는 `kalilinux/kali-rolling`(nmap·hydra·curl)로 그림. 현재 계획은 `locustio/locust` + 우리 locust 공격 3종.
   둘 다 같은 MITRE 카테고리를 생성 → 어느 도구로 수집할지 §6에서 확정(§5-2에 두 방식 병기).

### 2-4. 매니페스트 전체 정합성 (정적 검증 — 런타임 아님)

`k8s/` 전 파일 교차검증 결과 아래는 **모두 정합** ✅:
- ConfigMap 키(`AUTH_DB_URL`/`POSTS_DB_URL`/`COMMENTS_DB_URL`/`*_SERVICE_URL`/`CONTROL_PLANE_URL`) ↔ 각 Deployment 참조 일치.
- Secret 키(`MYSQL_ROOT_PASSWORD`/`JWT_SECRET`) ↔ auth/post/comment/mysql 참조 일치.
- 모든 Service selector ↔ Pod label 일치, 포트(backend 8080·frontend 80·mysql 3306·control-plane 8080) 일치.
- mysql StatefulSet(`serviceName: mysql-service`, PVC `mysql-pvc`, headless) 정합. control-plane SA/ClusterRole/binding/`serviceAccountName` 정합.
- Ingress 경로(`/`, `/api/auth`, `/api/posts`, `/api/comments`) → 각 서비스 매핑 정합. `<svc>-model-pvc` ↔ 사이드카 volume 일치.

배포 전 반드시 챙길 전제·주의:
1. **Secret 생성 필수**: `deepmesh-secret`는 예시만 존재(gitignore). `kubectl create secret generic deepmesh-secret ...` 안 하면 auth/post/comment/mysql이 기동 못 함.
2. ⚠️ **Deployment 2종 동시 적용 금지**: 각 서비스의 `deployment.yaml`과 `deployment-with-sidecar.yaml`은 **같은 이름의 Deployment**를 정의 → 디렉토리째 `kubectl apply -f k8s/auth-service/` 하면 서로 덮어써 비결정적. **수집 단계엔 사이드카 없는 `deployment.yaml`만**, 서빙 단계에만 `deployment-with-sidecar.yaml`을 골라 적용.
3. **frontend 사이드카 매니페스트 없음**: `k8s/frontend/`엔 `deployment-with-sidecar.yaml`이 없음 → 서빙 단계에서 프론트에도 프록시가 필요하면 추가 작성 필요(수집엔 무관).
4. **런타임 전제**: `local-path` storageClass, nginx ingress controller 설치, 이미지 pull 가능.
5. mysql `MYSQL_DATABASE=auth_db`만 초기 생성 — `posts_db`/`comments_db`는 JDBC `createDatabaseIfNotExist=true`로 자동 생성(정합).

> ⚠️ **"서버가 제대로 기능 중인가"는 정적 매니페스트만으로 판정 불가.** pod Running/Ready·이미지 pull·PVC 바인딩·secret 존재 여부는
> 런타임 확인(`kubectl get pods -n deepmesh -o wide`, §5-0)이 유일한 방법이다. 정적 검증은 "매니페스트가 올바르며 배포 가능"까지만 보장.

---

## 3. 디렉토리 재구성 계획 (수집 전 로컬 작업)

가이드 §1 구조로 맞춘다. `local_files/`는 그대로 두고 `locust/`를 **새로 구성**(원본 보존).

```
locust/                                  # 새로 생성, 이후 클러스터에 업로드
├── common/harness.py                    # local_files/common/harness.py 복사
├── benign/
│   ├── auth_locustfile.py               # 복사
│   ├── post_locustfile.py               # 복사
│   ├── comment_locustfile.py            # 복사
│   └── frontend_locustfile.py           # benign_frontend_locustfile.py → 이 이름으로 복사
└── attack/
    ├── k8s_enum_locustfile.py           # 복사
    ├── k8s_manipulate_locustfile.py     # 복사
    └── k8s_bruteforce_locustfile.py     # 복사

result/                                  # 빈 디렉토리 구조만 생성 (pcap 저장소)
├── benign/                              # benign_<svc>.pcap — OCSVM/KD-CNN 학습셋(benign만 학습)
└── test/
    ├── benign/                          # 학습에 안 쓴 held-out benign — 평가(FPR)
    └── attack/                          # attack_<enum|manipulate|brute>.pcap — 분포분리 확인·지도상한·OCSVM 평가
```
> **왜 `result/attack/`(비-test)는 없나**: 배포 모델은 benign만으로 비지도 학습하고 **attack은 학습에 안 쓴다**. attack의 용도(분포 분리 확인/이미지화, 지도학습 상한, OCSVM 평가)는 전부 평가·분석이므로 **`result/test/attack/` 하나면 충분**. (benign은 학습 대상이라 학습셋+held-out 둘 다 필요 → 비대칭이 정상.)

작업 항목:
- [ ] `locust/common`, `locust/benign`, `locust/attack` 생성 후 위 매핑대로 파일 복사.
- [ ] **복사 시 `modify_plan.md`의 수집기 수정 반영**: ① auth benign에서 `/internal/auth/validate` 태스크 제거 + `signup`의 `email` 제거, ② `k8s_bruteforce`에 `SHARED_HEADERS`+공유 pacing 정렬(confound 제거), ③ frontend는 정적/SPA 유지, ④ attack은 **enum/manipulate/bruteforce 3종**(앱 계층 횡적이동 공격은 논문 범위 밖이라 미포함).
- [ ] `benign_frontend_locustfile.py` → `frontend_locustfile.py`로 이름 변경하여 복사 (import·클래스명은 그대로 동작).
- [ ] `db_locustfile.py`는 **생성하지 않음** (mysql은 백엔드 부하의 부산물로 수동 캡처).
- [ ] `result/{benign,test/benign,test/attack}` 빈 디렉토리 생성 (attack은 평가 전용 → `test/attack`만).
- [ ] `study_kubernetes_attack/`, `*.png`는 로컬 참고용 — 클러스터 업로드 대상에서 제외.

> import 무결성: benign 파일은 `dirname(dirname(__file__))`를 sys.path에 추가하므로
> `-f locust/benign/xxx.py` 실행 시 `locust/`가 경로에 잡혀 `from common.harness import ...`가 성립.
> → `common/`은 반드시 `locust/common/`에 위치해야 함(위 구조 준수).

---

## 4. 수집 규모 및 정책 결정 (§4-1, §4-2)

논문 Table 1/2의 **패킷 수**를 목표로 삼는다(파인튜닝 수치 재현이 목적이므로 시간이 아니라 **패킷 수 기준**으로 수집·모니터링).
`-t`(시간)는 목표 패킷 수에 도달할 때까지의 러닝타임일 뿐이며, 실제로는 `tcpdump` 진행 중 패킷 카운트를 보며 정지한다.
학습용과 test용은 **다른 시간창 + 다른 시드**로 별도 run(데이터 누수 방지).

### 4-1. benign (학습용 → `result/benign/`, 테스트용 → `result/test/benign/`)

| 서비스 | 논문 대응 워크로드 | 목표 패킷수(≈논문 Table 1) | 학습 러닝(초기값) | 테스트 러닝 | 필요 env |
|---|---|---|---|---|---|
| frontend | Web(React+Nginx) 175,201 | **~175K** | `-u 20 -r 4 -t 600s` | `-u 10 -r 2 -t 180s` | HOST(:80) |
| auth | FastAPI backend 152,398 | **~150K** | `-u 20 -r 4 -t 600s` | `-u 10 -r 2 -t 180s` | HOST |
| post | (backend 계열) | **~150K** | `-u 20 -r 4 -t 600s` | `-u 10 -r 2 -t 180s` | HOST, AUTH_HOST |
| comment | (backend 계열) | **~150K** | `-u 20 -r 4 -t 600s` | `-u 10 -r 2 -t 180s` | HOST, AUTH_HOST, POST_HOST |
| mysql | PostgreSQL DB 54,878 | **~55K** | (백엔드 부하 중 동시 캡처) | (동일) | — |

- 목표 패킷수는 **논문과 동질적 규모 재현**을 위한 가이드값. 러닝타임은 도달 여부를 보며 가감(위 `-t`는 초기값).
- 세션당 ≥5 패킷이라야 이미지가 생성되므로, 단발 요청보다 **연속 요청(세션 지속)** 이 유리 — harness의 burst/active pacing이 이를 유도.
- 파일명 충돌 방지: `benign_<svc>.pcap` vs `test/benign/benign_<svc>.pcap`.

### 4-2. attack (전량 → `result/test/attack/`)

> 공격은 CNN(비지도) 학습엔 미사용 — 전량 **평가·분석용**으로 `result/test/attack/`에 저장. 용도: ① benign/attack 분포 분리 확인(이미지화/PCA),
> ② 지도학습 상한 예측, ③ OCSVM 모델 평가. enum/manipulate는 권한 없으면 403이라도 패킷은 유효(§4-3).
> ★ **규모(시각화 목적)**: 논문 Table 2의 최소치(enum~84·manip~108·brute~6.5K)는 **참고값**일 뿐, 트래픽 자체를 시각화하려면 부족하다
> (w=5 → enum 84패킷 ≈ 16 이미지). 따라서 **benign(~150K)만큼은 아니지만 시각화에 충분한 양**(각 시나리오 수천~수만 패킷)을 수집하도록 확대한다.
> ※ ②지도학습 상한을 낼 때는 `test/attack/` 안에서 **train/test 내부 분할(또는 CV)** 로 낙관 편향 방지(디렉토리 통합과 무관한 분석 규율).

| 시나리오 | 파일 | 논문 최소치(참고) | 러닝(run.sh `ATTACK_*_OPTS` 기본, 시각화용 확대) | 비고 |
|---|---|---|---|---|
| 정보열거 | k8s_enum | ~84 | `-u 10 -r 2 -t 300s` | attacker pod, read-only GET (8종 엔드포인트 → 다양성) |
| 리소스조작 | k8s_manipulate | ~108 | `-u 10 -r 2 -t 300s` | 전부 `?dryRun=All` (안전) |
| 스캔+브루트 | k8s_bruteforce | ~6,523 | `-u 20 -r 5 -t 300s` | auth 대상(confound 정렬), 파괴 없음 |

- 실제 패킷수는 `tcpdump` 카운트를 보며 `-t`/`-u`로 가감(시각화에 충분한 시퀀스 확보가 목표).
- (제안서 범위 밖) escape 613 / remote-access 262 패킷은 **수집 안 함** — HTTP 아님/탈출 계열.

### 4-3. ⚠️ 결정 필요: attacker SA 권한(RBAC)

- **옵션 A (기본 SA, 전부 403)**: 추가 설정 없음. "권한 없는 침해 pod"의 열거/조작 **시도** 트래픽 확보. 라벨은 여전히 공격.
- **옵션 B (과도한 권한 재현)**: attacker SA에 `pods/services/secrets/... get,list,create` Role 바인딩 →
  실제 열거·조작이 200으로 성공. 논문의 "과도한 권한" 상황과 응답 페이로드까지 재현.
- **제안**: 둘 다 필요하면 **A로 1회, B로 1회** 각각 수집해 응답코드 다양성 확보. 실행 전 사용자 확정 필요(§6 질문).

---

## 5. 클러스터 수집 절차 (실행 단계)

> 전제: 모든 서비스가 `deepmesh`에 배포·Ready 상태. 노드 SSH(`vagrant ssh`)와 `kubectl` 사용 가능.
> 캡처는 반드시 **pod netns의 eth0**에서(-i any/SLL 금지 — C 파서 오프셋 정합).
>
> **오케스트레이션**: `bash locust/run.sh all` = **스냅샷 → benign(auth/post/comment/frontend) → attack(enum/manipulate/brute) → 스냅샷 복원**을 한 번에 실행(수집기+DB 브래킷만 담당, tcpdump 캡처는 노드에서 병행). 개별 단계는 `run.sh snapshot|benign|attack|restore`. 아래 §5-0~§5-3은 그 각 단계의 상세(캡처 좌표 포함).

### 5-0. 준비
```bash
kubectl get svc,pods -n deepmesh -o wide            # 최신 IP/노드 재확인 (§5-1 표 갱신)
mkdir -p /vagrant/result/benign \
         /vagrant/result/test/benign /vagrant/result/test/attack   # attack 은 평가 전용 → test/attack 만
pip3 install locust requests                        # locust 실행 노드/pod에
# locust/ 디렉토리를 노드 동기화 경로(/vagrant/locust)로 업로드

# ★ 전체 수집 시작 '전에' DB 스냅샷 (net-zero 기준점) — 수집 후 이 시점으로 복원한다
cd /vagrant/locust && bash db_snapshot.sh snapshot   # → db_snapshot.sql 저장
```

### 5-1. benign 수집 (서비스별, pod IP 고정 + 해당 노드 netns 캡처)
> 캡처 노드는 **배경 §의 실측 배치표** 참조. 💡 **`k8s-worker1`에 auth·post·comment 각 1 replica + mysql-0이 모두 있어**,
> 백엔드 3종 + mysql benign을 이 한 노드에서 캡처하면 편하다(frontend만 worker2/worker3).
```bash
# 예: post-service #1 (k8s-worker1, pod IP 10.244.194.89 — 재확인값 사용)
# 터미널 A (k8s-worker1): 대상 pod netns eth0 캡처
CID=$(sudo crictl ps --name post-service -q | head -1)
PID=$(sudo crictl inspect --output go-template --template '{{.info.pid}}' "$CID")
sudo timeout 300 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 \
  -w /vagrant/result/benign/benign_post.pcap tcp &

# 터미널 B (같은 노드): 그 pod IP로 부하 고정 (예: worker1의 auth=10.244.194.87)
cd /vagrant/locust
export AUTH_HOST=http://10.244.194.87:8080
locust -f benign/post_locustfile.py --host http://10.244.194.89:8080 --headless -u 20 -r 4 -t 600s
```
- auth·comment·frontend 동일 방식. frontend는 `--host http://<frontend-pod-ip>:80`(worker2 10.244.126.26 / worker3 10.244.100.215).
- comment는 `AUTH_HOST` + `POST_HOST` 함께 지정(worker1 기준: comment 10.244.194.90, auth 10.244.194.87, post 10.244.194.89).
- **mysql**: 위 백엔드 부하가 도는 동안 `mysql-0`(**k8s-worker1**, 10.244.194.79) netns eth0을 함께 캡처 → `benign_mysql.pcap`.
- 테스트셋은 동일 명령을 `-t`/`-u` 축소값으로, 저장 경로만 `result/test/benign/`으로.
- ⚠️ benign 종료는 반드시 `--run-time`(-t)으로 자연 종료 → 각 유저의 `on_stop`이 실행돼 생성 게시물/댓글이 삭제된다(강제 kill 금지).

### 5-2. attack 수집 (침해 pod에서)  — `run.sh attack`
> attacker pod는 `kalilinux/kali-rolling`(nmap·hydra·curl) + nodeSelector로 노드 고정(예: `k8s-worker3`).
> 공격 도구는 §6에서 확정: **(권장) locust 3종**(MITRE 매핑·재현성) 또는 **native**(nmap/hydra/curl).
> ※ DB 복원은 attack 단계가 아니라 **전체 흐름의 마지막 단계(§5-3, `run.sh restore`)** 로 분리됨 — `run.sh all`이면 attack 직후 자동 복원.

```bash
# 공격 locust를 configmap으로 (파일명 그대로 마운트)
kubectl -n deepmesh create configmap k8s-attacks --from-file=locust/attack/

# (옵션 B 선택 시) attacker SA + Role 바인딩 먼저 적용

# attacker pod — Kali, k8s-worker3 고정 + SA 토큰 자동 마운트  (노드 라벨은 실제 hostname: k8s-worker3)
kubectl -n deepmesh run attacker --image=kalilinux/kali-rolling --restart=Never \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"k8s-worker3"},"containers":[{"name":"attacker","image":"kalilinux/kali-rolling","command":["sleep","infinity"],"resources":{"requests":{"cpu":"200m","memory":"256Mi"},"limits":{"cpu":"500m","memory":"512Mi"}},"volumeMounts":[{"name":"f","mountPath":"/mnt"}]}],"volumes":[{"name":"f","configMap":{"name":"k8s-attacks"}}]}}'
# (locust 방식이면 pod 안에서: apt update && apt install -y python3-pip && pip3 install locust requests)

# 터미널 A (k8s-worker3): attacker pod egress 캡처 (timeout 으로 공격 창에 맞춰 자동 종료 → 복원 트래픽 미포함)
vagrant ssh k8s-worker3
CID=$(sudo crictl ps --name attacker -q | head -1)
PID=$(sudo crictl inspect --output go-template --template '{{.info.pid}}' "$CID")
# 공격 3종 합 ≈ 900s(기본) → timeout 1000 으로 bound. 캡처는 run.sh restore 이전에 종료됨.
sudo timeout 1000 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/test/attack/attack_all.pcap tcp &

# 터미널 B (kubectl 가능한 호스트): 공격 3종 순차 실행
cd /vagrant/locust && bash run.sh attack
```
- `run.sh attack` = enum → manipulate → bruteforce 순차 실행(kubectl exec). 위 예시는 한 파일(`attack_all.pcap`) 통캡처.
- **시나리오별 pcap 분리(시각화 라벨용, 권장)**: 시나리오를 개별 실행하며 각자 pcap을 따로 캡처 —
  터미널 A에서 `attack_enum.pcap`으로 캡처 시작 → 터미널 B `bash run.sh enum` → 종료 후 `attack_manipulate.pcap`으로 바꿔 `run.sh manipulate` → `attack_brute.pcap`으로 `run.sh brute`.
- 규모는 `ATTACK_ENUM_OPTS`/`ATTACK_MANIP_OPTS`/`ATTACK_BRUTE_OPTS` env로 조정(기본 시각화용 확대값, §4-2).
- 정리: `kubectl -n deepmesh delete pod attacker; kubectl -n deepmesh delete configmap k8s-attacks` (+옵션 B의 RBAC 제거).

### 5-3. DB 복원 (net-zero 마지막 단계)  — `run.sh restore`
- `bash run.sh restore`(= `db_snapshot.sh restore`)로 §5-0 스냅샷 시점으로 `auth_db/posts_db/comments_db`를 되돌리고 카운트 검증.
- ⚠️ 복원은 **전체 수집(benign+attack)의 마지막 단계**다. §5-0에서 스냅샷을 먼저 떠 둬야 함. `run.sh all`이면 이 단계가 자동 포함된다.
- 🔒 **복원(삭제) 트래픽은 pcap에 잡히지 않는다** — 2중 보장:
  1. **타이밍**: 복원은 모든 캡처가 끝난 뒤에만 실행. 각 캡처는 phase별 `timeout`(benign은 `timeout 300`, attack도 `-t`에 맞춰 `timeout`)으로 이미 종료된 상태.
  2. **경로**: 복원은 `mysql-0` 내부에서 **localhost 소켓**으로 SQL을 실행(`kubectl exec … mysql …`) → pod **eth0에 트래픽이 없음**. mysql 캡처는 benign 단계에서만 켜졌다 phase 종료로 꺼지므로, 복원 시점엔 mysql-0에 활성 캡처도 없다. (auth/post/comment/frontend·attacker pod는 복원과 무관.)

### 5-4. pcap 회수 → 로컬 학습
- 노드 `/vagrant/result/*` → Vagrant 동기화로 호스트에 저장 → scp로 로컬 회수.
- 로컬(GPU): 이미지화 → 지도학습 분리 상한 확인 → 지식증류(teacher→student→OCSVM) → held-out 평가.

---

## 6. 실행 전 사용자 확정 필요 (질문)

1. **클러스터 최신 IP/노드**: 배경 §의 배치표는 설계도 기반 **예측**(매니페스트에 노드 고정 없음). 실제 pod의 노드·IP를 `kubectl get pods -n deepmesh -o wide`로 확인해 배치표를 확정해야 함.
2. **attacker SA 권한**: §4-3 옵션 A(전부 403) / B(권한 부여로 성공 재현) / 둘 다 — 어느 것으로 수집?
3. **attacker 도구**: locust 3종(권장, MITRE 매핑) vs Kali native(nmap/hydra/curl, 설계도 도구셋) — §5-2 중 선택.
4. **수집 규모**: §4 목표 패킷수(frontend ~175K / backend ~150K / mysql ~55K / attack 84·108·6.5K) 재현 vs 자체 규모, test 분리 비율.
5. **frontend 대상 포트**: pod IP:80 직접 캡처 vs NodePort(30080) 경유 — pod netns 캡처 정합을 위해 pod IP:80 권장.
6. **사이드카 CPU limit**: 설계도는 proxy limit 1,000m인데 매니페스트 누락 → 지연/처리량 재현 위해 매니페스트에 추가할지(평가 단계). 지금 수집엔 무관.
7. **control-plane 배포 형태**: 설계도는 master-node `masterNode.py` 프로세스, 매니페스트는 `deepmesh` Deployment — 실제 어느 쪽으로 떠 있는지 확인.

---

## 7. 체크리스트

- [ ] `local_files/` → `locust/` 재구성 (frontend 파일명 정리, db 파일 미생성) — §3
- [ ] `result/{benign,test/benign,test/attack}` 생성 (attack은 평가 전용) — §3
- [ ] `kubectl get svc,pods -n deepmesh -o wide`로 IP/노드 최신화 + **replicas ≥ 2** 확인 — §5-0
- [ ] **수집 전 DB 스냅샷** `run.sh snapshot`(= `db_snapshot.sh snapshot`, net-zero 기준점) — §5-0
- [ ] 캡처 요건 점검: **pod netns eth0 + `-s 0` + 양방향 + 세션 ≥5 패킷** (전처리 1479B·w=5 정합) — 배경 §
- [ ] attacker SA 권한 정책 확정 (옵션 A/B) — §4-3
- [ ] benign 수집 `run.sh benign` (auth/post/comment/frontend + mysql 부산물, `--run-time` 자연 종료 → on_stop 정리) → `result/benign/` — §4-1, §5-1
- [ ] attacker pod 배포 → `run.sh attack` (enum/manipulate/brute) → `result/test/attack/` — §4-2, §5-2
- [ ] **DB 복원** `run.sh restore` → 스냅샷 시점 카운트와 일치 검증 — §5-3, §8  *(위 4단계는 `run.sh all`로 일괄 실행 가능)*
- [ ] attacker pod·configmap(·RBAC) 정리 — §5-2
- [ ] pcap 로컬 회수 → 이미지화(동일 C `.so`) → KD 학습(teacher→student CNN-2x8) → **목표 수치 대비 평가** — §5-4, 배경 §

---

## 8. 설계 한계 노트 (수집 전 인지 — 논문 방식대로 규정)

- **상태 무변경(net-zero) 보장 방식 — 스냅샷·복원(사전 데이터 보존)**:
  1. **수집 전 스냅샷**(§5-0 `db_snapshot.sh snapshot`): 현재 DB 상태를 `db_snapshot.sql`로 저장 = 되돌릴 기준점.
  2. **run 중 자체 정리**: benign 수집기가 생성한 게시물/댓글을 각 유저의 `on_stop`에서 삭제(정상 `--run-time` 종료 시).
  3. **수집 후 복원**(`run.sh restore`, `run.sh all`이면 attack 직후 자동): 스냅샷 시점으로 `auth_db/posts_db/comments_db`를 되돌림 → 수집 중 추가된 **사용자 계정**(삭제 API 없음)과 on_stop이 놓친 잔여물까지 정확히 제거하되 **사전 데이터는 보존**.
  - `mysqldump --add-drop-table` 기반이라 복원 시 테이블을 DROP 후 재생성해 수집 중 변경분을 정확히 폐기. 복원은 전체 수집의 **마지막 단계**여야 함(스냅샷→benign→attack→복원).
- **benign 기준선의 방향**: 위 benign은 각 **서비스 pod의 정상 north-south + 그로 인한 정상 east-west**(사용자→서비스, 서비스→서비스)다. 반면 K8s API 공격(enum/manipulate)은 **attacker pod의 egress**(pod → API 서버 10.96.0.1:443)로 방향·대상이 다르다.
- **K8s API-egress 정상 기준선 부재 → "이탈"로 규정(논문 방식, 확정)**: 앱 pod는 평소 K8s API를 거의 호출하지 않아 "정상 API-egress"가 희박하다. 논문은 이를 위해 전용 정상-API-egress 클래스를 만들지 않고, **서비스별 모델을 각 서비스의 정상 트래픽으로 학습한 뒤 "앱 pod의 K8s API 호출 = 이탈(이상)"으로 규정**한다(논문은 React+Nginx pod 트래픽으로 학습하고 K8s 공격을 이상으로 탐지). 따라서 **이번 수집도 웹앱 benign만 확보**하고, K8s API-egress benign은 별도 수집하지 않는다. (Jenkins/Prometheus처럼 정상적으로 API를 쓰는 컴포넌트는 논문에서 **별도 워크로드**로 수집됐을 뿐, 앱 서비스 탐지기의 기준선이 아니다.) → 이는 부재-기반 탐지라는 한계를 수반함을 명시. (modify_plan.md §6-5와 정합)
- **cross-environment skew**: 선행연구가 공개한 attack pcap은 다른 클러스터 산출물이라, 우리 benign과 섞으면 TTL/MSS/window 차이로 오분리 가능 → 검증은 정상·공격 모두 **우리 클러스터에서** 수집해 맞춘다.
- **캡처 지점 정합**: 반드시 pod netns eth0(Ethernet 프레임)에서 캡처(`-i any`/SLL 금지) — C 파서 오프셋 정합(배경 §과 동일).
