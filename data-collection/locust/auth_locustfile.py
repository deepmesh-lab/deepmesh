# auth_locustfile.py
# 실행 방법:
#   locust -f auth_locustfile.py --host http://<INGRESS_IP>:30080 \
#          --users 20 --spawn-rate 4 --run-time 300s --headless
#
# 환경변수:
#   HOST  - 대상 서버 URL (기본값: http://localhost:8080)

import os
import uuid
import logging

from locust import HttpUser, task, between, events

logger = logging.getLogger(__name__)


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {
        "username": f"user_{uid}",
        "email": f"user_{uid}@test.local",
        "password": "Test@12345!",
    }


class AuthUser(HttpUser):
    host = os.environ.get("HOST", "http://localhost:8080")
    wait_time = between(1, 3)

    def on_start(self):
        """초기화: signup -> login 수행 후 토큰 저장"""
        self._credentials = _random_user()
        self._access_token: str | None = None
        self._refresh_token: str | None = None

        # signup
        with self.client.post(
            "/api/auth/signup",
            json=self._credentials,
            catch_response=True,
            name="/api/auth/signup (on_start)",
        ) as resp:
            if not resp.ok:
                logger.warning(
                    "[signup on_start] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"signup failed: {resp.status_code}")

        # login
        self._do_login()

    # ------------------------------------------------------------------ #
    # helper                                                               #
    # ------------------------------------------------------------------ #

    def _do_login(self, name: str = "/api/auth/login (helper)") -> bool:
        payload = {
            "email": self._credentials["email"],
            "password": self._credentials["password"],
        }
        with self.client.post(
            "/api/auth/login",
            json=payload,
            catch_response=True,
            name=name,
        ) as resp:
            if resp.ok:
                data = resp.json()
                self._access_token = data.get("accessToken") or data.get("access_token")
                self._refresh_token = data.get("refreshToken") or data.get("refresh_token")
                return True
            else:
                logger.warning(
                    "[login helper] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"login failed: {resp.status_code}")
                return False

    def _auth_headers(self) -> dict:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    # ------------------------------------------------------------------ #
    # tasks                                                                #
    # ------------------------------------------------------------------ #

    @task(3)
    def task_login(self):
        payload = {
            "email": self._credentials["email"],
            "password": self._credentials["password"],
        }
        with self.client.post(
            "/api/auth/login",
            json=payload,
            catch_response=True,
        ) as resp:
            if resp.ok:
                data = resp.json()
                self._access_token = data.get("accessToken") or data.get("access_token")
                self._refresh_token = data.get("refreshToken") or data.get("refresh_token")
            else:
                logger.warning(
                    "[task_login] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"login failed: {resp.status_code}")

    @task(1)
    def task_signup(self):
        new_user = _random_user()
        with self.client.post(
            "/api/auth/signup",
            json=new_user,
            catch_response=True,
        ) as resp:
            if not resp.ok:
                logger.warning(
                    "[task_signup] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"signup failed: {resp.status_code}")

    @task(1)
    def task_logout(self):
        with self.client.post(
            "/api/auth/logout",
            headers=self._auth_headers(),
            catch_response=True,
        ) as resp:
            if resp.ok:
                self._access_token = None
                self._refresh_token = None
                # 로그아웃 후 재로그인
                self._do_login()
            else:
                logger.warning(
                    "[task_logout] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"logout failed: {resp.status_code}")

    @task(1)
    def task_refresh(self):
        if not self._refresh_token:
            # refresh token 없으면 재로그인 시도
            self._do_login()
            return

        with self.client.post(
            "/api/auth/refresh",
            json={"refreshToken": self._refresh_token},
            catch_response=True,
        ) as resp:
            if resp.ok:
                data = resp.json()
                self._access_token = data.get("accessToken") or data.get("access_token")
                self._refresh_token = data.get("refreshToken") or data.get("refresh_token")
            else:
                logger.warning(
                    "[task_refresh] status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                resp.failure(f"refresh failed: {resp.status_code}")
                # 만료된 경우 재로그인
                self._do_login()
