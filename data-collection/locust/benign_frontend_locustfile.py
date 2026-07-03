# benign_frontend_locustfile.py — frontend(Nginx+React) 정상 트래픽 (benign.md)
#
# 실행:
#   locust -f locust/benign_frontend_locustfile.py --host http://localhost:3000 \
#          --users 20 --spawn-rate 4 --run-time 300s --headless
#
# 정상 사용자의 "페이지 로드"를 재현: index.html + 정적 자산(JS/CSS/이미지) 다발 GET,
# SPA 라우트(Nginx가 index.html로 폴백 → 200). 존재하는 것만 요청 → 4xx 없어야 benign.

import os
import re

from locust import HttpUser, task, between

# React 라우터 경로들(Nginx SPA 폴백으로 전부 index.html 200 반환)
SPA_ROUTES = ["/", "/posts", "/login", "/signup"]


class FrontendUser(HttpUser):
    host = os.environ.get("HOST", "http://localhost:3000")
    wait_time = between(1, 4)

    def on_start(self):
        # index.html 을 받아 참조된 로컬 정적 자산 링크를 추출(실제 브라우저 흉내)
        self._assets = []
        try:
            resp = self.client.get("/", name="GET / [index]")
            if resp.ok:
                hrefs = re.findall(r'(?:src|href)="(/[^"]+)"', resp.text)
                # 외부/앵커 제외, 정적 자산만
                self._assets = sorted(set(
                    h for h in hrefs if not h.startswith("//") and "." in h.split("/")[-1]
                ))
        except Exception:
            pass

    @task(5)
    def load_page(self):
        # 페이지 진입 = index.html + 그 페이지가 참조하는 자산 다발(한 커넥션에 연속)
        self.client.get("/", name="GET / [index]")
        for asset in self._assets:
            self.client.get(asset, name="GET /assets/* [static]")

    @task(3)
    def spa_route(self):
        # SPA 라우팅(Nginx try_files 폴백 → index.html 200)
        import random
        self.client.get(random.choice(SPA_ROUTES), name="GET [spa-route]")

    @task(1)
    def favicon(self):
        self.client.get("/vite.svg", name="GET /vite.svg")
