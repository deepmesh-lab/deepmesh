# session.md — KD-CNN+OCSVM 학습·분석 세션 종합

> deepmesh MSA 트래픽으로 논문(*Lightweight Service Mesh for Intrusion Detection using KD-CNN*)의
> 침입탐지 파이프라인을 **전처리 → Colab 학습 → 결과 분석 → 누수 검증 → 커밋 계획**까지 진행한 세션 기록.
> 상세는 각 문서로 링크: [`model.md`](model.md) · [`commit.md`](commit.md) · [`collect.md`](collect.md) · [`training/COLAB_PLAN.md`](training/COLAB_PLAN.md)

---

## 0. 세션 목표와 흐름

이전 세션에서 **트래픽 수집(net-zero) + pcap 회수 + 전처리(npy)** 까지 완료. 이번 세션은:

1. **teacher 아키텍처 불일치 해소** (논문 Table 5 vs repo 실제 코드)
2. **Colab 학습 실행** (`k8s.ipynb`) — 서비스별 2x8 배포모델 + auth 크기 스윕 5종
3. **결과 분석** → [`model.md`](model.md) 작성
4. **마스킹 ON/OFF 시각적 ablation** (`viz_svm` vs `viz_svm2`)
5. **서비스별 모델 설계 근거** 정리
6. **데이터 누수 감사** (`training/leakage_audit.py`) — 성능이 진짜임을 검증
7. **GitHub 커밋 계획** → [`commit.md`](commit.md) 작성

---

## 1. 이 세션의 산출물

### 생성/수정한 문서·스크립트
| 파일 | 종류 | 역할 |
|---|---|---|
| `model.md` | 신규 | ★ 학습 결과 총정리(성능·누수감사·크기스윕·마스킹·설계근거·한계, 10개 절) |
| `commit.md` | 신규 | GitHub 4개 PR 계획 + 커밋 제외 정책 + 서버 명령어 요약 |
| `session.md` | 신규 | (본 문서) 세션 전체 종합 |
| `training/leakage_audit.py` | 신규 | 데이터 누수 감사 스크립트(exit 0/1, CI 게이트) |
| `training/sweep_sizes.py` | 신규 | 학생 5종 크기 스윕(동일 teacher 재사용, 공정 비교) |
| `training/student_cnn.py` | 수정 | Student 5종(1x8/1x16/2x8/2x16/2x32) + Teacher(shallow/deep), default=2x8 |
| `training/train_kd_pipeline.py` | 수정 | `--teacher-pth`(사전학습 teacher 재사용), arch 5종 지원 |
| `training/COLAB_PLAN.md` | 수정 | teacher=shallow 정합, 크기 스윕 절 추가 |
| `.gitignore` | 수정 | pcap/npy/모델바이너리/zip/local_files/pdf 제외 |
| `k8s.ipynb` | 실행 | Colab 학습 노트북(출력 포함) |

### 학습 결과물 (`colab_results/`)
- `models/<svc>/` — auth·post·comment·frontend·mysql 배포 2x8 (`student_ts.pt`, `ocsvm.pkl`, `threshold.json`, `eval_results.json`)
- `models/auth_sweep/<arch>/` — 1x8·1x16·2x8·2x16·2x32 크기 비교
- `viz_svm/*.png` — OCSVM 결정경계(마스킹 ON) / 루트 `viz_svm2/*.png` — unmask 입력(ablation)
- `leakage_audit.json` — 누수 감사 결과(총 0건)

---

## 2. 핵심 결과 — 최종 held-out 성능 (배포 2x8, 마스킹 ON)

**test benign(FPR) + test attack(Recall).** train benign으로만 학습, test는 별도 시점 캡처.

| service | vs attack | ROC-AUC | FPR(test) | Recall |
|---|---|---|---|---|
| auth | brute | 0.925 | 0.116 | 0.971 |
| auth | k8s | 0.961 | 0.116 | 1.000 |
| post | k8s | 1.000 | 0.065 | 1.000 |
| comment | k8s | 1.000 | 0.011 | 1.000 |
| frontend | k8s | 0.999 | 0.025 | 0.997 |
| mysql | k8s | 0.999 | 0.010 | 1.000 |

- **탐지력 우수**(Recall 0.97~1.00), ROC-AUC 0.925~1.00 — 논문 목표(95.7%)를 auth-brute만 소폭 하회.
- **FPR이 target 1% 초과**(auth 11.6%): train↔test benign **분포 이동** — 캘리브레이션 이슈(모델 결함 아님).

### 학생 크기 스윕 (내부 val)
| arch | params | val ROC-AUC | Recall@thr | 비고 |
|---|---|---|---|---|
| 1x8 | 1.23K | 0.861 | 0.478 | 과소적합 |
| **2x8** | **5.69K** | **1.000** | **0.999** | **배포 채택**(sweet spot) |
| 1x16 | 12.64K | 1.000 | 0.995 | |
| 2x16 | 13.87K | 1.000 | 0.997 | |
| 2x32 | 87.26K | 0.993 | 0.900 | 커도 이득 없음 |

---

## 3. 핵심 발견·결정

### 3-1. Teacher 아키텍처 불일치 (해소)
- 논문 Table 5 headline teacher "CNN-4x128 **743.52K**"는 **repo에 없는 값**(논문표↔코드 불일치).
- repo 실제 teacher: **shallow 314.69K**(`train_k8s.Encoder`) / **deep 3.31M**(`Encoderv2`).
- 논문 공개 코드가 2x8/2x16/2x32/1x16 증류에 실제 쓴 것 = **shallow**. 1x8만 deep.
- **결정**: `--teacher shallow` 고정(논문 코드 정합, 크기 스윕 공정 비교). 743.52K는 재현 불가로 명시.

