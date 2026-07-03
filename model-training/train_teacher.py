"""
Teacher 대조학습(NT-Xent) 스크립트 — 논문 원본 규약 정합.

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
  - 모델: TeacherEncoder(deep, 원본 Encoderv2), 입력 (B,1,VEC_LEN,WIN_SIZE)
  - 증강: 가우시안 노이즈(σ=0.01) + [0,1] 클립 (원본 train_k8s_1x8.py 와 동일; 셔플 없음)
  - 손실: NT-Xent (temperature 기본 0.1)
  - 정상(benign) 트래픽만 사용
"""

import argparse
import os

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from tqdm import tqdm

from student_cnn import TeacherEncoder, FEAT_DIM
from data_utils import ContrastiveImages


def nt_xent_loss(z_i: torch.Tensor, z_j: torch.Tensor, temperature: float = 0.1) -> torch.Tensor:
    """NT-Xent. z_i,z_j: (B,D) (여기서 L2 정규화 후 코사인 유사도 사용)."""
    z_i = F.normalize(z_i, dim=1)
    z_j = F.normalize(z_j, dim=1)
    B = z_i.size(0)
    z = torch.cat([z_i, z_j], dim=0)                 # (2B, D)
    sim = torch.mm(z, z.T) / temperature             # (2B, 2B)
    sim = sim.masked_fill(torch.eye(2 * B, dtype=torch.bool, device=z.device), float("-inf"))
    labels = torch.cat([torch.arange(B, 2 * B, device=z.device),
                        torch.arange(0, B, device=z.device)])
    return F.cross_entropy(sim, labels)


def train(args: argparse.Namespace) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[학습] device={device}")

    dataset = ContrastiveImages(args.data, sigma=args.sigma, limit=args.limit)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True,
                        num_workers=0, drop_last=True)

    if len(loader) == 0:
        raise SystemExit(f"[오류] 배치가 0개입니다(샘플 {len(dataset)} < batch {args.batch_size}). "
                         f"--batch-size 를 줄이세요.")

    model = TeacherEncoder(out_dim=args.embed_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    print(f"[학습] epochs={args.epochs} batch={args.batch_size} embed={args.embed_dim} "
          f"temp={args.temperature} sigma={args.sigma} | batches/epoch={len(loader)} | device={device}")
    if device.type == "cpu":
        print("[안내] CPU 학습은 deep teacher 특성상 느립니다. GPU 권장 또는 --epochs 축소.")

    model.train()
    for epoch in range(1, args.epochs + 1):
        total = 0.0
        pbar = tqdm(loader, desc=f"teacher epoch {epoch}/{args.epochs}", leave=False)
        for v1, v2 in pbar:
            v1, v2 = v1.to(device), v2.to(device)
            loss = nt_xent_loss(model(v1), model(v2), temperature=args.temperature)
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            total += loss.item()
            pbar.set_postfix(loss=f"{loss.item():.4f}")
        print(f"  Epoch [{epoch:>4}/{args.epochs}] nt_xent: {total/len(loader):.6f}", flush=True)

    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "teacher.pth")
    torch.save({"state_dict": model.state_dict(), "embed_dim": args.embed_dim}, save_path)
    print(f"[저장] {save_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Teacher 대조학습(NT-Xent) — 논문 정합")
    p.add_argument("--data", required=True, help="X_benign.npy 디렉토리")
    p.add_argument("--out", required=True, help="teacher.pth 저장 디렉토리")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=256, dest="batch_size")
    p.add_argument("--embed-dim", type=int, default=FEAT_DIM, dest="embed_dim")
    p.add_argument("--temperature", type=float, default=0.1, help="NT-Xent 온도(원본 0.1)")
    p.add_argument("--sigma", type=float, default=0.01, help="증강 가우시안 노이즈 std(원본 0.01)")
    p.add_argument("--limit", type=int, default=None, help="학습 윈도우 수 상한(CPU 속도조절, 예: 2000)")
    train(p.parse_args())


if __name__ == "__main__":
    main()
