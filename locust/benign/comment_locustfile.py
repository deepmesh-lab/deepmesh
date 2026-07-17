# comment_locustfile.py — comment-service 정상 트래픽 (공유 하네스 기반)
#
# 실행:
#   $env:HOST="http://<comment-pod-ip>:8080"; $env:AUTH_HOST="http://<auth-pod-ip>:8080"; $env:POST_HOST="http://<post-pod-ip>:8080"
#   locust -f locust/benign/comment_locustfile.py --host $env:HOST --headless -u 20 -r 4 -t 600s
#
# BaseUser 상속: attack 과 동일 pacing + 공통 헤더. 읽기 위주 + 자연 4xx.
# ★ 상태 정리(net-zero): 이 유저가 만든 (1) 댓글 전부, (2) setup 에서 만든 seed 게시물 전부를
#   on_stop 에서 삭제한다. (댓글 조회는 comment→post exists, 댓글 작성은 comment→auth validate + comment→post exists
#   east-west 를 정상적으로 유발한다.)

from __future__ import annotations   # Python 3.7+ 에서 str|None 등 표기 호환(런타임 평가 안 함)

import os
import sys
import uuid
import random
import logging

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import BaseUser, SHARED_HEADERS  # noqa: E402
from locust import task  # noqa: E402

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")
POST_HOST = os.environ.get("POST_HOST", "http://localhost:8080")


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {"username": f"user_{uid}", "password": "Test@12345!"}  # email 없음(SignupRequest 스키마)


def _signup_and_login(credentials: dict) -> str | None:
    try:
        requests.post(f"{AUTH_HOST}/api/auth/signup", json=credentials, headers=SHARED_HEADERS, timeout=10)
    except Exception as exc:
        logger.warning("[auth signup] error: %s", exc)
    try:
        resp = requests.post(
            f"{AUTH_HOST}/api/auth/login",
            json={"username": credentials["username"], "password": credentials["password"]},
            headers=SHARED_HEADERS, timeout=10,
        )
        if resp.ok:
            return resp.json().get("accessToken")
    except Exception as exc:
        logger.warning("[auth login] error: %s", exc)
    return None


