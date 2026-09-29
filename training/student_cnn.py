"""Student·Teacher CNN 인코더.

입력은 (B, 1, VEC_LEN, WIN_SIZE)이며 semantic은 (B, 1, 20, 5),
raw-byte는 (B, 1, 1479, 5). l2=True이면 출력을 L2 정규화한다."""

import torch
import torch.nn as nn
import torch.nn.functional as F

WIN_SIZE = 5
DEFAULT_VEC_LEN = 20      # semantic 특징 수
FEAT_DIM = 128


def _maybe_norm(z: torch.Tensor, l2: bool) -> torch.Tensor:
    return F.normalize(z, dim=1) if l2 else z


class StudentEncoder(nn.Module):
    """1x8: Conv 1층, 8채널, 풀링 1×1."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 8, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)), nn.Flatten(),
            nn.Linear(8, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


class StudentEncoder2x8(nn.Module):
    """2x8: Conv 2층(4→8채널), 풀링 2×2."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 4, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(4),
            nn.Conv2d(4, 8, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((2, 2)), nn.Flatten(),
            nn.Linear(8 * 2 * 2, 32), nn.ReLU(),
            nn.BatchNorm1d(32), nn.Dropout(0.3),
            nn.Linear(32, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


class StudentEncoder2x16(nn.Module):
    """2x16: Conv 2층(8→16채널), 풀링 2×2."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 8, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(8),
            nn.Conv2d(8, 16, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((2, 2)), nn.Flatten(),
            nn.Linear(16 * 2 * 2, 64), nn.ReLU(),
            nn.BatchNorm1d(64), nn.Dropout(0.3),
            nn.Linear(64, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


class StudentEncoder1x16(nn.Module):
    """1x16: Conv 1층, 16채널, 풀링 2×2."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((2, 2)), nn.Flatten(),
            nn.Linear(16 * 2 * 2, 64), nn.ReLU(),
            nn.Linear(64, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


class StudentEncoder2x32(nn.Module):
    """2x32: Conv 2층(16→32채널), 풀링 4×4."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(16),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
            nn.Linear(32 * 4 * 4, 128), nn.ReLU(),
            nn.BatchNorm1d(128), nn.Dropout(0.3),
            nn.Linear(128, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


def make_student(arch: str = "2x8", out_dim: int = FEAT_DIM, l2: bool = False) -> nn.Module:
    """아키텍처 이름으로 Student를 생성한다."""
    table = {
        "1x8":  StudentEncoder,
        "1x16": StudentEncoder1x16,
        "2x8":  StudentEncoder2x8,
        "2x16": StudentEncoder2x16,
        "2x32": StudentEncoder2x32,
    }
    a = arch.lower()
    if a not in table:
        raise ValueError(f"unknown student arch: {arch} (지원: {', '.join(table)})")
    return table[a](out_dim, l2)


class TeacherShallow(nn.Module):
    """Conv 2층(32→64채널) Teacher."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(32),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
            nn.Linear(64 * 4 * 4, 256), nn.ReLU(),
            nn.BatchNorm1d(256), nn.Dropout(0.3),
            nn.Linear(256, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


class TeacherEncoder(nn.Module):
    """Conv 6층(64→128→256채널) Teacher."""

    def __init__(self, out_dim: int = FEAT_DIM, l2: bool = False):
        super().__init__()
        self.l2 = l2
        self.net = nn.Sequential(
            nn.Conv2d(1, 64, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(64),
            nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(64),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(128),
            nn.Conv2d(128, 128, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(128),

            nn.Conv2d(128, 256, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(256),
            nn.Conv2d(256, 256, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(256),

            nn.AdaptiveAvgPool2d((4, 4)), nn.Flatten(),
            nn.Linear(256 * 4 * 4, 512), nn.ReLU(),
            nn.BatchNorm1d(512), nn.Dropout(0.4),
            nn.Linear(512, out_dim),
        )

    def forward(self, x): return _maybe_norm(self.net(x), self.l2)


def make_teacher(arch: str = "deep", out_dim: int = FEAT_DIM, l2: bool = False) -> nn.Module:
    """shallow 또는 deep Teacher를 생성한다."""
    arch = arch.lower()
    if arch == "shallow":
        return TeacherShallow(out_dim, l2)
    if arch == "deep":
        return TeacherEncoder(out_dim, l2)
    raise ValueError(f"unknown teacher arch: {arch} (지원: shallow, deep)")
