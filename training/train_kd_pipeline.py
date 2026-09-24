"""서비스별 Teacher·Student CNN과 OCSVM 학습.

정상 데이터를 학습·검증으로 나누고, 검증 점수의 분위수로 임계값을 정한다.
X_attack.npy가 있으면 gamma 선택과 평가에 사용한다.

산출물: teacher.pth, student.pth, student_ts.pt, ocsvm.pkl,
threshold.json, eval_results.json"""
import argparse
import json
import os

import joblib
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.svm import OneClassSVM
from sklearn.metrics import roc_auc_score, average_precision_score
from torch.utils.data import Dataset, DataLoader

# MODEL_MODULE로 모델 정의 모듈 지정
_MODEL_MODULE = os.environ.get("MODEL_MODULE", "student_cnn")
_sc = __import__(_MODEL_MODULE)
make_student, make_teacher, FEAT_DIM, WIN_SIZE = _sc.make_student, _sc.make_teacher, _sc.FEAT_DIM, _sc.WIN_SIZE
from data_utils import apply_transport_mask, mask_transport_enabled, group_val_mask

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_npy_subset(path: str, cap: int | None, seed: int, with_sess: bool = False):
    """NPY에서 최대 cap개를 무작위로 읽어 정규화하고 마스킹한다.
    with_sess=True이면 같은 인덱스의 세션 ID도 반환한다."""
    arr = np.load(path, mmap_mode="r")
    n = len(arr)
    rng = np.random.default_rng(seed)
    # 무작위 표본의 인덱스를 정렬해 mmap 접근 순서 유지
    idx = np.sort(rng.choice(n, cap, replace=False)) if (cap and n > cap) else np.arange(n)
    X = np.asarray(arr[idx], dtype=np.float32)
    X = np.nan_to_num(X)
    if X.max() > 1.5:            # 0~255 저장값 정규화
        X = np.clip(X, 0, 255) / 255.0
    else:
        X = np.clip(X, 0.0, 1.0)
    # 윈도우 축을 마지막으로 이동
    if X.shape[2] != WIN_SIZE and X.shape[1] == WIN_SIZE:
        X = np.transpose(X, (0, 2, 1))
    # 20행 semantic 입력은 MASK_TRANSPORT=0 필요
    X = apply_transport_mask(X)
    if not with_sess:
        return X
    # 이미지와 같은 인덱스로 세션 ID 로드
    spath = os.path.join(os.path.dirname(path), os.path.basename(path).replace("X_", "sess_", 1))
    sess = np.asarray(np.load(spath, mmap_mode="r")[idx], dtype=np.int64) if os.path.exists(spath) else None
    return X, sess


def split_train_val(X: np.ndarray, sess, val_frac: float, seed: int):
    """세션별로 학습·검증을 나눈다. 세션 ID가 없으면 윈도우별로 나눈다."""
    if sess is None:
        print("[경고] sess_*.npy 없음 → 랜덤 window 분할(near-dup 누수 위험). 재전처리로 sess 생성 권장.")
        rng = np.random.default_rng(seed); idx = rng.permutation(len(X)); k = int(len(X) * (1 - val_frac))
        return X[idx[:k]], X[idx[k:]]
    vm = group_val_mask(sess, val_frac, seed)
    return X[~vm], X[vm]


class ContrastiveMem(Dataset):
    def __init__(self, X, sigma=0.01): self.X, self.sigma = X, sigma
    def __len__(self): return len(self.X)
    def _aug(self, x): return np.clip(x + np.random.normal(0, self.sigma, x.shape).astype(np.float32), 0, 1)
    def __getitem__(self, i):
        x = self.X[i]
        return (torch.from_numpy(self._aug(x)).unsqueeze(0),
                torch.from_numpy(self._aug(x)).unsqueeze(0))


class BenignMem(Dataset):
    def __init__(self, X): self.X = X
    def __len__(self): return len(self.X)
    def __getitem__(self, i): return torch.from_numpy(self.X[i]).unsqueeze(0)


def nt_xent(z1, z2, temp=0.1):
    z1, z2 = F.normalize(z1, dim=1), F.normalize(z2, dim=1)
    z = torch.cat([z1, z2], 0); N = z1.size(0)
    sim = (z @ z.T) / temp
    sim.masked_fill_(torch.eye(2 * N, dtype=torch.bool, device=z.device), -9e15)
    labels = torch.arange(N, device=z.device)
    labels = torch.cat([labels + N, labels])
    return F.cross_entropy(sim, labels)

