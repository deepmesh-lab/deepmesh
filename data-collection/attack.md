# attack.md — 공격 트래픽 시나리오 설계 (attack_locust 작성 전 기획)

> 목적: 논문 재현을 위해 **라벨된 악성 트래픽**을 서비스별로 생성한다. 실제 존재하는
> 엔드포인트/취약점만 대상으로 하며, **시퀀스 기반(5-패킷 슬라이딩 윈도우) 이미지가
> 효과적인 시나리오**를 우선한다. 이 문서 확정 후 `attack_*_locustfile.py` 를 만든다.
>
> 대상 시스템은 우리 소유의 IDS 테스트베드다(방어 연구용 라벨 데이터 생성). 모든 공격은
> 우리 게시판 MSA에만 향한다.

---

## 0. 원칙

1. **라벨링은 "의도" 기준.** benign 수집은 4xx가 0%여야 했지만, **attack은 서버가
   막아서 4xx/403/404가 나도 상관없다** — 공격 시도 자체가 악성 라벨이다. 캡처 **시간창**을
   malicious로 라벨한다.
2. **benign 캡처와 절대 섞지 않는다.** attack pcap은 별도 디렉토리
   (`./pcap/attacks/<service>/`)에 저장 → 전처리에서 `--attack` 로 넣어 `X_attack.npy` 생성.
3. **DoS/자원고갈은 범위 밖**(논문도 제외). 볼륨성 공격은 brute-force·enumeration·scraping으로
   구성하되 rate를 과하지 않게(초당 수십 건 수준) — 탐지용 패턴 생성이 목적이지 서비스 마비가 아님.
4. **HTTP로 표현 가능한 공격만 locust로.** DB 직접 공격·컨테이너 내부발 lateral movement는
   locust로 불가(§5) → 별도 방법.

---

## 1. 시퀀스 기반 이미지가 "효과적인" 조건 — 판단 기준

논문 Fig.5의 핵심은 "단일 패킷 이미지는 안 갈라지고, **연속 5패킷 시퀀스**라야 갈라진다"였다.
따라서 **악성 신호가 여러 요청/패킷에 걸친 시간·볼륨 패턴에 있는** 공격일수록 시퀀스 이미지가
잘 잡는다.

| 신호 유형 | 시퀀스 효과 | 예 |
|---|---|---|
| **버스트/고volume 반복** (짧은 시간 동일 엔드포인트 난타) | ★★★ | brute-force, 계정 farming, 댓글 스팸 |
| **순차 스캔/열거** (ID·경로를 1씩 증가시키며 훑음) | ★★★ | postId enumeration, 존재 오라클, 경로 스캔 |
| **지속적 대량 인출** (페이지네이션 끝까지 빠르게) | ★★☆ | 게시글/댓글 벌크 exfiltration |
| **비정상 호출 시퀀스** (정상 클라가 안 하는 내부호출 연쇄) | ★★☆ | lateral movement 체인 (+ cross-replica 검증이 핵심) |
| **단일 요청 페이로드 내용** (한 요청의 바이트가 악성) | ★☆☆ | SQLi, 단발 path traversal, 단발 토큰 위조 |

→ ★★★/★★☆ 시나리오를 **주력**으로, ★☆☆(페이로드형)은 **비교·완전성용**으로 포함한다.
   (★☆☆는 시퀀스보다 패킷 바이트 내용에 의존 — 논문 표현에서도 상대적으로 약한 케이스임을 명시.)

---

## 2. 대상별 공격 시나리오 (실재 엔드포인트 기준)

### 2-1. auth-service (localhost:8080)

| ID | 시나리오 | 엔드포인트/메서드 | 상세 | 시퀀스 | MITRE |
|---|---|---|---|---|---|
| **A1** | 크리덴셜 브루트포스 | `POST /api/auth/login` | 고정 username + 패스워드 사전 난타. 거의 동일한 소형 POST가 초당 다수, 응답 401 연속 | ★★★ | T1110 |
| **A2** | 크리덴셜 스터핑 | `POST /api/auth/login` | (username,password) 쌍 목록을 순차 시도. A1과 유사하나 username도 가변 | ★★★ | T1110.004 |
| **A3** | 계정 farming(가입 폭주) | `POST /api/auth/signup` | 무작위 계정 대량 생성. 성공(200) 다수 + 중복시 409 | ★★☆ | T1136 |
| **A4** | 내부신뢰 엔드포인트 악용 | `GET /internal/auth/validate` | **외부 클라가 직접** validate 호출(정상은 post/comment만 호출) + 토큰 재생/위조(garbage Bearer) 반복 | ★★☆ | T1550/T1078 |
| **A5** | 로그인 SQLi 시도 | `POST /api/auth/login`,`/signup` | username/password에 `' OR '1'='1`, `admin'--`, `UNION SELECT` 등 주입(JPA라 대개 실패하나 페이로드가 라벨 대상) | ★☆☆ | T1190 |

