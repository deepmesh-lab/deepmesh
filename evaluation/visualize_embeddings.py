"""
visualize_embeddings.py — 트래픽 임베딩 분포 + OCSVM 결정경계 시각화

논문 Fig.5 처럼, 세션 시퀀스 이미지 → student encoder 임베딩(예: 128-d) 을
PCA(또는 t-SNE)로 2D/3D 로 축소해 좌표평면/공간의 점으로 그린다.
임베딩 공간이 OCSVM 이 실제로 판정하는 공간이므로, 결정경계도 함께 시각화한다.

두 가지 모드:
  (1) 단일 서비스: benign(+선택 attack) 산점도 + OCSVM 결정경계.
      --data 를 1개만 주면 이 모드. --ocsvm 을 주면 실제 점수로 색칠 + 경계 참조.
  (2) 서비스 비교: --data 를 여러 개 주면, 동일 student 로 임베딩 후 같은 PCA 공간에
      서비스별 색으로 겹쳐 그린다(논문의 per-service 분리 주장 확인용).

사용 예:
  # 단일 서비스 (경계 포함)
  python visualize_embeddings.py \
      --data ../model-training/data/auth-service \
      --student ../model-training/models/auth-service/student_ts.pt \
      --ocsvm  ../model-training/models/auth-service/ocsvm.pkl \
      --dim 2 --out auth_dist.png
  # 아직 학습 전이면 원본 동봉 모델로 빠르게:
  #   --student ../../ServiceMesh/DataPlane/Model/student_encoder_1x8_ts.pt (student_ts.pt로 복사해 사용)

  # 서비스 비교 (한 공간에 겹쳐 그리기)
  python visualize_embeddings.py \
      --data ../model-training/data/auth-service ../model-training/data/post-service ../model-training/data/comment-service \
      --student <공용 student_ts.pt> --dim 2 --out services_overlay.png

필요 패키지: torch, scikit-learn, joblib, numpy, matplotlib
"""

import argparse
import os

import joblib
import numpy as np
import torch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.svm import OneClassSVM  # noqa: E402


def load_images(npy_path: str) -> torch.Tensor | None:
    if not os.path.exists(npy_path):
        return None
    X = np.load(npy_path)  # (N, VEC_LEN, WIN_SIZE), 이미 /255 정규화
    if len(X) == 0:
        return None
    return torch.tensor(X, dtype=torch.float32).unsqueeze(1)  # (N,1,VEC_LEN,WIN_SIZE)


def embed(student, X: torch.Tensor, batch: int = 256) -> np.ndarray:
    outs = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            outs.append(student(X[i:i + batch]).cpu().numpy())
    return np.concatenate(outs, axis=0)


def subsample(arr: np.ndarray, n: int, seed: int = 42) -> np.ndarray:
    if len(arr) <= n:
        return arr
    rng = np.random.default_rng(seed)
    return arr[rng.choice(len(arr), n, replace=False)]


def reduce_dims(E: np.ndarray, dim: int, method: str, fit_on: np.ndarray):
    if method == "tsne":
        from sklearn.manifold import TSNE
        # t-SNE 는 transform 을 지원하지 않아 전체를 한 번에 fit_transform
        return None  # 호출부에서 별도 처리
    reducer = PCA(n_components=dim)
    reducer.fit(fit_on)
    return reducer


