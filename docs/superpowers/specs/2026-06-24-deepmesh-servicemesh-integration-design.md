# deepmesh × lightweight_servicemesh 통합 설계

**날짜**: 2026-06-24  
**대상 프로젝트**: deepmesh MSA + lightweight_servicemesh (KD-CNN 침입 탐지)  
**목표**: 논문 "Lightweight Service Mesh for Intrusion Detection using KD-CNN in Cloud-Native Environments" (ACM CCS Workshop 2025)의 구조를 deepmesh 환경에 충실하게 재현

---

## 1. 전체 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                      │
│                                                          │
│  Master Node (4c / 8GB)                                  │
│  ├── Kubernetes API Server                               │
│  └── Control Plane DaemonSet                             │
│      ├── Pod Info Provider  ← ReplicaSet Pod IP 관리     │
│      └── Request Verifier   ← 요청 일관성 검증            │
│                                                          │
│  Worker Nodes ×3 (12c / 24GB each)                       │
│  └── Namespace: deepmesh                                 │
│      ├── Pod: auth-service (replicas: 2)                 │
│      │   ├── Main Container  (Spring Boot :8080)         │
│      │   └── Proxy Container (Python Sidecar :9000)      │
│      │       ├── Traffic Handler                         │
│      │       ├── Traffic Converter (패킷 → 5×1479 이미지) │
│      │       └── Anomaly Detector  (KD-CNN + OCSVM)      │
│      ├── Pod: post-service    (replicas: 2, 동일 구조)   │
│      ├── Pod: comment-service (replicas: 2, 동일 구조)   │
│      ├── Pod: frontend        (replicas: 2)              │
│      └── StatefulSet: mysql                              │
│                                                          │
└─────────────────────────────────────────────────────────┘

GPU 서버 (별도)
└── 모델 학습 전용
    ├── auth-service:    teacher.pth → student.pt + ocsvm.pkl
    ├── post-service:    teacher.pth → student.pt + ocsvm.pkl
    └── comment-service: teacher.pth → student.pt + ocsvm.pkl
```

**서비스별 모델 분리**: 각 서비스가 독립적인 Student 모델(CNN-2x16) + OCSVM을 보유.  
논문의 service-specific 탐지 전략 적용 — 전역 단일 모델 대비 false positive 25% 이상 감소 (논문 결과).

---

## 2. 개발 단계 (Phase)

### Phase 1 — deepmesh K8s 마이그레이션

**목표**: Docker Compose 구성을 K8s Manifest로 전환  
**완료 기준**: `kubectl get pods -n deepmesh` 전체 Running, 서비스 간 HTTP 통신 정상

| 리소스 | 종류 | 비고 |
|---|---|---|
| Namespace | `deepmesh` | |
| MySQL | StatefulSet + PersistentVolumeClaim | `mysql-data` 볼륨 대체 |
| auth-service | Deployment (replicas: 2) + ClusterIP Service | |
| post-service | Deployment (replicas: 2) + ClusterIP Service | |
| comment-service | Deployment (replicas: 2) + ClusterIP Service | |
| frontend | Deployment (replicas: 2) + LoadBalancer Service | |
| Ingress | Ingress | 외부 트래픽 진입점 |
| 시크릿 | Secret | `MYSQL_ROOT_PASSWORD`, `JWT_SECRET` |
| 설정 | ConfigMap | DB URL, 서비스 간 URL |

> replicas: 2 이상이어야 Control Plane의 Relay 로직이 동작함.  
> Relay는 이상 탐지 시 동일 ReplicaSet의 다른 Pod에서 정상 응답을 가져오는 방식.

**테스트**:
- [ ] 전체 Pod Running 확인
- [ ] auth-service 회원가입/로그인 API 정상 응답
- [ ] post-service, comment-service API 정상 응답
- [ ] 서비스 간 HTTP 통신 (comment → post → auth) 정상

**커밋 단위 예시**:
```
feat: add deepmesh namespace and MySQL StatefulSet manifest
feat: add auth-service Deployment and ClusterIP Service manifest
feat: add post-service Deployment and ClusterIP Service manifest
feat: add comment-service Deployment and ClusterIP Service manifest
feat: add frontend Deployment and LoadBalancer Service manifest
feat: add Ingress manifest for external traffic routing
feat: add Secret and ConfigMap for deepmesh configuration
```

---

### Phase 2 — 데이터 수집 파이프라인

**목표**: 서비스별 Benign/Attack 트래픽 .pcap 파일 수집  
**완료 기준**: 서비스별 Benign 데이터 10만 패킷 이상, 각 Attack 시나리오 데이터 수집 완료

#### Benign 수집

```
트래픽 생성 (locust 또는 k6)
├── auth-service: 회원가입, 로그인, 토큰 갱신
├── post-service: 게시글 CRUD
└── comment-service: 댓글 CRUD, cursor 페이지네이션
         ↓