> A4 주: 단발 호출 자체가 이미 이상(외부→internal)이라 **cross-replica 검증(Algorithm 1)**이
> 주 탐지기다. 시퀀스 이미지는 반복 probe일 때 보조. 토큰 iteration을 섞어 시퀀스성을 높인다.

### 2-2. post-service (localhost:8082)

| ID | 시나리오 | 엔드포인트/메서드 | 상세 | 시퀀스 | MITRE |
|---|---|---|---|---|---|
| **P1** | postId 열거/스크래핑 | `GET /api/posts/{id}` (id=1..N 순차) | 전체 게시글 ID 공간을 순차적으로 훑어 덤프. 정상은 몇 개만 조회 | ★★★ | T1119 |
| **P2** | 존재 오라클 열거 | `GET /internal/posts/{postId}/exists` | **인증 없는 내부 엔드포인트**를 postId 순회로 때려 유효 ID 지도 작성 | ★★★ | T1087/T1595 |
| **P3** | 대량 삭제 시도 | `DELETE /api/posts/{id}` (id 순회) | ID 순회 삭제. 소유권 검사로 대부분 403/404지만 **순차 DELETE 버스트 패턴**이 신호 | ★★★ | T1485 |
| **P4** | 벌크 exfiltration | `GET /api/posts?page=1..N&size=50` | 최대 size로 전 페이지를 빠르게 순회해 전량 인출 | ★★☆ | T1030 |
| **P5** | 게시글 SQLi/XSS 페이로드 | `POST /api/posts` | title/content에 주입 페이로드. 단일 요청 내용이 악성 | ★☆☆ | T1190 |
| **P6** | 경로 탐색/엔드포인트 스캔 | `GET /actuator/*`, `/api/../`, `/.env`, 인코딩된 `../` | 숨은 경로 probing, 404 버스트 | ★★☆ | T1083/T1595 |

### 2-3. comment-service (localhost:8081)

| ID | 시나리오 | 엔드포인트/메서드 | 상세 | 시퀀스 | MITRE |
|---|---|---|---|---|---|
| **C1** ★대표 | 댓글 일괄 삭제(무인증) | `DELETE /internal/posts/{postId}/comments` | **인증 없는 내부 엔드포인트**를 postId 순회로 때려 전 게시글 댓글 말살. comment가 평소 절대 안 받는 패턴 | ★★★ | T1485 |
| **C2** | 댓글 exfiltration | `GET /api/comments/{postId}/comments?size=50` (cursor walk) | 모든 게시글의 댓글을 커서로 끝까지 순회 인출 | ★★☆ | T1030 |
| **C3** | 댓글 스팸 flood | `POST /api/comments/{postId}/comments` | 동일 게시글에 댓글 대량 반복 작성(모더레이트 rate) | ★★☆ | T1565 |
| **C4** | 댓글 SQLi 페이로드 | `POST /api/comments/{postId}/comments` | content에 주입 페이로드 | ★☆☆ | T1190 |

### 2-4. frontend (Nginx+React, localhost:3000)

| ID | 시나리오 | 엔드포인트/메서드 | 상세 | 시퀀스 | MITRE |
|---|---|---|---|---|---|
| **F1** | 파일/엔드포인트 스캔 | `GET /admin`, `/.env`, `/.git/config`, `/config.js`, 사전 기반 경로 | 정적 SPA에 대한 숨은 파일 probing, 404 버스트 | ★★☆ | T1595 |
| **F2** | nginx 경로 탐색 | `GET /../../etc/passwd`, 인코딩 traversal | 단발 traversal 페이로드 | ★☆☆ | T1083 |

> frontend는 정적 SPA라 공격 표면이 얇다. 스캐닝(F1)이 현실적 주력이고, 실제 침해보다는
> **정상 대비 이질적 요청 패턴** 생성이 목적.

---

## 3. 시퀀스 효과 랭킹 (우선순위)

- **★★★ (주력, 시퀀스가 결정적):** P1, P2, P3, C1, A1, A2
- **★★☆ (볼륨/연쇄, 시퀀스 유효):** A3, A4, P4, P6, C2, C3, F1
- **★☆☆ (페이로드형, 시퀀스 약함 — 비교용):** A5, P5, C4, F2

→ 데이터 균형: 주력 ★★★에서 표본을 많이, ★☆☆는 소량. 논문 Fig.5식 분리를 보이려면 ★★★
   시나리오가 핵심.

---

## 4. 생성할 attack_locust 파일 (§확정 후 구현)

```
data-collection/attacks/
├── attack_auth_locustfile.py       # A1 A2 A3 A4 A5
├── attack_post_locustfile.py       # P1 P2 P3 P4 P5 P6
├── attack_comment_locustfile.py    # C1 C2 C3 C4
├── attack_frontend_locustfile.py   # F1 F2
└── attack_db.py                    # (locust 아님) MySQL 클라이언트 — §5
```

