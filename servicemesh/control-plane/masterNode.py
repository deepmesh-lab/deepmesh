"""
Control Plane — Pod Info Provider + Request Verifier
포트: 8080
환경변수:
  NAMESPACE=deepmesh
  UPDATE_INTERVAL=30  (초, Pod IP 목록 갱신 주기)
  KNOWN_SERVICES=auth-service,post-service,comment-service
"""
from flask import Flask, request, jsonify
import kubernetes
import threading
import time
import logging
import base64
import os

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

NAMESPACE = os.environ.get("NAMESPACE", "deepmesh")
UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "30"))
KNOWN_SERVICES = [
    s.strip()
    for s in os.environ.get(
        "KNOWN_SERVICES", "auth-service,post-service,comment-service"
    ).split(",")
    if s.strip()
]

# Pod IP 레지스트리: { "auth-service": ["10.0.0.1", ...], ... }
pod_registry: dict[str, list[str]] = {svc: [] for svc in KNOWN_SERVICES}
registry_lock = threading.Lock()

app = Flask(__name__)


# ──────────────────────────────────────────────
# Pod Info Provider
# ──────────────────────────────────────────────

def _load_k8s_client() -> kubernetes.client.CoreV1Api:
    """
    in-cluster config 우선, 실패 시 kubeconfig fallback.
    """
    try:
        kubernetes.config.load_incluster_config()
        logger.info("K8s in-cluster config 로드 성공")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("K8s kubeconfig 로드 성공 (fallback)")
    return kubernetes.client.CoreV1Api()


def update_pod_registry() -> None:
    """
    K8s API를 통해 deepmesh 네임스페이스 Pod 목록을 조회하고
    pod_registry 딕셔너리를 갱신한다.

    pod_registry 구조:
    {
        "auth-service":    ["10.0.0.1", "10.0.0.2"],
        "post-service":    ["10.0.0.3"],
        "comment-service": ["10.0.0.4"],
    }
    """
    try:
        v1 = _load_k8s_client()
    except Exception as exc:
        logger.error("K8s 클라이언트 초기화 실패: %s", exc)
        return

    while True:
        new_registry: dict[str, list[str]] = {svc: [] for svc in KNOWN_SERVICES}
        try:
            for svc in KNOWN_SERVICES:
                pods = v1.list_namespaced_pod(
                    namespace=NAMESPACE,
                    label_selector=f"app={svc}",
                )
                ips = [
                    pod.status.pod_ip
                    for pod in pods.items
                    if pod.status and pod.status.pod_ip
                    and pod.status.phase == "Running"
                ]
                new_registry[svc] = ips
                logger.debug("서비스=%s, Pod IPs=%s", svc, ips)

            with registry_lock:
                pod_registry.update(new_registry)

            all_ips = sum(len(v) for v in new_registry.values())
            logger.info("Pod 레지스트리 갱신 완료: 총 %d개 Pod IP", all_ips)

        except Exception as exc:
            logger.error("Pod 레지스트리 갱신 중 오류: %s", exc)

        time.sleep(UPDATE_INTERVAL)


# ──────────────────────────────────────────────
# Request Verifier API
# ──────────────────────────────────────────────

def _all_known_ips() -> set[str]:
    """pod_registry에 등록된 모든 Pod IP를 flat set으로 반환."""
    with registry_lock:
        return {ip for ips in pod_registry.values() for ip in ips}


@app.route("/send/internal_request_body", methods=["POST"])
def verify_request():
    """
    이상 트래픽 최종 허가/거부 판정 엔드포인트.

    요청 body (JSON):
    {
        "request_body": "<base64 encoded bytes>",
        "headers":      { ... },
        "source_ip":    "10.0.0.x"   (선택)
    }

    판정 로직:
    1. source_ip가 알려진 Pod IP에 없으면 → deny
    2. request_body 디코딩 후 최소 길이 미달 → deny
    3. 위 조건 통과 → allow

    반환:
    { "allow": true/false, "reason": "..." }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"allow": False, "reason": "요청 body 파싱 실패"}), 400

    source_ip: str | None = data.get("source_ip")
    encoded_body: str | None = data.get("request_body")

    # ── 1. source_ip 검증 ──────────────────────
    if source_ip:
        known_ips = _all_known_ips()
        if known_ips and source_ip not in known_ips:
            logger.warning("알 수 없는 source_ip=%s → deny", source_ip)
            return jsonify(
                {"allow": False, "reason": f"알 수 없는 출발지 IP: {source_ip}"}
            )
    else:
        logger.debug("source_ip 미제공 — IP 검증 생략")

    # ── 2. request_body 기본 검증 ──────────────
    if not encoded_body:
        return jsonify({"allow": False, "reason": "request_body 필드 없음"})

    try:
        raw_body: bytes = base64.b64decode(encoded_body)
    except Exception:
        return jsonify({"allow": False, "reason": "request_body base64 디코딩 실패"})

    MIN_BODY_LEN = 1
    if len(raw_body) < MIN_BODY_LEN:
        logger.warning("request_body 너무 짧음 (len=%d) → deny", len(raw_body))
        return jsonify(
            {"allow": False, "reason": f"request_body 길이 부족 ({len(raw_body)} bytes)"}
        )

    # ── 3. 허용 ───────────────────────────────
    logger.info("요청 허용: source_ip=%s, body_len=%d", source_ip, len(raw_body))
    return jsonify({"allow": True, "reason": "검증 통과"})


# ──────────────────────────────────────────────
# Health 엔드포인트
# ──────────────────────────────────────────────

@app.route("/health")
def health():
    with registry_lock:
        snapshot = {svc: list(ips) for svc, ips in pod_registry.items()}
    return jsonify({"status": "ok", "pods": snapshot})


# ──────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Pod Info Provider 백그라운드 스레드 시작
    t = threading.Thread(target=update_pod_registry, daemon=True, name="pod-info-provider")
    t.start()
    logger.info(
        "Control Plane 시작 — namespace=%s, interval=%ds, services=%s",
        NAMESPACE, UPDATE_INTERVAL, KNOWN_SERVICES,
    )
    app.run(host="0.0.0.0", port=8080)