### 3-2. 데이터 누수 감사 (성능이 진짜인가) → [`leakage_audit.py`]
행 단위 blake2b 해시 대조, **전 항목 0건**:

| 검사 | 결과 |
|---|---|
| train benign ∩ test benign | 0.00% (전 서비스) |
| attack ∩ train benign | 0 |
| attack ∩ test benign | 0 |
| brute ∩ k8s | 0 |

- **코드 확정**: 파이프라인은 `X_benign.npy`만 로드, `X_testbenign`은 코드 참조조차 없음(cell 6 평가만).
- **결정적 반증**: 누수라면 전부 만점이어야 하나, **auth-brute만 0.925로 낮음** → K8s 이탈은 프로토콜(:443 TLS)·목적지가 benign(:8080 HTTP)과 확연히 달라 "원래 쉬운 과제", brute(같은 :8080)만 어려움. 이 비대칭이 누수 부재의 증거.

### 3-3. 마스킹 ON/OFF 시각적 ablation (`viz_svm` vs `viz_svm2`)
`viz_svm2`는 마스킹-학습 모델에 **unmask 입력**을 넣어 그린 것(threshold가 마스킹 모델과 일치):
- **auth/post/comment**: unmask 시 k8s가 PC1 −700~+1300로 폭발 → 전송계층(seq/ack/window) **캡처 종속 confound**. 신호 아님.
- **brute**: transport confound 이득 없음(benign과 겹침) → 앱계층 난제임을 재확인.
- **frontend**: 마스킹 ON/OFF 거의 무관 → payload/행동 기반 분리(robust).
- **mysql**: 마스킹 끄면 오히려 겹침 심화 → 마스킹 이득 최대.
- **결정**: 마스킹 ON 학습이 타당. 배포 시 **런타임 입력도 동일 마스킹 필수**(unmask 시 임베딩 폭주).

### 3-4. 왜 서비스별(per-service) 모델인가
"backend benign이 겹쳐 보이는데 왜 안 합치나?"에 대한 답:
- **임계값이 서비스마다 178배 차이**(auth −0.39 vs comment −70.42) → 겹침은 2D 착시, 128D 기하는 다름.
- 탐지 대상이 "서비스별 정상으로부터의 이탈" → 합치면 합집합 경계가 커져 **공격이 숨을 공간 확대**.
- 사이드카 배포 구조상 서비스별이 자연스럽고 비용 ~0, 알림 국소화(attribution) 이점.

---

## 4. 재현 방법 (실행 명령)

### 4-1. Colab 학습 (`k8s.ipynb` 흐름)
```python
# 1) 셋업: Drive에서 training_colab.zip → unzip → build_parser.sh → .so
# 2) 서비스별 X_attack 생성 (auth=brute+k8s, 그외=k8s)
# 3) 크기 스윕 (논문 Table 5)
!python sweep_sizes.py --data data/auth --out models/auth_sweep --teacher shallow --limit 50000
# 4) 배포 2x8 전 서비스 학습 (마스킹 ON)
for s in ['auth','post','comment','frontend','mysql']:
    !MASK_TRANSPORT=1 python train_kd_pipeline.py --data data/{s} --out models/{s} --arch 2x8 --teacher shallow --limit 50000
# 5) held-out 평가 (test benign + test attack) — model.md §2 표 재현
# 6) 마스킹 OFF ablation (선택): MASK_TRANSPORT=0 재학습
```

### 4-2. 데이터 누수 감사
```bash
cd training && python leakage_audit.py                 # exit 0 = 통과
python leakage_audit.py --json ../colab_results/leakage_audit.json
```

### 4-3. 전처리 (pcap → npy)
```bash
cd training && bash build_parser.sh && python preprocess_k8s.py
```

### 4-4. 트래픽 재수집
→ [`collect.md`](collect.md) §2~§6 (3계층 업로드 → nsenter/tcpdump 캡처 → attacker/RBAC → 회수 → DB 복원).

---

## 5. GitHub 커밋 계획 (요약, 상세는 [`commit.md`](commit.md))

**브랜치**: `feat/traffic → develop`. 대용량(pcap 3GB/npy 2.8GB/zip 308MB/모델바이너리) 제외.

| PR | 내용 |
|---|---|
| #1 feat(locust) | 트래픽 생성 도구 + net-zero |
| #2 docs(collect) | 수집 런북 + K8s 서버 명령어 총정리 |
| #3 feat(training) | 전처리+KD-CNN/OCSVM 파이프라인(+누수감사) |
| #4 docs(model) | 결과 분석 + 시각화 |

---

## 6. 남은 작업 (Issue)

| # | 작업 | 근거 |
|---|---|---|
| A | 마스킹 OFF **정량** ablation (재학습 후 test 지표 비교) | model.md §9-3 |
| B | FPR 캘리브레이션 갭 해소 (threshold 재보정) | model.md §3 (test FPR>1%) |
| C | 사이드카 배포 + 지연 벤치(≤14ms·≥600rps, `cpu:1000m`) | model.md §10 |

---

## 7. 문서 지도

| 문서 | 다루는 것 |
|---|---|
| `session.md` | (본 문서) 세션 전체 종합·색인 |
| `model.md` | 학습 결과 상세 분석(성능/누수/마스킹/설계근거/한계) |
| `commit.md` | 커밋/PR 계획 + 제외 정책 + 서버 명령어 요약 |
| `collect.md` | 트래픽 수집 실행 런북(명령어 전체) |
| `traffic_collect.md`, `modify_plan.md` | 수집 설계 원안·수정 계획 |
| `training/COLAB_PLAN.md` | Colab 학습 절차서 |
