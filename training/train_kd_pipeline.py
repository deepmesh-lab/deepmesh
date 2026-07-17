"""
train_kd_pipeline.py — 한 서비스에 대한 KD-CNN + OCSVM 통합 학습 파이프라인 (Colab용).

반영한 보완점(#1~#6, checkpoint2.md / masking.md 근거):
  #1 OCSVM 대용량 불가 → benign 랜덤 서브샘플로 fit (OCSVM 은 별도 상한).
  #2 held-out 없음 → benign 을 seed 고정 train/val 랜덤 분리. OCSVM fit=train, threshold·FPR=val.
  #3 gamma=10 암기 → gamma 그리드에서 val ROC-AUC 최고값 자동 선택(기본 [scale,0.1,1,10]).
  #4 threshold 보정 없음 → val benign 만으로 target-FPR 분위수 threshold 산출·저장(배포 가능).
  #5 --limit 앞 N개 편향 → 랜덤 서브샘플(seed).
  #6 L2 정규화 옵션 → --l2 로 teacher/student 출력 단위구면 정규화(저마진 완화, ablation).
  + 전송계층 마스킹은 data_utils.apply_transport_mask(MASK_TRANSPORT) 로 로드 시 적용.

산출물(--out): teacher.pth, student.pth, student_ts.pt, ocsvm.pkl, threshold.json, eval_results.json

사용:
  python train_kd_pipeline.py --data ./data/auth-service --out ./data/models/auth-service \
      --arch 2x16 --teacher deep --limit 50000 --val-frac 0.3 --l2
"""
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

from student_cnn import make_student, make_teacher, FEAT_DIM, WIN_SIZE
from data_utils import apply_transport_mask, mask_transport_enabled, group_val_mask

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ─────────────────────────── 데이터 ───────────────────────────

def load_npy_subset(path: str, cap: int | None, seed: int, with_sess: bool = False):
    """(N,VEC_LEN,WIN_SIZE) npy 를 mmap 으로 랜덤 cap개 로드(#5) + 정규화 + 마스킹.
    with_sess=True 면 정렬된 sess_*.npy 를 같은 인덱스로 로드해 (X, sess) 반환(세션 분할용)."""
    arr = np.load(path, mmap_mode="r")
    n = len(arr)
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(n, cap, replace=False)) if (cap and n > cap) else np.arange(n)
    X = np.asarray(arr[idx], dtype=np.float32)
    X = np.nan_to_num(X)
    if X.max() > 1.5:            # 0~255 저장분 방어
        X = np.clip(X, 0, 255) / 255.0
    else:
        X = np.clip(X, 0.0, 1.0)
    if X.shape[2] != WIN_SIZE and X.shape[1] == WIN_SIZE:  # 축 교정
        X = np.transpose(X, (0, 2, 1))
    X = apply_transport_mask(X)   # 전송계층 마스킹(토글)
    if not with_sess:
        return X
    spath = os.path.join(os.path.dirname(path), os.path.basename(path).replace("X_", "sess_", 1))
    sess = np.asarray(np.load(spath, mmap_mode="r")[idx], dtype=np.int64) if os.path.exists(spath) else None
    return X, sess


def split_train_val(X: np.ndarray, sess, val_frac: float, seed: int):
    """세션(group) 단위 분할(누수 방지). sess=None 이면 랜덤 window 분할로 폴백(경고)."""
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


# ─────────────────────────── 학습 ───────────────────────────

def nt_xent(z1, z2, temp=0.1):
    z1, z2 = F.normalize(z1, dim=1), F.normalize(z2, dim=1)
    z = torch.cat([z1, z2], 0); N = z1.size(0)
    sim = (z @ z.T) / temp
    sim.masked_fill_(torch.eye(2 * N, dtype=torch.bool, device=z.device), -9e15)
    labels = torch.arange(N, device=z.device)
    labels = torch.cat([labels + N, labels])
    return F.cross_entropy(sim, labels)


