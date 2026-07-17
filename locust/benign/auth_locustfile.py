# auth_locustfile.py — auth-service 정상 트래픽 (공유 하네스 기반)
#
# 실행:
#   $env:HOST="http://<auth-pod-ip>:8080"
#   locust -f locust/benign/auth_locustfile.py --host $env:HOST --headless -u 20 -r 4 -t 600s
#
# ■ confound 제거: common.harness.BaseUser 상속(attack 과 동일 pacing 분포 + 공통 헤더).
# ■ north-south 정상 사용자 흐름만: signup / login / refresh / logout + 자연 4xx(오타 401).
#   - /internal/auth/validate 는 benign 에서 호출하지 않는다. 이 내부 엔드포인트의 정상 호출자는
#     peer 서비스(post/comment)이며, 그 east-west 는 post/comment 부하 시 자동 생성된다(modify_plan §6-1).
# ■ 상태 변경/정리: auth 는 게시물/댓글을 만들지 않는다. 단 signup 으로 만들어진 '사용자'는
#   삭제 API 가 없어 수집기 차원에서 되돌릴 수 없다 → run.sh 가 수집 전 스냅샷(snapshot)을 떠 두고
#   전체 수집 종료 후 스냅샷 시점으로 복원(restore)해 net-zero 를 보장한다. traffic_collect.md §5-0/§5-3/§8 참조.

from __future__ import annotations   # Python 3.7+ 에서 str|None 등 표기 호환(런타임 평가 안 함)

import os
import sys
import uuid
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import BaseUser  # noqa: E402
from locust import task  # noqa: E402

logger = logging.getLogger(__name__)


def _random_user() -> dict:
    uid = uuid.uuid4().hex[:10]
    return {"username": f"user_{uid}", "password": "Test@12345!"}  # SignupRequest 는 email 없음


class AuthUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        """signup -> login 후 access token 저장 (refresh 는 httpOnly 쿠키로 세션에 자동 보관)."""
        self._credentials = _random_user()
        self._access_token: str | None = None

        with self.client.post(
            "/api/auth/signup", json=self._credentials,
            catch_response=True, name="/api/auth/signup (setup)",
        ) as resp:
            if not resp.ok:
                logger.warning("[signup setup] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"signup failed: {resp.status_code}")
        self._do_login()

    # ------------------------------------------------------------------ #
    def _do_login(self, name: str = "/api/auth/login (helper)") -> bool:
        payload = {"username": self._credentials["username"], "password": self._credentials["password"]}
        with self.client.post("/api/auth/login", json=payload, catch_response=True, name=name) as resp:
            if resp.ok:
                self._access_token = resp.json().get("accessToken")
                return True
            logger.warning("[login helper] status=%s body=%s", resp.status_code, resp.text[:200])
            resp.failure(f"login failed: {resp.status_code}")
            return False

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    # ------------------------------------------------------------------ #
    # 정상 태스크 (north-south)                                           #
    # ------------------------------------------------------------------ #
    @task(3)
    def task_login(self):
        payload = {"username": self._credentials["username"], "password": self._credentials["password"]}
        with self.client.post("/api/auth/login", json=payload, catch_response=True) as resp:
            if resp.ok:
                self._access_token = resp.json().get("accessToken")
            else:
                logger.warning("[task_login] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"login failed: {resp.status_code}")

    @task(1)
    def task_refresh(self):
        # 세션에 보관된 refresh 쿠키(httpOnly, path=/api/auth)로 access token 재발급.
        # validate 제거로 빠진 '자주 일어나는 정상 인증 유지' 트래픽을 대체.
        with self.client.post("/api/auth/refresh", catch_response=True, name="/api/auth/refresh") as resp:
            if resp.ok:
                self._access_token = resp.json().get("accessToken")
            elif resp.status_code in (401, 403):
                resp.success()      # 쿠키 만료/로그아웃 상태 — 정상 흐름이므로 benign
                self._do_login()    # 재로그인으로 복구
            else:
                logger.warning("[task_refresh] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"refresh failed: {resp.status_code}")

    @task(1)
    def task_signup(self):
        with self.client.post("/api/auth/signup", json=_random_user(), catch_response=True) as resp:
            if not resp.ok:
                logger.warning("[task_signup] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"signup failed: {resp.status_code}")

    @task(1)
    def task_logout(self):
        if not self._access_token and not self._do_login():
            return
        with self.client.post("/api/auth/logout", headers=self._auth_headers(), catch_response=True) as resp:
            if resp.ok:
                self._access_token = None
                self._do_login()   # 다음 태스크 위해 재로그인(정상 사용자의 재접속 흐름)
            else:
                logger.warning("[task_logout] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"logout failed: {resp.status_code}")

    # ------------------------------------------------------------------ #
    # 자연스러운 4xx (benign) — "4xx=공격" 지름길 차단                     #
    # ------------------------------------------------------------------ #
    @task(1)
    def benign_typo_login(self):
        """정상 사용자의 비밀번호 오타 → 401. 실제 서비스에서 흔함."""
        payload = {"username": self._credentials["username"], "password": "wrong_" + uuid.uuid4().hex[:6]}
        with self.client.post(
            "/api/auth/login", json=payload, catch_response=True, name="/api/auth/login [typo→401]",
        ) as resp:
            resp.success()  # 401 기대 — 정상 사용자의 실수이므로 benign
            if not self._access_token:
                self._do_login()

    # 주: auth 는 게시물/댓글을 만들지 않으므로 정리(on_stop)할 상태가 없다.
    #     signup 으로 생성된 사용자는 삭제 API 부재로 되돌릴 수 없음(파일 상단 주석 참조).
