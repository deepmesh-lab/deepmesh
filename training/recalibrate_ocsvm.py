"""CNN을 고정한 채 OCSVM과 임계값을 재보정한다.

- gamma·nu는 DETECT(없으면 HARD)의 검증 AUC로 선택
- 임계값은 정상 검증 점수의 fpr_cap 분위수

입력: data/<svc>/X_benign.npy, data/_attack/X_attack_<svc>_<scen>.npy
모델: models/<svc>/student_ts.pt"""
import argparse, json, os, shutil
import numpy as np, torch, joblib
from sklearn.svm import OneClassSVM
from sklearn.metrics import roc_auc_score, roc_curve

from data_utils import group_val_mask

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MODELS = os.path.join(HERE, "models")
SERVICES = ["auth", "post", "comment", "frontend", "mysql"]

# 서비스별 공격 시나리오
POD_SCENS = {
    "post":     ["enum_seq", "l2", "l3", "d1", "k1", "k2"],
    "comment":  ["enum_seq", "l2", "l3", "d1", "k1", "k2"],
    "auth":     ["cred_enum", "d1", "k1", "k2"],
    "frontend": ["scan_seq", "r1", "k1", "k2"],
    "mysql":    ["e1", "c2", "k1", "k2"],
}
# --detect/--hard로 시나리오 분류 변경
DEFAULT_DETECT = ["scan_seq", "enum_seq", "l3", "r1", "k1", "k2", "e1", "c2"]
DEFAULT_HARD   = ["l2", "d1", "cred_enum"]


def load_imgs(path, n, rng, with_sess=False):
    """NPY에서 최대 n개를 뽑아 0~1로 제한한다. with_sess=True이면 세션 ID도 반환한다."""
    if not os.path.exists(path):
        return (None, None) if with_sess else None
    arr = np.load(path, mmap_mode="r"); m = len(arr)
    idx = np.sort(rng.choice(m, min(n, m), replace=False))
    X = np.nan_to_num(np.clip(np.asarray(arr[idx], dtype=np.float32), 0, 1))
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
    return np.concatenate(out) if out else np.empty((0,))


def _load_group(svc, scens, cap, rng, ts):
    """공격 이미지를 임베딩해 전체 배열과 시나리오별 배열을 반환한다."""
    per = {}
    feats = []
    for scen in scens:
        p = os.path.join(DATA, "_attack", f"X_attack_{svc}_{scen}.npy")
        X = load_imgs(p, cap, rng)
        if X is None or len(X) == 0:
            continue
        f = embed(ts, X)
        per[scen] = f
        feats.append(f)
    return (np.concatenate(feats) if feats else np.empty((0,))), per


