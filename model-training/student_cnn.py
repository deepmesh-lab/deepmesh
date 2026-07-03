"""
모델 정의 — 논문 원본(train_k8s_1x8.py) 아키텍처에 정합.

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN

입력 규약(중요): **(B, 1, VEC_LEN, WIN_SIZE)** = (B, 1, 1479, 5)
  - 런타임 프록시(proxy_detection._to_image)의 (1,1,VEC_LEN,WIN_SIZE) 와 동일 축.
  - preprocess_deepmesh 는 (N, VEC_LEN, WIN_SIZE) 로 저장 → 채널 unsqueeze 로 (B,1,VEC_LEN,WIN_SIZE).
  - AdaptiveAvgPool 로 끝나므로 VEC_LEN(payload resize) 이 바뀌어도 구조 변경 불필요.

원본과의 정합:
  - StudentEncoder(1x8): Conv(1→8,3x3)+ReLU → AdaptiveAvgPool((1,1)) → Linear(8, out_dim).
    **L2 정규화 없음**(원본 그대로). OCSVM 이 raw feature 위에서 학습.
  - TeacherEncoder(deep, 원본 Encoderv2): 대조학습(NT-Xent)용 교사.
"""

import torch
import torch.nn as nn

WIN_SIZE = 5
DEFAULT_VEC_LEN = 1479
FEAT_DIM = 128


class StudentEncoder(nn.Module):
    """원본 train_k8s_1x8.py 의 StudentEncoder (1x8). 입력 (B,1,VEC_LEN,WIN_SIZE)."""

    def __init__(self, out_dim: int = FEAT_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(1, 8, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(8, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class TeacherEncoder(nn.Module):
    """원본 Encoderv2 (deep). 대조학습용 교사. 입력 (B,1,VEC_LEN,WIN_SIZE)."""

    def __init__(self, out_dim: int = FEAT_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(1, 64, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(64),
            nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(64),
            nn.MaxPool2d(2),

            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(128),
            nn.Conv2d(128, 128, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(128),

            nn.Conv2d(128, 256, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(256),
            nn.Conv2d(256, 256, 3, padding=1), nn.ReLU(), nn.BatchNorm2d(256),

            nn.AdaptiveAvgPool2d((4, 4)),
            nn.Flatten(),
            nn.Linear(256 * 4 * 4, 512), nn.ReLU(),
            nn.BatchNorm1d(512), nn.Dropout(0.4),
            nn.Linear(512, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