**각 파일 공통 설계:**
- 기존 benign locust처럼 `on_start`에서 auth 로그인(토큰 확보). 단 **일부 공격은 무인증**
  (A4 validate, P2 exists, C1 internal delete)이라 토큰 없이 호출.
- 시나리오별 `@task(weight)`로 구성하되, **★★★ 시나리오에 높은 weight**.
- env로 강도 조절: `RATE`(초당), `ID_RANGE`(열거 상한), `--run-time`으로 캡처창 제어.
- **성공/실패를 실패로 세지 않음**(catch_response + 항상 success 처리) — 어차피 악성 라벨.
- 시퀀스성 확보 위해 **keep-alive/커넥션 재사용**(HttpUser 기본) 유지 → 한 세션에 연속 패킷 축적.

**시나리오별 페이로드는 "트래픽 생성용"으로 표현**(무기화된 익스플로잇이 아니라, 탐지기가
학습할 이질적 요청 바이트를 만드는 수준).

---

## 5. locust로 **안 되는** 것 + 대안 (★내 이견 포함)

### 5-1. DB 공격 (MySQL) — locust 불가
MySQL은 HTTP가 아니라 **바이너리 프로토콜**이라 HTTP 부하생성기로 트래픽을 못 만든다.
- **benign DB 트래픽:** 백엔드 locust(auth/post/comment) 실행 중 **`deepmesh-mysql` netns를
  캡처**하면 백엔드가 발생시키는 정상 쿼리 트래픽이 잡힌다(→ benign.md).
- **attack DB 트래픽(`attack_db.py`):** 별도 **MySQL 클라이언트 스크립트**로 3306에 접속.
  실재 취약점은 CLAUDE.md §9의 **공유 root 크리덴셜** — 한 서비스 크리덴셜로 **다른 서비스 DB**
  (auth_db/posts_db/comments_db)를 열람/덤프하는 cross-DB 접근(T1078/T1555). `pymysql`로
  `SELECT * FROM ...` 대량 인출 등. **이건 attack_locust가 아니라 attack_db.py로 분리.**

### 5-2. 진짜 lateral movement (컨테이너 내부발) — locust는 근사만
논문 위협모델은 **침해된 pod 내부에서** 다른 서비스로 향하는 east-west 요청이다. 외부 locust는
"내부 엔드포인트를 외부에서 직접 호출"하는 것으로 **근사**할 뿐이다(A4/P2/C1이 이 근사).
진짜 재현은 pod에 exec로 들어가 스크립트 실행이 정확하지만 시연 범위상 근사 채택.
- 이 계열의 **주 탐지기는 이미지가 아니라 cross-replica 검증(Algorithm 1)** 임을 명심.

---

## 6. 캡처 & 라벨링 절차 (서비스별 반복)

```powershell
# 1) 캡처 시작 (attack 전용 디렉토리)
bash capture_docker.sh post-service 120 ./pcap/attacks/post-service
# 2) 공격 부하 실행 (동시)
$env:HOST="http://localhost:8082"; $env:AUTH_HOST="http://localhost:8080"
locust -f attacks/attack_post_locustfile.py --host http://localhost:8082 --users 10 --spawn-rate 5 --run-time 120s --headless
# 3) 전처리로 X_attack.npy 생성 (benign과 동일 .so)
python ../model-training/preprocess_deepmesh.py `
  --benign ./pcap/<svc>/*.pcap --attack ./pcap/attacks/<svc>/*.pcap `
  --out ../model-training/data/<svc> --parser-so ../servicemesh/proxy/packet_parser_stack.so
```
→ 이후 `visualize_embeddings.py`(공격점 검은 x)로 분리 확인 + `evaluate.py`로 정량평가.

---

## 7. 요약 & 내 의견/이견

- **동의:** DB·Nginx+React까지 수집해 논문 워크로드 구성을 맞추는 것 → 맞다. benign은 둘 다 필요.
- **이견 1 (DB):** DB는 **attack_locust로 만들 수 없다**(비-HTTP). benign은 캡처-부산물,
  attack은 `attack_db.py`(MySQL 클라이언트)로 분리해야 한다.
- **이견 2 (페이로드형 공격):** SQLi/단발 traversal(A5/P5/C4/F2)은 **시퀀스 효과가 낮다**.
  포함은 하되 "시퀀스로 잘 잡히는 케이스"로 기대하면 안 되고, 비교/완전성용으로 소량만.
- **이견 3 (frontend):** 정적 SPA라 공격 표면이 얇아 **스캐닝(F1)** 위주가 현실적. 침해형
  공격은 무리.
- **강조:** 논문식 "갈라지는 그림"과 정량 우위는 **★★★ 시퀀스형 공격(P1/P2/P3/C1/A1/A2)** 에서
  가장 잘 나온다. 여기에 표본을 집중하자.

**확정 요청:** 위 시나리오/파일 구성으로 진행할지, 특정 시나리오 가감이 필요한지 알려줘.
확정되면 `attack_*_locustfile.py` + `attack_db.py` 를 만든다.
