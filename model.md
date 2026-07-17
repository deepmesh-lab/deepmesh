# model.md — KD-CNN + OCSVM 학습 결과 총정리

> 논문 *"Lightweight Service Mesh for Intrusion Detection using KD-CNN in Cloud-Native Environments"* 재현.
> 서비스별 **Teacher(대조학습) → Student(지식증류) → OCSVM(benign-only)** 파이프라인을
> 우리가 K8s 클러스터에서 직접 수집한 트래픽으로 학습·평가한 결과.
> 산출물: `colab_results/models/`, 실행 노트북: `k8s.ipynb`, 파이프라인: `training/`.

---

## 1. 데이터 구성 — 무엇으로 학습하고 무엇으로 평가했나

| 구분 | 파일 | 사용처 |
|---|---|---|
| **train benign** | `data/<svc>/X_benign.npy` | **학습 전용**. 세션 단위로 train/val(30%) 분리 → train으로 teacher·student·OCSVM fit |
| **(내부) val benign** | ↑ 위에서 분리 | gamma 선택 · threshold(target-FPR 1%) 보정 · `eval_results.json` 수치 |
| **test benign** | `data/<svc>/X_testbenign.npy` | **최종 held-out 평가 전용** (별도 시점 캡처, 학습에 전혀 미사용) |
| **test attack** | `data/_attack/X_brute.npy`, `X_k8s.npy` | 평가 전용 (gamma 선택엔 내부 attack 일부만) |

- **학습은 오직 benign** (one-class). attack은 threshold/gamma 튜닝과 평가에만 등장.
- **공격 매핑(논문 아이디어)**: `brute`=앱계층 무차별 대입(auth 전용), `k8s`=침해 pod의 K8s API egress 이탈(enum+manipulate, 전 서비스 공통).
  - **auth** → `{brute, k8s}` 로 평가
  - **post / comment / frontend / mysql** → `{k8s}` 로 평가
- **전송계층 마스킹 ON** (`MASK_TRANSPORT=1`): 세션이미지 rows 7–18(window/urgptr/seq/ack)을 0으로 → 캡처환경 confound 제거. 전 결과가 이 조건.

### 학습 규모 (2x8 배포모델 기준)
| svc | benign train | benign val | test benign | 세션분할 |
|---|---|---|---|---|
| auth | 34,945 | 15,055 | 있음 | ON |
| post | 31,572 | 18,428 | 있음 | ON |
| comment | 32,441 | 17,559 | 있음 | ON |
| frontend | 16,583 | 2,092 | 있음 | ON |
| mysql | 37,948 | 12,052 | 있음 | ON |

(benign 원본 캡: auth/post/comment/mysql 각 60,000 window, frontend 18,675 — `--limit 50000`로 서브샘플)

---

## 2. 모델 구성 (논문 정합)

| 요소 | 구성 | 파라미터 |
|---|---|---|
| **Teacher** | `shallow` (`train_k8s.Encoder`) — Conv 1→32→64 → AAP(4,4) → FC 256 → 128, NT-Xent 대조학습 | **314.69K** |
| **Student (배포)** | `2x8` — Conv 1→4→8 → AAP(2,2) → FC 32 → 128, KD(MSE) 증류 | **5.69K** |
| **OCSVM** | RBF, ν=0.1, gamma는 val ROC-AUC 그리드(`scale,0.1,1,10`)에서 자동 선택 | — |
| 임베딩 차원 | 128 | |
| epoch | teacher 30 / student 20 | |
| threshold | val benign에서 target-FPR=1% 분위수 (`threshold_df`) | |

> **Teacher 주의**: 논문 Table 5 headline teacher "CNN-4x128, 743.52K"는 공개 repo에 **존재하지 않는 값**(논문표↔코드 불일치). repo 공개 코드가 2x8/2x16/2x32/1x16 증류에 실제 쓴 teacher는 **shallow(314.69K)** 이므로 이를 채택(논문 코드 정합). 1x8만 deep(3.31M) 사용.

---

## 3. 최종 성능 — held-out TEST benign + TEST attack (★ 진짜 수치)

**cell 6 출력. 배포모델 2x8, 마스킹 ON.** threshold는 학습 때 val benign으로 target-FPR 1%에 맞춰 고정한 값을 그대로 사용.

