"""학습 이미지 로딩, 세션 분할, 증강 유틸.

배열은 (N, VEC_LEN, WIN_SIZE), 모델 입력은 (N, 1, VEC_LEN, WIN_SIZE)다."""

import os

import numpy as np
import torch
from torch.utils.data import Dataset

from student_cnn import WIN_SIZE


# raw-byte 헤더의 window/urgptr/seq/ack 행. 런타임과 같은 마스킹을 적용한다.
MASK_ROWS = list(range(7, 19))


def mask_transport_enabled() -> bool:
    return os.environ.get("MASK_TRANSPORT", "1").strip().lower() not in ("0", "false", "no", "off", "")


_mask_logged = False


def apply_transport_mask(X: np.ndarray) -> np.ndarray:
    """7~18행을 0으로 만든다. MASK_TRANSPORT=0이면 적용하지 않는다."""
    if getattr(X, "ndim", 0) == 3 and X.shape[1] <= 18:
        return X
    global _mask_logged
    on = mask_transport_enabled()
    if not _mask_logged:
        print(f"[마스킹] 전송계층(window/urgptr/seq/ack, rows 7-18) 마스킹 = {'ON' if on else 'OFF'} (MASK_TRANSPORT)")
        _mask_logged = True
    if not on:
        return X
    X = X.copy()
    X[:, MASK_ROWS, :] = 0.0
    return X


def load_windows(data_dir: str, name: str = "X_benign.npy", limit: int | None = None) -> np.ndarray:
    """(N, VEC_LEN, WIN_SIZE) float32 배열을 로드하고 축과 값을 정규화한다.
    limit을 지정하면 앞에서부터 해당 개수만 사용한다."""
    path = os.path.join(data_dir, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{name} 를 찾을 수 없습니다: {path}")
    X = np.load(path).astype(np.float32)
    if limit is not None and limit > 0:
        X = X[:limit]
    if X.ndim != 3:
        raise ValueError(f"기대 shape (N, VEC_LEN, WIN_SIZE), got {X.shape}")
    # 윈도우 축을 마지막으로
    if X.shape[2] != WIN_SIZE and X.shape[1] == WIN_SIZE:
        X = np.transpose(X, (0, 2, 1))
    X = np.nan_to_num(X)
    if X.max() > 1.5:  # 0~255 저장값 정규화
        X = np.clip(X, 0, 255) / 255.0
    else:
        X = np.clip(X, 0.0, 1.0)
    X = apply_transport_mask(X)
    return X


def group_val_mask(groups: np.ndarray, val_frac: float, seed: int = 42) -> np.ndarray:
    """세션별 검증 마스크를 반환한다(True=val). 같은 세션은 한쪽에만 배정한다."""
    n = len(groups)
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    rng.shuffle(uniq)
    n_val = max(1, int(round(len(uniq) * val_frac)))
    val_set = set(uniq[:n_val].tolist())
    return np.fromiter((g in val_set for g in groups), dtype=bool, count=n)


def to_tensor(X: np.ndarray) -> torch.Tensor:
    """(N, VEC_LEN, WIN_SIZE)에 채널 축을 추가한다."""
    return torch.from_numpy(X).unsqueeze(1).contiguous()


def augment(x: np.ndarray, sigma: float = 0.01) -> np.ndarray:
    """가우시안 노이즈를 더하고 0~1로 제한한다."""
    return np.clip(x + np.random.normal(0, sigma, x.shape).astype(np.float32), 0.0, 1.0)


class BenignImages(Dataset):
    """KD/OCSVM용 (1, VEC_LEN, WIN_SIZE) 샘플."""

    def __init__(self, data_dir: str, limit: int | None = None):
        self.data = load_windows(data_dir, limit=limit)
        print(f"[데이터] {self.data.shape} from {os.path.join(data_dir, 'X_benign.npy')}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> torch.Tensor:
        return torch.from_numpy(self.data[idx]).unsqueeze(0)  # (1, VEC_LEN, WIN_SIZE)


class ContrastiveImages(Dataset):
    """같은 이미지에서 두 증강 샘플을 만든다."""

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
