# frontend의 정상 정적 파일 요청을 생성(SPA fallback, ETag, 정적 자산 로딩을 재현)
from __future__ import annotations

import os
import sys
import re
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.harness import BaseUser  # noqa: E402
from locust import task  # noqa: E402

# CACHE_BUST=1이면 매번 본문을 다시 받음
import os as _os
import random as _rnd
CACHE_BUST = _os.environ.get("CACHE_BUST", "0") == "1"

def _bust(url: str) -> str:
    if not CACHE_BUST:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_={_rnd.randint(0, 1 << 30)}"

# SPA 라우트와 가중치
STATIC_ROUTES = [
    ("/",                 3),
    ("/posts",            8),
    ("/auth/sign-in",     3),
    ("/auth/sign-up",     1),
    ("/auth/session",     1),
    ("/posts/new",        1),
]
_ROUTE_PATHS = [p for p, _ in STATIC_ROUTES]
_ROUTE_WEIGHTS = [w for _, w in STATIC_ROUTES]

SEED_POST_LO, SEED_POST_HI = 1, 300

# SPA fallback 대상 경로
STALE_ASSETS = ["/assets/old-bundle.js", "/assets/legacy.css", "/img/removed.png"]


class FrontendUser(BaseUser):
    host = os.environ.get("HOST", "http://localhost:3000")

    def setup(self):
        self._etags: dict[str, str] = {}
        self._assets: list[str] = []
        try:
            resp = self.client.get("/", name="GET / [index]")
            if resp.ok:
                self._remember_etag("/", resp)
                self._assets = self._extract_assets(resp.text)
        except Exception:
            pass

    # index.html의 정적 자산 경로를 반환
    @staticmethod
    def _extract_assets(html: str) -> list[str]:
        hrefs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
        return sorted({
            h for h in hrefs
            if not h.startswith("//") and "." in h.split("/")[-1]
        })

    def _remember_etag(self, url: str, resp) -> None:
        etag = resp.headers.get("ETag")
        if etag:
            self._etags[url] = etag

    # ETag 재검증 또는 cache bust 요청
    def _conditional_get(self, url: str, name: str):
        headers = {}
        if not CACHE_BUST:
            cached = self._etags.get(url)
            if cached:
                headers["If-None-Match"] = cached
        req_url = _bust(url)
        with self.client.get(req_url, headers=headers, catch_response=True, name=name) as resp:
            if resp.status_code == 304:
                resp.success()
            elif resp.ok:
                self._remember_etag(url, resp)
                resp.success()
            else:
                resp.failure(f"unexpected status: {resp.status_code}")
            return resp

    def _load_assets(self) -> None:
        for asset in self._assets:
            self._conditional_get(asset, name="GET /assets/* [static]")

    # SPA 문서와 정적 자산을 불러오고+ ETag를 기억
    def _enter(self, path: str, name: str) -> None:
        resp = self._conditional_get(path, name=name)
        if resp is not None:
            self._load_assets()
        if not self._assets and resp is not None and resp.status_code == 200:
            self._assets = self._extract_assets(resp.text)

    # SPA 라우트
    @task(6)
    def task_enter_static_route(self):
        path = random.choices(_ROUTE_PATHS, weights=_ROUTE_WEIGHTS)[0]
        self._enter(path, name="GET [spa-route]")

    # 게시글 상세
    @task(4)
    def task_enter_post_detail(self):
        pid = random.randint(SEED_POST_LO, SEED_POST_HI)
        self._enter(f"/posts/{pid}", name="GET /posts/[id] [spa-route]")

    # 게시글 수정 화면
    @task(1)
    def task_enter_post_edit(self):
        pid = random.randint(SEED_POST_LO, SEED_POST_HI)
        self._enter(f"/posts/{pid}/edit", name="GET /posts/[id]/edit [spa-route]")

    # 새로고침
    @task(3)
    def task_reload(self):
        cached_docs = [u for u in self._etags if not u.startswith("/assets/")]
        path = random.choice(cached_docs) if cached_docs else "/posts"
        self._enter(path, name="GET [spa-route] [reload]")

    # 존재하지 않는 자산
    @task(1)
    def task_stale_asset(self):
        stale = random.choice(STALE_ASSETS)
        with self.client.get(
            stale, catch_response=True, name="GET /assets/[missing-200] index.html",
        ) as resp:
            resp.success()