def train_teacher(X, arch, embed, l2, epochs, bs, sigma):
    teacher = make_teacher(arch, embed, l2).to(DEVICE)
    opt = torch.optim.Adam(teacher.parameters(), lr=1e-3)
    loader = DataLoader(ContrastiveMem(X, sigma), batch_size=bs, shuffle=True, drop_last=True)
    teacher.train()
    for ep in range(1, epochs + 1):
        tot = 0.0
        for v1, v2 in loader:
            v1, v2 = v1.to(DEVICE), v2.to(DEVICE)
            loss = nt_xent(teacher(v1), teacher(v2))
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        print(f"  [teacher {ep}/{epochs}] nt_xent={tot/max(len(loader),1):.4f}", flush=True)
    return teacher


def train_student(X, teacher, arch, embed, l2, epochs, bs):
    student = make_student(arch, embed, l2).to(DEVICE)
    n_params = sum(p.numel() for p in student.parameters())
    print(f"  [student] arch={arch} params={n_params:,} ({n_params/1000:.2f}K) l2={l2}")
    opt = torch.optim.Adam(student.parameters(), lr=1e-3)
    crit = nn.MSELoss()
    loader = DataLoader(BenignMem(X), batch_size=bs, shuffle=True, drop_last=True)
    teacher.eval()
    student.train()
    for ep in range(1, epochs + 1):
        tot = 0.0
        for x in loader:
            x = x.to(DEVICE)
            with torch.no_grad():
                t = teacher(x)
            loss = crit(student(x), t.detach())
            opt.zero_grad(); loss.backward(); opt.step(); tot += loss.item()
        print(f"  [student {ep}/{epochs}] kd_mse={tot/max(len(loader),1):.6f}", flush=True)
    return student


def extract(model, X, bs=1024):
    model.eval(); out = []
    with torch.no_grad():
        for i in range(0, len(X), bs):
            b = torch.from_numpy(X[i:i+bs]).unsqueeze(1).to(DEVICE)
            out.append(model(b).cpu().numpy())
    return np.concatenate(out)


# ─────────────────────────── 파이프라인 ───────────────────────────

