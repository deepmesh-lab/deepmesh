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
            json={"username": credentials["username"], "password": credentials["password"]},
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
            f"{POST_HOST}/api/posts?page=1&size=10",   # 서버는 1-based(page>=1)
            headers=headers,
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            items = (
                data if isinstance(data, list) else data.get("data", [])  # PostListResponse.data
            )
            return [item["postId"] for item in items if "postId" in item]  # PostResponse.postId
        else:
            logger.warning(
                "[fetch_post_ids] status=%s body=%s (POST_HOST=%s)",
                resp.status_code, resp.text[:200], POST_HOST,
            )
    except Exception as exc:
        logger.warning("[fetch_post_ids] error: %s (POST_HOST=%s)", exc, POST_HOST)
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
            return data.get("postId")   # PostResponse.postId
        else:
            logger.warning(
                "[create_post seed] status=%s body=%s (POST_HOST=%s, token=%s)",
                resp.status_code, resp.text[:200], POST_HOST, bool(token),
            )
    except Exception as exc:
        logger.warning("[create_post seed] error: %s (POST_HOST=%s)", exc, POST_HOST)
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

        # post 없으면 여러 개 생성(댓글 대상 다양화)
        if not self._post_ids:
            for _ in range(3):
                pid = _create_post(self._access_token)
                if pid:
                    self._post_ids.append(pid)

        if not self._post_ids:
            logger.warning(
                "[CommentUser on_start] post_id 확보 실패 "
                "(token=%s, AUTH_HOST=%s, POST_HOST=%s) — 위 fetch/seed 경고의 status 확인",
                bool(self._access_token), AUTH_HOST, POST_HOST,
            )

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
            f"/api/comments/{pid}/comments",   # 실제 comment-service 경로(/api/comments/...)
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                # 읽기 트래픽만 생성. update/delete 대상은 '내가 만든 댓글'(_comment_ids)로만
                # 한정하므로, 여기서 남의 댓글 id 를 수집하지 않는다(소유권 403 방어).
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
            f"/api/comments/{pid}/comments",   # 실제 comment-service 경로
            json=payload,
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                try:
                    data = resp.json()
                    cid = data.get("commentId")   # CommentResponse.commentId
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
            if resp.status_code == 404:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
                resp.success()   # 이미 삭제됨(레이스) → benign 처리
            elif not resp.ok:
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
            if resp.ok or resp.status_code == 404:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
                resp.success()   # 성공 또는 이미 삭제됨(레이스) → benign 처리
            else:
                logger.warning(
                    "[delete_comment] id=%s status=%s body=%s",
                    cid,
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"delete_comment failed: {resp.status_code}")
