# comment_locustfile.py
# 실행 방법:
#   locust -f comment_locustfile.py --host http://<INGRESS_IP>:30080 \
#          --users 20 --spawn-rate 4 --run-time 300s --headless
#
# 환경변수:
#   HOST       - comment-service URL (기본값: http://localhost:8080)
#   AUTH_HOST  - auth-service URL (기본값: http://localhost:8080)
#   POST_HOST  - post-service URL  (기본값: http://localhost:8080)

import os
import uuid
import random
import logging

import requests
from locust import HttpUser, task, between

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")
POST_HOST = os.environ.get("POST_HOST", "http://localhost:8080")


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


def _fetch_post_ids(token: str | None) -> list[int]:
    """post-service에서 post id 목록 조회"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.get(
            f"{POST_HOST}/api/posts?page=0&size=10",
            headers=headers,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            items = (
                data if isinstance(data, list) else data.get("content", [])
            )
            return [item["id"] for item in items if "id" in item]
    except Exception as exc:
        logger.warning("[fetch_post_ids] error: %s", exc)
    return []


def _create_post(token: str | None) -> int | None:
    """post-service에서 임시 post 생성 후 id 반환"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    uid = uuid.uuid4().hex[:8]
    try:
        resp = requests.post(
            f"{POST_HOST}/api/posts",
            json={"title": f"Seed Post {uid}", "content": f"Seed content {uid}"},
            headers=headers,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            return data.get("id")
    except Exception as exc:
        logger.warning("[create_post seed] error: %s", exc)
    return None


class CommentUser(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8080")
    wait_time = between(1, 3)

    def on_start(self):
        """초기화: login 후 post_id 목록 확보"""
        self._credentials = _random_user()
        self._access_token: str | None = _signup_and_login(self._credentials)
        self._post_ids: list[int] = []
        self._comment_ids: list[int] = []  # (post_id, comment_id) 튜플 목록

        # post_id 목록 조회
        self._post_ids = _fetch_post_ids(self._access_token)

        # post 없으면 하나 생성
        if not self._post_ids:
            pid = _create_post(self._access_token)
            if pid:
                self._post_ids.append(pid)

        if not self._post_ids:
            logger.warning("[CommentUser on_start] post_id 확보 실패")

    # ------------------------------------------------------------------ #
    # helper                                                               #
    # ------------------------------------------------------------------ #

    def _auth_headers(self) -> dict:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    def _random_post_id(self) -> int | None:
        return random.choice(self._post_ids) if self._post_ids else None

    def _random_comment(self) -> tuple[int, int] | None:
        """저장된 (post_id, comment_id) 중 랜덤 반환"""
        return random.choice(self._comment_ids) if self._comment_ids else None

    # ------------------------------------------------------------------ #
    # tasks                                                                #
    # ------------------------------------------------------------------ #

    @task(5)
    def list_comments(self):
        pid = self._random_post_id()
        if pid is None:
            return

        with self.client.get(
            f"/api/posts/{pid}/comments",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                try:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("content", [])
                    for item in items:
                        cid = item.get("id")
                        if cid:
                            entry = (pid, cid)
                            if entry not in self._comment_ids:
                                self._comment_ids.append(entry)
                except Exception:
                    pass
            else:
                logger.warning(
                    "[list_comments] post_id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"list_comments failed: {resp.status_code}")

    @task(3)
    def create_comment(self):
        pid = self._random_post_id()
        if pid is None:
            return

        uid = uuid.uuid4().hex[:8]
        payload = {"content": f"Test comment {uid} for post {pid}."}
        with self.client.post(
            f"/api/posts/{pid}/comments",
            json=payload,
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                try:
                    data = resp.json()
                    cid = data.get("id")
                    if cid:
                        self._comment_ids.append((pid, cid))
                except Exception:
                    pass
            else:
                logger.warning(
                    "[create_comment] post_id=%s status=%s body=%s",
                    pid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"create_comment failed: {resp.status_code}")

    @task(1)
    def update_comment(self):
        entry = self._random_comment()
        if entry is None:
            return

        _post_id, cid = entry
        uid = uuid.uuid4().hex[:8]
        with self.client.put(
            f"/api/comments/{cid}",
            json={"content": f"Updated comment {uid}."},
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if not resp.ok:
                logger.warning(
                    "[update_comment] id=%s status=%s body=%s",
                    cid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"update_comment failed: {resp.status_code}")

    @task(1)
    def delete_comment(self):
        entry = self._random_comment()
        if entry is None:
            return

        _post_id, cid = entry
        with self.client.delete(
            f"/api/comments/{cid}",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
            else:
                logger.warning(
                    "[delete_comment] id=%s status=%s body=%s",
                    cid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"delete_comment failed: {resp.status_code}")