def run(a):
    os.makedirs(a.out, exist_ok=True)
    print(f"[pipeline] {a.data} → {a.out} | device={DEVICE} | mask={'ON' if mask_transport_enabled() else 'OFF'}")

    Xb, sess_b = load_npy_subset(os.path.join(a.data, "X_benign.npy"), a.limit, a.seed, with_sess=True)
    b_tr, b_val = split_train_val(Xb, sess_b, a.val_frac, a.seed)
    n_sess = len(np.unique(sess_b)) if sess_b is not None else 0
    print(f"[data] benign total={len(Xb)} (sessions={n_sess}) → train={len(b_tr)} val={len(b_val)} "
          f"(세션분할={'ON' if sess_b is not None else 'OFF(랜덤)'}, VEC_LEN={Xb.shape[1]})")

    # 1) teacher (사전학습 로드 or 신규) → 2) student (train split 만 사용)
    if getattr(a, "teacher_pth", None) and os.path.exists(a.teacher_pth):
        ck = torch.load(a.teacher_pth, map_location=DEVICE)
        teacher = make_teacher(ck.get("arch", a.teacher), ck.get("embed_dim", a.embed_dim), ck.get("l2", a.l2)).to(DEVICE)
        teacher.load_state_dict(ck["state_dict"]); teacher.eval()
        print(f"[teacher] loaded {a.teacher_pth} (동일 teacher 재사용)")
    else:
        teacher = train_teacher(b_tr, a.teacher, a.embed_dim, a.l2, a.epochs_teacher, a.batch_size, a.sigma)
    student = train_student(b_tr, teacher, a.arch, a.embed_dim, a.l2, a.epochs_student, a.batch_size)

    # 3) OCSVM: train 특징에서 최대 ocsvm_fit_max 개로 fit(#1). gamma 그리드에서 val ROC-AUC 최고 선택(#3)
    feat_tr = extract(student, b_tr)
    feat_val = extract(student, b_val)
    rng = np.random.default_rng(a.seed)
    if len(feat_tr) > a.ocsvm_fit_max:
        feat_fit = feat_tr[rng.choice(len(feat_tr), a.ocsvm_fit_max, replace=False)]
    else:
        feat_fit = feat_tr
    print(f"[ocsvm] fit on {len(feat_fit)} (train feats)")

    # attack 은 one-class 학습엔 미사용 — gamma 선택/평가에만 쓰임. 없으면 benign-only 로 학습만 하고
    # gamma/threshold(Youden)/평가는 로컬 recalibrate_ocsvm.py + evaluate.py 에서 attack 전량으로 확정.
    attack_path = os.path.join(a.data, "X_attack.npy")
    if os.path.exists(attack_path):
        Xa = load_npy_subset(attack_path, a.attack_cap, a.seed + 1)
        feat_atk = extract(student, Xa)
        m = min(len(feat_val), len(feat_atk))   # val 균형
        fa = feat_atk[rng.choice(len(feat_atk), m, replace=False)] if len(feat_atk) > m else feat_atk
        fv = feat_val[rng.choice(len(feat_val), m, replace=False)] if len(feat_val) > m else feat_val
        y_val = np.r_[np.zeros(len(fv)), np.ones(len(fa))]
        best = None
        for g in a.gammas.split(","):        # gamma 그리드 → val ROC-AUC 최고
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
        # benign-only: 잠정 gamma(gammas 첫 항목)로 OCSVM fit + benign target-FPR threshold. attack 지표는 None.
        g_name = a.gammas.split(",")[0]
        g_val = g_name if g_name == "scale" else float(g_name)
        ocsvm = OneClassSVM(kernel="rbf", gamma=g_val, nu=a.nu).fit(feat_fit)
        df_val_benign = ocsvm.decision_function(feat_val)
        thr_df = float(np.quantile(df_val_benign, a.target_fpr))
        fpr_val = float((df_val_benign < thr_df).mean()); fpr0 = float((df_val_benign < 0).mean())
        val_auc = pr_auc = rec_val = rec0 = None; m = 0
        print(f"[benign-only] attack 없음 → 잠정 gamma={g_name}, benign target-FPR threshold(FPR={fpr_val:.4f}). "
              f"gamma/threshold/eval 은 로컬 recalibrate_ocsvm.py 로 확정하세요.")

    # 5) OCSVM + threshold 저장
    joblib.dump(ocsvm, os.path.join(a.out, "ocsvm.pkl"))
    torch.save({"state_dict": teacher.state_dict(), "embed_dim": a.embed_dim, "arch": a.teacher, "l2": a.l2},
               os.path.join(a.out, "teacher.pth"))
    torch.save({"state_dict": student.state_dict(), "embed_dim": a.embed_dim, "arch": a.arch, "l2": a.l2},
               os.path.join(a.out, "student.pth"))

    # 6) TorchScript export (l2 는 student 모듈에 내장되어 함께 trace됨)
    vec_len = Xb.shape[1]
    student.eval()
    dummy = torch.zeros(1, 1, vec_len, WIN_SIZE, device=DEVICE)
    with torch.no_grad():
        ts = torch.jit.trace(student, dummy)
    ts.save(os.path.join(a.out, "student_ts.pt"))

    # threshold.json — 런타임 SCORE_THRESHOLD 로 thr_df 사용(is_malicious = decision_function < thr_df)
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


def main():
    p = argparse.ArgumentParser(description="KD-CNN + OCSVM 통합 학습 파이프라인 (#1~#6 반영)")
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--arch", default="2x8", choices=["1x8", "1x16", "2x8", "2x16", "2x32"])
    p.add_argument("--teacher", default="deep", choices=["shallow", "deep"])
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
    run(p.parse_args())


if __name__ == "__main__":
    main()
