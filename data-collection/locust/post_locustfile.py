# post_locustfile.py
# 실행 방법:
#   locust -f post_locustfile.py --host http://<INGRESS_IP>:30080 \
#          --users 20 --spawn-rate 4 --run-time 300s --headless
#
# 환경변수:
#   HOST       - post-service URL (기본값: http://localhost:8080)
#   AUTH_HOST  - auth-service URL (기본값: http://localhost:8080)

import os
import uuid
import random
import logging

import requests
from locust import HttpUser, task, between

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {
        "username": f"user_{uid}",
        "email": f"user_{uid}@test.local",
        "password": "Test@12345!",
    }


def _signup_and_login(credentials: dict) -> str | None:
    """auth-service에서 signup → login 후 access token 반환"""
    try:
        requests.post(f"{AUTH_HOST}/api/auth/signup", json=credentials, timeout=10)
    except Exception as exc:
        logger.warning("[auth signup] error: %s", exc)

    try:
        resp = requests.post(
            f"{AUTH_HOST}/api/auth/login",
            json={"username": credentials["username"], "password": credentials["password"]},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            return data.get("accessToken") or data.get("access_token")
    except Exception as exc:
        logger.warning("[auth login] error: %s", exc)

    return None


class PostUser(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8080")
    wait_time = between(1, 3)

    def on_start(self):
        """초기화: auth-service 로그인 후 토큰 획득"""
        self._credentials = _random_user()
        self._access_token: str | None = _signup_and_login(self._credentials)
        self._post_ids: list[int] = []       # 읽기용(목록에서 수집, 남의 글 포함)
        self._my_post_ids: list[int] = []    # 내가 만든 글만(수정/삭제 대상 — 소유권 403 방어)

        if not self._access_token:
            logger.warning("[PostUser on_start] 토큰 획득 실패 - 비인증 상태로 진행")

    # ------------------------------------------------------------------ #
    # helper                                                               #
    # ------------------------------------------------------------------ #

    def _auth_headers(self) -> dict:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    def _random_post_id(self) -> int | None:
        return random.choice(self._post_ids) if self._post_ids else None

    def _random_my_post_id(self) -> int | None:
        return random.choice(self._my_post_ids) if self._my_post_ids else None

    # ------------------------------------------------------------------ #
    # tasks                                                                #
    # ------------------------------------------------------------------ #

    @task(5)
    def list_posts(self):
        # 정상 트래픽의 다양성 확보를 위해 page/size 를 변화시킨다(서버는 1-based).
        page = random.randint(1, 3)
        size = random.choice([5, 10, 20])
        with self.client.get(
            f"/api/posts?page={page}&size={size}",
            headers=self._auth_headers(),
            catch_response=True,
            name="/api/posts?page=[p]&size=[s]",  # locust 통계에서 하나로 집계
        ) as resp:
            if resp.ok:
                # 서버 PostListResponse 는 목록을 'data' 필드에 담는다
                try:
                    data = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else data
                    for item in items:
                        pid = item.get("postId")   # PostResponse 는 postId 필드
                        if pid and pid not in self._post_ids:
                            self._post_ids.append(pid)
                except Exception:
                    pass
            else:
                logger.warning(
                    "[list_posts] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"list_posts failed: {resp.status_code}")

    @task(4)
    def get_post(self):
        pid = self._random_post_id()
        if pid is None:
            return

        with self.client.get(
            f"/api/posts/{pid}",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                # 다른 유저가 이미 삭제한 글 → 스테일 id 정리, benign 레이스로 처리(실패 아님)
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                resp.success()
            elif not resp.ok:
                logger.warning(
                    "[get_post] id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"get_post failed: {resp.status_code}")

    @task(2)
    def create_post(self):
        uid = uuid.uuid4().hex[:8]
        payload = {
            "title": f"Test Post {uid}",
            "content": f"This is test content for post {uid}. Generated for traffic simulation.",
        }
        with self.client.post(
            "/api/posts",
            json=payload,
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                try:
                    data = resp.json()
                    pid = data.get("postId")   # PostResponse 는 postId 필드
                    if pid:
                        if pid not in self._post_ids:
                            self._post_ids.append(pid)
                        if pid not in self._my_post_ids:
                            self._my_post_ids.append(pid)   # 내가 만든 글 → 수정/삭제 가능
                except Exception:
                    pass
            else:
                logger.warning(
                    "[create_post] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"create_post failed: {resp.status_code}")

    @task(1)
    def update_post(self):
        pid = self._random_my_post_id()   # 내 글만 수정(소유권 403 방어)
        if pid is None:
            return

        uid = uuid.uuid4().hex[:8]
        payload = {
            "title": f"Updated Post {uid}",
            "content": f"Updated content {uid}.",
        }
        with self.client.put(
            f"/api/posts/{pid}",
            json=payload,
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                # 이미 삭제된 내 글 → 정리 후 benign 처리
                if pid in self._my_post_ids:
                    self._my_post_ids.remove(pid)
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                resp.success()
            elif not resp.ok:
                logger.warning(
                    "[update_post] id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"update_post failed: {resp.status_code}")

    @task(1)
    def delete_post(self):
        pid = self._random_my_post_id()   # 내 글만 삭제(소유권 403 방어)
        if pid is None:
            return

        with self.client.delete(
            f"/api/posts/{pid}",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok or resp.status_code == 404:
                # 성공 또는 이미 삭제됨(레이스) → 정리, benign 처리
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                if pid in self._my_post_ids:
                    self._my_post_ids.remove(pid)
                resp.success()
            else:
                logger.warning(
                    "[delete_post] id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"delete_post failed: {resp.status_code}")
