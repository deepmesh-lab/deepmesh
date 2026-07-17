"""
visualize_dist.py — 서비스별 benign vs attack 분포 분리 가능성 시각화(전처리 직후, 모델 학습 전).

■ 무엇을: preprocess_k8s 산출 npy를 로드 → 마스킹(MASK_TRANSPORT) → 원시 세션이미지 벡터의
  PCA 2D 산점도 + 정량 분리도(top-50 PCA 위 LogisticRegression hold-out ROC-AUC).
■ 매핑(논문): auth = benign vs {brute, k8s}, 그 외 = benign vs {k8s(enum+manip 이탈)}.
■ ⚠️ 이건 '원시 이미지' 기준 사전 점검이다. 논문의 최종 분리도는 학습된 인코더 임베딩(Colab) 기준이며,
   원시에서 겹쳐 보여도 인코더가 분리할 수 있다(논문 Fig.5: 단일이미지 겹침 → 시퀀스/임베딩 분리).

사용: cd training && python visualize_dist.py      # 마스킹 ON(기본)
     MASK_TRANSPORT=0 python visualize_dist.py     # 마스킹 OFF(ablation)
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

from data_utils import apply_transport_mask, mask_transport_enabled

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
VIZ = os.path.join(HERE, "viz")
PER_CLASS = 2000   # 클래스당 시각화/평가 샘플 상한

SVC_ATTACK = {
    "auth":     ["brute", "k8s"],
    "post":     ["k8s"],
    "comment":  ["k8s"],
    "frontend": ["k8s"],
    "mysql":    ["k8s"],
}
COLORS = {"benign": "#2b6cb0", "brute": "#c53030", "k8s": "#dd6b20"}


def load(path, cap):
    if not os.path.exists(path):
        return None
    X = np.load(path).astype(np.float32)
    if len(X) == 0:
        return None
    if len(X) > cap:
        X = X[np.random.default_rng(0).choice(len(X), cap, replace=False)]
    X = X / 255.0 if X.max() > 1.5 else X
    X = apply_transport_mask(X)              # (N, 1479, 5) rows 7-18 마스킹(토글)
    return X.reshape(len(X), -1)             # (N, 7395)


def sep_auc(Xb, Xa):
    """top-50 PCA 위 LogisticRegression hold-out ROC-AUC (사전 분리도)."""
    X = np.vstack([Xb, Xa]); y = np.r_[np.zeros(len(Xb)), np.ones(len(Xa))]
    k = min(50, X.shape[0] - 1, X.shape[1])
    Z = PCA(n_components=k, random_state=0).fit_transform(X)
    Ztr, Zte, ytr, yte = train_test_split(Z, y, test_size=0.3, stratify=y, random_state=0)
    lr = LogisticRegression(max_iter=1000).fit(Ztr, ytr)
    return roc_auc_score(yte, lr.predict_proba(Zte)[:, 1])


def main():
    os.makedirs(VIZ, exist_ok=True)
    mask_on = mask_transport_enabled()
    tag = "maskON" if mask_on else "maskOFF"
    print(f"[viz] masking={'ON' if mask_on else 'OFF'} → viz/*_{tag}.png")
    summary = []

    for svc, atks in SVC_ATTACK.items():
        Xb = load(os.path.join(DATA, svc, "X_benign.npy"), PER_CLASS)
        if Xb is None:
            print(f"[{svc}] benign 없음 → skip"); continue
        groups = {"benign": Xb}
        for a in atks:
            Xa = load(os.path.join(DATA, "_attack", f"X_{a}.npy"), PER_CLASS)
            if Xa is not None:
                groups[a] = Xa

        # 정량 분리도: benign vs (각 attack)
        aucs = {a: sep_auc(Xb, groups[a]) for a in atks if a in groups}

        # PCA 2D 산점 (전체 클래스 공통 공간)
        allX = np.vstack(list(groups.values()))
        Z = PCA(n_components=2, random_state=0).fit_transform(allX)
        plt.figure(figsize=(6, 5))
        off = 0
        for name, X in groups.items():
            z = Z[off:off + len(X)]; off += len(X)
            plt.scatter(z[:, 0], z[:, 1], s=6, alpha=0.35,
                        c=COLORS.get(name, "#666"), label=f"{name} (n={len(X)})")
        title = f"{svc}  [{tag}]  " + " ".join(f"AUC({a})={aucs[a]:.2f}" for a in aucs)
        plt.title(title, fontsize=10); plt.legend(markerscale=2, fontsize=8)
        plt.xlabel("PC1"); plt.ylabel("PC2"); plt.tight_layout()
        out = os.path.join(VIZ, f"{svc}_{tag}.png")
        plt.savefig(out, dpi=130); plt.close()
        print(f"[{svc}] {title}  → {out}")
        summary.append((svc, aucs))

    print("\n=== 사전 분리도(ROC-AUC, top-50 PCA+LR, hold-out) ===")
    for svc, aucs in summary:
        print(f"  {svc:10} " + "  ".join(f"{a}:{v:.3f}" for a, v in aucs.items()))
    print("※ 원시 이미지 기준. 최종 분리도는 학습 인코더 임베딩(Colab) 으로 재확인.")


if __name__ == "__main__":
    main()
