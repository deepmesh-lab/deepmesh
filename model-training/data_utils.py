"""
학습용 데이터 로딩/증강 유틸 — 논문 규약 (B, 1, VEC_LEN, WIN_SIZE) 정합.

preprocess_deepmesh 는 X_benign.npy 를 (N, VEC_LEN, WIN_SIZE) 로 저장한다(이미 /255).
여기서는 채널 축을 붙여 (N, 1, VEC_LEN, WIN_SIZE) 텐서를 만든다.
과거 (N, WIN_SIZE, VEC_LEN) 방향으로 저장된 경우도 자동 교정한다.
"""

import os

import numpy as np
import torch
from torch.utils.data import Dataset

from student_cnn import WIN_SIZE


def load_windows(data_dir: str, name: str = "X_benign.npy", limit: int | None = None) -> np.ndarray:
    """(N, VEC_LEN, WIN_SIZE) float32 배열 로드(방향 자동 교정, 값은 그대로 사용).

    limit 지정 시 앞에서부터 limit개만 사용(CPU 학습 속도 조절용).
    """
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{name} 를 찾을 수 없습니다: {path}")
    X = np.load(path).astype(np.float32)
    if limit is not None and limit > 0:
        X = X[:limit]
    if X.ndim != 3:
        raise ValueError(f"기대 shape (N, VEC_LEN, WIN_SIZE), got {X.shape}")
    # 마지막 축이 WIN_SIZE(=5) 가 아니고 가운데 축이 5면 transpose 로 교정
    if X.shape[2] != WIN_SIZE and X.shape[1] == WIN_SIZE:
        X = np.transpose(X, (0, 2, 1))
    # 안전 클리핑(전처리에서 /255 되어 있으나 방어적으로 0~1 보장)
    X = np.nan_to_num(X)
    if X.max() > 1.5:  # 혹시 0~255 로 저장된 경우
        X = np.clip(X, 0, 255) / 255.0
    else:
        X = np.clip(X, 0.0, 1.0)
    return X


def to_tensor(X: np.ndarray) -> torch.Tensor:
    """(N, VEC_LEN, WIN_SIZE) → (N, 1, VEC_LEN, WIN_SIZE) float32 텐서."""
    return torch.from_numpy(X).unsqueeze(1).contiguous()


def augment(x: np.ndarray, sigma: float = 0.01) -> np.ndarray:
    """원본 대조학습 증강: 가우시안 노이즈 + [0,1] 클립 (구조 파괴적 셔플 없음)."""
    return np.clip(x + np.random.normal(0, sigma, x.shape).astype(np.float32), 0.0, 1.0)


class BenignImages(Dataset):
    """KD/OCSVM 용: (1, VEC_LEN, WIN_SIZE) 샘플을 그대로 반환(증강 없음)."""

    def __init__(self, data_dir: str, limit: int | None = None):
        self.data = load_windows(data_dir, limit=limit)
        print(f"[데이터] {self.data.shape} from {os.path.join(data_dir, 'X_benign.npy')}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> torch.Tensor:
        return torch.from_numpy(self.data[idx]).unsqueeze(0)  # (1, VEC_LEN, WIN_SIZE)


class ContrastiveImages(Dataset):
    """Teacher 대조학습용: 같은 샘플에서 두 augmented view (각 (1,VEC_LEN,WIN_SIZE)) 반환."""

    def __init__(self, data_dir: str, sigma: float = 0.01, limit: int | None = None):
        self.data = load_windows(data_dir, limit=limit)
        self.sigma = sigma
        print(f"[데이터] {self.data.shape} from {os.path.join(data_dir, 'X_benign.npy')}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int):
        x = self.data[idx]
        v1 = torch.from_numpy(augment(x, self.sigma)).unsqueeze(0)
        v2 = torch.from_numpy(augment(x, self.sigma)).unsqueeze(0)
        return v1, v2
