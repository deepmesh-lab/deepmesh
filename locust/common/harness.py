"""
harness.py — benign/attack 트래픽 생성기 공유 하네스 (confound 제거용).

■ 왜 필요한가 (confound 제거)
  기존 수집은 benign(wait 4~12s)과 attack(wait 0.02~0.3s)의 **속도 자체가 라벨과 일치**해서,
  모델이 요청 '내용'이 아니라 TCP 전송계층 동역학(윈도우/타이밍)만 보고 갈랐다.
  (검증: 헤더 19B[내용 0B]만으로 지도학습 AUC 0.94.) → 실제 공격자가 정상 속도로 오면 못 잡음.

■ 원칙
  "공격자가 숨길 수 없는 것(요청 내용·시퀀스·표적)에서만 달라지게 하고,
   조절 가능/환경적인 것(속도·클라이언트 지문)은 benign·attack 동일하게 맞춘다."
  → 여기서 pacing 분포와 클라이언트 헤더를 **양쪽 공통**으로 고정한다.

■ 적용 범위 (modify_plan.md 결정과 정합)
  - benign 4종(auth/post/comment/frontend): `BaseUser` 상속 → 공유 pacing + 공유 헤더.
  - attack `k8s_bruteforce`: benign과 **같은 엔드포인트**(/api/auth/login)를 때리므로 confound 정렬 필요.
    → `SHARED_HEADERS` 주입 + `wait_time = shared_wait_time` 로 동일 pacing 분포 사용.
  - attack `k8s_enum` / `k8s_manipulate`: 대상이 K8s API 서버(benign 등가물 없음)라 **정렬하지 않음**
    (침해 도구의 지문이 앱과 다른 것이 오히려 현실적) — 이 하네스를 쓰지 않는다.

사용(benign):
  from common.harness import BaseUser, SHARED_HEADERS
  class MyUser(BaseUser):
      def setup(self): ...        # on_start 대신 setup() 훅 사용
      @task(3)
      def do(self): ...

사용(standalone attack — bruteforce):
  from common.harness import SHARED_HEADERS, shared_wait_time, always_success
  class K8sBruteUser(HttpUser):
      wait_time = shared_wait_time          # benign 과 동일 pacing 분포
      def on_start(self):
          self.client.headers.update(SHARED_HEADERS)   # benign 과 동일 지문
          ...
"""
import os
import random

from locust import HttpUser


# ── 공유 pacing 프로파일 ─────────────────────────────────────────────
# benign·attack 모두 이 분포에서 동일 가중치로 추첨한다.
# → benign도 burst(자산 다발/앱)를, attack도 low-and-slow(정상 위장)를 만들어
#   "속도 = 공격" 지름길을 원천 차단한다.
PACE_PROFILES = [
    ("human",  (4.0, 12.0)),   # 사람 열람(느긋)
    ("active", (0.5, 2.0)),    # 활동적 사용/모바일 앱
    ("burst",  (0.02, 0.3)),   # 자산 다발 / 고속 클라이언트
]
PACE_WEIGHTS = [1, 1, 1]

# 파일별로 pacing 분포를 강제하고 싶을 때 env 로 프로파일 고정 가능(디버그용).
_FORCED = os.environ.get("PACE_PROFILE")  # "human" | "active" | "burst" | None


# ── 공유 클라이언트 지문 ─────────────────────────────────────────────
# benign·attack 이 같은 User-Agent/Accept 를 쓰게 해 지문 차이로 인한 누출 방지.
# Accept 는 JSON 백엔드(Spring Boot, /api/**)와 정적 프론트(Nginx, HTML/JS/CSS) 양쪽을 포괄.
SHARED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) DeepMeshClient/1.0",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def pick_pace():
    """공유 pacing 분포에서 (이름, (lo, hi)) 하나를 추첨. _FORCED 지정 시 고정."""
    if _FORCED:
        return _FORCED, dict(PACE_PROFILES)[_FORCED]
    return random.choices(PACE_PROFILES, weights=PACE_WEIGHTS)[0]


def shared_wait_time(user):
    """standalone HttpUser(공격 등)가 benign과 **동일 pacing 분포**를 쓰게 하는 wait_time.

      class K8sBruteUser(HttpUser):
          wait_time = shared_wait_time

    locust 는 클래스 속성에 할당된 함수를 `wait_time(self)` 로 호출하므로 user 는 인스턴스다.
    사용자 인스턴스별로 최초 1회 프로파일을 추첨해 캐시한다(BaseUser 와 동일 규칙).
    """
    rng = getattr(user, "_pace_range", None)
    if rng is None:
        user._pace_name, user._pace_range = pick_pace()
        rng = user._pace_range
    lo, hi = rng
    return random.uniform(lo, hi)


class BaseUser(HttpUser):
    """benign 공통 베이스. pacing·헤더를 여기서 고정한다."""

    abstract = True
    _pace_range = (4.0, 12.0)  # setup 전 첫 호출 대비 기본값

    def wait_time(self):
        lo, hi = self._pace_range
        return random.uniform(lo, hi)

    def on_start(self):
        # 1) pacing 프로파일 추첨(양쪽 동일 분포)
        self._pace_name, self._pace_range = pick_pace()
        # 2) 공통 헤더 주입
        self.client.headers.update(SHARED_HEADERS)
        # 3) 하위 초기화 훅
        self.setup()

    def setup(self):
        """하위 클래스 초기화(토큰 확보 등). on_start 대신 오버라이드."""
        pass


def always_success(cm):
    """attack 트래픽용: 4xx/403/404 가 나도 실패로 세지 않음(의도 기준 라벨).

      with self.client.get(path, catch_response=True) as cm 를 넘겨도 되고,
      always_success(self.client.get(path, catch_response=True)) 형태로도 쓴다.
    """
    with cm as r:
        r.success()
