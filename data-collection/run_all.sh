#!/usr/bin/env bash
# ============================================================
# run_all.sh — benign/attack 트래픽 수집 + 전처리 전체 파이프라인 (Docker)
#
# Git Bash 에서 실행. docker compose 가 이미 떠 있어야 함(msa/).
#   cd deepmesh-temp-ai/data-collection && bash run_all.sh [phase]
#
# phase (기본 all):
#   preflight  - .so 빌드 + 파이썬 패키지 확인
#   benign     - auth/post/comment/frontend + DB(부산물) 정상 트래픽 수집
#   attack     - auth/post/comment/frontend + DB 공격 트래픽 수집
#   preprocess - 각 서비스 pcap → X_benign/X_attack .npy
#   all        - 위 전부 순서대로
#
# 강도/시간 조절(환경변수):
#   BENIGN_DURATION(기본180) ATTACK_DURATION(기본120) USERS(기본15) SPAWN(기본5) ID_RANGE(기본300)
# ============================================================
set -u

BENIGN_DURATION="${BENIGN_DURATION:-180}"
ATTACK_DURATION="${ATTACK_DURATION:-120}"
USERS="${USERS:-15}"
SPAWN="${SPAWN:-5}"
export ID_RANGE="${ID_RANGE:-300}"

SO="../servicemesh/proxy/packet_parser_stack.so"
SO_SRC="../servicemesh/proxy/packet_parser_stack.c"
PREPROC="../model-training/preprocess_deepmesh.py"
DATA="../model-training/data"

# auth 8080 / comment 8081 / post 8082 / frontend 3000 / mysql 3306
AUTH=http://localhost:8080
POST=http://localhost:8082
COMMENT=http://localhost:8081
FRONT=http://localhost:3000

PHASE="${1:-all}"
log() { echo -e "\n\033[1;36m[$(date +%H:%M:%S)] $*\033[0m"; }

# --- python 실행기 자동 탐지 (Git Bash 에 python 이 PATH에 없을 수 있음) ---
# 우선순위: 환경변수 PYTHON > python > python3 > py -3 > 알려진 설치 경로
# /usr/bin/python3(Git Bash 내장)은 pip·패키지가 없으므로 배제하고,
# 패키지(numpy)나 pip 을 실제로 가진 Windows Python 을 고른다.
# 후보 파이썬 목록. Git Bash의 $USER/$HOME 이 실제 프로필 폴더와 다를 수 있어
# /c/Users/*/... 글롭으로 실제 설치 경로를 탐색한다(내장 /usr/bin/python3 은 pip 없어서 배제됨).
CANDS=("${PYTHON:-}" "py -3" python)
for p in "$HOME"/AppData/Local/Programs/Python/Python3*/python.exe \
         /c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe \
         /mnt/c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe \
         "/c/Program Files/Python3"*/python.exe \
         "/mnt/c/Program Files/Python3"*/python.exe; do
  [ -x "$p" ] && CANDS+=("$p")
done
CANDS+=(python3)
PY=""
for cand in "${CANDS[@]}"; do
  [ -z "$cand" ] && continue
  $cand --version >/dev/null 2>&1 || continue
  if $cand -c "import numpy" >/dev/null 2>&1 || $cand -m pip --version >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[오류] pip/패키지를 가진 python 을 못 찾음. 아래처럼 실제 경로를 직접 지정하세요:"
  echo "       ls /c/Users/*/AppData/Local/Programs/Python/Python3*/python.exe   # 경로 확인"
  echo "       PYTHON=\"<위 경로>\" bash run_all.sh $PHASE"
  exit 1
fi
echo "[info] PYTHON = $PY"
$PY --version 2>&1 | tail -1

# capture(백그라운드) + locust(포그라운드) 동시 실행
cap_and_load() {  # <container> <pcapdir> <locustfile> <host> <duration>
  local container=$1 pcapdir=$2 lf=$3 lhost=$4 dur=$5
  mkdir -p "$pcapdir"
  bash capture_docker.sh "$container" "$dur" "$pcapdir" >/dev/null 2>&1 &
  local cap=$!
  sleep 2  # 캡처 시작 대기
  $PY -m locust -f "$lf" --host "$lhost" --users "$USERS" --spawn-rate "$SPAWN" \
         --run-time "${dur}s" --headless 2>&1 | grep -iE "Aggregated|fail|Response time" | tail -n 4
  wait "$cap" 2>/dev/null
}

# ---------------- preflight ----------------
phase_preflight() {
  log "PREFLIGHT: .so 빌드 + 패키지 확인"
  if [ ! -f "$SO" ]; then
    gcc -shared -fPIC -O2 -o "$SO" "$SO_SRC" && echo "  .so 빌드 완료" || { echo "  gcc 실패 — 수동 빌드 필요"; exit 1; }
  else echo "  .so 존재: $SO"; fi
  $PY -c "import scapy,numpy,tqdm" 2>/dev/null || $PY -m pip install -q scapy numpy tqdm
  $PY -c "import locust" 2>/dev/null || $PY -m pip install -q locust
  docker compose -f ../msa/docker-compose.yml ps 2>/dev/null | grep -q "auth-service" \
    || echo "  [경고] msa 컨테이너가 안 보임 — 'cd ../msa && docker compose up -d' 먼저"
}

