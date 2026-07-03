"""
evaluate.py — 침입 탐지 모델 성능 평가 스크립트

StudentCNN TorchScript 모델(student_ts.pt) + OCSVM(ocsvm.pkl) 로드 후
benign/attack 샘플에 대한 분류 성능 지표를 계산한다.

사용법:
    python evaluate.py --data ./data/auth-service/ --model-dir ./models/auth-service/ \
                       [--service-name auth-service] [--batch-size 256]
"""

import argparse
import json
import os
import sys

import joblib
import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


# ---------------------------------------------------------------------------
# 모델 로드
# ---------------------------------------------------------------------------

def load_models(model_dir: str, device: torch.device):
    """student_ts.pt와 ocsvm.pkl을 로드하여 반환한다.

    Args:
        model_dir: student_ts.pt, ocsvm.pkl이 위치한 디렉터리 경로
        device:    TorchScript 모델을 올릴 장치

    Returns:
        ts_model: torch.jit.ScriptModule
        ocsvm:    sklearn OneClassSVM 객체
    """
    ts_path = os.path.join(model_dir, "student_ts.pt")
    ocsvm_path = os.path.join(model_dir, "ocsvm.pkl")

    if not os.path.isfile(ts_path):
        raise FileNotFoundError(f"TorchScript 모델을 찾을 수 없습니다: {ts_path}")
    if not os.path.isfile(ocsvm_path):
        raise FileNotFoundError(f"OCSVM 모델을 찾을 수 없습니다: {ocsvm_path}")

    ts_model = torch.jit.load(ts_path, map_location=device)
    ts_model.eval()

    ocsvm = joblib.load(ocsvm_path)

    return ts_model, ocsvm


# ---------------------------------------------------------------------------
# Embedding 추출
# ---------------------------------------------------------------------------

def extract_embeddings(
    ts_model: torch.jit.ScriptModule,
    X: np.ndarray,
    device: torch.device,
    batch_size: int = 256,
) -> np.ndarray:
    """TorchScript 모델로 입력 배열의 embedding을 배치 단위로 추출한다.

    Args:
        ts_model:   로드된 TorchScript 모델
        X:          입력 배열, shape (N, VEC_LEN, WIN_SIZE) — 채널 축 추가 후 (N,1,VEC_LEN,WIN_SIZE)
        device:     연산 장치
        batch_size: 배치 크기

    Returns:
        embeddings: numpy 배열, shape (N, embed_dim)
    """
    all_embeddings = []
    n = len(X)

    with torch.no_grad():
        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            batch = torch.tensor(X[start:end], dtype=torch.float32, device=device)
            batch = batch.unsqueeze(1)  # (B, VEC_LEN, WIN_SIZE) → (B, 1, VEC_LEN, WIN_SIZE)
            emb = ts_model(batch)
            all_embeddings.append(emb.cpu().numpy())

    return np.concatenate(all_embeddings, axis=0)


# ---------------------------------------------------------------------------
# 전체 평가 파이프라인
# ---------------------------------------------------------------------------

def evaluate(
    X_benign: np.ndarray,
    X_attack: np.ndarray | None,
    model_dir: str,
    device: torch.device,
    batch_size: int = 256,
) -> dict:
    """전체 평가 파이프라인을 실행하고 결과를 dict로 반환한다.

    OCSVM predict 규칙:
        정상(benign) → +1 반환 → label 0
        이상(attack) → -1 반환 → label 1

    Args:
        X_benign:   benign 샘플 배열
        X_attack:   attack 샘플 배열 (None이면 benign-only 평가)
        model_dir:  모델 파일 디렉터리
        device:     연산 장치
        batch_size: embedding 추출 배치 크기

    Returns:
        results dict (지표 포함)
    """
    ts_model, ocsvm = load_models(model_dir, device)

    # --- benign embedding 및 예측 ---
    emb_benign = extract_embeddings(ts_model, X_benign, device, batch_size)
    raw_benign = ocsvm.predict(emb_benign)          # +1 or -1
    pred_benign = (raw_benign == -1).astype(int)    # +1→0, -1→1
    y_true_benign = np.zeros(len(X_benign), dtype=int)

    # OCSVM decision scores for ROC-AUC (부호 반전: 이상일수록 높은 score)
    score_benign = -ocsvm.decision_function(emb_benign)

    results = {
        "n_benign": int(len(X_benign)),
        "n_attack": 0,
    }

    if X_attack is not None and len(X_attack) > 0:
        # --- attack embedding 및 예측 ---
        emb_attack = extract_embeddings(ts_model, X_attack, device, batch_size)
        raw_attack = ocsvm.predict(emb_attack)
        pred_attack = (raw_attack == -1).astype(int)
        y_true_attack = np.ones(len(X_attack), dtype=int)
        score_attack = -ocsvm.decision_function(emb_attack)

        y_true = np.concatenate([y_true_benign, y_true_attack])
        y_pred = np.concatenate([pred_benign, pred_attack])
        y_score = np.concatenate([score_benign, score_attack])

        results["n_attack"] = int(len(X_attack))

        cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
        tn, fp, fn, tp = cm.ravel()

        accuracy  = accuracy_score(y_true, y_pred)
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall    = recall_score(y_true, y_pred, zero_division=0)
        f1        = f1_score(y_true, y_pred, zero_division=0)
        fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        fnr       = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        roc_auc   = roc_auc_score(y_true, y_score)

        results.update({
            "confusion_matrix": cm.tolist(),
            "tn": int(tn), "fp": int(fp),
            "fn": int(fn), "tp": int(tp),
            "accuracy":  round(float(accuracy),  4),
            "precision": round(float(precision), 4),
            "recall":    round(float(recall),    4),
            "f1":        round(float(f1),        4),
            "fpr":       round(float(fpr),       4),
            "fnr":       round(float(fnr),       4),
            "roc_auc":   round(float(roc_auc),   4),
            "mode":      "full",
        })

    else:
        # attack 데이터 없음 — benign-only (FPR만 계산)
        fp = int(pred_benign.sum())
        tn = int(len(pred_benign) - fp)
        fpr = fp / len(pred_benign) if len(pred_benign) > 0 else 0.0

        results.update({
            "confusion_matrix": [[tn, fp], [None, None]],
            "tn": tn, "fp": fp,
            "fn": None, "tp": None,
            "accuracy":  None,
            "precision": None,
            "recall":    None,
            "f1":        None,
            "fpr":       round(float(fpr), 4),
            "fnr":       None,
            "roc_auc":   None,
            "mode":      "benign_only",
        })

    return results


