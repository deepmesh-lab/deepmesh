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


# ─────────────────────────────────────────────────────────────────────
# 전송계층 confound 마스킹 (토글) — 자세한 근거: 프로젝트 루트 masking.md
#
# 헤더 19B 레이아웃(C 파서 packet_parser_stack.c 순서):
#   0 ttl | 1 proto | 2 ip_flags | 3-4 frag_offset | 5 data_offset | 6 tcp_flags
#   7-8 window | 9-10 urgptr | 11-14 seq | 15-18 ack | 19~ payload
#
# 마스킹 대상 = window(7-8) + urgptr(9-10) + seq(11-14) + ack(15-18) = rows 7..18.
#   - window: TCP 흐름제어 상태(응답크기/부하/OS 의존) → 우리 동질 환경에선 공격의미 아닌 confound.
#     (헤더만으로 AUC 0.91; window 제거 시 0.63으로 급락)
#   - seq/ack: 연결별 랜덤 순번(신호 0, 분산 큼) → OCSVM 마진 교란·암기 유발.
#   - 유지 = ttl/proto/ip_flags/frag/data_offset/tcp_flags(rows 0-6) + payload → 내용 기반 학습.
#
# ⚠️ 런타임(proxy_detection._to_image)과 반드시 동일해야 함(train/serve 정합).
# 토글: 환경변수 MASK_TRANSPORT (기본 "1"=마스킹 ON, "0"/"false"=OFF, ablation용).
MASK_ROWS = list(range(7, 19))  # window+urgptr+seq+ack


def mask_transport_enabled() -> bool:
    return os.environ.get("MASK_TRANSPORT", "1").strip().lower() not in ("0", "false", "no", "off", "")


_mask_logged = False


def apply_transport_mask(X: np.ndarray) -> np.ndarray:
    """(N, VEC_LEN, WIN_SIZE) 에서 전송계층 confound 행(7-18)을 0 으로. MASK_TRANSPORT=0 이면 무변경."""
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
    X = apply_transport_mask(X)  # 전송계층 confound 마스킹(토글)
    return X


def group_val_mask(groups: np.ndarray, val_frac: float, seed: int = 42) -> np.ndarray:
    """세션(group) 단위 train/val 분할용 boolean val 마스크.

    슬라이딩 윈도우 near-duplicate가 train/val 에 갈라져 들어가는 누수를 막기 위해, 같은 세션의
    윈도우는 통째로 한쪽에만 배정한다. 반환: val_mask(True=val). groups=None 이면 랜덤 분할로 폴백.
    """
    n = len(groups)
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    rng.shuffle(uniq)
    n_val = max(1, int(round(len(uniq) * val_frac)))
    val_set = set(uniq[:n_val].tolist())
    return np.fromiter((g in val_set for g in groups), dtype=bool, count=n)


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
