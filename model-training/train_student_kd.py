"""
Student KD 학습 — 논문 원본(train_k8s_1x8.py) 규약 정합.

  - Student: StudentEncoder(1x8), 입력 (B,1,VEC_LEN,WIN_SIZE), L2 정규화 없음
  - KD Loss: MSE(student(x), teacher(x).detach())  (원본 kd_loss 와 동일)
  - Teacher: 사전학습된 TeacherEncoder(deep) 로드 후 freeze
  - 정상(benign) 트래픽만 사용
"""

import argparse
import os
import sys

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from student_cnn import StudentEncoder, TeacherEncoder, FEAT_DIM
from data_utils import BenignImages


def train(args: argparse.Namespace) -> None:
    for path in (args.data, args.teacher):
        if not os.path.exists(path):
            print(f"[오류] 경로 없음: {path}", file=sys.stderr)
            sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[학습] device={device}")

    ckpt = torch.load(args.teacher, map_location=device)
    t_dim = ckpt.get("embed_dim", FEAT_DIM)
    teacher = TeacherEncoder(out_dim=t_dim).to(device)
    teacher.load_state_dict(ckpt["state_dict"])
    teacher.eval()
    for prm in teacher.parameters():
        prm.requires_grad = False
    print(f"[Teacher] 로드: {args.teacher} (embed={t_dim})")

    student = StudentEncoder(out_dim=args.embed_dim).to(device)
    n_params = sum(p.numel() for p in student.parameters())
    print(f"[Student] 1x8 파라미터 {n_params:,} ({n_params/1000:.2f}K)")

    loader = DataLoader(BenignImages(args.data, limit=args.limit), batch_size=args.batch_size,
                        shuffle=True, num_workers=0)
    optimizer = torch.optim.Adam(student.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    print(f"[학습] epochs={args.epochs} batch={args.batch_size} | batches/epoch={len(loader)} | device={device}")
    student.train()
    for epoch in range(1, args.epochs + 1):
        total = 0.0
        pbar = tqdm(loader, desc=f"student epoch {epoch}/{args.epochs}", leave=False)
        for x in pbar:
            x = x.to(device)
            with torch.no_grad():
                t_feat = teacher(x)
            loss = criterion(student(x), t_feat.detach())
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            total += loss.item()
            pbar.set_postfix(loss=f"{loss.item():.4f}")
        print(f"  Epoch [{epoch:>4}/{args.epochs}] kd_mse: {total/max(len(loader),1):.6f}", flush=True)

    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "student.pth")
    torch.save({"state_dict": student.state_dict(), "embed_dim": args.embed_dim}, save_path)
    print(f"[저장] {save_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Student KD(MSE) — 논문 정합")
    p.add_argument("--data", required=True)
    p.add_argument("--teacher", required=True, help="teacher.pth")
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=20, help="원본 20")
    p.add_argument("--batch-size", type=int, default=256, dest="batch_size")
    p.add_argument("--embed-dim", type=int, default=FEAT_DIM, dest="embed_dim")
    p.add_argument("--limit", type=int, default=None, help="학습 윈도우 수 상한(CPU 속도조절)")
    train(p.parse_args())


if __name__ == "__main__":
    main()
