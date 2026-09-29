# 정상 및 공격 트래픽의 pacing, 헤더, CORS 처리를 공유
import os
import random
import time

from locust import HttpUser


# pacing 프로파일
PACE_PROFILES = [
    ("human",  (4.0, 12.0)),
    ("active", (0.5, 2.0)),
    ("burst",  (0.02, 0.3)),
]
PACE_WEIGHTS = [1, 1, 1]

# 환경변수로 pacing을 고정
_FORCED = os.environ.get("PACE_PROFILE")


# CORS 설정
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "http://dev-server:31403")
PREFLIGHT_MAX_AGE = float(os.environ.get("PREFLIGHT_MAX_AGE", "3600"))


# 공통 요청 헤더
SHARED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DeepMeshClient/1.0",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": CORS_ORIGIN,
}


# preflight 설정
_CORS_SAFELISTED = {"accept", "accept-language", "content-language"}

H_NONE = ()
H_JSON = ("Content-Type",)
H_AUTH = ("Authorization",)
H_JSON_AUTH = ("Authorization", "Content-Type")


def cors_request_header_names(extra_headers=None) -> str:
    # preflight에 필요한 헤더명을 반환
    names = sorted({
        h.lower() for h in (extra_headers or ())
        if h.lower() not in _CORS_SAFELISTED
    })
    return ",".join(names)


def needs_preflight(method: str, extra_headers=None) -> bool:
    # 요청에 preflight가 필요한지 확인
    if cors_request_header_names(extra_headers):
        return True
    return method.upper() not in ("GET", "HEAD", "POST")


def preflight(client, cache: dict, method: str, path: str,
              extra_headers=None, name: str = None) -> None:
    # 캐시가 만료된 비단순 요청에 OPTIONS를 전송
    if not needs_preflight(method, extra_headers):
        return

    key = (method.upper(), path)
    now = time.monotonic()
    if cache.get(key, 0.0) > now:
        return

    headers = {
        "Origin": CORS_ORIGIN,
        "Access-Control-Request-Method": method.upper(),
    }
    acrh = cors_request_header_names(extra_headers)
    if acrh:
        headers["Access-Control-Request-Headers"] = acrh

    with client.request(
        "OPTIONS", path, headers=headers, catch_response=True,
        name=name or f"OPTIONS {path}",
    ) as resp:
        if resp.status_code == 200:
            cache[key] = now + PREFLIGHT_MAX_AGE
            resp.success()
        else:
            resp.failure(f"preflight failed: {resp.status_code}")


def pick_pace():
    # pacing 프로파일을 선택
    if _FORCED:
        return _FORCED, dict(PACE_PROFILES)[_FORCED]
    return random.choices(PACE_PROFILES, weights=PACE_WEIGHTS)[0]


def shared_wait_time(user):
    # 사용자별 pacing 지연을 반환
    rng = getattr(user, "_pace_range", None)
    if rng is None:
        user._pace_name, user._pace_range = pick_pace()
        rng = user._pace_range
    lo, hi = rng
    return random.uniform(lo, hi)


def think(user, scale: float = 1.0):
    # task 내부의 연속 요청 사이에 '사용자 행동 지연'을 삽입
    # scale: 이 지연을 사용자 pace_range 에 곱해 조절(작성=1.0, 가벼운 확인=0.4 등).
    rng = getattr(user, "_pace_range", None)
    if rng is None:
        user._pace_name, user._pace_range = pick_pace()
        rng = user._pace_range
    lo, hi = rng
    time.sleep(random.uniform(lo, hi) * scale)


class BaseUser(HttpUser):
    # 공통 Locust 사용자 기반 클래스

    abstract = True
    _pace_range = (4.0, 12.0)

    def wait_time(self):
        lo, hi = self._pace_range
        return random.uniform(lo, hi)

    def on_start(self):
        self._pace_name, self._pace_range = pick_pace()
        self.client.headers.update(SHARED_HEADERS)
        self._preflight_cache = {}
        self.setup()

    def setup(self):
        pass

    def preflight(self, method, path, extra_headers=None, name=None):
        # 필요한 OPTIONS 요청을 전송
        preflight(self.client, self._preflight_cache, method, path, extra_headers, name)


def always_success(cm):
    # 응답 상태와 관계없이 요청을 성공으로 기록
    with cm as r:
        r.success()