def _es_split(X, frac, seed):
    """조기 종료용 검증 데이터를 분리한다. 데이터가 32개 미만이면 생략한다."""
    if frac <= 0 or len(X) < 32:
        return X, None
    rng = np.random.default_rng(seed + 1)
    idx = rng.permutation(len(X)); k = int(len(X) * (1 - frac))
    return X[idx[:k]], X[idx[k:]]

def train_teacher(X, arch, embed, l2, epochs, bs, sigma,
                  patience=5, min_delta=1e-4, es_frac=0.1, seed=42):
    teacher = make_teacher(arch, embed, l2).to(DEVICE)
    opt = torch.optim.Adam(teacher.parameters(), lr=1e-3)
    X_fit, X_es = _es_split(X, es_frac, seed)
    loader = DataLoader(ContrastiveMem(X_fit, sigma), batch_size=bs, shuffle=True, drop_last=True)
    es_loader = (DataLoader(ContrastiveMem(X_es, sigma), batch_size=bs, shuffle=False, drop_last=False)
                 if X_es is not None else None)
    best, best_state, bad = float("inf"), None, 0
    for ep in range(1, epochs + 1):
        teacher.train(); tot = 0.0
        for v1, v2 in loader:
            v1, v2 = v1.to(DEVICE), v2.to(DEVICE)
            loss = nt_xent(teacher(v1), teacher(v2))
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        msg = f"  [teacher {ep}/{epochs}] nt_xent={tot/max(len(loader),1):.4f}"
        if es_loader is None:
            print(msg, flush=True); continue
        teacher.eval(); vtot, nb = 0.0, 0
        with torch.no_grad():
            for v1, v2 in es_loader:
                if v1.size(0) < 2: continue          # 대조학습에 필요한 최소 배치 크기
                v1, v2 = v1.to(DEVICE), v2.to(DEVICE)
                vtot += nt_xent(teacher(v1), teacher(v2)).item(); nb += 1
        vloss = vtot / max(nb, 1)
        print(msg + f" val={vloss:.4f}", flush=True)
        if vloss < best - min_delta:
            best, bad = vloss, 0
            best_state = {k: v.detach().cpu().clone() for k, v in teacher.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                print(f"  [teacher] early stop @ep{ep} (best val={best:.4f})", flush=True); break
    if best_state is not None:
        teacher.load_state_dict(best_state)      # 검증 손실이 가장 낮은 가중치 복원
    return teacher

def train_student(X, teacher, arch, embed, l2, epochs, bs,
                  patience=5, min_delta=1e-6, es_frac=0.1, seed=42):
    student = make_student(arch, embed, l2).to(DEVICE)
    n_params = sum(p.numel() for p in student.parameters())
    print(f"  [student] arch={arch} params={n_params:,} ({n_params/1000:.2f}K) l2={l2}")
    opt = torch.optim.Adam(student.parameters(), lr=1e-3)
    crit = nn.MSELoss()
    X_fit, X_es = _es_split(X, es_frac, seed)
    loader = DataLoader(BenignMem(X_fit), batch_size=bs, shuffle=True, drop_last=True)
    es_loader = (DataLoader(BenignMem(X_es), batch_size=bs, shuffle=False, drop_last=False)
                 if X_es is not None else None)
    teacher.eval()
    best, best_state, bad = float("inf"), None, 0
    for ep in range(1, epochs + 1):
        student.train(); tot = 0.0
        for x in loader:
            x = x.to(DEVICE)
            with torch.no_grad(): t = teacher(x)
            loss = crit(student(x), t.detach())
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        msg = f"  [student {ep}/{epochs}] kd_mse={tot/max(len(loader),1):.6f}"
        if es_loader is None:
            print(msg, flush=True); continue
        student.eval(); vtot, nb = 0.0, 0
        with torch.no_grad():
            for x in es_loader:
                x = x.to(DEVICE)
                vtot += crit(student(x), teacher(x)).item(); nb += 1
        vloss = vtot / max(nb, 1)
        print(msg + f" val={vloss:.6f}", flush=True)
        if vloss < best - min_delta:
            best, bad = vloss, 0
            best_state = {k: v.detach().cpu().clone() for k, v in student.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                print(f"  [student] early stop @ep{ep} (best val={best:.6f})", flush=True); break
    if best_state is not None:
        student.load_state_dict(best_state)
    return student

def extract(model, X, bs=1024):
    model.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            b = torch.from_numpy(X[i:i+bs]).unsqueeze(1).to(DEVICE)
            out.append(model(b).cpu().numpy())
    return np.concatenate(out)
def _export_ts(model, vec_len, path):
    model.eval()
    with torch.no_grad():
        ts = torch.jit.trace(model, torch.zeros(1, 1, vec_len, WIN_SIZE, device=DEVICE))
    ts.save(path)

def _fit_ocsvm_thr(feat_fit, feat_val, feat_atk, a):
    """gamma를 선택하고 정상 검증 데이터의 target-FPR 분위수로 임계값을 정한다."""
    rng = np.random.default_rng(a.seed + 7)
    if feat_atk is not None and len(feat_atk):
        m = min(len(feat_val), len(feat_atk))
        fa = feat_atk[rng.choice(len(feat_atk), m, replace=False)] if len(feat_atk) > m else feat_atk
        fv = feat_val[rng.choice(len(feat_val), m, replace=False)] if len(feat_val) > m else feat_val
        y = np.r_[np.zeros(len(fv)), np.ones(len(fa))]
        best = None
        for g in a.gammas.split(","):
            gv = g if g == "scale" else float(g)
            oc = OneClassSVM(kernel="rbf", gamma=gv, nu=a.nu).fit(feat_fit)
            auc = roc_auc_score(y, np.r_[-oc.decision_function(fv), -oc.decision_function(fa)])
            if best is None or auc > best[0]:
                best = (auc, g, oc)
        _, g_name, ocsvm = best
    else:
        g_name = a.gammas.split(",")[0]
        gv = g_name if g_name == "scale" else float(g_name)
        ocsvm = OneClassSVM(kernel="rbf", gamma=gv, nu=a.nu).fit(feat_fit)
    thr = float(np.quantile(ocsvm.decision_function(feat_val), a.target_fpr))
    return ocsvm, thr, g_name


def run(a):
    os.makedirs(a.out, exist_ok=True)
    print(f"[pipeline] {a.data} → {a.out} | device={DEVICE} | mask={'ON' if mask_transport_enabled() else 'OFF'}")

    # 정상 데이터와 세션 ID 로드
    Xb, sess_b = load_npy_subset(os.path.join(a.data, "X_benign.npy"), a.limit, a.seed, with_sess=True)
    # 같은 세션은 학습·검증 중 한쪽에만 배정
    b_tr, b_val = split_train_val(Xb, sess_b, a.val_frac, a.seed)
    n_sess = len(np.unique(sess_b)) if sess_b is not None else 0
    print(f"[data] benign total={len(Xb)} (sessions={n_sess}) → train={len(b_tr)} val={len(b_val)} "
          f"(세션분할={'ON' if sess_b is not None else 'OFF(랜덤)'}, VEC_LEN={Xb.shape[1]})")

    # Teacher를 로드하거나 학습한 뒤 Student 학습
    es_frac = 0.0 if getattr(a, "no_early_stop", False) else a.es_frac
    teacher_loaded = bool(getattr(a, "teacher_pth", None) and os.path.exists(a.teacher_pth))
    if teacher_loaded:
        ck = torch.load(a.teacher_pth, map_location=DEVICE)
        teacher = make_teacher(ck.get("arch", a.teacher), ck.get("embed_dim", a.embed_dim), ck.get("l2", a.l2)).to(DEVICE)
        teacher.load_state_dict(ck["state_dict"]); teacher.eval()
        print(f"[teacher] loaded {a.teacher_pth} (동일 teacher 재사용)")
    else:
        teacher = train_teacher(b_tr, a.teacher, a.embed_dim, a.l2, a.epochs_teacher, a.batch_size, a.sigma)
    student = train_student(b_tr, teacher, a.arch, a.embed_dim, a.l2, a.epochs_student, a.batch_size)

    # OCSVM 학습 표본 수 제한
    feat_tr = extract(student, b_tr)
    feat_val = extract(student, b_val)
    rng = np.random.default_rng(a.seed)
    if len(feat_tr) > a.ocsvm_fit_max:
        feat_fit = feat_tr[rng.choice(len(feat_tr), a.ocsvm_fit_max, replace=False)]
    else:
        feat_fit = feat_tr
    print(f"[ocsvm] fit on {len(feat_fit)} (train feats)")

    # X_attack.npy는 gamma 선택과 평가에 사용. 시나리오별 파일은 여기서 읽지 않는다.
    attack_path = os.path.join(a.data, "X_attack.npy")
    if os.path.exists(attack_path):
        Xa = load_npy_subset(attack_path, a.attack_cap, a.seed + 1)
        feat_atk = extract(student, Xa)
        m = min(len(feat_val), len(feat_atk))   # 정상·공격 표본 수 맞춤
        fa = feat_atk[rng.choice(len(feat_atk), m, replace=False)] if len(feat_atk) > m else feat_atk
        fv = feat_val[rng.choice(len(feat_val), m, replace=False)] if len(feat_val) > m else feat_val
        y_val = np.r_[np.zeros(len(fv)), np.ones(len(fa))]
        best = None
        for g in a.gammas.split(","):        # 검증 AUC로 gamma 선택
            gv = g if g == "scale" else float(g)
            oc = OneClassSVM(kernel="rbf", gamma=gv, nu=a.nu).fit(feat_fit)
            s = np.r_[-oc.decision_function(fv), -oc.decision_function(fa)]
            auc = roc_auc_score(y_val, s)
            print(f"  [gamma={g}] val ROC-AUC={auc:.4f}")
            if best is None or auc > best[0]:
                best = (auc, g, gv, oc)
        val_auc, g_name, g_val, ocsvm = best
        df_val_benign = ocsvm.decision_function(feat_val)
        thr_df = float(np.quantile(df_val_benign, a.target_fpr))
        fpr_val = float((df_val_benign < thr_df).mean())
        rec_val = float((ocsvm.decision_function(fa) < thr_df).mean())
        fpr0 = float((df_val_benign < 0).mean())
        rec0 = float((ocsvm.decision_function(fa) < 0).mean())
        pr_auc = float(average_precision_score(y_val, np.r_[-ocsvm.decision_function(fv), -ocsvm.decision_function(fa)]))
        print(f"[ocsvm] 선택 gamma={g_name} (val ROC-AUC={val_auc:.4f})")
        print(f"[threshold] thr_df={thr_df:.5f} → val FPR={fpr_val:.4f} Recall={rec_val:.4f} | cut0 FPR={fpr0:.4f} Rec={rec0:.4f}")
    else:
        # 공격 데이터가 없으면 첫 gamma와 정상 점수의 분위수 사용
        g_name = a.gammas.split(",")[0]
        g_val = g_name if g_name == "scale" else float(g_name)
        ocsvm = OneClassSVM(kernel="rbf", gamma=g_val, nu=a.nu).fit(feat_fit)
        df_val_benign = ocsvm.decision_function(feat_val)
        thr_df = float(np.quantile(df_val_benign, a.target_fpr))
        fpr_val = float((df_val_benign < thr_df).mean()); fpr0 = float((df_val_benign < 0).mean())
        val_auc = pr_auc = rec_val = rec0 = None; m = 0
        print(f"[benign-only] attack 없음 → 잠정 gamma={g_name}, benign target-FPR threshold(FPR={fpr_val:.4f}). "
              f"gamma/threshold/eval 은 로컬 recalibrate_ocsvm.py 로 확정하세요.")

    # 모델 저장
    joblib.dump(ocsvm, os.path.join(a.out, "ocsvm.pkl"))
    torch.save({"state_dict": teacher.state_dict(), "embed_dim": a.embed_dim, "arch": a.teacher, "l2": a.l2},
               os.path.join(a.out, "teacher.pth"))
    torch.save({"state_dict": student.state_dict(), "embed_dim": a.embed_dim, "arch": a.arch, "l2": a.l2},
               os.path.join(a.out, "student.pth"))

    # L2 정규화를 포함해 TorchScript로 저장
    vec_len = Xb.shape[1]
    student.eval()
    dummy = torch.zeros(1, 1, vec_len, WIN_SIZE, device=DEVICE)
    with torch.no_grad():
        ts = torch.jit.trace(student, dummy)
    ts.save(os.path.join(a.out, "student_ts.pt"))

    # decision_function < threshold_df이면 이상
    with open(os.path.join(a.out, "threshold.json"), "w", encoding="utf-8") as f:
        json.dump({"threshold_df": thr_df, "target_fpr": a.target_fpr, "gamma": g_name,
                   "nu": a.nu, "l2": a.l2, "arch": a.arch, "teacher": a.teacher,
                   "mask_transport": mask_transport_enabled(), "vec_len": vec_len}, f, indent=2)

    r4 = lambda v: round(float(v), 4) if v is not None else None
    results = {
        "service": os.path.basename(os.path.normpath(a.data)),
        "n_benign_train": len(b_tr), "n_benign_val": len(b_val), "n_attack_eval": int(m),
        "arch": a.arch, "teacher": a.teacher, "l2": a.l2, "gamma": g_name, "nu": a.nu,
        "val_roc_auc": r4(val_auc), "val_pr_auc": r4(pr_auc),
        "threshold_df": thr_df, "target_fpr": a.target_fpr,
        "val_fpr_at_thr": r4(fpr_val), "val_recall_at_thr": r4(rec_val),
        "val_fpr_at_0": r4(fpr0), "val_recall_at_0": r4(rec0),
        "attack_used": os.path.exists(attack_path), "mask_transport": mask_transport_enabled(),
    }
    with open(os.path.join(a.out, "eval_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("[DONE]", json.dumps(results, ensure_ascii=False))
    return results
    # 선택: Teacher 산출물 저장
    if not teacher_loaded and not getattr(a, "no_teacher_artifacts", False):
        ft_tr, ft_val = extract(teacher, b_tr), extract(teacher, b_val)
        ff = ft_tr[rng.choice(len(ft_tr), a.ocsvm_fit_max, replace=False)] if len(ft_tr) > a.ocsvm_fit_max else ft_tr
        ft_atk = extract(teacher, Xa) if os.path.exists(attack_path) else None
        t_oc, t_thr, t_g = _fit_ocsvm_thr(ff, ft_val, ft_atk, a)
        joblib.dump(t_oc, os.path.join(a.out, "teacher_ocsvm.pkl"))
        _export_ts(teacher, vec_len, os.path.join(a.out, "teacher_ts.pt"))
        with open(os.path.join(a.out, "teacher_threshold.json"), "w", encoding="utf-8") as f:
            json.dump({"threshold_df": t_thr, "target_fpr": a.target_fpr, "gamma": t_g, "nu": a.nu,
                       "l2": a.l2, "arch": a.teacher, "kind": "teacher",
                       "mask_transport": mask_transport_enabled(), "vec_len": vec_len}, f, indent=2)
        print(f"[teacher-save] teacher_ts.pt / teacher_ocsvm.pkl / teacher_threshold.json (thr_df={t_thr:.5f})")

def main():
    p = argparse.ArgumentParser(description="KD-CNN + OCSVM 통합 학습 파이프라인 (#1~#6 반영)")
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--arch", default="2x8", choices=["1x8", "1x16", "2x8", "2x16", "2x32"])
    p.add_argument("--teacher", default="deep", choices=["shallow", "deep", "4x128"])
    p.add_argument("--teacher-pth", default=None, dest="teacher_pth",
                   help="사전학습 teacher.pth 로드(크기 스윕에서 동일 teacher 재사용 → 공정 비교)")
    p.add_argument("--embed-dim", type=int, default=FEAT_DIM, dest="embed_dim")
    p.add_argument("--l2", action="store_true", help="임베딩 L2 정규화(저마진 완화, ablation)")
    p.add_argument("--limit", type=int, default=50000, help="benign 서브샘플 상한(#5, 랜덤)")
    p.add_argument("--attack-cap", type=int, default=30000, dest="attack_cap", help="평가용 attack 상한")
    p.add_argument("--val-frac", type=float, default=0.3, dest="val_frac", help="benign held-out 비율(#2)")
    p.add_argument("--ocsvm-fit-max", type=int, default=15000, dest="ocsvm_fit_max", help="OCSVM fit 상한(#1)")
    p.add_argument("--gammas", default="scale,0.1,1.0,10.0", help="gamma 그리드(#3)")
    p.add_argument("--nu", type=float, default=0.1)
    p.add_argument("--target-fpr", type=float, default=0.01, dest="target_fpr", help="threshold 보정 목표 FPR(#4)")
    p.add_argument("--epochs-teacher", type=int, default=30, dest="epochs_teacher")
    p.add_argument("--epochs-student", type=int, default=20, dest="epochs_student")
    p.add_argument("--batch-size", type=int, default=512, dest="batch_size")
    p.add_argument("--sigma", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--patience-teacher", type=int, default=5, dest="patience_teacher")
    p.add_argument("--patience-student", type=int, default=5, dest="patience_student")
    p.add_argument("--es-frac", type=float, default=0.1, dest="es_frac", help="조기 종료용 내부 holdout 비율(train split에서 분리; b_val 불변)")
    p.add_argument("--no-early-stop", action="store_true", dest="no_early_stop")
    p.add_argument("--no-teacher-artifacts", action="store_true", dest="no_teacher_artifacts",
                   help="teacher 자체 OCSVM/threshold/TS 저장 생략")
    run(p.parse_args())


if __name__ == "__main__":
    main()