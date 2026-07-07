"""
TorchScript 내보내기 스크립트

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
목적: 학습된 Student CNN을 TorchScript (.pt) 형식으로 변환
      Sidecar Proxy (C/Python 혼합) 환경에서 Python 없이 추론 가능
변환 방식: torch.jit.trace — 더미 입력 (1, 5, 1479) 으로 trace
"""

import argparse
import os
import sys

import torch

from student_cnn import StudentCNN


# ---------------------------------------------------------------------------
# 내보내기 메인
# ---------------------------------------------------------------------------

def export(args: argparse.Namespace) -> None:
    # 경로 검증
    if not os.path.exists(args.student):
        print(f"[오류] --student 경로가 존재하지 않습니다: {args.student}", file=sys.stderr)
        sys.exit(1)

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