def _fetch_post_ids(token: str | None) -> list[int]:
    headers = dict(SHARED_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(f"{POST_HOST}/api/posts?page=1&size=10", headers=headers, timeout=10)
        if resp.ok:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("data", [])
            return [item["postId"] for item in items if "postId" in item]
        logger.warning("[fetch_post_ids] status=%s (POST_HOST=%s)", resp.status_code, POST_HOST)
    except Exception as exc:
        logger.warning("[fetch_post_ids] error: %s (POST_HOST=%s)", exc, POST_HOST)
    return []


def _create_post(token: str | None) -> int | None:
    headers = dict(SHARED_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    uid = uuid.uuid4().hex[:8]
    try:
        resp = requests.post(
            f"{POST_HOST}/api/posts",
            json={"title": f"Seed Post {uid}", "content": f"Seed content {uid}"},
            headers=headers, timeout=10,
        )
        if resp.ok:
            return resp.json().get("postId")
        logger.warning("[create_post seed] status=%s (POST_HOST=%s)", resp.status_code, POST_HOST)
    except Exception as exc:
        logger.warning("[create_post seed] error: %s (POST_HOST=%s)", exc, POST_HOST)
    return None


def _delete_post(token: str | None, pid: int) -> None:
    """seed 게시물 정리용 — post-service 에 DELETE (삭제 시 남은 댓글도 연쇄삭제됨)."""
    headers = dict(SHARED_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        requests.delete(f"{POST_HOST}/api/posts/{pid}", headers=headers, timeout=10)
    except Exception as exc:
        logger.warning("[cleanup seed post] id=%s error=%s (POST_HOST=%s)", pid, exc, POST_HOST)


class CommentUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        self._credentials = _random_user()
        self._access_token: str | None = _signup_and_login(self._credentials)
        self._post_ids: list[int] = _fetch_post_ids(self._access_token)   # 기존 글(타인) — 삭제 대상 아님
        self._my_seed_posts: list[int] = []                                # 내가 만든 seed 글 — 정리 대상
        self._comment_ids: list[tuple[int, int]] = []                      # 내가 만든 (pid,cid) — 정리 대상
        if not self._post_ids:
            for _ in range(3):
                pid = _create_post(self._access_token)
                if pid:
                    self._post_ids.append(pid)
                    self._my_seed_posts.append(pid)
        if not self._post_ids:
            logger.warning("[CommentUser setup] post_id 확보 실패 (AUTH=%s POST=%s)", AUTH_HOST, POST_HOST)

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    def _ensure_token(self):
        if not self._access_token:
            self._access_token = _signup_and_login(self._credentials)

    def _random_post_id(self) -> int | None:
        return random.choice(self._post_ids) if self._post_ids else None

    def _random_comment(self) -> tuple[int, int] | None:
        return random.choice(self._comment_ids) if self._comment_ids else None

    # ------------------------------------------------------------------ #
    @task(5)
    def list_comments(self):
        pid = self._random_post_id()
        if pid is None:
            return
        with self.client.get(
            f"/api/comments/{pid}/comments", headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[pid]/comments",
        ) as resp:
            if not resp.ok:
                logger.warning("[list_comments] pid=%s status=%s", pid, resp.status_code)
                resp.failure(f"list_comments failed: {resp.status_code}")

    @task(2)
    def create_comment(self):
        pid = self._random_post_id()
        if pid is None:
            return
        uid = uuid.uuid4().hex[:8]
        with self.client.post(
            f"/api/comments/{pid}/comments", json={"content": f"Test comment {uid} for post {pid}."},
            headers=self._auth_headers(), catch_response=True, name="/api/comments/[pid]/comments [create]",
        ) as resp:
            if resp.ok:
                try:
                    cid = resp.json().get("commentId")
                    if cid:
                        self._comment_ids.append((pid, cid))
                except Exception:
                    pass
            else:
                logger.warning("[create_comment] pid=%s status=%s", pid, resp.status_code)
                resp.failure(f"create_comment failed: {resp.status_code}")

    @task(1)
    def update_comment(self):
        entry = self._random_comment()
        if entry is None:
            return
        _pid, cid = entry
        uid = uuid.uuid4().hex[:8]
        with self.client.put(
            f"/api/comments/{cid}", json={"content": f"Updated comment {uid}."},
            headers=self._auth_headers(), catch_response=True, name="/api/comments/[cid] [update]",
        ) as resp:
            if resp.status_code == 404:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
                resp.success()
            elif not resp.ok:
                logger.warning("[update_comment] cid=%s status=%s", cid, resp.status_code)
                resp.failure(f"update_comment failed: {resp.status_code}")

    @task(1)
    def delete_comment(self):
        entry = self._random_comment()
        if entry is None:
            return
        _pid, cid = entry
        with self.client.delete(
            f"/api/comments/{cid}", headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[cid] [delete]",
        ) as resp:
            if resp.ok or resp.status_code == 404:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
                resp.success()
            else:
                logger.warning("[delete_comment] cid=%s status=%s", cid, resp.status_code)
                resp.failure(f"delete_comment failed: {resp.status_code}")

    # 자연스러운 4xx (benign) — 없는 글의 댓글 조회 404(스테일 링크).
    @task(1)
    def benign_missing_comments(self):
        pid = random.randint(1, 100000)
        with self.client.get(
            f"/api/comments/{pid}/comments", headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[missing]/comments→404",
        ) as resp:
            resp.success()

    # ------------------------------------------------------------------ #
    # 정리(net-zero): 내가 만든 댓글 → seed 게시물 순으로 전부 삭제 → 수집 전/후 상태 무변경        #
    # ------------------------------------------------------------------ #
    def on_stop(self):
        self._ensure_token()
        # 1) 내가 만든 댓글 삭제 (comment-service)
        for entry in list(self._comment_ids):
            _pid, cid = entry
            try:
                with self.client.delete(
                    f"/api/comments/{cid}", headers=self._auth_headers(),
                    catch_response=True, name="/api/comments/[cleanup] [delete]",
                ) as resp:
                    if resp.ok or resp.status_code == 404:
                        resp.success()
                    else:
                        resp.failure(f"cleanup delete failed: {resp.status_code}")
            except Exception as exc:
                logger.warning("[cleanup comment] cid=%s error=%s", cid, exc)
            finally:
                if entry in self._comment_ids:
                    self._comment_ids.remove(entry)
        # 2) setup 에서 내가 만든 seed 게시물 삭제 (post-service) — 남은 댓글은 연쇄삭제됨
        for pid in list(self._my_seed_posts):
            _delete_post(self._access_token, pid)
            self._my_seed_posts.remove(pid)
