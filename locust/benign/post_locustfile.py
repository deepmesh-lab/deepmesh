# post_locustfile.py — post-service 정상 트래픽 (공유 하네스 기반)
#
# 실행:
#   $env:HOST="http://<post-pod-ip>:8080"; $env:AUTH_HOST="http://<auth-pod-ip>:8080"
#   locust -f locust/benign/post_locustfile.py --host $env:HOST --headless -u 20 -r 4 -t 600s
#
# BaseUser 상속: attack 과 동일 pacing 분포 + 공통 헤더(confound 제거). 읽기 위주 + 자연 4xx(없는 글 404).
# ★ 상태 정리(net-zero): 이 유저가 생성한 게시물은 실행 종료 시 on_stop 에서 전부 삭제한다.
#   (게시물 생성/삭제는 post→auth validate, 삭제 시 post→comment 연쇄삭제 east-west 를 정상적으로 유발한다.)

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


class PostUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:8080")

    def setup(self):
        self._credentials = _random_user()
        self._access_token: str | None = _signup_and_login(self._credentials)
        self._post_ids: list[int] = []       # 조회로 알게 된 글(타인 글 포함) — 삭제 대상 아님
        self._my_post_ids: list[int] = []     # 내가 만든 살아있는 글 — on_stop 정리 대상
        if not self._access_token:
            logger.warning("[PostUser setup] 토큰 획득 실패 - 비인증 진행")

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}

    def _ensure_token(self):
        if not self._access_token:
            self._access_token = _signup_and_login(self._credentials)

    def _random_post_id(self) -> int | None:
        return random.choice(self._post_ids) if self._post_ids else None

    def _random_my_post_id(self) -> int | None:
        return random.choice(self._my_post_ids) if self._my_post_ids else None

    # ------------------------------------------------------------------ #
    @task(5)
    def list_posts(self):
        page = random.randint(1, 3)
        size = random.choice([5, 10, 20])
        with self.client.get(
            f"/api/posts?page={page}&size={size}", headers=self._auth_headers(),
            catch_response=True, name="/api/posts?page=[p]&size=[s]",
        ) as resp:
            if resp.ok:
                try:
                    data = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else data
                    for item in items:
                        pid = item.get("postId")
                        if pid and pid not in self._post_ids:
                            self._post_ids.append(pid)
                except Exception:
                    pass
            else:
                logger.warning("[list_posts] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"list_posts failed: {resp.status_code}")

    @task(6)
    def get_post(self):
        pid = self._random_post_id()
        if pid is None:
            return
        with self.client.get(f"/api/posts/{pid}", headers=self._auth_headers(), catch_response=True) as resp:
            if resp.status_code == 404:
                if pid in self._post_ids:
                    self._post_ids.remove(pid)
                resp.success()
            elif not resp.ok:
                logger.warning("[get_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"get_post failed: {resp.status_code}")

    @task(1)
    def create_post(self):
        uid = uuid.uuid4().hex[:8]
        payload = {
            "title": f"Test Post {uid}",
            "content": f"This is test content for post {uid}. Generated for traffic simulation.",
        }
        with self.client.post("/api/posts", json=payload, headers=self._auth_headers(), catch_response=True) as resp:
            if resp.ok:
                try:
                    pid = resp.json().get("postId")
                    if pid:
                        if pid not in self._post_ids:
                            self._post_ids.append(pid)
                        if pid not in self._my_post_ids:
                            self._my_post_ids.append(pid)
                except Exception:
                    pass
            else:
                logger.warning("[create_post] status=%s body=%s", resp.status_code, resp.text[:200])
                resp.failure(f"create_post failed: {resp.status_code}")

    @task(1)
    def update_post(self):
        pid = self._random_my_post_id()
        if pid is None:
            return
        uid = uuid.uuid4().hex[:8]
        payload = {"title": f"Updated Post {uid}", "content": f"Updated content {uid}."}
        with self.client.put(f"/api/posts/{pid}", json=payload, headers=self._auth_headers(), catch_response=True) as resp:
            if resp.status_code == 404:
                self._my_post_ids = [x for x in self._my_post_ids if x != pid]
                self._post_ids = [x for x in self._post_ids if x != pid]
                resp.success()
            elif not resp.ok:
                logger.warning("[update_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"update_post failed: {resp.status_code}")

    @task(1)
    def delete_post(self):
        pid = self._random_my_post_id()
        if pid is None:
            return
        with self.client.delete(f"/api/posts/{pid}", headers=self._auth_headers(), catch_response=True) as resp:
            if resp.ok or resp.status_code == 404:
                self._my_post_ids = [x for x in self._my_post_ids if x != pid]
                self._post_ids = [x for x in self._post_ids if x != pid]
                resp.success()
            else:
                logger.warning("[delete_post] id=%s status=%s body=%s", pid, resp.status_code, resp.text[:200])
                resp.failure(f"delete_post failed: {resp.status_code}")

    # 자연스러운 4xx (benign) — 이미 삭제됐거나 없는 글 조회. "4xx=공격" 지름길 차단.
    @task(1)
    def benign_missing_get(self):
        pid = random.randint(1, 100000)
        with self.client.get(
            f"/api/posts/{pid}", headers=self._auth_headers(),
            catch_response=True, name="/api/posts/[missing]→404",
        ) as resp:
            resp.success()  # 404 기대 — benign(스테일 링크)

    # ------------------------------------------------------------------ #
    # 정리(net-zero): 실행 종료 시 내가 만든 글을 전부 삭제 → 수집 전/후 서비스 상태 무변경    #
    # ------------------------------------------------------------------ #
    def on_stop(self):
        if not self._my_post_ids:
            return
        self._ensure_token()   # 장시간 실행으로 토큰 만료됐을 수 있어 재확보
        for pid in list(self._my_post_ids):
            try:
                with self.client.delete(
                    f"/api/posts/{pid}", headers=self._auth_headers(),
                    catch_response=True, name="/api/posts/[cleanup] [delete]",
                ) as resp:
                    if resp.ok or resp.status_code == 404:
                        resp.success()
                    else:
                        resp.failure(f"cleanup delete failed: {resp.status_code}")
            except Exception as exc:
                logger.warning("[cleanup post] id=%s error=%s", pid, exc)
            finally:
                if pid in self._my_post_ids:
                    self._my_post_ids.remove(pid)
