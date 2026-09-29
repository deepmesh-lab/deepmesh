# auth-service의 정상 인증 흐름을 생성(생성 데이터는 스냅샷 복원으로 정리)
from __future__ import annotations

import os
import sys
import uuid
import random
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import BaseUser, H_JSON, H_AUTH, think  # noqa: E402
from locust import task  # noqa: E402

logger = logging.getLogger(__name__)


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {"username": f"user_{uid}", "password": "Test@12345!"}


class AuthUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        self._credentials = _random_user()
        self._access_token: str | None = None
        self._do_signup(self._credentials, name="/api/auth/signup (setup)")
        self._do_login(name="/api/auth/login (setup)")

    def _do_signup(self, credentials: dict, name: str) -> int:
        self.preflight("POST", "/api/auth/signup", H_JSON, name="OPTIONS /api/auth/signup")
        with self.client.post(
            "/api/auth/signup", json=credentials, catch_response=True, name=name,
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            elif resp.status_code == 409:
                resp.success()
            else:
                logger.warning("[signup] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"signup failed: {resp.status_code}")
            return resp.status_code

    def _do_login(self, name: str = "/api/auth/login") -> bool:
        self.preflight("POST", "/api/auth/login", H_JSON, name="OPTIONS /api/auth/login")
        payload = {
            "username": self._credentials["username"],
            "password": self._credentials["password"],
        }
        with self.client.post("/api/auth/login", json=payload, catch_response=True, name=name) as resp:
            if resp.ok:
                self._access_token = resp.json().get("accessToken")
                return True
            logger.warning("[login] status=%s body=%s", resp.status_code, resp.text[:200])
            resp.failure(f"login failed: {resp.status_code}")
            return False

    # 앱 시작 시 토큰 갱신을 재현
    def _do_refresh(self, name: str) -> int:
        with self.client.post("/api/auth/refresh", catch_response=True, name=name) as resp:
            if resp.ok:
                self._access_token = resp.json().get("accessToken")
                resp.success()
            elif resp.status_code == 401:
                self._access_token = None
                resp.success()
            else:
                logger.warning("[refresh] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"refresh failed: {resp.status_code}")
            return resp.status_code

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    # 앱 시작 또는 새로고침
    @task(5)
    def task_boot_refresh(self):
        self._do_refresh(name="/api/auth/refresh [boot]")

    # 로그인
    @task(2)
    def task_login(self):
        self._do_login(name="/api/auth/login")

    # 쿠키 없는 세션
    @task(2)
    def task_anonymous_boot(self):
        self.client.cookies.clear()
        self._access_token = None
        self._do_refresh(name="/api/auth/refresh [anonymous-401]")
        if random.random() < 0.7:
            think(self)   # 익명 부팅(401) 후 사용자가 로그인하기까지의 지연
            self._do_login(name="/api/auth/login [after-anonymous]")

    # 신규 가입
    @task(1)
    def task_signup_new(self):
        self._do_signup(_random_user(), name="/api/auth/signup")

    # 중복 가입
    @task(1)
    def task_duplicate_signup(self):
        with self.client.post(
            "/api/auth/signup", json=self._credentials,
            catch_response=True, name="/api/auth/signup [duplicate-409]",
        ) as resp:
            resp.success()

    # 잘못된 비밀번호
    @task(1)
    def task_typo_login(self):
        payload = {
            "username": self._credentials["username"],
            "password": "wrong_" + uuid.uuid4().hex[:6],
        }
        with self.client.post(
            "/api/auth/login", json=payload,
            catch_response=True, name="/api/auth/login [typo-401]",
        ) as resp:
            resp.success()

    # 로그아웃 후 재로그인
    @task(1)
    def task_logout_cycle(self):
        if not self._access_token and not self._do_login(name="/api/auth/login [pre-logout]"):
            return
        self.preflight("POST", "/api/auth/logout", H_AUTH, name="OPTIONS /api/auth/logout")
        with self.client.post(
            "/api/auth/logout", headers=self._auth_headers(),
            catch_response=True, name="/api/auth/logout",
        ) as resp:
            if resp.ok:
                self._access_token = None
                resp.success()
            elif resp.status_code == 401:
                self._access_token = None
                resp.success()
            else:
                logger.warning("[logout] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"logout failed: {resp.status_code}")
                return
        think(self)   # 로그아웃 후 다시 접속하기까지의 사용자 지연
        self._do_refresh(name="/api/auth/refresh [after-logout-401]")
        think(self)   # 재접속(401) 후 재로그인하기까지의 지연
        self._do_login(name="/api/auth/login [re-login]")
