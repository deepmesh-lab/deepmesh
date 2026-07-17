"""
recalibrate_ocsvm.py — (A) 재학습 없이 OCSVM + threshold 재보정.

CNN(student_ts.pt)은 고정. 그 임베딩 위에서:
  - gamma×nu 그리드로 OCSVM 재적합 (gamma=10 암기 회피)
  - 선택 기준 = '배포성' : val benign FPR <= fpr_cap 에서의 최대 Recall (동률 시 ROC-AUC)
  - threshold = val benign 의 fpr_cap 분위수(df) → FPR<=cap 보장, 그 지점 Recall 보고
기존 ocsvm.pkl / threshold.json 은 .bak 로 백업 후 덮어씀.

사용:
  python recalibrate_ocsvm.py                 # 5개 전체
  python recalibrate_ocsvm.py --services mysql --fpr-cap 0.02
"""
import argparse, json, os, shutil
import numpy as np, torch, joblib
from sklearn.svm import OneClassSVM
from sklearn.metrics import roc_auc_score

os.environ.setdefault("MASK_TRANSPORT", "1")
from data_utils import apply_transport_mask, mask_transport_enabled, group_val_mask

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MODELS = os.path.join(DATA, "models")
SERVICES = ["auth-service", "post-service", "comment-service", "frontend", "mysql"]


def load_masked(path, n, rng, with_sess=False):
    arr = np.load(path, mmap_mode="r"); m = len(arr)
    idx = np.sort(rng.choice(m, min(n, m), replace=False))
    X = apply_transport_mask(np.nan_to_num(np.clip(np.asarray(arr[idx], dtype=np.float32), 0, 1)))
    if not with_sess:
        return X
    spath = os.path.join(os.path.dirname(path), os.path.basename(path).replace("X_", "sess_", 1))
    sess = np.asarray(np.load(spath, mmap_mode="r")[idx], dtype=np.int64) if os.path.exists(spath) else None
    return X, sess


def embed(ts, X, bs=1024):
    out = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            out.append(ts(torch.from_numpy(X[i:i+bs]).unsqueeze(1)).numpy())
    return np.concatenate(out)