각 Pod 네트워크 인터페이스에서 tcpdump 캡처
         ↓
서비스별 benign_<service>.pcap 저장
```

#### Attack 수집 (MITRE ATT&CK 기반)

| 시나리오 | MITRE 기법 | deepmesh 특화 내용 |
|---|---|---|
| K8s 클러스터 정보 열거 | T1589, T1528, T1613 | ServiceAccount 토큰 탈취 후 API 서버 접근 |
| K8s 리소스 조작 | T1609 | Network Policy 변조로 서비스 간 격리 우회 |
| 컨테이너 탈출 | T1610, T1611 | privileged 설정 악용 |
| Brute-Force 공격 | T1595, T1110 | auth-service `/login` 무차별 대입 |
| JWT 위조/탈취 | T1219 | 만료 토큰 재사용, 서명 없는 토큰 시도 |

**테스트**:
- [ ] 서비스별 Benign .pcap 파일 생성 및 패킷 수 확인
- [ ] 5가지 Attack 시나리오 .pcap 파일 생성
- [ ] `Preprocess/k8s_preprocess.py` 적용 시 5×1479 이미지 시퀀스 정상 생성

**커밋 단위 예시**:
```
feat: add locust traffic generation scripts for deepmesh services
feat: add tcpdump capture scripts for each service pod
feat: add attack scenario scripts for K8s lateral movement
feat: add JWT abuse attack scenario scripts
```

---

### Phase 3 — 서비스별 모델 학습 (GPU 서버)

**목표**: 서비스별 Teacher → Student KD 학습 완료  
**완료 기준**: 서비스별 `student.pt` + `ocsvm.pkl` 생성, K8s ROC-AUC 90% 이상

#### 학습 파이프라인

```
benign_<service>.pcap + attack_<service>.pcap
         ↓
Preprocess (k8s_preprocess.py 수정 적용)
→ 5×1479 그레이스케일 이미지 시퀀스
         ↓
[서비스별 독립 학습 — GPU 서버]
Teacher CNN 학습 (NT-Xent Contrastive, 정상 트래픽만)
         ↓
Student KD 학습 (MSE Distillation, CNN-2x16 구성)
         ↓
OCSVM 학습 (Student 임베딩 기반)
         ↓
TorchScript 변환: student_<service>.pt
         ↓
K8s ConfigMap or PersistentVolume으로 배포
```

**모델 구성**: CNN-2x16 (13.87K params, 2.02M FLOPs)  
논문 Table 5 기준 Teacher 대비 ROC-AUC 0.01% 차이, 추론 속도 6배 향상.

**테스트**:
- [ ] 서비스별 Teacher 학습 loss 수렴 확인
- [ ] Student KD 학습 loss 수렴 확인
- [ ] 서비스별 Precision, Recall, F1, ROC-AUC 측정 (목표: ROC-AUC ≥ 90%)
- [ ] TorchScript 변환 후 추론 결과 동일성 확인

**커밋 단위 예시**:
```
feat: add deepmesh-specific preprocessing pipeline for pcap files
feat: add teacher model training script for deepmesh services
feat: add student KD training script with CNN-2x16 architecture
feat: add OCSVM training script on student embeddings
feat: add TorchScript export and model validation script
```

---

### Phase 4 — Data Plane Proxy 완성

**목표**: `proxy_detection.py`의 Drop/Relay/Forward 로직 구현  
**완료 기준**: Algorithm 1 완전 구현, 이상 트래픽 차단 및 Relay 동작 확인

#### 구현 대상 (Algorithm 1)

```python
if is_malicious:
    if traffic_type == 'response':
        # Relay: 동일 ReplicaSet 다른 Pod에서 정상 응답 가져오기
        rep_ip = control_plane.get_replica_ip(pod_ip)
        rep_response = fetch_from_replica(rep_ip, original_request)
        if rep_response != current_response:
            replace_response(rep_response)   # Relay
    else:  # request
        if not control_plane.verify_request(request):
            drop(traffic)                    # Drop
else:
    forward(traffic)                         # Forward