# ---------------------------------------------------------------------------
# 결과 출력
# ---------------------------------------------------------------------------

def print_report(results: dict, service_name: str) -> None:
    """평가 결과를 포맷에 맞춰 터미널에 출력한다."""

    def fmt(val, decimals=4):
        return f"{val:.{decimals}f}" if val is not None else "N/A"

    print(f"\n=== 모델 평가 결과: {service_name} ===")
    print(f"샘플 수: benign={results['n_benign']}, attack={results['n_attack']}")

    cm = results.get("confusion_matrix")
    print("\nConfusion Matrix:")
    if results["mode"] == "full":
        tn, fp = cm[0]
        fn, tp = cm[1]
        print(f"[[{tn:>6}  {fp:>6}]")
        print(f" [{fn:>6}  {tp:>6}]]")
    else:
        tn, fp = cm[0]
        print(f"[[{tn:>6}  {fp:>6}]")
        print(f" [{'N/A':>6}  {'N/A':>6}]]  (attack 데이터 없음)")

    print()
    print(f"Accuracy:  {fmt(results['accuracy'])}")
    print(f"Precision: {fmt(results['precision'])}")
    print(f"Recall:    {fmt(results['recall'])}")
    print(f"F1-score:  {fmt(results['f1'])}")
    print(f"FPR:       {fmt(results['fpr'])}")
    print(f"FNR:       {fmt(results['fnr'])}")
    print(f"ROC-AUC:   {fmt(results['roc_auc'])}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="침입 탐지 모델(StudentCNN + OCSVM) 성능 평가"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="X_benign.npy, X_attack.npy가 위치한 디렉터리",
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        help="student_ts.pt, ocsvm.pkl이 위치한 디렉터리",
    )
    parser.add_argument(
        "--service-name",
        default=None,
        help="출력 헤더에 표시할 서비스 이름 (기본: model-dir 기준)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="embedding 추출 배치 크기 (기본: 256)",
    )
    args = parser.parse_args()

    # service_name 결정
    service_name = args.service_name or os.path.basename(os.path.abspath(args.model_dir))

    # 데이터 로드
    benign_path = os.path.join(args.data, "X_benign.npy")
    attack_path = os.path.join(args.data, "X_attack.npy")

    if not os.path.isfile(benign_path):
        print(f"[오류] X_benign.npy를 찾을 수 없습니다: {benign_path}", file=sys.stderr)
        sys.exit(1)

    X_benign = np.load(benign_path)
    X_attack = np.load(attack_path) if os.path.isfile(attack_path) else None

    if X_attack is None:
        print("[경고] X_attack.npy 없음 — benign 전용 평가(FPR만) 수행합니다.")

    # 장치 설정
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 평가 실행
    results = evaluate(
        X_benign=X_benign,
        X_attack=X_attack,
        model_dir=args.model_dir,
        device=device,
        batch_size=args.batch_size,
    )

    # 출력
    print_report(results, service_name)

    # JSON 저장
    os.makedirs(args.model_dir, exist_ok=True)
    out_path = os.path.join(args.model_dir, "eval_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