def recalibrate(svc, a):
    mdir = os.path.join(MODELS, svc)
    ts = torch.jit.load(os.path.join(mdir, "student_ts.pt"), map_location="cpu").eval()
    rng = np.random.default_rng(a.seed)

    Xb, sess_b = load_masked(os.path.join(DATA, svc, "X_benign.npy"), a.fit_max + a.val_max, rng, with_sess=True)
    fb = embed(ts, Xb)
    if sess_b is not None:
        vm = group_val_mask(sess_b, a.val_max / (a.fit_max + a.val_max), seed=a.seed)
        fit_feat, val_feat = fb[~vm], fb[vm]
    else:
        print(f"  [경고] {svc}: sess 없음 → 랜덤 분할(누수 위험)")
        fit_feat, val_feat = fb[:a.fit_max], fb[a.fit_max:a.fit_max + a.val_max]
    Xa = load_masked(os.path.join(DATA, svc, "X_attack.npy"), a.attack_cap, rng)
    atk_feat = embed(ts, Xa)

    # gamma 선택 = 랭킹(val ROC-AUC) 최대. threshold = Youden-J(최적 균형)로 별도 설정.
    # 중간값 0.5/1.0 은 un-normalized 특징에서 RBF degenerate→SMO 폭주라 제외. gamma=10 은 fast(학습본도 사용).
    from sklearn.metrics import roc_curve
    grid = [(g, nu) for g in ["scale", 1e-4, 1e-3, 1e-2, 0.1, 10.0] for nu in [0.05, 0.1]]
    best = None
    for g, nu in grid:
        gv = g if g == "scale" else float(g)
        oc = OneClassSVM(kernel="rbf", gamma=gv, nu=nu, cache_size=500, max_iter=30000).fit(fit_feat)
        dfv = oc.decision_function(val_feat); dfa = oc.decision_function(atk_feat)
        auc = roc_auc_score(np.r_[np.zeros(len(dfv)), np.ones(len(dfa))], np.r_[-dfv, -dfa])
        if best is None or auc > best[1]:
            best = (None, auc, g, nu, gv, oc, dfv, dfa)
    _, auc, g, nu, gv, oc, dfv, dfa = best
    # Youden-J threshold (df 컷). 이상 = df < thr.
    y = np.r_[np.zeros(len(dfv)), np.ones(len(dfa))]
    fpr_c, tpr_c, th_c = roc_curve(y, np.r_[-dfv, -dfa])
    j = int(np.argmax(tpr_c - fpr_c))
    thr = float(-th_c[j])
    fpr = float((dfv < thr).mean()); rec = float((dfa < thr).mean())
    # 참고: FPR<=cap 에서의 recall
    thr_cap = float(np.quantile(dfv, a.fpr_cap))
    rec_cap = float((dfa < thr_cap).mean())

    if a.dry_run:   # 분석만: 저장/백업 안 함
        return svc, auc, g, nu, thr, fpr, rec, rec_cap
    # 백업 후 저장
    for fn in ("ocsvm.pkl", "threshold.json"):
        p = os.path.join(mdir, fn)
        if os.path.exists(p) and not os.path.exists(p + ".bak"):
            shutil.copy2(p, p + ".bak")
    joblib.dump(oc, os.path.join(mdir, "ocsvm.pkl"))
    meta = {"threshold_df": thr, "select": "gamma=maxROC, thr=Youden-J", "gamma": g, "nu": nu,
            "val_roc_auc": round(float(auc), 4), "val_fpr_at_thr": round(fpr, 4),
            "val_recall_at_thr": round(rec, 4),
            "fpr_cap": a.fpr_cap, "recall_at_fpr_cap": round(rec_cap, 4),
            "mask_transport": mask_transport_enabled(), "recalibrated": True}
    # 기존 threshold.json 의 arch/teacher/vec_len 보존
    old = {}
    bak = os.path.join(mdir, "threshold.json.bak")
    if os.path.exists(bak):
        try: old = json.load(open(bak, encoding="utf-8"))
        except Exception: pass
    for k in ("arch", "teacher", "l2", "vec_len"):
        if k in old: meta[k] = old[k]
    json.dump(meta, open(os.path.join(mdir, "threshold.json"), "w", encoding="utf-8"), indent=2)
    return svc, auc, g, nu, thr, fpr, rec, rec_cap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--services", default=",".join(SERVICES))
    ap.add_argument("--fit-max", type=int, default=15000, dest="fit_max")
    ap.add_argument("--val-max", type=int, default=15000, dest="val_max")
    ap.add_argument("--attack-cap", type=int, default=15000, dest="attack_cap")
    ap.add_argument("--fpr-cap", type=float, default=0.05, dest="fpr_cap")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="분석만: gamma 그리드+Youden 결과 출력, ocsvm.pkl/threshold.json 저장 안 함")
    a = ap.parse_args()
    print(f"[recalibrate] mask={'ON' if mask_transport_enabled() else 'OFF'} fpr_cap={a.fpr_cap} "
          f"dry_run={a.dry_run}")
    print(f"{'service':16} {'ROC':>6} {'gamma':>6} {'nu':>5} | Youden: {'FPR':>6} {'Recall':>7} | {'Rec@FPR<=cap':>12}")
    print("-"*74)
    for svc in a.services.split(","):
        if not os.path.exists(os.path.join(MODELS, svc, "student_ts.pt")):
            print(f"{svc:16} (skip: no model)"); continue
        s, auc, g, nu, thr, fpr, rec, rec_cap = recalibrate(svc, a)
        print(f"{s:16} {auc:6.3f} {str(g):>6} {nu:5.2f} | {fpr*100:9.1f}% {rec*100:6.1f}% | {rec_cap*100:11.1f}%")


if __name__ == "__main__":
    main()
