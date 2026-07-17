"""
eval_table.py — 서비스별 KD-CNN(student_ts.pt) + OCSVM 모델의 F1-score / ROC-AUC를
'테스트 데이터만'으로 계산해 표로 출력.

테스트 데이터:
  benign = data/<svc>/X_testbenign.npy   (test/benign pcap 산출)
  attack = data/_attack/X_k8s.npy  (전 서비스 공통 '이탈')  + auth 는 X_brute 추가
평가 규약(evaluate.py 정합):
  이상 판정 = ocsvm.decision_function(emb) < threshold_df      → F1(attack=positive)
  ROC-AUC   = roc_auc_score(y, -decision_function)             (순위 기반, 임계값 무관)
정규화 정합(train_kd_pipeline 과 동일): raw uint8 → /255 → 전송계층 마스킹(MASK_TRANSPORT).

사용:
  cd training && python eval_table.py
  python eval_table.py --cap 20000 --models-root ../colab_results/models
"""
import argparse, json, os
import numpy as np, torch, joblib
from sklearn.metrics import f1_score, roc_auc_score

os.environ.setdefault("MASK_TRANSPORT", "1")
from data_utils import apply_transport_mask, mask_transport_enabled

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# svc: 평가에 쓸 attack npy 목록 (COLAB_PLAN §4 매핑)
SVC_ATTACK = {
    "auth":     ["X_brute", "X_k8s"],
    "post":     ["X_k8s"],
    "comment":  ["X_k8s"],
    "frontend": ["X_k8s"],
    "mysql":    ["X_k8s"],
}


def load_norm(path, cap, rng):
    """raw uint8 npy → (선택 subsample) → float32 /255 → 마스킹. 학습 정규화와 동일."""
    if not os.path.exists(path):
        return None
    arr = np.load(path, mmap_mode="r")
    m = len(arr)
    if m == 0:
        return None
    idx = np.sort(rng.choice(m, min(cap, m), replace=False)) if m > cap else slice(None)
    X = np.asarray(arr[idx], dtype=np.float32)
    X = np.nan_to_num(X)
    X = np.clip(X, 0, 255) / 255.0 if X.max() > 1.5 else np.clip(X, 0.0, 1.0)
    return apply_transport_mask(X)          # rows 7-18 → 0 (MASK_TRANSPORT)


def embed(ts, X, bs=1024):
    out = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            b = torch.from_numpy(X[i:i + bs]).unsqueeze(1)   # (B,1,1479,5)
            out.append(ts(b).numpy())
    return np.concatenate(out)


def eval_service(svc, models_root, cap, rng):
    mdir = os.path.join(models_root, svc)
    ts_path = os.path.join(mdir, "student_ts.pt")
    if not os.path.exists(ts_path):
        return None
    ts = torch.jit.load(ts_path, map_location="cpu").eval()
    ocsvm = joblib.load(os.path.join(mdir, "ocsvm.pkl"))
    meta = json.load(open(os.path.join(mdir, "threshold.json"), encoding="utf-8"))
    thr = float(meta["threshold_df"])

    Xb = load_norm(os.path.join(DATA, svc, "X_testbenign.npy"), cap, rng)
    if Xb is None:
        return None
    Xa_list = [load_norm(os.path.join(DATA, "_attack", f"{n}.npy"), cap, rng) for n in SVC_ATTACK[svc]]
    Xa = np.concatenate([x for x in Xa_list if x is not None]) if any(x is not None for x in Xa_list) else None
    if Xa is None:
        return None

    df_b = ocsvm.decision_function(embed(ts, Xb))
    df_a = ocsvm.decision_function(embed(ts, Xa))
    y = np.r_[np.zeros(len(df_b)), np.ones(len(df_a))]
    score = np.r_[-df_b, -df_a]                       # 이상일수록 큼
    pred = (np.r_[df_b, df_a] < thr).astype(int)      # 이상=1

    return {
        "svc": svc, "n_benign": len(df_b), "n_attack": len(df_a),
        "arch": meta.get("arch", "?"), "gamma": str(meta.get("gamma", "?")), "nu": meta.get("nu", "?"),
        "f1": f1_score(y, pred, zero_division=0),
        "roc_auc": roc_auc_score(y, score),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-root", default=os.path.join(HERE, "..", "colab_results", "models"))
    ap.add_argument("--cap", type=int, default=15000, help="클래스당 테스트 샘플 상한(속도/메모리)")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)

    print(f"[eval] mask={'ON' if mask_transport_enabled() else 'OFF'}  cap={a.cap}  "
          f"models={os.path.abspath(a.models_root)}")
    print(f"\n{'service':10} {'arch':5} {'gamma':>6} {'nu':>5} {'n_benign':>9} {'n_attack':>9} "
          f"{'F1':>7} {'ROC-AUC':>8}")
    print("-" * 70)
    rows = []
    for svc in SVC_ATTACK:
        r = eval_service(svc, a.models_root, a.cap, rng)
        if r is None:
            print(f"{svc:10} (skip: 모델/데이터 없음)"); continue
        rows.append(r)
        print(f"{r['svc']:10} {r['arch']:5} {r['gamma']:>6} {str(r['nu']):>5} "
              f"{r['n_benign']:>9} {r['n_attack']:>9} {r['f1']:>7.4f} {r['roc_auc']:>8.4f}")
    if rows:
        mf1 = np.mean([r["f1"] for r in rows]); mauc = np.mean([r["roc_auc"] for r in rows])
        print("-" * 70)
        print(f"{'mean':10} {'':5} {'':>6} {'':>5} {'':>9} {'':>9} {mf1:>7.4f} {mauc:>8.4f}")


if __name__ == "__main__":
    main()
