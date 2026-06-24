"""
StudentCNN (CNN-2x16) — Knowledge Distillation Student Model

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
구조: Conv(1→16) + Conv(16→16) + AdaptiveAvgPool + Linear + L2 norm
파라미터 수: ~13.87K (Teacher 대비 경량화)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class StudentCNN(nn.Module):
    """
    Knowledge Distillation용 Student CNN (CNN-2x16).

    Input:  (B, 5, 1479)  — 채널 차원 unsqueeze 후 (B, 1, 5, 1479) 로 처리
    Output: (B, embed_dim) — L2 정규화된 embedding 벡터

    구조:
      Conv 블록 1: Conv2d(1, 16, k=(1,7), s=(1,3)) → BN → ReLU → MaxPool2d((1,2))
      Conv 블록 2: Conv2d(16, 16, k=(1,5), s=(1,2)) → BN → ReLU → AdaptiveAvgPool2d((5,16))
      Flatten → Linear(5*16*16=1280, embed_dim) → L2 Normalize
    """

    def __init__(self, embed_dim: int = 128):
        super().__init__()

        # Conv 블록 1: (B, 1, 5, 1479) → (B, 16, 5, ?)
        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=(1, 7), stride=(1, 3)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )

        # Conv 블록 2: → AdaptiveAvgPool로 (B, 16, 5, 16) 고정
        self.conv2 = nn.Sequential(
            nn.Conv2d(16, 16, kernel_size=(1, 5), stride=(1, 2)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((5, 16)),
        )

        # Projection head: 5*16*16=1280 → embed_dim → L2 normalize
        self.fc = nn.Linear(5 * 16 * 16, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # (B, 5, 1479) → (B, 1, 5, 1479)
        x = x.unsqueeze(1)

        x = self.conv1(x)
        x = self.conv2(x)

        x = x.flatten(1)           # (B, 5*16*16=1280)
        x = self.fc(x)             # (B, embed_dim)
        x = F.normalize(x, dim=1)  # L2 정규화
        return x
