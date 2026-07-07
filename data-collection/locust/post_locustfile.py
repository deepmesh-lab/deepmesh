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
            json={"email": credentials["email"], "password": credentials["password"]},
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
        self._post_ids: list[int] = []

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

    # ------------------------------------------------------------------ #
    # tasks                                                                #
    # ------------------------------------------------------------------ #

    @task(5)
    def list_posts(self):
        with self.client.get(
            "/api/posts?page=0&size=10",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                # 서버로부터 post id 목록 수집 (content 배열 지원)
                try:
                    data = resp.json()
                    items = (
                        data.get("content") or data
                        if isinstance(data, list)
                        else data.get("content", [])
                    )
                    for item in items:
                        pid = item.get("id")
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
            if not resp.ok:
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
                    pid = data.get("id")
                    if pid and pid not in self._post_ids:
                        self._post_ids.append(pid)
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
        pid = self._random_post_id()
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
            if not resp.ok:
                logger.warning(
                    "[update_post] id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"update_post failed: {resp.status_code}")

    @task(1)
    def delete_post(self):
        pid = self._random_post_id()
        if pid is None:
            return

        with self.client.delete(
            f"/api/posts/{pid}",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
            else:
                logger.warning(
                    "[delete_post] id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"delete_post failed: {resp.status_code}")
