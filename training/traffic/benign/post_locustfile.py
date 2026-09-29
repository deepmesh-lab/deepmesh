# post-service의 정상 게시글 흐름을 생성
# 읽기는 비인증 size=10을 사용하며 쓰기는 토큰을 검증
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
    CORS_ORIGIN, cors_request_header_names, needs_preflight,
)
from locust import task  # noqa: E402

logger = logging.getLogger(__name__)

AUTH_HOST = os.environ.get("AUTH_HOST", "http://localhost:8080")

PAGE_SIZE = 10
# 존재하지 않는 게시글 범위
MISSING_ID_LO, MISSING_ID_HI = 100_000, 999_999


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {"username": f"user_{uid}", "password": "Test@12345!"}

# auth 보조 호출의 preflight를 전송
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

# 테스트 사용자를 생성하고 로그인
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


class PostUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        self._credentials = _random_user()
        self._aux_pf_cache: dict = {}
        self._access_token: str | None = _signup_and_login(self._credentials, self._aux_pf_cache)
        self._post_ids: list[int] = []
        self._my_post_ids: list[int] = []
        self._page = 1
        self._total_page = 1
        if not self._access_token:
            logger.warning("[PostUser setup] 토큰 획득 실패, 일부 쓰기 작업이 실패할 수 있음")

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

    def _forget(self, pid: int):
        self._post_ids = [x for x in self._post_ids if x != pid]
        self._my_post_ids = [x for x in self._my_post_ids if x != pid]

    def _random_post_id(self) -> int | None:
        return random.choice(self._post_ids) if self._post_ids else None

    def _random_my_post_id(self) -> int | None:
        return random.choice(self._my_post_ids) if self._my_post_ids else None

    # 목록 페이지를 선택
    def _next_page(self) -> int:
        r = random.random()
        if r < 0.60:
            self._page = 1
        elif r < 0.85:
            self._page = min(self._page + 1, max(1, self._total_page))
        else:
            self._page = max(1, self._page - 1)
        return self._page

    # 게시글 목록
    @task(5)
    def task_list_posts(self):
        page = self._next_page()
        with self.client.get(
            f"/api/posts?page={page}&size={PAGE_SIZE}",
            catch_response=True, name="/api/posts?page=[p]&size=10",
        ) as resp:
            if not resp.ok:
                logger.warning("[list_posts] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"list_posts failed: {resp.status_code}")
                return
            try:
                data = resp.json()
                self._total_page = max(1, int(data.get("totalPage", 1)))
                for item in data.get("data", []):
                    pid = item.get("postId")
                    if pid and pid not in self._post_ids:
                        self._post_ids.append(pid)
            except Exception:
                pass

    # 게시글 상세
    @task(6)
    def task_get_post(self):
        pid = self._random_post_id()
        if pid is None:
            return
        with self.client.get(
            f"/api/posts/{pid}", catch_response=True, name="/api/posts/[id]",
        ) as resp:
            if resp.status_code == 404:
                self._forget(pid)
                resp.success()
            elif not resp.ok:
                logger.warning("[get_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"get_post failed: {resp.status_code}")

    # 게시글 작성
    @task(1)
    def task_create_post(self):
        self.preflight("POST", "/api/posts", H_JSON_AUTH, name="OPTIONS /api/posts")
        uid = uuid.uuid4().hex[:8]
        payload = {
            "title": f"Test Post {uid}",
            "content": f"This is test content for post {uid}. "
                       f"Generated for traffic simulation.",
        }
        with self.client.post(
            "/api/posts", json=payload, headers=self._auth_headers(),
            catch_response=True, name="/api/posts [create]",
        ) as resp:
            if resp.status_code == 201:
                resp.success()
                try:
                    pid = resp.json().get("postId")
                    if pid:
                        if pid not in self._post_ids:
                            self._post_ids.append(pid)
                        if pid not in self._my_post_ids:
                            self._my_post_ids.append(pid)
                except Exception:
                    pass
            elif self._reauth_if_unauthorized(resp):
                resp.success()
            else:
                logger.warning("[create_post] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"create_post failed: {resp.status_code}")

    # 게시글 수정
    @task(1)
    def task_update_post(self):
        pid = self._random_my_post_id()
        if pid is None:
            return
        path = f"/api/posts/{pid}"
        self.preflight("PUT", path, H_JSON_AUTH, name="OPTIONS /api/posts/[id]")
        uid = uuid.uuid4().hex[:8]
        payload = {"title": f"Updated Post {uid}", "content": f"Updated content {uid}."}
        with self.client.put(
            path, json=payload, headers=self._auth_headers(),
            catch_response=True, name="/api/posts/[id] [update]",
        ) as resp:
            if resp.status_code == 404:
                self._forget(pid)
                resp.success()
            elif self._reauth_if_unauthorized(resp):
                resp.success()
            elif not resp.ok:
                logger.warning("[update_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"update_post failed: {resp.status_code}")

    # 게시글 삭제
    @task(1)
    def task_delete_post(self):
        pid = self._random_my_post_id()
        if pid is None:
            return
        path = f"/api/posts/{pid}"
        self.preflight("DELETE", path, H_AUTH, name="OPTIONS /api/posts/[id]")
        with self.client.delete(
            path, headers=self._auth_headers(),
            catch_response=True, name="/api/posts/[id] [delete]",
        ) as resp:
            if resp.ok or resp.status_code == 404:
                self._forget(pid)
                resp.success()
            elif self._reauth_if_unauthorized(resp):
                resp.success()
            else:
                logger.warning("[delete_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"delete_post failed: {resp.status_code}")

    # 존재하지 않는 게시글
    @task(1)
    def task_missing_post(self):
        pid = random.randint(MISSING_ID_LO, MISSING_ID_HI)
        with self.client.get(
            f"/api/posts/{pid}", catch_response=True, name="/api/posts/[missing-404]",
        ) as resp:
            resp.success()