```

#### Proxy Container 구성

```
ServiceMesh/DataPlane/
├── Dockerfile              (기존 활용, 서비스별 모델 경로 수정)
├── Proxy/
│   ├── packet_parser_stack.c  (기존 활용)
│   └── proxy_detection.py     (Drop/Relay/Forward 완성)
├── Model/
│   ├── student_auth.pt
│   ├── ocsvm_auth.pkl
│   ├── student_post.pt
│   ├── ocsvm_post.pkl
│   ├── student_comment.pt
│   └── ocsvm_comment.pkl
└── iptables.sh             (기존 활용)
```

**테스트**:
- [ ] 정상 트래픽 → Forward 동작 확인
- [ ] 이상 응답 트래픽 → Relay 동작 확인 (다른 Pod 응답으로 대체)
- [ ] 이상 요청 트래픽 (미확인) → Drop 동작 확인
- [ ] 이상 요청 트래픽 (검증 통과) → Forward 동작 확인

**커밋 단위 예시**:
```
feat: implement Forward logic in proxy_detection.py
feat: implement Drop logic with Control Plane request verification
feat: implement Relay logic using ReplicaSet peer Pod response
feat: add service-specific model loading by SERVICE_NAME env var
feat: update Dockerfile for multi-service model support
```

---

### Phase 5 — Control Plane 완성

**목표**: Pod Info Provider + Request Verifier 완전 구현  
**완료 기준**: Data Plane에서 Control Plane API 정상 조회, Relay/Drop 판정 동작

#### Pod Info Provider

- K8s API를 주기적으로 폴링 → ReplicaSet별 Pod IP 목록 유지
- `GET /pods/{namespace}/{replicaset}` → Pod IP 목록 반환
- Data Plane Proxy가 Relay 대상 Pod IP를 조회하는 데 사용

#### Request Verifier

- 각 Worker의 Proxy로부터 요청 정보(hash) 수신 및 저장
- `POST /requests` → 요청 정보 등록
- `GET /requests/{request_hash}` → 동일 요청의 다른 Pod 관찰 여부 반환
- `workerNode.py`: Worker Node에서 요청 정보를 Master로 전달

#### 배포

- Control Plane은 Master Node에 DaemonSet 또는 Deployment로 배포
- Data Plane ↔ Control Plane 통신: 클러스터 내부 ClusterIP Service

**테스트**:
- [ ] Pod Info Provider API 응답 정상 (ReplicaSet Pod IP 목록)
- [ ] Request Verifier 등록/조회 API 정상
- [ ] Data Plane에서 Control Plane API 호출 정상
- [ ] 전체 통합: 이상 트래픽 시나리오에서 Drop/Relay 판정 정상

**커밋 단위 예시**:
```
feat: implement Pod Info Provider with K8s API polling
feat: implement Request Verifier registration and lookup API
feat: implement workerNode request forwarding to masterNode
feat: add Control Plane Deployment and ClusterIP Service manifest
feat: integrate Data Plane with Control Plane API calls
```

---

### Phase 6 — 통합 테스트 및 성능 측정

**목표**: 논문과 동일한 메트릭으로 성능 검증  
**완료 기준**: 탐지 성능 ROC-AUC ≥ 90%, 레이턴시 측정 결과 문서화

#### 탐지 성능 측정

- Precision, Recall, F1-score, ROC-AUC
- 서비스별 측정 + 전체 평균

#### 네트워크 오버헤드 측정 (wrk/wrk2)

| 구성 | Latency | Throughput |
|---|---|---|
| 기본 (Proxy 없음) | 측정 | 측정 |
| 제안 (Detection 비활성) | 측정 | 측정 |
| 제안 (Detection 활성) | 측정 | 측정 |

비교 대상으로 Istio, Linkerd 선택적 포함.

#### 추론 레이턴시

- 이미지당 평균 탐지 시간 (ms)
- 1 vCPU 제약 조건 하에서 측정 (논문 조건 동일)

**커밋 단위 예시**:
```
feat: add detection performance evaluation script
feat: add network overhead benchmark scripts using wrk2
docs: add performance measurement results
```

---

## 3. 커밋 메시지 컨벤션

```
<type>: <subject>

type 목록:
- feat:  새 기능
- fix:   버그 수정
- refactor: 리팩토링 (기능 변경 없음)
- test:  테스트 추가/수정
- docs:  문서
- chore: 빌드/설정 변경
```

- 기능 단위로 커밋 (파일 단위가 아닌 논리적 기능 단위)
- Phase 완료 시 태그 생성: `phase1`, `phase2`, ... `phase6`

---

## 4. 주요 기술 결정

| 결정 사항 | 선택 | 근거 |
|---|---|---|
| Student 모델 구성 | CNN-2x16 | 논문 Table 5: ROC-AUC 96.57%, 추론 0.592ms — 정확도·속도 균형 최적 |
| replicas | 2 | Relay 로직 동작 최소 요건 |
| 데이터 수집 환경 | K8s (Phase 1 완료 후) | 수집 환경과 배포 환경 일치 → 트래픽 패턴 동일 |
| Control Plane 위치 | Master Node | K8s API 접근 권한, 중앙 집중 관리 |
| 모델 배포 방식 | PersistentVolume | 모델 파일 크기 (~수 MB) ConfigMap 한계 초과 가능성 |
