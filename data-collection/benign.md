# benign.md — DB / Nginx+React 정상 트래픽 수집 설계

> 논문은 benign을 여러 워크로드(Web=React+Nginx, Backend, **DB**, CI/CD, 모니터링)에서 수집했다.
> 우리 스택 대응: **DB = MySQL(`deepmesh-mysql`)**, **Web = frontend(React+Nginx, `frontend`)**.
> auth/post/comment 백엔드 benign은 기존 locust로 이미 수집하므로, 여기서는 **DB와 Web** 만 다룬다.
>
> 공통 전제: C 파서는 HTTP 여부와 무관하게 **모든 TCP 패킷**을 (19B 헤더 + payload)로 이미지화한다.
> 따라서 MySQL 바이너리 프로토콜 트래픽도 동일 파이프라인으로 전처리된다(평문이어야 함 →
> `DB_SSL_MODE=DISABLED` 확인).

---

## 1. DB (MySQL) benign — ★ locust로 만들지 않는다 (부산물 캡처)

### 왜 locust가 아닌가
MySQL은 HTTP가 아니라 **바이너리 wire 프로토콜**(3306)이다. HTTP 부하생성기(locust)로는
DB 트래픽을 만들 수 없다. 정상 DB 트래픽은 **백엔드 서비스가 요청을 처리하며 발생시키는
쿼리**가 전부다. 따라서:

> **정상 DB 트래픽 = 백엔드 benign locust를 돌리는 동안 `deepmesh-mysql` netns를 캡처.**

### 정상 DB 트래픽의 특성 (무엇이 담기나)
- TCP 핸드셰이크 + MySQL 핸드셰이크(서버 greeting, auth), 커넥션 풀 유지(keepalive-time 300s).
- `COM_QUERY`/prepared statement 패킷: `SELECT`/`INSERT`/`UPDATE`/`DELETE` (JPA가 생성).
  예: 로그인 시 `SELECT ... FROM users WHERE username=?`, 게시글 조회 시 `SELECT ... FROM posts`,
  결과셋 반환 패킷 등.
- HikariCP 풀이 커넥션을 재사용 → **한 세션(5-tuple)에 여러 쿼리 패킷이 누적** → 5-패킷 시퀀스
  윈도우가 자연히 채워짐(시퀀스 이미지에 유리).

### 절차
```powershell
# 터미널 A: MySQL netns 캡처 (3306). eth0 Ethernet 프레임.
bash capture_docker.sh deepmesh-mysql 300 ./pcap/mysql
# 터미널 B~D: 세 백엔드 benign locust를 동시에 돌려 DB 쿼리를 유발
#   (auth/post/comment locust를 각각 --run-time 300s 로 실행)
```
```powershell
# 전처리 (benign과 동일 .so)
python ../model-training/preprocess_deepmesh.py `
  --benign ./pcap/mysql/*.pcap `
  --out ../model-training/data/mysql `
  --parser-so ../servicemesh/proxy/packet_parser_stack.so
```
→ `data/mysql/X_benign.npy` 생성. 이후 학습/시각화 대상에 `mysql` 추가.

> 주의: 캡처는 반드시 `deepmesh-mysql`의 **eth0**(백엔드↔DB 트래픽). `-i any`(SLL)면 C 파서 오프셋
> 어긋나 이미지 0개.

---

## 2. Nginx+React (frontend) benign — locust 가능 (정적 자산 브라우징)

### 무엇을 흉내 내나
frontend 컨테이너는 **Nginx가 React SPA 정적 자산**(index.html, `/assets/*.js|css`, favicon,
이미지)을 서빙한다. 정상 사용자의 "페이지 로드" 행위를 재현:
- `GET /` → index.html
- `GET /assets/index-*.js`, `GET /assets/*.css` → 번들
- `GET /vite.svg`, `/favicon.ico` 등
- SPA 라우팅 경로(`GET /posts`, `/login` 등)도 Nginx가 index.html로 폴백(정상 200) → 이 패턴 포함.

> SPA가 백엔드로 보내는 API 호출(`/api/...`)은 **이미 auth/post/comment benign에서 커버**되므로
> frontend benign은 **Nginx 정적 서빙 트래픽**에 집중한다.

### 정상 트래픽 특성
- 한 "페이지 로드"가 index.html + 여러 자산을 **연속 GET**(keep-alive 한 커넥션) → 5-패킷 시퀀스
  윈도우가 잘 참(브라우저의 자산 다발 요청 패턴).
- 대부분 200/304, 큰 payload(JS 번들)와 작은 payload(favicon) 혼재.

### 필요 산출물: `benign_frontend_locustfile.py` (신규)
- `HttpUser(host=http://localhost:3000)`.
- `on_start`에서 `GET /`로 index.html 받고, HTML에서 `/assets/...` 링크를 파싱해 그 자산들을
  연속 GET(실제 브라우저 흉내). 파싱이 번거로우면 자산 경로를 미리 목록화(빌드 산출물명)해 GET.
- task: 페이지 로드 시퀀스 반복(홈/목록/상세 라우트), 정적 자산 다발 요청.
- **정상이므로 4xx가 나면 안 됨**(존재하는 자산만 요청) — benign 판정 기준.

### 절차
```powershell
# 터미널 A: frontend netns 캡처
bash capture_docker.sh frontend 300 ./pcap/frontend
# 터미널 B: 정적 브라우징 부하
locust -f benign_frontend_locustfile.py --host http://localhost:3000 --users 20 --spawn-rate 4 --run-time 300s --headless
```
```powershell
python ../model-training/preprocess_deepmesh.py `
  --benign ./pcap/frontend/*.pcap `
  --out ../model-training/data/frontend `
  --parser-so ../servicemesh/proxy/packet_parser_stack.so
```
→ `data/frontend/X_benign.npy`.

---

## 3. 수집 후 워크로드 구성 (논문 대응)

| 논문 워크로드 | 우리 대응 | benign 수집 방법 |
|---|---|---|
| Web (React+Nginx) | `frontend` | `benign_frontend_locustfile.py` + frontend netns 캡처 |
| Backend | auth/post/comment | 기존 benign locust (완료/진행) |
| **DB (PostgreSQL)** | **MySQL** | 백엔드 locust 부산물 + `deepmesh-mysql` netns 캡처 (**locust 아님**) |
| CI/CD, 모니터링 | (우리 스택엔 없음) | 생략 — 게시판 시연 범위 밖 |

---

## 4. 요약 & 내 의견/이견

- **동의:** DB·Web 둘 다 benign 수집 필요(논문 워크로드 다양성 → per-service 모델 대비 효과).
- **이견/유의 (DB):** DB benign은 **locust로 생성 불가** → 백엔드 부하의 **부산물로 캡처**가 유일한
  현실적 방법. `benign_db_locustfile.py` 같은 건 만들 수 없다.
- **frontend:** 정적 자산 GET 위주. SPA의 API 호출은 백엔드 benign과 중복이므로 Nginx 서빙만 담자.
- **시퀀스 관점:** DB(풀 커넥션에 쿼리 다발)·Web(페이지당 자산 다발) 둘 다 **한 커넥션에 연속
  패킷이 잘 쌓여** 5-윈도우가 자연히 차므로 시퀀스 이미지에 적합하다.
- **CI/CD·모니터링**은 우리 게시판엔 없으니 생략(논문과 1:1 아님을 명시).

**확정 요청:** 이 방향으로 (1) `benign_frontend_locustfile.py` 생성, (2) DB는 부산물 캡처 절차만
문서화(코드 없음)로 진행할지 알려줘. attack.md와 함께 확정되면 실제 파일들을 만든다.
