# 대시보드 프론트엔드 배포

`deepmesh` 네임스페이스에 nginx 컨테이너로 배포한다. 정적 파일만 서빙하고,
`/dashboard/*` 요청은 같은 클러스터의 `dashboard-backend:8080`으로 넘긴다.
브라우저 입장에서는 화면과 API가 같은 오리진이라 **CORS 설정이 필요 없다.**

| 파일 | 역할 |
|---|---|
| `configmap.yaml` | nginx 설정. 백엔드 주소가 여기에만 있다 |
| `deployment.yaml` | nginx 파드 2개 |
| `service.yaml` | NodePort 30090 |

## 1. 이미지 빌드와 푸시

```bash
cd dashboard/frontend
docker build -t uicheolshin/dashboard-frontend:latest \
  --build-arg VITE_USE_MOCK=false .
docker push uicheolshin/dashboard-frontend:latest
```

`VITE_*` 값은 **빌드 시점에 코드 안으로 구워진다.** Deployment에 환경변수로 넣어도
아무 효과가 없다. 반대로 백엔드 주소(`VITE_DASHBOARD_API_URL`)는 비워 둬야 앱이
같은 오리진으로만 요청하고, 주소 변경이 ConfigMap 한 곳으로 끝난다.

## 2. 배포

```bash
kubectl apply -f k8s/dashboard/
```

## 3. 확인

```bash
kubectl -n deepmesh rollout status deploy/dashboard-frontend
kubectl -n deepmesh get pods -l app=dashboard-frontend
```

브라우저에서 `http://<노드IP>:30090` (예: `http://192.168.56.10:30090`)

## 4. 설정을 바꿨을 때

ConfigMap을 고쳐도 파드는 자동으로 재시작되지 않는다.

```bash
kubectl apply -f k8s/dashboard/configmap.yaml
kubectl -n deepmesh rollout restart deploy/dashboard-frontend
```

## 백엔드가 아직 없어도 된다

nginx가 백엔드 주소를 **요청이 올 때** 해석하도록 해 두었기 때문에,
`dashboard-backend` Service가 없어도 파드는 정상적으로 뜬다.
화면 우측 상단 토글을 `MOCK`에 두면 백엔드 없이 전체 화면을 확인할 수 있다.

백엔드가 준비되면 `deepmesh` 네임스페이스에 이름이 `dashboard-backend`,
포트가 `8080`인 Service를 만들기만 하면 된다. 프론트엔드는 손대지 않는다.
