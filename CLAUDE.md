# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Spring Boot 3 + React 19 기반 MSA 데모에 KD-CNN 침입 탐지 Service Mesh를 통합하는 프로젝트.  
논문 "Lightweight Service Mesh for Intrusion Detection using KD-CNN in Cloud-Native Environments" (ACM CCSW '25) 구현체.

실제 서비스 코드는 `msa/`, K8s 매니페스트는 `k8s/`, Service Mesh 컴포넌트는 `servicemesh/`에 있다.

## 통합 계획 문서

- **설계 문서**: [`docs/superpowers/specs/2026-06-24-deepmesh-servicemesh-integration-design.md`](docs/superpowers/specs/2026-06-24-deepmesh-servicemesh-integration-design.md)
- **구현 계획**: [`.claude/plans/2026-06-24-deepmesh-servicemesh-integration.md`](.claude/plans/2026-06-24-deepmesh-servicemesh-integration.md)

## 주요 명령어

### 전체 환경 실행 (Docker Compose — 개발용)
```bash
cd msa
docker-compose up --build
docker-compose down -v
```

### K8s 전체 배포
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/mysql/
kubectl apply -f k8s/auth-service/
kubectl apply -f k8s/post-service/
kubectl apply -f k8s/comment-service/
kubectl apply -f k8s/frontend/
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/control-plane/
kubectl get pods -n deepmesh
```

### 백엔드 서비스 (각 서비스 디렉토리에서)
```bash
./gradlew bootRun        # 로컬 실행
./gradlew bootJar        # 빌드
./gradlew test           # 테스트
```

### 프론트엔드
```bash
cd msa/frontend
npm install
npm run dev              # 개발 서버 (localhost:3000)
npm run build
npm run lint
```

### 데이터 수집 및 모델 학습
```bash
# Benign 트래픽 생성
locust -f data-collection/locust/auth_locustfile.py --host http://<INGRESS_IP> \
  --users 10 --spawn-rate 2 --run-time 300s --headless

# 패킷 캡처
./data-collection/capture.sh auth-service 300

# 전처리 → Teacher 학습 → Student KD → OCSVM → TorchScript 변환
python model-training/preprocess_deepmesh.py --benign ./pcap/auth*.pcap --out ./data/auth-service/
python model-training/train_teacher.py --data ./data/auth-service/ --out ./models/auth-service/
python model-training/train_student_kd.py --data ./data/auth-service/ --teacher ./models/auth-service/teacher.pth --out ./models/auth-service/
python model-training/train_ocsvm.py --data ./data/auth-service/ --student ./models/auth-service/student.pth --out ./models/auth-service/
python model-training/export_torchscript.py --student ./models/auth-service/student.pth --out ./models/auth-service/
python model-training/evaluate.py --data ./data/auth-service/ --model-dir ./models/auth-service/
```

## 아키텍처

### 서비스 구성 (K8s, 네임스페이스: deepmesh)

| 서비스 | replicas | 포트 | DB |
|---|---|---|---|
| auth-service | 2 | 8080 | auth_db |
| post-service | 2 | 8080 | posts_db |
| comment-service | 2 | 8080 | comments_db |
| frontend | 2 | 80 | — |
| mysql | 1 (StatefulSet) | 3306 | 3개 DB |
| control-plane | 1 | 8080 | — |

### Sidecar Proxy 구조 (각 서비스 Pod)

```
Pod
├── Main Container  (Spring Boot :8080)
└── reverse-proxy   (Python Sidecar :9011)
    ├── iptables → 트래픽을 9011로 리다이렉션
    ├── Traffic Converter: 패킷 → 5×1479 grayscale 이미지
    └── Anomaly Detector: Student CNN-2x16 + OCSVM
        → Forward / Drop / Relay (논문 Algorithm 1)
```

### Control Plane (masterNode)

- **Pod Info Provider**: kubectl로 ReplicaSet Pod IP 목록 주기적 수집 → 각 Proxy에 push
- **Request Verifier**: `POST /send/internal_request_body` — Drop/Forward 판정
- Proxy Port: `9011` (iptables 예외 처리됨)
- Control Plane Port: `8080`

### 서비스별 모델

각 서비스마다 독립적인 모델 보유 (PersistentVolume 마운트):
```
/app/model/
├── student_ts.pt    ← TorchScript Student CNN-2x16
└── ocsvm.pkl        ← OneClassSVM
```

## 환경변수

### 프론트엔드 (`msa/frontend/.env-example`)
```
VITE_AUTH_API_URL=http://localhost:8080
VITE_POST_API_URL=http://localhost:8082
VITE_COMMENT_API_URL=http://localhost:8081
```

### Proxy Container (K8s env)
```
TARGET_PORT=8080
PROXY_PORT=9011
POD_IP=<자동 주입>
SERVICE_NAME=auth-service
CONTROL_PLANE_URL=http://control-plane-service.deepmesh:8080
```

## 커밋 컨벤션

```
feat:     새 기능
fix:      버그 수정
refactor: 리팩토링
test:     테스트
docs:     문서
chore:    빌드/설정
```

메시지는 한국어로 한 줄 요약. Phase 완료 시 태그: `phase1` ~ `phase6`
