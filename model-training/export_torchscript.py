"""
TorchScript 내보내기 스크립트

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
목적: 학습된 Student CNN을 TorchScript (.pt) 형식으로 변환
      Sidecar Proxy (C/Python 혼합) 환경에서 Python 없이 추론 가능
변환 방식: torch.jit.trace — 더미 입력 (1, 5, 1479) 으로 trace
"""

import argparse
import os

import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------------------------------------------------------------------------
# Student 모델 정의 (로드용)
# ---------------------------------------------------------------------------

class StudentCNN(nn.Module):
    """
    Knowledge Distillation용 Student CNN (CNN-2x16).

    Input:  (B, 5, 1479)  — 채널 차원 unsqueeze 후 (B, 1, 5, 1479) 로 처리
    Output: (B, embed_dim) — L2 정규화된 embedding 벡터
    """

    def __init__(self, embed_dim: int = 128):
        super().__init__()

        self.conv1 = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=(1, 7), stride=(1, 3)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=(1, 2)),
        )
        self.conv2 = nn.Sequential(
            nn.Conv2d(16, 16, kernel_size=(1, 5), stride=(1, 2)),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((5, 16)),
        )
        self.fc = nn.Linear(5 * 16 * 16, embed_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.unsqueeze(1)
        x = self.conv1(x)
        x = self.conv2(x)
        x = x.flatten(1)
        x = self.fc(x)
        x = F.normalize(x, dim=1)
        return x


# ---------------------------------------------------------------------------
# 내보내기 메인
# ---------------------------------------------------------------------------

def export(args: argparse.Namespace) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[내보내기] 디바이스: {device}")

    # Student 로드
    ckpt = torch.load(args.student, map_location=device)
    embed_dim = ckpt.get("embed_dim", 128)
    model = StudentCNN(embed_dim=embed_dim).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    print(f"[Student] 로드 완료: {args.student} (embed_dim={embed_dim})")

    # 더미 입력 생성: (1, 5, 1479)
    dummy_input = torch.zeros(1, 5, 1479, device=device)

    # TorchScript trace 변환
    print("[TorchScript] torch.jit.trace 변환 중...")
    with torch.no_grad():
        traced_model = torch.jit.trace(model, dummy_input)
    print("[TorchScript] 변환 완료")

    # 저장
    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "student_ts.pt")
    traced_model.save(save_path)
    print(f"[저장] TorchScript 모델 저장 완료: {save_path}")

    # 검증: 로드 후 더미 입력으로 forward 통과 확인
    print("[검증] TorchScript 모델 로드 및 forward 검증 중...")
    loaded_model = torch.jit.load(save_path, map_location=device)
    loaded_model.eval()

    with torch.no_grad():
        verify_input = torch.zeros(1, 5, 1479, device=device)
        output = loaded_model(verify_input)

    print(f"[검증] forward 통과 완료: output shape={tuple(output.shape)}, "
          f"L2 norm={output.norm(dim=1).item():.6f}")

    # 원본 모델과 출력 비교
    with torch.no_grad():
        original_output = model(dummy_input)
    max_diff = (output - original_output).abs().max().item()
    print(f"[검증] 원본 모델 대비 최대 오차: {max_diff:.2e}")

    if max_diff < 1e-5:
        print("[검증] PASS — TorchScript 변환이 정확합니다.")
    else:
        print(f"[경고] 변환 오차가 큽니다 (max_diff={max_diff:.2e}). 확인이 필요합니다.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Student CNN TorchScript 내보내기 스크립트"
    )
    parser.add_argument(
        "--student",
        type=str,
        required=True,
        help="학습된 student.pth 경로 (예: ./models/auth-service/student.pth)",
    )
    parser.add_argument(
        "--out",
        type=str,
        required=True,
        help="student_ts.pt 를 저장할 디렉터리 (예: ./models/auth-service/)",
    )

    args = parser.parse_args()
    export(args)


if __name__ == "__main__":
    main()
