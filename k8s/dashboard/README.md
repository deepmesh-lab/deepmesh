# 대시보드 배포

`deepmesh` 네임스페이스에 백엔드와 프론트엔드를 함께 올린다. 프론트엔드는 nginx로 정적
파일만 서빙하고, `/dashboard/*` 요청은 같은 클러스터의 `dashboard-backend:8080`으로
넘긴다. 브라우저 입장에서는 화면과 API가 같은 오리진이라 **CORS 설정이 필요 없다.**

```
브라우저 ──> NodePort 30090 ──> dashboard-frontend (nginx x2)
                                    ├─ 정적 파일
                                    └─ /dashboard/* 프록시
                                         ↓
                                  dashboard-backend:8080 (ClusterIP, 1개)
                                         ├─ MySQL (mysql-service:3306 / dashboard_db)
                                         └─ K8s API (토폴로지 조회 → rbac.yaml)
```

| 파일 | 역할 |
|---|---|
| `frontend-configmap.yaml` | nginx 설정. 백엔드 주소가 여기에만 있다 |
| `frontend-deployment.yaml` | nginx 파드 2개 |
| `frontend-service.yaml` | NodePort 30090 |
| `backend-deployment.yaml` | 백엔드 파드 1개 |
| `backend-service.yaml` | ClusterIP 8080. **이름을 바꾸지 말 것** — nginx가 이 이름으로 프록시한다 |
| `rbac.yaml` | 백엔드가 K8s API를 읽기 위한 ServiceAccount·Role |

백엔드 replicas가 1인 것은 의도다. SSE 구독자는 자기가 붙은 인스턴스의 브로드캐스트만
받으므로, 늘리면 이벤트를 못 받는 클라이언트가 생긴다. 늘리려면 인스턴스 간 이벤트
전파(pub/sub)가 먼저 필요하다.

## 1. 선행 조건

이미 돼 있으면 건너뛴다.

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml   # DASHBOARD_DB_URL · DASHBOARD_URL
kubectl apply -f k8s/mysql/           # 백엔드가 dashboard_db를 쓴다
```

Secret은 gitignore 대상이라 직접 만든다. 백엔드가 `MYSQL_ROOT_PASSWORD`를 참조한다.

```bash
kubectl create secret generic deepmesh-secret \
  --namespace=deepmesh \
  --from-literal=MYSQL_ROOT_PASSWORD='<비밀번호>' \
  --from-literal=JWT_SECRET='<jwt-시크릿>'
```

DB는 `DASHBOARD_DB_URL`에 `createDatabaseIfNotExist=true`가 붙어 있어 따로 만들지 않아도 된다.

## 2. 프론트엔드 이미지 빌드와 푸시

```bash
cd dashboard/frontend
docker build -t uicheolshin/dashboard-frontend:latest \
  --build-arg VITE_USE_MOCK=false .
docker push uicheolshin/dashboard-frontend:latest
```

`VITE_*` 값은 **빌드 시점에 코드 안으로 구워진다.** Deployment에 환경변수로 넣어도
아무 효과가 없다. 반대로 백엔드 주소(`VITE_DASHBOARD_API_URL`)는 비워 둬야 앱이
같은 오리진으로만 요청하고, 주소 변경이 ConfigMap 한 곳으로 끝난다.

두 Deployment 모두 `imagePullPolicy: Always`다. 같은 태그(`:latest`, 백엔드는 `:v2`)를
재사용하므로 이 설정이 없으면 노드가 캐시된 옛 이미지를 계속 쓴다. 반대로 말하면
push를 빠뜨린 채 rollout만 돌리면 바뀐 게 없다.

## 3. 배포

백엔드가 `dashboard-backend-sa`를 요구하므로 RBAC를 먼저 적용한다.

```bash
kubectl apply -f k8s/dashboard/rbac.yaml
kubectl apply -f k8s/dashboard/
```

## 4. 확인

```bash
kubectl -n deepmesh rollout status deploy/dashboard-backend
kubectl -n deepmesh rollout status deploy/dashboard-frontend
kubectl -n deepmesh get pods -l app=dashboard-frontend
```

브라우저에서 `http://<노드IP>:30090` (예: `http://192.168.56.10:30090`)

기존 `k8s/ingress.yaml`에는 얹지 않는다. 거기 걸린 `rewrite-target: /`가 모든 경로를
`/`로 바꿔 버려서 정적 자산 경로가 전부 깨진다.

## 5. 설정을 바꿨을 때

ConfigMap을 고쳐도 파드는 자동으로 재시작되지 않는다.

```bash
kubectl apply -f k8s/dashboard/frontend-configmap.yaml
kubectl -n deepmesh rollout restart deploy/dashboard-frontend
```

## 백엔드가 아직 없어도 된다

nginx가 백엔드 주소를 **요청이 올 때** 해석하도록 해 두었다. `proxy_pass`에 이름을 그대로
쓰면 nginx 시작 시점에 DNS를 찾고, 그때 `dashboard-backend`가 없으면
"host not found in upstream"으로 컨테이너가 아예 뜨지 못한다. 변수로 두었기 때문에
백엔드 Service가 없어도 화면은 뜨고 `/dashboard` 요청만 502가 된다. 화면 우측 상단
토글을 `MOCK`에 두면 백엔드 없이 전체 화면을 확인할 수 있다.

## 안 되면 볼 곳

| 증상 | 원인 |
|---|---|
| 화면은 뜨는데 `/dashboard/*`가 502 | 백엔드 파드·Service 확인. Service 이름은 반드시 `dashboard-backend` |
| nginx 파드가 CrashLoop | `frontend-configmap.yaml`의 `resolver kube-dns...` 이름이 안 풀리는 경우. `kubectl -n kube-system get svc kube-dns`의 CLUSTER-IP로 바꾼다 |
| 백엔드가 Pending·Error | Secret 또는 `deepmesh-config` 누락, 혹은 `rbac.yaml` 미적용 |
| 대시보드에 이벤트가 안 쌓임 | 사이드카가 `DASHBOARD_URL`로 판정을 보내야 한다. MSA가 사이드카 버전으로 떠 있는지 확인 |
| 코드를 고쳤는데 화면이 그대로 | `VITE_*`는 빌드 타임 값이다. 이미지 재빌드·재푸시 후 `rollout restart` |
