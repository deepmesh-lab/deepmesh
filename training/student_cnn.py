"""
모델 정의 — 논문 원본(train_k8s_*.py) 아키텍처에 정합.

입력 규약(중요): **(B, 1, VEC_LEN, WIN_SIZE)** = (B, 1, 275, 5) (resize 후).
  - 런타임 프록시(proxy_detection._to_image)의 (1,1,VEC_LEN,WIN_SIZE) 와 동일 축.
  - AdaptiveAvgPool 로 끝나므로 VEC_LEN(payload resize) 이 바뀌어도 구조 변경 불필요.

원본 대응:
  - Student: 1x8 / 2x8(train_k8s_2x8) / 2x16(train_k8s_2x16).
  - Teacher: shallow(train_k8s.Encoder, ~314K) / deep(train_k8s_deep.Encoderv2, ~743K).
  - L2 정규화(toggle): 논문은 임베딩 L2 정규화를 사용(NT-Xent 내부). 여기서는 forward 출력에
    F.normalize 를 적용하는 옵션으로 노출 → OCSVM 이 단위구면에서 각도 마진(저마진/저스케일 완화).
    기본 OFF(논문 배포 기본과 동일: 인코더 출력은 raw). --l2 로 ablation.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

WIN_SIZE = 5
DEFAULT_VEC_LEN = 1479
FEAT_DIM = 128


def _maybe_norm(z: torch.Tensor, l2: bool) -> torch.Tensor:
    return F.normalize(z, dim=1) if l2 else z


# ─────────────────────────── Student ───────────────────────────

class StudentEncoder(nn.Module):
    """1x8 (원본 train_k8s_1x8.py). Conv(1→8)+ReLU → AdaptiveAvgPool((1,1)) → Linear(8,out)."""

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
    """2x8 (원본 train_k8s_2x8.py). Conv(1→4)+BN → Conv(4→8) → AAP(2,2) → Linear(32→32)+BN+Drop → Linear(32,out)."""

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
    """2x16 (원본 train_k8s_2x16.py). Conv(1→8)+BN → Conv(8→16) → AAP(2,2) → Linear(64→64)+BN+Drop → Linear(64,out)."""

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
    """1x16 (원본 train_k8s_1x16.py). Conv(1→16) → AAP(2,2) → Linear(64→64) → Linear(64,out). (BN 없음)  ~12.64K"""

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
    """2x32 (원본 train_k8s_2x32.py). Conv(1→16)+BN → Conv(16→32) → AAP(4,4) → Linear(512→128)+BN+Drop → Linear(128,out).  ~87.26K"""

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
    """'1x8' | '1x16' | '2x8' | '2x16' | '2x32' (논문 Table 5 전체)."""
    table = {
        "1x8":  StudentEncoder,      # ~1.23K
        "1x16": StudentEncoder1x16,  # ~12.64K
        "2x8":  StudentEncoder2x8,   # ~5.69K (배포 모델)
        "2x16": StudentEncoder2x16,  # ~13.87K
        "2x32": StudentEncoder2x32,  # ~87.26K
    }
    a = arch.lower()
    if a not in table:
        raise ValueError(f"unknown student arch: {arch} (지원: {', '.join(table)})")
    return table[a](out_dim, l2)


# ─────────────────────────── Teacher ───────────────────────────

class TeacherShallow(nn.Module):
    """원본 train_k8s.Encoder (얕은 교사, ~314K). 2x16/2x8 student 의 실제 교사."""

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
    """원본 train_k8s_deep.Encoderv2 (deep, ~3.31M). 입력 (B,1,VEC_LEN,WIN_SIZE).
    ⚠️ 논문 Table 5 headline teacher(CNN-4x128, 743.52K)는 repo에 없음 — shallow(314K)/deep(3.31M)만 존재.
       KD 비교 목적엔 어느 쪽이든 무방하나 학생 5종 스윕은 동일 teacher 고정 권장(sweep_sizes.py)."""

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
    """'shallow'(원본 2x16 교사) | 'deep'(원본 Encoderv2)."""
    arch = arch.lower()
    if arch == "shallow":
        return TeacherShallow(out_dim, l2)
    if arch == "deep":
        return TeacherEncoder(out_dim, l2)
    raise ValueError(f"unknown teacher arch: {arch} (지원: shallow, deep)")
