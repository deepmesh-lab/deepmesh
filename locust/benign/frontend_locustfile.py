# frontend_locustfile.py — frontend(Nginx+React) 정상 트래픽 (공유 하네스 기반)
#
# 실행:
#   $env:HOST="http://<frontend-pod-ip>:80"
#   locust -f locust/benign/frontend_locustfile.py --host $env:HOST --headless -u 20 -r 4 -t 600s
#
# 정상 사용자의 "페이지 로드"(index.html + 정적 자산 다발) + SPA 라우트.
# BaseUser 상속: attack 과 동일 pacing + 공통 헤더. 자연 4xx(없는 자산) 소량.
# ★ 상태 정리 불필요: frontend nginx 는 정적 서빙 + SPA fallback 만 하고(proxy_pass 없음, nginx.conf 확인),
#   API 는 브라우저가 백엔드를 직접 호출한다. 즉 이 수집기는 GET 만 하므로 서비스 상태를 바꾸지 않는다(net-zero).

from __future__ import annotations   # Python 3.7+ 호환(일관성)

import os
import sys
import re
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import BaseUser  # noqa: E402
from locust import task  # noqa: E402

SPA_ROUTES = ["/", "/posts", "/login", "/signup"]


class FrontendUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:3000")

    def setup(self):
        self._assets = []
        try:
            resp = self.client.get("/", name="GET / [index]")
            if resp.ok:
                hrefs = re.findall(r'(?:src|href)="(/[^"]+)"', resp.text)
                self._assets = sorted(set(
                    h for h in hrefs if not h.startswith("//") and "." in h.split("/")[-1]
                ))
        except Exception:
            pass

    @task(5)
    def load_page(self):
        # 페이지 진입 = index.html + 참조 자산 다발(한 커넥션 연속) → 5-패킷 시퀀스 자연히 참(w=5 정합)
        self.client.get("/", name="GET / [index]")
        for asset in self._assets:
            self.client.get(asset, name="GET /assets/* [static]")

    @task(3)
    def spa_route(self):
        self.client.get(random.choice(SPA_ROUTES), name="GET [spa-route]")

    @task(1)
    def favicon(self):
        self.client.get("/vite.svg", name="GET /vite.svg")

    # 자연스러운 4xx (benign) — 오래된 캐시/삭제된 자산 요청 404. "404=공격" 지름길 차단.
    @task(1)
    def benign_missing_asset(self):
        stale = random.choice(["/assets/old-bundle.js", "/assets/legacy.css", "/img/removed.png"])
        with self.client.get(stale, catch_response=True, name="GET /assets/[missing]→404") as resp:
            resp.success()
