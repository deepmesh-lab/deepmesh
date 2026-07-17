# COLAB_PLAN.md — 서비스별 KD-CNN+OCSVM 학습 계획 (Colab)

> `training/` 파이프라인(논문 정합)을 Colab GPU에서 benign pcap별로 학습하는 절차.
> 전처리=학습=런타임 정합은 **동일 C 파서**(`packet_parser_stack.c`) 공유로 보장.

## 0. 전제
- `preprocess_k8s.py`로 생성한 `training/data/<svc>/{X_benign,X_testbenign}.npy` + `data/_attack/{X_brute,X_k8s}.npy` 확보.
  (⚠️ **먼저 데이터 무결성 확인** — 아래 §5. train benign 손상/ GRO 이슈 해결 후 진행.)
- 아키텍처/하이퍼파라미터는 `student_cnn.py`(논문 정합) 기준.

## 1. Colab 업로드 물
```
training/
├── packet_parser_stack.c        # Colab(Linux)에서 재빌드 (로컬 .so는 플랫폼 종속)
├── student_cnn.py data_utils.py train_kd_pipeline.py evaluate.py recalibrate_ocsvm.py
├── preprocess_k8s.py            # (재전처리 필요 시)
└── data/                        # npy (uint8) — zip 후 업로드 권장
```
- npy는 uint8이라 zip 압축률 높음: `zip -qr data.zip data/` 후 업로드.

## 2. Colab 초기 셋업
```bash
!apt-get -qq install build-essential >/dev/null
%cd training
!bash build_parser.sh                      # Linux .so 생성
!pip -q install scikit-learn joblib        # torch/numpy는 Colab 기본
```

## 3. 학습 — 마스킹 ON (1차)
서비스별 `train_kd_pipeline.py`(teacher NT-Xent → student KD → OCSVM). `data_utils`가 로드 시 마스킹(rows 7-18) 적용.
```bash
# 예: auth (2x8 배포모델, shallow teacher(논문 정합)). MASK_TRANSPORT=1(기본)
!MASK_TRANSPORT=1 python train_kd_pipeline.py \
    --data data/auth --out models/auth \
    --arch 2x8 --teacher shallow --limit 50000 --val-frac 0.3 --target-fpr 0.01
```
- 5개 서비스 일괄: `colab_run_all.py`를 우리 레이아웃(data/<svc>)으로 돌리거나 루프.
- 산출: `models/<svc>/{teacher.pth, student.pth, student_ts.pt, ocsvm.pkl, threshold.json, eval_results.json}`.

### 3-1. 학생 크기 스윕 (논문 Table 5 전체 비교)
`student_cnn.py`는 논문 5종을 모두 지원: **1x8·1x16·2x8·2x16·2x32**. `sweep_sizes.py`가 **teacher를 한 번만 학습해 5개 학생이 동일 teacher로 증류**(공정 비교) 후 표 출력.
```bash
!python sweep_sizes.py --data data/auth --out models/auth_sweep --teacher shallow
```
| arch | params | 논문 Table 5 |
|---|---|---|
| 1x8 | 1.23K | 최소, 정확도 하락 |
| 2x8 | **5.69K** | **배포 모델**(균형) |
| 1x16 | 12.64K | |
| 2x16 | 13.87K | |
| 2x32 | 87.26K | 최대 |

**teacher 선택(중요)**: 논문 공개 코드는 2x8/2x16/2x32/1x16을 **shallow(314.69K, `train_k8s.Encoder`)** 로, 1x8만 **deep(3.31M, `Encoderv2`)** 로 증류. 논문 Table 5 headline "CNN-4x128 743.52K"는 **repo에 없는 값(논문표↔코드 불일치)** → 재현 불가. **`--teacher shallow` 고정이 논문 정합** (sweep 기본값). deep은 옵션.
- FLOPs·지연은 논문 Table 5/Fig 7 대응: 학습 후 `thop`(`pip install thop`)로 FLOPs, 단일 vCPU에서 이미지당 추론시간 측정.

## 4. 평가 (논문식 매핑)
서비스별 `{test benign(0)}` vs `{attack(1)}`:
- **auth**: test benign auth vs `X_brute` (앱계층 공격) + `X_k8s` (이탈).
- **그 외**: test benign vs `X_k8s` (침해 pod의 K8s API egress = 이탈).
- 지표: Precision/Recall/F1/ROC-AUC + target-FPR threshold에서 FPR/Recall.
- `recalibrate_ocsvm.py`로 gamma/threshold를 attack 전량으로 로컬 확정.

## 5. 분포 시각화 (2단계)
1. **원시(전처리 직후)**: `visualize_dist.py` — PCA 2D + top-50 PCA LR AUC (사전 점검).
2. **임베딩(학습 후, 논문 Fig.5)**: 학습된 student 인코더로 benign/attack 임베딩 추출 → PCA/t-SNE 2D. (아래 스니펫)
```python
# student 임베딩 PCA (서비스별)
import torch, numpy as np, joblib
from student_cnn import make_student
from data_utils import load_windows   # 마스킹 포함 로드
st = make_student('2x8'); st.load_state_dict(torch.load('models/auth/student.pth')['state_dict']); st.eval()
def emb(X):
    with torch.no_grad():
        return st(torch.from_numpy(X).unsqueeze(1)).numpy()
# Xb=test benign, Xa=attack → emb → PCA(2) → scatter
```

## 6. 마스킹 OFF (2차, ablation)
같은 학습을 `MASK_TRANSPORT=0`로 반복 → 전송계층 confound 포함 시 성능 변화 비교(마스킹 효과 정량화).
```bash
!MASK_TRANSPORT=0 python train_kd_pipeline.py --data data/auth --out models_nomask/auth --arch 2x8 --teacher shallow
```

## 7. 목표 수치 (논문, 배포 CNN-2x8)
- Precision 87.4% / Recall 89.9% / ROC-AUC 95.7%, 추론 0.518ms/img(단일 vCPU), E2E ≤14ms·≥600 req/s.
- 서비스별 결과를 이 목표와 대조. 미달 시 arch/gamma/nu/epoch, 마스킹 여부, 데이터 규모 재점검.

## 8. 산출물 보존
```bash
!cd models && zip -qr /content/models.zip * && echo "→ Drive 로 복사"
```
- 최종 배포: `student_ts.pt` + `ocsvm.pkl` + `threshold.json` + Linux `packet_parser_stack.so`를
  `deployment-with-sidecar.yaml`의 `reverse-proxy`(`model-pvc`)에 탑재. 런타임 `proxy_detection.py`가 로드.
  ⚠️ 마스킹을 켜고 학습했다면 런타임도 동일 마스킹 필요(파서에 baking 또는 proxy에서 적용).
