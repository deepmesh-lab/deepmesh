"""
OneClassSVM 학습 — 논문 원본(train_k8s_1x8.py) 규약 정합.

  - Student(1x8) embedding 위에서 OCSVM 학습 (benign only)
  - 원본 하이퍼파라미터: kernel=rbf, gamma=10.0, nu=0.1 (CLI 로 조정 가능)
  - 입력 (B,1,VEC_LEN,WIN_SIZE)
"""

import argparse
import os
import sys

import joblib
import numpy as np
import torch
from sklearn.svm import OneClassSVM
from torch.utils.data import DataLoader

from student_cnn import StudentEncoder, FEAT_DIM
from data_utils import BenignImages


def extract(student, loader, device) -> np.ndarray:
    student.eval()
    outs = []
    with torch.no_grad():
        for x in loader:
            outs.append(student(x.to(device)).cpu().numpy())
    return np.concatenate(outs, axis=0)


def train(args: argparse.Namespace) -> None:
    for path in (args.data, args.student):
        if not os.path.exists(path):
            print(f"[오류] 경로 없음: {path}", file=sys.stderr)
            sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(args.student, map_location=device)
    embed_dim = ckpt.get("embed_dim", FEAT_DIM)
    student = StudentEncoder(out_dim=embed_dim).to(device)
    student.load_state_dict(ckpt["state_dict"])
    student.eval()
    print(f"[Student] 로드: {args.student} (embed={embed_dim})")

    loader = DataLoader(BenignImages(args.data, limit=args.limit), batch_size=args.batch_size, shuffle=False)
    feats = extract(student, loader, device)
    print(f"[Embedding] {feats.shape}")

    gamma = args.gamma if args.gamma == "scale" else float(args.gamma)
    print(f"[OCSVM] kernel=rbf gamma={gamma} nu={args.nu}")
    ocsvm = OneClassSVM(kernel="rbf", gamma=gamma, nu=args.nu)
    ocsvm.fit(feats)

    preds = ocsvm.predict(feats)  # +1 정상 / -1 이상
    fp = float(np.mean(preds == -1)) * 100
    print(f"[검증] benign 자기예측 이상율(FPR): {fp:.2f}%")

    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "ocsvm.pkl")
    joblib.dump(ocsvm, save_path)
    print(f"[저장] {save_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="OneClassSVM 학습 — 논문 정합(rbf, gamma=10, nu=0.1)")
    p.add_argument("--data", required=True)
    p.add_argument("--student", required=True, help="student.pth")
    p.add_argument("--out", required=True)
    p.add_argument("--batch-size", type=int, default=256, dest="batch_size")
    p.add_argument("--gamma", default="10.0", help="OCSVM gamma (원본 10.0, 또는 'scale')")
    p.add_argument("--nu", type=float, default=0.1, help="OCSVM nu (원본 0.1)")
    p.add_argument("--limit", type=int, default=None, help="feature 추출 윈도우 수 상한")
    train(p.parse_args())


if __name__ == "__main__":
    main()
