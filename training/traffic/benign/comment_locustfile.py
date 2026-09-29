# comment-service의 정상 댓글 흐름을 생성.
from __future__ import annotations

import os
import sys
import uuid
import random
import logging

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import (  # noqa: E402
    BaseUser, SHARED_HEADERS, H_JSON, H_JSON_AUTH, H_AUTH,
    CORS_ORIGIN, cors_request_header_names, needs_preflight, think,
)
from locust import task  # noqa: E402

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")
POST_HOST = os.environ.get("POST_HOST", "http://localhost:8080")

PAGE_SIZE = 10
HOT_POST_IDS = [int(x) for x in os.environ.get("HOT_POST_IDS", "1,2,3,4,5").split(",") if x.strip()]
HOT_READ_BIAS = 0.55
HOT_WRITE_BIAS = 0.65
MISSING_ID_LO, MISSING_ID_HI = 100_000, 999_999


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {"username": f"user_{uid}", "password": "Test@12345!"}

# 보조 호출의 preflight 전송
def _aux_preflight(cache: dict, url: str, method: str, extra_headers) -> None:
    if not needs_preflight(method, extra_headers):
        return
    key = (method.upper(), url)
    if key in cache:
        return
    headers = dict(SHARED_HEADERS)
    headers["Origin"] = CORS_ORIGIN
    headers["Access-Control-Request-Method"] = method.upper()
    acrh = cors_request_header_names(extra_headers)
    if acrh:
        headers["Access-Control-Request-Headers"] = acrh
    try:
        requests.options(url, headers=headers, timeout=10)
        cache[key] = True
    except Exception as exc:
        logger.warning("[aux preflight] %s %s error=%s", method, url, exc)


def _signup_and_login(credentials: dict, pf_cache: dict) -> str | None:
    signup_url = f"{AUTH_HOST}/api/auth/signup"
    login_url = f"{AUTH_HOST}/api/auth/login"
    _aux_preflight(pf_cache, signup_url, "POST", H_JSON)
    try:
        requests.post(signup_url, json=credentials, headers=SHARED_HEADERS, timeout=10)
    except Exception as exc:
        logger.warning("[auth signup] error: %s", exc)
    _aux_preflight(pf_cache, login_url, "POST", H_JSON)
    try:
        resp = requests.post(
            login_url,
            json={"username": credentials["username"], "password": credentials["password"]},
            headers=SHARED_HEADERS, timeout=10,
        )
        if resp.ok:
            return resp.json().get("accessToken")
        logger.warning("[auth login] status=%s", resp.status_code)
    except Exception as exc:
        logger.warning("[auth login] error: %s", exc)
    return None

# 열람할 게시글 ID 조회
def _fetch_post_ids(pages: int = 2) -> list[int]:
    ids: list[int] = []
    for page in range(1, pages + 1):
        try:
            resp = requests.get(
                f"{POST_HOST}/api/posts?page={page}&size={PAGE_SIZE}",
                headers=SHARED_HEADERS, timeout=10,
            )
            if not resp.ok:
                logger.warning("[fetch_post_ids] page=%s status=%s", page, resp.status_code)
                continue
            for item in resp.json().get("data", []):
                pid = item.get("postId")
                if pid and pid not in ids:
                    ids.append(pid)
        except Exception as exc:
            logger.warning("[fetch_post_ids] page=%s error=%s (POST_HOST=%s)", page, exc, POST_HOST)
    return ids


class CommentUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        self._credentials = _random_user()
        self._aux_pf_cache: dict = {}
        self._access_token: str | None = _signup_and_login(self._credentials, self._aux_pf_cache)
        self._post_ids: list[int] = _fetch_post_ids()
        self._comment_ids: list[tuple[int, int]] = []
        self._hot_post = random.choice(HOT_POST_IDS) if HOT_POST_IDS else None
        for pid in HOT_POST_IDS:
            if pid not in self._post_ids:
                self._post_ids.append(pid)
        if not self._post_ids:
            logger.warning("[CommentUser setup] post_id 확보 실패 (POST_HOST=%s)", POST_HOST)

    def _ensure_token(self):
        if not self._access_token:
            self._access_token = _signup_and_login(self._credentials, self._aux_pf_cache)

    def _auth_headers(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    def _reauth_if_unauthorized(self, resp) -> bool:
        if resp.status_code == 401: # 401 응답이면 토큰을 다시 발급
            self._access_token = None
            self._ensure_token()
            return True
        return False

    # 인기 게시글 우선 선택
    def _pick_post(self, hot_bias: float) -> int | None:
        if self._hot_post is not None and random.random() < hot_bias:
            return self._hot_post
        return random.choice(self._post_ids) if self._post_ids else None

    # 댓글 첫 페이지를 조회
    def _load_first_page(self, pid: int, name: str) -> dict | None:
        
        with self.client.get(
            f"/api/comments/{pid}/comments?size={PAGE_SIZE}",
            catch_response=True, name=name,
        ) as resp:
            if resp.status_code == 404:
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                resp.success()
                return None
            if not resp.ok:
                logger.warning("[list_comments] pid=%s status=%s", pid, resp.status_code)
                resp.failure(f"list_comments failed: {resp.status_code}")
                return None
            try:
                return resp.json()
            except Exception:
                return None

    def _forget_comment(self, entry):
        if entry in self._comment_ids:
            self._comment_ids.remove(entry)

    # 댓글 목록
    @task(5)
    def task_list_comments(self):
        pid = self._pick_post(HOT_READ_BIAS)
        if pid is None:
            return
        data = self._load_first_page(pid, name="/api/comments/[pid]/comments?size=10")
        if not data:
            return
        cursor = data.get("nextCursor")
        if data.get("hasNext") and cursor is not None and random.random() < 0.5:
            think(self, scale=0.4)   # 다음 페이지로 스크롤하기 전 짧은 열람 지연
            with self.client.get(
                f"/api/comments/{pid}/comments?cursor={cursor}&size={PAGE_SIZE}",
                catch_response=True, name="/api/comments/[pid]/comments?cursor=[c]&size=10",
            ) as resp:
                if resp.status_code == 404:
                    resp.success()
                elif not resp.ok:
                    logger.warning("[load_more] pid=%s cursor=%s status=%s", pid, cursor, resp.status_code)
                    resp.failure(f"load_more failed: {resp.status_code}")

    # 댓글 작성
    @task(2)
    def task_create_comment(self):
        pid = self._pick_post(HOT_WRITE_BIAS)
        if pid is None:
            return
        path = f"/api/comments/{pid}/comments"
        self.preflight("POST", path, H_JSON_AUTH, name="OPTIONS /api/comments/[pid]/comments")
        uid = uuid.uuid4().hex[:8]
        with self.client.post(
            path, json={"content": f"Test comment {uid} for post {pid}."},
            headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[pid]/comments [create]",
        ) as resp:
            if resp.status_code == 201:
                resp.success()
                try:
                    cid = resp.json().get("commentId")
                    if cid:
                        self._comment_ids.append((pid, cid))
                except Exception:
                    pass
            elif resp.status_code == 404:
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                resp.success()
                return
            elif self._reauth_if_unauthorized(resp):
                resp.success()
                return
            else:
                logger.warning("[create_comment] pid=%s status=%s", pid, resp.status_code)
                resp.failure(f"create_comment failed: {resp.status_code}")
                return
        think(self)   # 작성 후 결과를 확인하는 사용자 지연
        self._load_first_page(pid, name="/api/comments/[pid]/comments [reload]")

    # 댓글 수정
    @task(1)
    def task_update_comment(self):
        if not self._comment_ids:
            return
        entry = random.choice(self._comment_ids)
        pid, cid = entry
        path = f"/api/comments/{cid}"
        self.preflight("PUT", path, H_JSON_AUTH, name="OPTIONS /api/comments/[cid]")
        uid = uuid.uuid4().hex[:8]
        with self.client.put(
            path, json={"content": f"Updated comment {uid}."},
            headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[cid] [update]",
        ) as resp:
            if resp.status_code == 404:
                self._forget_comment(entry)
                resp.success()
                return
            if self._reauth_if_unauthorized(resp):
                resp.success()
                return
            if not resp.ok:
                logger.warning("[update_comment] cid=%s status=%s", cid, resp.status_code)
                resp.failure(f"update_comment failed: {resp.status_code}")
                return
        think(self)   # 수정 후 결과를 확인하는 사용자 지연
        self._load_first_page(pid, name="/api/comments/[pid]/comments [reload]")

    # 댓글 삭제
    @task(1)
    def task_delete_comment(self):
        if not self._comment_ids:
            return
        entry = random.choice(self._comment_ids)
        pid, cid = entry
        path = f"/api/comments/{cid}"
        self.preflight("DELETE", path, H_AUTH, name="OPTIONS /api/comments/[cid]")
        with self.client.delete(
            path, headers=self._auth_headers(),
            catch_response=True, name="/api/comments/[cid] [delete]",
        ) as resp:
            if resp.ok or resp.status_code == 404:
                self._forget_comment(entry)
                resp.success()
            elif self._reauth_if_unauthorized(resp):
                resp.success()
                return
            else:
                logger.warning("[delete_comment] cid=%s status=%s", cid, resp.status_code)
                resp.failure(f"delete_comment failed: {resp.status_code}")
                return
        think(self)   # 삭제 후 결과를 확인하는 사용자 지연
        self._load_first_page(pid, name="/api/comments/[pid]/comments [reload]")

    # 존재하지 않는 게시글의 댓글 조회
    @task(1)
    def task_missing_post_comments(self):
        pid = random.randint(MISSING_ID_LO, MISSING_ID_HI)
        with self.client.get(
            f"/api/comments/{pid}/comments?size={PAGE_SIZE}",
            catch_response=True, name="/api/comments/[missing-404]/comments",
        ) as resp:
            resp.success()