| service | vs attack | ROC-AUC | FPR(test benign) | Recall(attack) |
|---|---|---|---|---|
| **auth** | brute | 0.925 | 0.116 | 0.971 |
| **auth** | k8s | 0.961 | 0.116 | 1.000 |
| **post** | k8s | 1.000 | 0.065 | 1.000 |
| **comment** | k8s | 1.000 | 0.011 | 1.000 |
| **frontend** | k8s | 0.999 | 0.025 | 0.997 |
| **mysql** | k8s | 0.999 | 0.010 | 1.000* |

\* mysql Recall 표기는 cell 6 기준 0.997.

### 해석
- **탐지력(Recall)은 전 서비스 0.97~1.00** — 공격을 거의 놓치지 않음. K8s 이탈(k8s)은 특히 완벽(1.0)에 가까움.
- **ROC-AUC 0.925~1.000** — 논문 목표(95.7%)를 auth-brute(0.925)만 소폭 하회, 나머지는 상회.
- **FPR이 target(1%)보다 높음** (auth 11.6%, post 6.5%): **분포 이동(distribution shift)** 때문. threshold를 train-캡처 val benign으로 잡았는데, test benign은 *다른 시점 캡처*라 benign 점수 분포가 살짝 밀림 → 같은 컷에서 오탐 증가. **모델 결함이 아니라 캘리브레이션 이슈** (§7 참고).

---

## 4. 데이터 누수 감사 (성능이 진짜인가)

ROC-AUC가 0.999~1.000으로 높아 "학습셋을 test로 쓴 것 아니냐"는 의심이 자연스럽다. **행 단위 해시 대조 + 코드 추적으로 누수 없음을 확정했다.**

### 검사 결과 (모두 0)
| 검사 | 결과 | 의미 |
|---|---|---|
| train benign ∩ test benign | **0.00%** (전 서비스) | test 이미지가 학습에 전혀 안 들어감 |
| attack ∩ train benign | **0** | 공격이 정상 학습에 안 섞임 |
| attack ∩ test benign | **0** | 평가셋 라벨 오염 없음 |
| brute ∩ k8s | **0** | 두 공격셋도 서로 독립 |

(blake2b 행 해시로 교집합 계수. train/test는 각각 `result/benign/`, `result/test/benign/`의 **다른 시점 별도 pcap**에서 전처리.)

**재현**: `cd training && python leakage_audit.py`
(누수 0건이면 exit 0, 하나라도 발견 시 exit 1 — CI 게이트로도 사용 가능. `--json audit.json`으로 결과 저장.
저장된 결과: `colab_results/leakage_audit.json`.)

### 코드 레벨 확정
- `train_kd_pipeline.py`는 **`X_benign.npy`만** 로드(학습). `X_testbenign`은 코드에 참조조차 없음 → test는 cell 6 최종 평가에서만 등장.
- 내부 val 분할은 **세션(group) 단위**라 같은 TCP 연결의 near-dup이 train/val로 쪼개지지 않음.

### 왜 높은가 — 누수가 아니라 "쉬운 과제"라서 (결정적 반증)
**auth-brute만 ROC 0.925로 낮다.** 누수였다면 난이도와 무관하게 전부 만점이어야 한다. 실제 비대칭:
- **k8s 이탈(≈1.0)**: 침해 파드가 **:443으로 K8s API 호출** → benign 앱 트래픽(:8080 HTTP/JSON)과 목적지·프로토콜(TLS)이 통째로 다름 → 자명하게 갈리는 easy task.
- **brute(0.925)**: benign과 **같은 :8080·같은 로그인 엔드포인트** → 유일한 hard case라 점수 하락.

이 **"easy는 1.0, hard는 0.925" 비대칭이 곧 누수 부재의 증거**다. 덤으로 §3의 **test FPR 갭(1% 초과)** 도 test가 진짜 unseen(분포 이동 발생)이라는 방증 — 누수라면 FPR도 1%에 딱 맞았을 것.

### 결론
성능은 **진짜**다. 단 높은 값은 "탐지가 마법같이 잘 돼서"가 아니라 **K8s egress 이탈이 benign과 프로토콜·목적지가 확연히 달라 원래 쉬운 문제**이기 때문. 진짜 어려운 앱계층 공격(brute)에서 점수가 떨어지는 것이 정상적이고 건강한 신호다.