def main():
    ap = argparse.ArgumentParser(description="트래픽 임베딩 분포 + OCSVM 결정경계 시각화")
    ap.add_argument("--data", nargs="+", required=True,
                    help="X_benign.npy(및 선택 X_attack.npy)가 있는 디렉토리(1개=단일, 여러개=비교)")
    ap.add_argument("--labels", nargs="*", default=None, help="서비스 라벨(생략 시 디렉토리명)")
    ap.add_argument("--student", required=True, help="student_ts.pt (TorchScript)")
    ap.add_argument("--ocsvm", default=None, help="ocsvm.pkl (단일 모드에서 실제 점수/경계 참조)")
    ap.add_argument("--dim", type=int, default=2, choices=[2, 3])
    ap.add_argument("--method", default="pca", choices=["pca", "tsne"])
    ap.add_argument("--max-points", type=int, default=3000, help="시각화 표본 상한(속도)")
    ap.add_argument("--out", default="embedding_dist.png")
    args = ap.parse_args()

    student = torch.jit.load(args.student, map_location="cpu").eval().to(torch.float32)
    labels = args.labels or [os.path.basename(os.path.normpath(d)) for d in args.data]

    # ── 각 디렉토리의 benign/attack 임베딩 계산 ──────────────────────
    per_service = []  # [(label, E_benign, E_attack or None)]
    for d, lab in zip(args.data, labels):
        Xb = load_images(os.path.join(d, "X_benign.npy"))
        if Xb is None:
            print(f"[SKIP] {d}: X_benign.npy 없음/빈값")
            continue
        Eb = embed(student, Xb)
        Xa = load_images(os.path.join(d, "X_attack.npy"))
        Ea = embed(student, Xa) if Xa is not None else None
        per_service.append((lab, Eb, Ea))
        print(f"[INFO] {lab}: benign {Eb.shape}" + (f", attack {Ea.shape}" if Ea is not None else ""))

    if not per_service:
        print("[ERROR] 시각화할 데이터가 없습니다.")
        return

    single = len(per_service) == 1

    # ── 차원축소용 fit 데이터(전체 benign 기준) ─────────────────────
    all_benign = np.concatenate([e for _, e, _ in per_service], axis=0)

    fig = plt.figure(figsize=(9, 7))
    ax = fig.add_subplot(111, projection="3d" if args.dim == 3 else None)

    if args.method == "tsne":
        # t-SNE: 모든 점을 모아 한 번에 축소 후 되돌려 배분
        from sklearn.manifold import TSNE
        chunks, meta = [], []
        for lab, Eb, Ea in per_service:
            Eb_s = subsample(Eb, args.max_points)
            chunks.append(Eb_s); meta.append((lab, "benign", len(Eb_s)))
            if Ea is not None:
                Ea_s = subsample(Ea, args.max_points)
                chunks.append(Ea_s); meta.append((lab, "attack", len(Ea_s)))
        Z = TSNE(n_components=args.dim, init="pca", perplexity=30,
                 random_state=42).fit_transform(np.concatenate(chunks, 0))
        idx = 0
        for lab, kind, n in meta:
            seg = Z[idx:idx + n]; idx += n
            _scatter(ax, seg, args.dim, label=f"{lab} ({kind})",
                     color="red" if kind == "attack" else None, marker="x" if kind == "attack" else "o")
        _finish(ax, args, "t-SNE embedding distribution")
        _save(fig, args.out)
        return

    # ── PCA ─────────────────────────────────────────────────────────
    reducer = PCA(n_components=args.dim).fit(all_benign)

    if single:
        lab, Eb, Ea = per_service[0]
        Eb_s = subsample(Eb, args.max_points)
        Zb = reducer.transform(Eb_s)

        # 실제 OCSVM 점수(있으면)로 색칠
        colors, cbar_label = None, None
        if args.ocsvm and os.path.exists(args.ocsvm):
            ocsvm = joblib.load(args.ocsvm)
            colors = ocsvm.decision_function(Eb_s)  # 양수=정상, 음수=이상
            cbar_label = "OCSVM decision_function (real model)"

        # 2D: 결정경계 contour (시각화용 2D OCSVM 을 PCA 평면에 재적합)
        if args.dim == 2:
            _draw_boundary_2d(ax, Zb)
        sc = _scatter(ax, Zb, args.dim, label=f"{lab} benign",
                      color=None if colors is not None else "tab:blue", c=colors,
                      cmap="coolwarm")
        if colors is not None:
            fig.colorbar(sc, ax=ax, label=cbar_label, shrink=0.8)

        if Ea is not None:
            Za = reducer.transform(subsample(Ea, args.max_points))
            _scatter(ax, Za, args.dim, label=f"{lab} attack", color="black", marker="x")

        _finish(ax, args, f"{lab}: traffic dist + OCSVM boundary (2D)" if args.dim == 2
                else f"{lab}: traffic distribution")
    else:
        # 서비스 비교 오버레이
        cmap = plt.get_cmap("tab10")
        for i, (lab, Eb, Ea) in enumerate(per_service):
            Zb = reducer.transform(subsample(Eb, args.max_points))
            _scatter(ax, Zb, args.dim, label=lab, color=cmap(i % 10))
        _finish(ax, args, "Per-service traffic embedding distribution (PCA)")

    _save(fig, args.out)


def _scatter(ax, Z, dim, label=None, color=None, c=None, cmap=None, marker="o"):
    if dim == 3:
        return ax.scatter(Z[:, 0], Z[:, 1], Z[:, 2], s=8, alpha=0.5,
                          label=label, color=color, c=c, cmap=cmap, marker=marker)
    return ax.scatter(Z[:, 0], Z[:, 1], s=10, alpha=0.6,
                      label=label, color=color, c=c, cmap=cmap, marker=marker)


def _draw_boundary_2d(ax, Zb: np.ndarray):
    """PCA 2D 평면에 시각화용 OCSVM 을 재적합해 결정경계를 그린다(고차원 실경계의 2D 투영 근사)."""
    viz = OneClassSVM(nu=0.1, gamma="scale").fit(Zb)
    pad = (Zb.max(0) - Zb.min(0)) * 0.15 + 1e-6
    xmin, ymin = Zb.min(0) - pad
    xmax, ymax = Zb.max(0) + pad
    xx, yy = np.meshgrid(np.linspace(xmin, xmax, 300), np.linspace(ymin, ymax, 300))
    dz = viz.decision_function(np.c_[xx.ravel(), yy.ravel()]).reshape(xx.shape)
    ax.contourf(xx, yy, dz, levels=np.linspace(dz.min(), 0, 8), cmap="Blues", alpha=0.25)
    ax.contour(xx, yy, dz, levels=[0], colors="red", linewidths=2)  # 결정경계
    ax.plot([], [], color="red", label="OCSVM boundary (2D approx.)")


def _finish(ax, args, title):
    ax.set_title(title)
    ax.set_xlabel("PC1" if args.method == "pca" else "dim1")
    ax.set_ylabel("PC2" if args.method == "pca" else "dim2")
    if args.dim == 3:
        ax.set_zlabel("PC3" if args.method == "pca" else "dim3")
    ax.legend(loc="best", fontsize=8)


def _save(fig, out):
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    print(f"[SAVED] {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
