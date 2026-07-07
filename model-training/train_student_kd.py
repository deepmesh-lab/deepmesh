"""
Student CNN Knowledge Distillation 학습 스크립트

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
구조: CNN-2x16 (Teacher 대비 경량화, ~13.87K 파라미터)
학습 방식: Teacher embedding을 soft target으로 사용하는 Knowledge Distillation
           KD Loss = MSE(student_embed, teacher_embed.detach())
입력: X_benign.npy (benign only — one-class KD)
"""

import argparse
import os
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

from student_cnn import StudentCNN


# ---------------------------------------------------------------------------
# Teacher 모델 정의 (로드용 — 구조 동일하게 유지)
# ---------------------------------------------------------------------------

class TeacherCNN(nn.Module):
    """
    Self-supervised Contrastive Learning용 Teacher CNN.

    Input:  (B, 5, 1479)  — 채널 차원 unsqueeze 후 (B, 1, 5, 1479) 로 처리
    Output: (B, embed_dim) — L2 정규화된 embedding 벡터
    """

    def __init__(self, embed_dim: int = 128):
        super().__init__()

        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=(1, 7), stride=(1, 3)),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=(1, 5), stride=(1, 2)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )
        self.conv3 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=(1, 3), stride=(1, 1)),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((5, 32)),
        )
        self.fc = nn.Linear(5 * 32 * 128, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.unsqueeze(1)
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = x.flatten(1)
        x = self.fc(x)
        x = F.normalize(x, dim=1)
        return x


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

class BenignDataset(Dataset):
    """
    X_benign.npy 를 로드해 float32 텐서로 반환.

    Args:
        data_dir: X_benign.npy 가 위치한 디렉터리 경로
    """

    def __init__(self, data_dir: str):
        npy_path = os.path.join(data_dir, "X_benign.npy")
        if not os.path.exists(npy_path):
            raise FileNotFoundError(f"X_benign.npy 를 찾을 수 없습니다: {npy_path}")

        self.data = np.load(npy_path).astype(np.float32)  # (N, 5, 1479)
        print(f"[데이터] 로드 완료: {self.data.shape} from {npy_path}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> torch.Tensor:
        return torch.from_numpy(self.data[idx])


# ---------------------------------------------------------------------------
# 학습 루프
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace) -> None:
    # 경로 검증
    if not os.path.exists(args.data):
        print(f"[오류] --data 경로가 존재하지 않습니다: {args.data}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.teacher):
        print(f"[오류] --teacher 경로가 존재하지 않습니다: {args.teacher}", file=sys.stderr)
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[학습] 디바이스: {device}")

    # Teacher 로드 및 freeze
    ckpt = torch.load(args.teacher, map_location=device)
    teacher_embed_dim = ckpt.get("embed_dim", 128)
    teacher = TeacherCNN(embed_dim=teacher_embed_dim).to(device)
    teacher.load_state_dict(ckpt["state_dict"])
    teacher.eval()
    for param in teacher.parameters():
        param.requires_grad = False
    print(f"[Teacher] 로드 완료: {args.teacher} (embed_dim={teacher_embed_dim})")

    # Student 생성
    student = StudentCNN(embed_dim=args.embed_dim).to(device)
    total_params = sum(p.numel() for p in student.parameters())
    print(f"[Student] 파라미터 수: {total_params:,} ({total_params/1000:.2f}K)")

    # 데이터셋 / DataLoader
    dataset = BenignDataset(args.data)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        drop_last=False,
    )

    # Optimizer & Loss
    optimizer = torch.optim.Adam(student.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    print(f"[학습] epochs={args.epochs}, batch_size={args.batch_size}, "
          f"embed_dim={args.embed_dim}")

    student.train()
    for epoch in range(1, args.epochs + 1):
        total_loss = 0.0
        for x in loader:
            x = x.to(device)

            # Teacher embedding (no grad, frozen)
            with torch.no_grad():
                teacher_embed = teacher(x)

            # Student embedding
            student_embed = student(x)

            # KD Loss: MSE(student_embed, teacher_embed)
            loss = criterion(student_embed, teacher_embed.detach())

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        if epoch % 10 == 0 or epoch == 1:
            avg_loss = total_loss / len(loader)
            print(f"  Epoch [{epoch:>4}/{args.epochs}]  kd_loss: {avg_loss:.6f}")

    # 모델 저장
    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "student.pth")
    torch.save(
        {
            "state_dict": student.state_dict(),
            "embed_dim": args.embed_dim,
        },
        save_path,
    )
    print(f"[저장] Student 모델 저장 완료: {save_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Student CNN Knowledge Distillation 학습 스크립트"
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="X_benign.npy 가 위치한 디렉터리 경로 (예: ./data/auth-service/)",
    )
    parser.add_argument(
        "--teacher",
        type=str,
        required=True,
        help="학습된 teacher.pth 경로 (예: ./models/auth-service/teacher.pth)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="학습된 student.pth 를 저장할 디렉터리 (예: ./models/auth-service/)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="학습 epoch 수 (기본: 100)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        dest="batch_size",
        help="미니배치 크기 (기본: 64)",
    )
    parser.add_argument(
        "--embed-dim",
        type=int,
        default=128,
        dest="embed_dim",
        help="embedding 차원 (기본: 128)",
    )

    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