---

## 5. 내부 val 수치 (`eval_results.json`) — 참고용(낙관적)

같은 캡처를 쪼갠 val이라 낙관적. 학습이 수렴했는지 sanity check 용도.

| svc | gamma | val ROC-AUC | FPR@thr | Recall@thr | threshold_df |
|---|---|---|---|---|---|
| auth | 1.0 | 0.9993 | 0.010 | 0.983 | −0.390 |
| post | 0.1 | 1.0000 | 0.010 | 1.000 | −5.514 |
| comment | scale | 1.0000 | 0.010 | 1.000 | −70.418 |
| frontend | 1.0 | 0.9998 | 0.010 | 0.998 | −2.596 |
| mysql | 0.1 | 0.9993 | 0.010 | 0.997 | −4.441 |

→ 내부 val에선 FPR이 정확히 1%로 맞음. test에서 벌어지는 격차(§3)가 곧 일반화 갭.

---

## 6. 학생 크기 스윕 (auth, 논문 Table 5 대응)

teacher(shallow) **1회 학습 후 5개 학생이 동일 teacher로 증류**(공정 비교). 내부 val 기준.

| arch | params | val ROC-AUC | Recall@thr | 비고 |
|---|---|---|---|---|
| 1x8 | 1.23K | 0.861 | 0.478 | **과소적합** — 너무 작아 탐지력 급락 |
| 2x8 | **5.69K** | 1.000 | 0.999 | **배포 채택** — 최소 크기로 최고 성능 |
| 1x16 | 12.64K | 1.000 | 0.995 | 양호하나 2x8보다 큼 |
| 2x16 | 13.87K | 1.000 | 0.997 | 양호 |
| 2x32 | 87.26K | 0.993 | 0.900 | 크지만 오히려 캘리브레이션 난이도↑ |

**결론**: **2x8이 크기 대비 성능의 sweet spot**. 1x8은 용량 부족으로 붕괴(Recall 0.48), 2x32는 커도 이득 없음 → 논문의 2x8 배포 선택을 우리 데이터로도 재확인.

---

## 7. 마스킹 ON vs OFF — 시각적 ablation (`viz_svm` vs `viz_svm2`)

배포 모델은 **전송계층(rows 7–18: window/urgptr/seq/ack) 마스킹 ON**으로 학습했다.
`viz_svm2/`는 **동일한 마스킹-학습 모델에 마스킹을 끈(transport 필드를 살린) 입력**을 넣어 그린 결정경계 시각화다
(threshold 값이 마스킹 모델의 `eval_results.json`과 정확히 일치 → 모델·OCSVM·임계값은 마스킹 모델 그대로, 입력만 unmask).
즉 **"전송계층 바이트가 실제로 무엇을 만들어내는가"** 를 드러내는 그림이다.

### 관측 (PCA 2D, 상단=설명분산, thr=배포 임계값)

| svc | 설명분산 | 마스킹 OFF에서 관측된 것 |
|---|---|---|
| **auth** | 53% | k8s가 PC1≈**−700**까지 폭발적으로 퍼짐. benign은 원점에 밀집, **brute(빨강)는 benign과 겹침** |
| **post** | 55% | k8s가 PC1≈**−800**까지 폭발, benign 원점 밀집 |
| **comment** | 59% | k8s가 PC1≈**+1300**까지 폭발, benign 원점의 한 점으로 응축 |
| **frontend** | 38% | **마스킹 ON과 사실상 동일**(scale ±20, 좌 k8s / 우 benign 깔끔 분리) |
| **mysql** | 38% | benign과 k8s가 **크게 겹침**(경계선이 두 덩어리를 관통), 좌하단에 k8s 부분군집만 분리 |

### 해석 — 마스킹이 제거한 것은 "캡처 종속 confound"