def recalibrate(svc, a, detect_set, hard_set):
    mdir = os.path.join(MODELS, svc)
    ts = torch.jit.load(os.path.join(mdir, "student_ts.pt"), map_location="cpu").eval()
    rng = np.random.default_rng(a.seed)

    Xb, sess_b = load_imgs(os.path.join(DATA, svc, "X_benign.npy"), a.fit_max + a.val_max, rng, with_sess=True)
    fb = embed(ts, Xb)
    if sess_b is not None:
        vm = group_val_mask(sess_b, a.val_max / (a.fit_max + a.val_max), seed=a.seed)
        fit_feat, val_feat = fb[~vm], fb[vm]
    else:
        print(f"  [경고] {svc}: sess 없음 → 랜덤 분할(누수 위험)")
        fit_feat, val_feat = fb[:a.fit_max], fb[a.fit_max:a.fit_max + a.val_max]

    scens = POD_SCENS.get(svc, [])
    detect_scens = [s for s in scens if s in detect_set]
    hard_scens   = [s for s in scens if s in hard_set]
    det_feat, det_per = _load_group(svc, detect_scens, a.attack_cap, rng, ts)
    hard_feat, hard_per = _load_group(svc, hard_scens, a.attack_cap, rng, ts)

    # DETECT → HARD 순으로 선택. 공격 데이터가 없으면 gamma='scale', nu=0.05.
    sel_feat = det_feat if len(det_feat) else (hard_feat if len(hard_feat) else None)
    grid = [(g, nu) for g in ["scale", 1e-4, 1e-3, 1e-2, 0.1, 10.0] for nu in [0.05, 0.1]]
    best = None
    if sel_feat is None:
        oc = OneClassSVM(kernel="rbf", gamma="scale", nu=0.05, cache_size=500, max_iter=30000).fit(fit_feat)
        best = ("scale", 0.05, oc, float("nan"))
    else:
        for g, nu in grid:
            gv = g if g == "scale" else float(g)
            oc = OneClassSVM(kernel="rbf", gamma=gv, nu=nu, cache_size=500, max_iter=30000).fit(fit_feat)
            dfv = oc.decision_function(val_feat); dfs = oc.decision_function(sel_feat)
            auc = roc_auc_score(np.r_[np.zeros(len(dfv)), np.ones(len(dfs))], np.r_[-dfv, -dfs])
            if best is None or auc > best[3]:
                best = (g, nu, oc, float(auc))
    g, nu, oc, sel_auc = best

    # 정상 검증 점수의 fpr_cap 분위수로 임계값 설정
    dfv = oc.decision_function(val_feat)
    thr = float(np.quantile(dfv, a.fpr_cap))
    fpr = float((dfv < thr).mean())

    def recall(feat): return float((oc.decision_function(feat) < thr).mean()) if len(feat) else float("nan")
    det_rec = {s: recall(f) for s, f in det_per.items()}
    hard_rec = {s: recall(f) for s, f in hard_per.items()}
    det_overall = recall(det_feat); hard_overall = recall(hard_feat)

    result = dict(svc=svc, gamma=g, nu=nu, sel_auc=sel_auc, thr=thr, fpr=fpr,
                  detect_scens=detect_scens, hard_scens=hard_scens,
                  det_rec=det_rec, hard_rec=hard_rec, det_overall=det_overall, hard_overall=hard_overall)
    if a.dry_run:
        return result

    for fn in ("ocsvm.pkl", "threshold.json"):
        p = os.path.join(mdir, fn)
        if os.path.exists(p) and not os.path.exists(p + ".bak"):
            shutil.copy2(p, p + ".bak")
    joblib.dump(oc, os.path.join(mdir, "ocsvm.pkl"))
    meta = {"threshold_df": thr, "select": "gamma=maxROC(DETECT), thr=benign fpr_cap 분위수",
            "gamma": g, "nu": nu, "fpr_cap": a.fpr_cap, "val_fpr_at_thr": round(fpr, 4),
            "detect_scenarios": detect_scens, "hard_scenarios": hard_scens,
            "detect_recall": {k: round(v, 4) for k, v in det_rec.items()},
            "detect_recall_overall": None if np.isnan(det_overall) else round(det_overall, 4),
            "hard_recall": {k: round(v, 4) for k, v in hard_rec.items()},
            "hard_recall_overall": None if np.isnan(hard_overall) else round(hard_overall, 4),
            "sel_val_roc_auc": None if np.isnan(sel_auc) else round(sel_auc, 4),
            "mask_transport": False, "semantic": True, "recalibrated": True}
    old = {}
    bak = os.path.join(mdir, "threshold.json.bak")
    if os.path.exists(bak):
        try: old = json.load(open(bak, encoding="utf-8"))
        except Exception: pass
    for k in ("arch", "teacher", "l2", "vec_len", "feat_len"):
        if k in old: meta[k] = old[k]
    json.dump(meta, open(os.path.join(mdir, "threshold.json"), "w", encoding="utf-8"), indent=2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--services", default=",".join(SERVICES))
    ap.add_argument("--detect", default=",".join(DEFAULT_DETECT), help="threshold/gamma 를 잡는 구조적 시나리오")
    ap.add_argument("--hard", default=",".join(DEFAULT_HARD), help="benign 근접 — recall 보고만, 임계 영향 X")
    ap.add_argument("--fit-max", type=int, default=15000, dest="fit_max")
    ap.add_argument("--val-max", type=int, default=15000, dest="val_max")
    ap.add_argument("--attack-cap", type=int, default=12000, dest="attack_cap")
    ap.add_argument("--fpr-cap", type=float, default=0.05, dest="fpr_cap")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    a = ap.parse_args()
    detect_set = set(x for x in a.detect.split(",") if x)
    hard_set = set(x for x in a.hard.split(",") if x)
    print(f"[recalibrate v2] semantic(mask OFF) fpr_cap={a.fpr_cap} dry_run={a.dry_run}")
    print(f"  DETECT(임계/gamma 근거)={sorted(detect_set)}  HARD(보고만)={sorted(hard_set)}")
    print("-" * 78)
    for svc in a.services.split(","):
        if not os.path.exists(os.path.join(MODELS, svc, "student_ts.pt")):
            print(f"[{svc}] (skip: no model)"); continue
        r = recalibrate(svc, a, detect_set, hard_set)
        auc = "  n/a" if np.isnan(r["sel_auc"]) else f"{r['sel_auc']:.3f}"
        print(f"[{svc}] gamma={str(r['gamma']):>5} nu={r['nu']:.2f} selROC={auc} "
              f"thr={r['thr']:.3f} val_FPR={r['fpr']*100:.1f}%")
        if r["det_rec"]:
            print(f"   DETECT recall: " + "  ".join(f"{s}={v*100:.0f}%" for s, v in r["det_rec"].items())
                  + f"   (overall {r['det_overall']*100:.0f}%)")
        if r["hard_rec"]:
            print(f"   HARD   recall: " + "  ".join(f"{s}={v*100:.0f}%" for s, v in r["hard_rec"].items())
                  + f"   (overall {r['hard_overall']*100:.0f}%)  ← 임계에 미반영")
        if not r["det_rec"] and not r["hard_rec"]:
            print("   (공격 파일 없음 — benign FPR 만으로 threshold)")


if __name__ == "__main__":
    main()