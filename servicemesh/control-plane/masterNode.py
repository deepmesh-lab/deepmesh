"""
Control Plane — Pod Info Provider + Request Verifier (cross-replica)
포트: 8080

논문 §4.2 / Algorithm 1 의 Request Verifier 를 이식.
  - Pod Info Provider: deepmesh 네임스페이스에서 reverse-proxy 사이드카를 가진 pod 를
    service(app 라벨)별로 수집 → 각 프록시에 "동료 pod 목록"을 push(/receive/pods_ip).
  - Request Verifier: POST /send/internal_request_body
      body {"pod_ip": ..., "signature_data": ...}
      같은 replicaset(=service)의 다른 pod 에서도 그 signature 가 관측됐는지로 판정:
        · 다른 pod 도 관측 → {"result": "valid"}   (정상 분산 트래픽 → forward)
        · 오직 그 pod 만    → {"result": "invalid"} (그 pod 만의 요청 = lateral movement 의심 → drop)

환경변수:
  NAMESPACE=deepmesh
  UPDATE_INTERVAL=10
  KNOWN_SERVICES=auth-service,post-service,comment-service
  PODS_IP_PORT=9012            (프록시의 pods_ip 수신 포트 = PROXY_PORT+1)
  SIDECAR_NAME=reverse-proxy
"""
import logging
import os
import threading
import time

import kubernetes
import requests
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NAMESPACE = os.environ.get("NAMESPACE", "deepmesh")
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "10"))
KNOWN_SERVICES = [s.strip() for s in os.environ.get(
    "KNOWN_SERVICES", "auth-service,post-service,comment-service").split(",") if s.strip()]
PODS_IP_PORT = int(os.environ.get("PODS_IP_PORT", "9012"))
SIDECAR_NAME = os.environ.get("SIDECAR_NAME", "reverse-proxy")

app = Flask(__name__)

# service → [ {name, ip} ]
pod_registry: dict[str, list[dict]] = {svc: [] for svc in KNOWN_SERVICES}
# service → { signature_data → set(pod_ip) }
request_seen: dict[str, dict[str, set]] = {svc: {} for svc in KNOWN_SERVICES}
_lock = threading.Lock()


# ──────────────────────────────────────────────
# Pod Info Provider
# ──────────────────────────────────────────────

def _load_k8s() -> kubernetes.client.CoreV1Api:
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
    return kubernetes.client.CoreV1Api()


def _service_of_ip(pod_ip: str) -> str | None:
    for svc, pods in pod_registry.items():
        if any(p["ip"] == pod_ip for p in pods):
            return svc
    return None


def _push_peer_lists():
    """각 pod 에게 '자기 자신을 제외한 동료 pod 목록'을 push. replica<=1 이면 skip."""
    for svc, pods in pod_registry.items():
        if len(pods) <= 1:
            continue
        for pod in pods:
            peers = [p for p in pods if p["ip"] != pod["ip"]]
            url = f"http://{pod['ip']}:{PODS_IP_PORT}/receive/pods_ip"
            try:
                requests.post(url, json={"name": pod["name"], "ip": pod["ip"],
                                         "pods_ip": peers}, timeout=3)
            except requests.RequestException:
                continue


def _update_loop():
    try:
        v1 = _load_k8s()
    except Exception as exc:
        logger.error("K8s 클라이언트 초기화 실패: %s", exc)
        return
    while True:
        new_reg: dict[str, list[dict]] = {svc: [] for svc in KNOWN_SERVICES}
        try:
            for svc in KNOWN_SERVICES:
                pods = v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={svc}")
                for pod in pods.items:
                    if not (pod.status and pod.status.pod_ip and pod.status.phase == "Running"):
                        continue
                    # reverse-proxy 사이드카가 있는 pod 만
                    names = [c.name for c in (pod.spec.containers or [])]
                    if SIDECAR_NAME not in names:
                        continue
                    new_reg[svc].append({"name": pod.metadata.name, "ip": pod.status.pod_ip})
            with _lock:
                pod_registry.update(new_reg)
            total = sum(len(v) for v in new_reg.values())
            logger.info("Pod 레지스트리 갱신: 총 %d pod", total)
            _push_peer_lists()
        except Exception as exc:
            logger.error("레지스트리 갱신 오류: %s", exc)
        time.sleep(UPDATE_INTERVAL)


# ──────────────────────────────────────────────
# Request Verifier (cross-replica)
# ──────────────────────────────────────────────

@app.route("/send/internal_request_body", methods=["POST"])
def verify_request():
    data = request.get_json(silent=True) or {}
    pod_ip = data.get("pod_ip")
    signature = data.get("signature_data", "")
    if not pod_ip:
        return jsonify({"result": "invalid", "reason": "pod_ip 누락"}), 400

    with _lock:
        svc = _service_of_ip(pod_ip)
        if svc is None:
            logger.warning("미등록 pod_ip=%s → invalid", pod_ip)
            return jsonify({"result": "invalid", "reason": "unknown pod"})

        seen = request_seen.setdefault(svc, {})
        ip_set = seen.get(signature)
        if ip_set is None:
            # 최초 관측 → 이 pod 만 봄 → invalid (논문: 첫 등장은 drop 대상)
            seen[signature] = {pod_ip}
            result = "invalid"
        elif ip_set == {pod_ip}:
            # 여전히 이 pod 만 → invalid
            result = "invalid"
        else:
            # 다른 replica 도 관측 → valid
            ip_set.add(pod_ip)
            result = "valid"

    return jsonify({"result": result})


@app.route("/health")
def health():
    with _lock:
        snap = {svc: [p["ip"] for p in pods] for svc, pods in pod_registry.items()}
    return jsonify({"status": "ok", "pods": snap})


if __name__ == "__main__":
    threading.Thread(target=_update_loop, name="pod-info-provider", daemon=True).start()
    logger.info("Control Plane 시작 — ns=%s, interval=%ds, services=%s, pods_ip_port=%d",
                NAMESPACE, UPDATE_INTERVAL, KNOWN_SERVICES, PODS_IP_PORT)
    app.run(host="0.0.0.0", port=8080)