1. **auth/post/comment의 스케일 폭발(−700 ~ +1300)은 신호가 아니라 confound다.**
   전송계층 seq/ack/window 바이트를 살리면 k8s 공격 임베딩이 극단 좌표로 튀는데, 이는 payload·행동이 아니라
   **benign 캡처와 attack 캡처의 전송계층 바이트가 캡처 시점 탓에 크게 다르기 때문**이다.
   "분리가 더 극적으로 보이지만" 그 분리는 **재현 불가능한 캡처 아티팩트** — 마스킹이 정확히 이걸 잘라낸다.
   (설명분산이 마스킹 OFF에서 53–59%로 치솟는 것도, 소수 transport 차원이 분산을 장악한다는 방증.)

2. **brute는 전송계층 confound 이득을 못 받는다(auth 그림에서 benign과 겹침).**
   brute-force는 앱계층 공격이라 전송 필드가 정상 로그인과 유사 → 마스킹을 켜든 끄든 **애초에 transport로는 안 갈린다.**
   이는 §3의 auth-brute ROC 0.925(최저)와 정확히 일치. **brute가 진짜 어려운 케이스**이고, 마스킹은 brute 탐지를 해치지 않는다.

3. **frontend는 마스킹 ON/OFF가 거의 무관(동일 그림).**
   frontend의 분리는 전송계층이 아니라 **payload/행동 기반**이라 robust. 우리 파이프라인에서 가장 "정직하게" 분리되는 서비스.

4. **mysql은 마스킹을 끄면 오히려 겹침이 심해진다.**
   mysql은 전송 바이트가 깨끗한 신호가 아니라 **노이즈를 주입** → 마스킹 ON이 분리에 유리. 마스킹의 이득이 가장 큰 서비스.

### 결론
마스킹은 (a) auth/post/comment에서 **캡처 종속 전송계층 confound로 인한 과대 분리**를 제거하고,
(b) frontend처럼 **진짜 content 기반 분리**는 그대로 보존하며,
(c) brute 같은 앱계층 난제의 탐지력을 **해치지 않는다**(원래 transport로 안 갈렸으므로).
→ **마스킹 ON 학습 결정이 타당함을 시각적으로 재확인.** 다만 이는 정성(定性) 근거이며,
정량 ablation(§9-3, `MASK_TRANSPORT=0` **재학습** 후 test 지표 비교)은 여전히 필요하다.

> ⚠️ 실무 함의: 배포 시 **런타임 입력도 반드시 동일 마스킹**을 해야 한다. viz_svm2가 보여주듯
> 마스킹-학습 모델에 unmask 입력을 넣으면 임베딩이 폭주(train/serve 불일치)한다.

---

## 8. 설계 근거 — 왜 서비스별(per-service) 모델인가

> "backend끼리 benign 분포가 겹쳐 보이는데 왜 하나로 안 합치나?"에 대한 답.
> 결론: **겹쳐 '보이는' 건 2D 투영 착시이고, 합치면 공격이 숨을 공간만 넓어진다.**

### 근거 0 — 우리 모델이 이미 "서비스마다 다르다"고 증명함
benign이 눈으로 겹쳐도 각 OCSVM이 잡은 **임계값·gamma가 서비스마다 극단적으로 다르다**:

| svc | gamma | threshold_df | test FPR |
|---|---|---|---|
| auth | 1.0 | **−0.39** | 11.6% |
| post | 0.1 | **−5.51** | 6.5% |
| comment | scale | **−70.42** | 1.1% |
| mysql | 0.1 | **−4.44** | 1.0% |

threshold가 **−0.39 vs −70.42 = 178배 차이**. backend benign이 진짜 같은 분포였다면 이 값이 비슷해야 한다.
실제로는 서비스별 임베딩 밀도·경계 스케일이 완전히 다르다 → **하나로 합치면 최소 두 서비스의 임계값이 심하게 어긋나 오탐/미탐 폭증**.
즉 "겹친다"는 PCA 2D 착시이고, 결정에 쓰는 128D 기하는 서비스마다 다르다.

### 근거 1 — 탐지 대상 자체가 "서비스별 정상으로부터의 이탈"
잡으려는 건 *전역 이상치*가 아니라 *"post답지 않은 post 트래픽"*. 침해된 post 파드가 K8s API로 lateral하게 튀는 순간을 잡으려면
"post의 정상"이 기준선이어야 한다. 3개 backend를 합치면 기준선이 **auth ∪ post ∪ comment 합집합**이 되고,
공격자는 *"다른 backend의 정상처럼"* 행동하기만 하면 통과한다.

