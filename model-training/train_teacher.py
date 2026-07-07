"""
Teacher CNN NT-Xent Contrastive Learning 학습 스크립트

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
학습 방식: Self-supervised Contrastive Learning (NT-Xent Loss)
입력: (B, 5, 1479) float32 — 정상 트래픽(benign)만 사용
"""

import argparse
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


# ---------------------------------------------------------------------------
# 모델 정의
# ---------------------------------------------------------------------------

class TeacherCNN(nn.Module):
    """
    Self-supervised Contrastive Learning용 Teacher CNN.

    Input:  (B, 5, 1479)  — 채널 차원 unsqueeze 후 (B, 1, 5, 1479) 로 처리
    Output: (B, embed_dim) — L2 정규화된 embedding 벡터
    """

    def __init__(self, embed_dim: int = 128):
        super().__init__()

        # Conv 블록 1: (B, 1, 5, 1479) → (B, 32, 5, 245)
        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=(1, 7), stride=(1, 3)),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )

        # Conv 블록 2: → (B, 64, 5, 30)
        self.conv2 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=(1, 5), stride=(1, 2)),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )

        # Conv 블록 3: → (B, 128, 5, 32) (AdaptiveAvgPool 으로 고정)
        self.conv3 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=(1, 3), stride=(1, 1)),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((5, 32)),
        )

        # Projection head: flatten → linear → L2 normalize
        self.fc = nn.Linear(5 * 32 * 128, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (B, 5, 1479) → (B, 1, 5, 1479)
        x = x.unsqueeze(1)

        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)

        x = x.flatten(1)           # (B, 5*32*128)
        x = self.fc(x)             # (B, embed_dim)
        x = F.normalize(x, dim=1)  # L2 정규화
        return x


# ---------------------------------------------------------------------------
# NT-Xent Loss
# ---------------------------------------------------------------------------

def nt_xent_loss(
    z_i: torch.Tensor,
    z_j: torch.Tensor,
    temperature: float = 0.5,
) -> torch.Tensor:
    """
    NT-Xent (Normalized Temperature-scaled Cross Entropy) Loss.

    Args:
        z_i: (B, embed_dim) — view 1 의 L2 정규화 embedding
        z_j: (B, embed_dim) — view 2 의 L2 정규화 embedding
        temperature: softmax 온도 파라미터 (기본 0.5)

    Returns:
        scalar loss tensor
    """
    B = z_i.size(0)

    # (2B, embed_dim) 로 concat
    z = torch.cat([z_i, z_j], dim=0)  # (2B, D)

    # cosine similarity matrix: (2B, 2B)
    # z 는 이미 L2 정규화됐으므로 matmul = cosine similarity
    sim = torch.mm(z, z.T) / temperature  # (2B, 2B)

    # 자기 자신과의 유사도 제거를 위한 마스크
    mask = torch.eye(2 * B, dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(mask, float('-inf'))

    # positive pair 인덱스
    # z_i[k] 의 positive 는 z_j[k] → 인덱스 k+B
    # z_j[k] 의 positive 는 z_i[k] → 인덱스 k
    labels = torch.cat([
        torch.arange(B, 2 * B, device=z.device),
        torch.arange(0, B, device=z.device),
    ])  # (2B,)

    loss = F.cross_entropy(sim, labels)
    return loss


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

def _augment(x: np.ndarray) -> torch.Tensor:
    """
    단일 샘플 (5, 1479) 에 대한 augmentation.
    1. 가우시안 노이즈 추가 (std=0.02)
    2. 패킷(열) 순서 랜덤 셔플
    """
    x = x.copy().astype(np.float32)

    # 1) 가우시안 노이즈
    x += np.random.normal(0, 0.02, x.shape).astype(np.float32)

    # 2) 패킷 순서 섞기 (열 방향: axis=1 → 1479 방향)
    perm = np.random.permutation(x.shape[1])
    x = x[:, perm]

    return torch.from_numpy(x)


class AugmentedDataset(Dataset):
    """
    X_benign.npy 를 로드하고 매 호출마다 독립적인 두 augmented view 를 반환.

    Args:
        data_dir: X_benign.npy 가 위치한 디렉터리 경로
    """

    def __init__(self, data_dir: str):
        npy_path = os.path.join(data_dir, "X_benign.npy")
        if not os.path.exists(npy_path):
            raise FileNotFoundError(f"X_benign.npy 를 찾을 수 없습니다: {npy_path}")

        self.data = np.load(npy_path)  # (N, 5, 1479)
        print(f"[데이터] 로드 완료: {self.data.shape} from {npy_path}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int):
        x = self.data[idx]  # (5, 1479)
        view1 = _augment(x)
        view2 = _augment(x)
        return view1, view2


# ---------------------------------------------------------------------------
# 학습 루프
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[학습] 디바이스: {device}")

    # 데이터셋 / DataLoader
    dataset = AugmentedDataset(args.data)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        drop_last=True,
    )

    # 모델 / Optimizer
    model = TeacherCNN(embed_dim=args.embed_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    print(f"[학습] epochs={args.epochs}, batch_size={args.batch_size}, "
          f"embed_dim={args.embed_dim}, temperature={args.temperature}")

    model.train()
    for epoch in range(1, args.epochs + 1):
        total_loss = 0.0
        for view1, view2 in loader:
            view1 = view1.to(device)
            view2 = view2.to(device)

            z_i = model(view1)
            z_j = model(view2)

            loss = nt_xent_loss(z_i, z_j, temperature=args.temperature)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        if epoch % 10 == 0 or epoch == 1:
            avg_loss = total_loss / len(loader)
            print(f"  Epoch [{epoch:>4}/{args.epochs}]  loss: {avg_loss:.6f}")

    # 모델 저장
    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "teacher.pth")
    torch.save(
        {
            "state_dict": model.state_dict(),
            "embed_dim": args.embed_dim,
        },
        save_path,
    )
    print(f"[저장] Teacher 모델 저장 완료: {save_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teacher CNN NT-Xent Contrastive Learning 학습 스크립트"
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="X_benign.npy 가 위치한 디렉터리 경로 (예: ./data/auth-service/)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="학습된 teacher.pth 를 저장할 디렉터리 (예: ./models/auth-service/)",
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
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.5,
        help="NT-Xent 온도 파라미터 (기본: 0.5)",
    )

    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
