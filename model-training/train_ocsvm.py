"""
OneClassSVM 학습 스크립트

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN
학습 방식: Student CNN embedding을 feature로 사용한 One-Class SVM 이상 탐지
           benign 데이터만으로 학습 (one-class classification)
입력: X_benign.npy + 학습된 student.pth
"""

import argparse
import os
import sys

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.svm import OneClassSVM
from torch.utils.data import Dataset, DataLoader

from student_cnn import StudentCNN


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

class BenignDataset(Dataset):
    """
    X_benign.npy 를 로드해 float32 텐서로 반환.

    Args:
        data_dir: X_benign.npy 가 위치한 디렉터리 경로
    """

    def __init__(self, data_dir: str):
        npy_path = os.path.join(data_dir, "X_benign.npy")
        if not os.path.exists(npy_path):
            raise FileNotFoundError(f"X_benign.npy 를 찾을 수 없습니다: {npy_path}")

        self.data = np.load(npy_path).astype(np.float32)  # (N, 5, 1479)
        print(f"[데이터] 로드 완료: {self.data.shape} from {npy_path}")

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> torch.Tensor:
        return torch.from_numpy(self.data[idx])


# ---------------------------------------------------------------------------
# Embedding 추출
# ---------------------------------------------------------------------------

def extract_embeddings(
    student: nn.Module,
    loader: DataLoader,
    device: torch.device,
    batch_size: int = 256,
) -> np.ndarray:
    """
    Student CNN으로 전체 데이터셋의 embedding 추출.

    Returns:
        embeddings: (N, embed_dim) float32 numpy 배열
    """
    student.eval()
    all_embeds = []

    with torch.no_grad():
        for x in loader:
            x = x.to(device)
            embed = student(x)
            all_embeds.append(embed.cpu().numpy())

    return np.concatenate(all_embeds, axis=0)


# ---------------------------------------------------------------------------
# 학습 메인
# ---------------------------------------------------------------------------

def train(args: argparse.Namespace) -> None:
    # 경로 검증
    if not os.path.exists(args.data):
        print(f"[오류] --data 경로가 존재하지 않습니다: {args.data}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.student):
        print(f"[오류] --student 경로가 존재하지 않습니다: {args.student}", file=sys.stderr)
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[학습] 디바이스: {device}")

    # Student 로드
    ckpt = torch.load(args.student, map_location=device)
    embed_dim = ckpt.get("embed_dim", 128)
    student = StudentCNN(embed_dim=embed_dim).to(device)
    student.load_state_dict(ckpt["state_dict"])
    student.eval()
    print(f"[Student] 로드 완료: {args.student} (embed_dim={embed_dim})")

    # 데이터셋 / DataLoader
    dataset = BenignDataset(args.data)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    # Embedding 추출
    print("[Embedding] Student CNN으로 benign embedding 추출 중...")
    embeddings = extract_embeddings(student, loader, device, batch_size=args.batch_size)
    print(f"[Embedding] 추출 완료: {embeddings.shape}")

    # OneClassSVM 학습
    print("[OCSVM] 학습 중... (kernel=rbf, gamma=scale, nu=0.05)")
    ocsvm = OneClassSVM(kernel="rbf", gamma="scale", nu=0.05)
    ocsvm.fit(embeddings)
    print("[OCSVM] 학습 완료")

    # 자기 자신 예측으로 false positive rate 확인
    # OneClassSVM: +1 = 정상, -1 = 이상
    preds = ocsvm.predict(embeddings)
    n_total = len(preds)
    n_anomaly = np.sum(preds == -1)
    fp_rate = n_anomaly / n_total * 100
    print(f"[검증] benign 샘플 {n_total}개 중 {n_anomaly}개 이상 분류")
    print(f"[검증] False Positive Rate: {fp_rate:.2f}%")

    # OCSVM 저장
    os.makedirs(args.out, exist_ok=True)
    save_path = os.path.join(args.out, "ocsvm.pkl")
    joblib.dump(ocsvm, save_path)
    print(f"[저장] OCSVM 모델 저장 완료: {save_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="OneClassSVM 학습 스크립트 — Student embedding 기반 이상 탐지"
    )
    parser.add_argument(
        "--data",
        type=str,
        required=True,
        help="X_benign.npy 가 위치한 디렉터리 경로 (예: ./data/auth-service/)",
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
        help="학습된 ocsvm.pkl 을 저장할 디렉터리 (예: ./models/auth-service/)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=256,
        dest="batch_size",
        help="embedding 추출 시 배치 크기 (기본: 256)",
    )

    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