### 근거 2 — 합집합 경계 = 더 큰 부피 = 공격이 숨을 공간 확대 (핵심 통계 논리)
OCSVM은 benign support(껍질)를 학습한다. 겹치지만 완전히 같지는 않은 3개 클러스터의 합집합 껍질은
각 껍질보다 **반드시 부피가 크다**. 늘어난 부피가 곧 **false-accept 영역** — 공격이 "정상 껍질 안"에 앉을 여지.
서비스별 모델은 각 정상을 최소 부피로 조여 이 여지를 없앤다. 민감도가 오르는 원리.

### 근거 3 — 배포 구조가 이미 서비스별(sidecar)
논문 아키텍처는 각 파드 옆 사이드카가 **자기 서비스 트래픽만** 본다(auth 사이드카는 post를 애초에 못 봄).
추론이 서비스별이니 학습도 서비스별이 자연스럽고, 모델도 5.69K라 5개 두는 비용이 사실상 0. 합치는 게 오히려 배포와 안 맞다.

### 근거 4 — 알림의 국소화(attribution)
서비스별 모델은 경보 시 **"어느 서비스가 이탈했는지"** 를 바로 알려준다 → 사고 대응에서 blast radius를 좁힌다.
합친 모델은 "backend 중 뭔가 이상함"까지만 말한다.

### 언제 합쳐도 되나 (정직한 반대편)
backend가 **진짜 상호 교환 가능**(동일 엔드포인트·릴리스 주기)하고 **공격이 서비스 무관**할 때만 손해가 없다.
그런데 그 가정이 성립하면 "lateral movement / 특정 파드 침해"라는 위협 모델 자체가 무의미해진다. 우리 위협 모델을 지키는 한 분리가 맞다.

---

## 9. 한계 및 후속 조치

1. **FPR 캘리브레이션 갭** (가장 중요): test benign FPR이 target 1%를 초과(auth 11.6%). 원인은 train↔test benign 캡처 분포 이동.
   → **후속**: threshold를 test benign 일부(또는 운영 초기 benign)로 재보정(`recalibrate_ocsvm.py`), 또는 학습 benign에 캡처 다양성 추가.
2. **auth-brute ROC 0.925**: brute-force가 정상 auth 로그인과 앱계층에서 가장 유사 → 상대적으로 어려움. 나머지(k8s 이탈)는 거의 완벽.
3. **마스킹 OFF 정량 ablation 미반영**: §7은 시각적(정성) 확인까지 완료. 남은 것은 cell 9(`MASK_TRANSPORT=0`로 **재학습** → `models_nomask/`) 후 test 지표(ROC/FPR/Recall)를 §3 표와 나란히 비교하는 정량화.
4. **시각화 경계 표시**: `viz_svm/frontend_svm.png`는 PCA 2축 설명분산이 38%로 낮아 경계 등고선이 평면에 안 잡힘(분류 자체는 정상). 발표용 경계선은 2D 대용 OCSVM로 별도 생성 가능.

---

## 10. 산출물 위치

```
colab_results/
├── models/<svc>/          # auth, post, comment, frontend, mysql (배포 2x8)
│   ├── student_ts.pt      # ★ 배포용 TorchScript
│   ├── ocsvm.pkl          # ★ 배포용 OCSVM
│   ├── threshold.json     # ★ 배포용 임계값(target-FPR 1% 보정)
│   ├── student.pth teacher.pth
│   └── eval_results.json  # 내부 val 수치
├── models/auth_sweep/<arch>/   # 1x8·1x16·2x8·2x16·2x32 크기 비교
├── viz_svm/<svc>_svm.png       # OCSVM 결정경계 (마스킹 ON, 배포 조건)
└── viz_svm2/<svc>_svm.png      # 동일 모델·unmask 입력 (§7 마스킹 ablation 시각화)
```

**배포**: `student_ts.pt` + `ocsvm.pkl` + `threshold.json` + Linux `packet_parser_stack.so` →
`deployment-with-sidecar.yaml`의 reverse-proxy(model-pvc)에 탑재, 런타임 `proxy_detection.py`가 로드.
⚠️ 학습을 마스킹 ON으로 했으므로 **런타임도 동일 마스킹 필요**.