# ---------------- benign ----------------
phase_benign() {
  log "BENIGN: auth"    ; cap_and_load auth-service    ./pcap/auth-service    locust/auth_locustfile.py    "$AUTH"  "$BENIGN_DURATION"
  log "BENIGN: post"    ; HOST=$POST AUTH_HOST=$AUTH cap_and_load post-service ./pcap/post-service locust/post_locustfile.py "$POST" "$BENIGN_DURATION"
  log "BENIGN: comment" ; HOST=$COMMENT AUTH_HOST=$AUTH POST_HOST=$POST cap_and_load comment-service ./pcap/comment-service locust/comment_locustfile.py "$COMMENT" "$BENIGN_DURATION"
  log "BENIGN: frontend"; cap_and_load frontend        ./pcap/frontend        locust/benign_frontend_locustfile.py "$FRONT" "$BENIGN_DURATION"

  # DB(부산물): mysql 캡처 중 3개 백엔드 locust 동시 실행
  log "BENIGN: db(부산물) — mysql 캡처 + 백엔드 3종 부하"
  mkdir -p ./pcap/mysql
  bash capture_docker.sh deepmesh-mysql "$BENIGN_DURATION" ./pcap/mysql >/dev/null 2>&1 & local cap=$!
  sleep 2
  $PY -m locust -f locust/auth_locustfile.py --host "$AUTH" --users "$USERS" --spawn-rate "$SPAWN" --run-time "${BENIGN_DURATION}s" --headless >/dev/null 2>&1 &
  HOST=$POST AUTH_HOST=$AUTH $PY -m locust -f locust/post_locustfile.py --host "$POST" --users "$USERS" --spawn-rate "$SPAWN" --run-time "${BENIGN_DURATION}s" --headless >/dev/null 2>&1 &
  HOST=$COMMENT AUTH_HOST=$AUTH POST_HOST=$POST $PY -m locust -f locust/comment_locustfile.py --host "$COMMENT" --users "$USERS" --spawn-rate "$SPAWN" --run-time "${BENIGN_DURATION}s" --headless >/dev/null 2>&1 &
  wait
}

# ---------------- attack ----------------
phase_attack() {
  log "ATTACK: auth"    ; cap_and_load auth-service    ./pcap/attacks/auth-service    attacks/attack_auth_locustfile.py    "$AUTH"  "$ATTACK_DURATION"
  log "ATTACK: post"    ; HOST=$POST AUTH_HOST=$AUTH cap_and_load post-service ./pcap/attacks/post-service attacks/attack_post_locustfile.py "$POST" "$ATTACK_DURATION"
  log "ATTACK: comment" ; HOST=$COMMENT AUTH_HOST=$AUTH POST_HOST=$POST cap_and_load comment-service ./pcap/attacks/comment-service attacks/attack_comment_locustfile.py "$COMMENT" "$ATTACK_DURATION"
  log "ATTACK: frontend"; cap_and_load frontend        ./pcap/attacks/frontend        attacks/attack_frontend_locustfile.py "$FRONT" "$ATTACK_DURATION"

  # DB 공격(비-locust): mysql 캡처 + pymysql cross-DB
  log "ATTACK: db — mysql 캡처 + attack_db.py(cross-DB)"
  $PY -c "import pymysql" 2>/dev/null || $PY -m pip install -q pymysql
  local pw; pw=$(grep -E '^MYSQL_ROOT_PASSWORD=' ../msa/.env 2>/dev/null | cut -d= -f2-)
  export MYSQL_ROOT_PASSWORD="${pw:-rootpassword}"
  mkdir -p ./pcap/attacks/mysql
  bash capture_docker.sh deepmesh-mysql "$ATTACK_DURATION" ./pcap/attacks/mysql >/dev/null 2>&1 & local cap=$!
  sleep 2
  $PY attacks/attack_db.py --duration "$ATTACK_DURATION" 2>&1 | tail -n 2
  wait "$cap" 2>/dev/null
}

# ---------------- preprocess ----------------
pp() {  # <svc>
  local svc=$1 b="./pcap/${svc}" a="./pcap/attacks/${svc}"
  local hasb hasa; hasb=$(ls "$b"/*.pcap 2>/dev/null | head -1); hasa=$(ls "$a"/*.pcap 2>/dev/null | head -1)
  if [ -z "$hasb" ]; then echo "  [skip] $svc: benign pcap 없음"; return; fi
  if [ -n "$hasa" ]; then
    $PY "$PREPROC" --benign "$b"/*.pcap --attack "$a"/*.pcap --out "$DATA/$svc" --parser-so "$SO" 2>&1 | grep -E "vec_len|n_benign|n_attack|shape|SKIP" | tail -n 4
  else
    $PY "$PREPROC" --benign "$b"/*.pcap --out "$DATA/$svc" --parser-so "$SO" 2>&1 | grep -E "vec_len|n_benign|shape" | tail -n 3
  fi
}
phase_preprocess() {
  log "PREPROCESS → X_benign/X_attack .npy"
  for svc in auth-service post-service comment-service frontend mysql; do echo "· $svc"; pp "$svc"; done
}

# ---------------- main ----------------
case "$PHASE" in
  preflight)  phase_preflight ;;
  benign)     phase_benign ;;
  attack)     phase_attack ;;
  preprocess) phase_preprocess ;;
  all)        phase_preflight; phase_benign; phase_attack; phase_preprocess ;;
  *) echo "phase: preflight|benign|attack|preprocess|all"; exit 1 ;;
esac
log "DONE ($PHASE)"
