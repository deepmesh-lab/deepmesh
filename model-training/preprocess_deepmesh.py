"""
pcap → 5×1479 이미지 시퀀스 전처리 스크립트
논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN

사용법:
    python preprocess_deepmesh.py \
        --benign ./pcap/auth*.pcap \
        --attack ./pcap/attacks/auth*.pcap \
        --out ./data/auth-service/ \
        [--window 5] \
        [--pkt-len 1479]
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
from tqdm import tqdm

try:
    from scapy.all import rdpcap
except ImportError:
    print("[ERROR] scapy가 설치되지 않았습니다. pip install scapy 실행 후 재시도하세요.")
    sys.exit(1)


def extract_payload(pkt, pkt_len: int) -> np.ndarray:
    """
    패킷에서 pkt_len 바이트 추출.
    - bytes(pkt) 로 raw bytes 획득 (IP 레이어부터)
    - pkt_len 보다 짧으면 0으로 패딩, 길면 잘라냄
    반환값: shape (pkt_len,), dtype uint8
    """
    raw = bytes(pkt)
    length = len(raw)

    if length >= pkt_len:
        payload = np.frombuffer(raw[:pkt_len], dtype=np.uint8)
    else:
        payload = np.zeros(pkt_len, dtype=np.uint8)
        payload[:length] = np.frombuffer(raw, dtype=np.uint8)

    return payload


def pcap_to_windows(pcap_files: list, window_size: int, pkt_len: int) -> np.ndarray:
    """
    pcap 파일 목록 → shape (N, window_size, pkt_len) numpy array.
    - 슬라이딩 윈도우: stride = window_size (겹치지 않음)
    - 패킷 수 < window_size 인 파일은 skip
    - 정규화: float32 / 255.0
    """
    all_windows = []

    for pcap_path in tqdm(pcap_files, desc="pcap 처리 중", unit="file"):
        try:
            packets = rdpcap(pcap_path)
        except Exception as e:
            print(f"  [WARN] {pcap_path} 읽기 실패: {e}")
            continue

        payloads = []
        for pkt in packets:
            payloads.append(extract_payload(pkt, pkt_len))

        n_pkts = len(payloads)
        if n_pkts < window_size:
            print(f"  [SKIP] {pcap_path}: 패킷 수 {n_pkts} < window_size {window_size}")
            continue

        # stride = window_size (비겹침 슬라이딩 윈도우)
        for i in range(0, n_pkts - window_size + 1, window_size):
            window = np.stack(payloads[i : i + window_size], axis=0)  # (window_size, pkt_len)
            all_windows.append(window)

    if len(all_windows) == 0:
        return np.empty((0, window_size, pkt_len), dtype=np.float32)

    arr = np.stack(all_windows, axis=0).astype(np.float32)  # (N, window_size, pkt_len)
    arr /= 255.0
    return arr


def expand_globs(patterns: list) -> list:
    """glob 패턴 리스트를 실제 파일 경로 리스트로 확장"""
    files = []
    for pattern in patterns:
        matched = sorted(glob.glob(pattern))
        if not matched:
            print(f"  [WARN] glob 패턴과 일치하는 파일 없음: {pattern}")
        files.extend(matched)
    return files


def main():
    parser = argparse.ArgumentParser(
        description="pcap 파일을 5×1479 이미지 시퀀스로 변환하여 .npy 저장"
    )
    parser.add_argument(
        "--benign",
        nargs="+",
        required=True,
        metavar="PCAP",
        help="정상 트래픽 pcap 파일 또는 glob 패턴 (예: ./pcap/auth*.pcap)",
    )
    parser.add_argument(
        "--attack",
        nargs="*",
        default=[],
        metavar="PCAP",
        help="공격 트래픽 pcap 파일 또는 glob 패턴 (생략 가능)",
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help="결과물을 저장할 디렉토리",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=5,
        metavar="N",
        help="슬라이딩 윈도우 크기 (default: 5)",
    )
    parser.add_argument(
        "--pkt-len",
        type=int,
        default=1479,
        metavar="BYTES",
        help="패킷당 추출 바이트 수 (default: 1479)",
    )
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    # --- glob 확장 ---
    benign_files = expand_globs(args.benign)
    attack_files = expand_globs(args.attack) if args.attack else []

    print(f"\n[INFO] benign 파일: {len(benign_files)}개")
    print(f"[INFO] attack 파일: {len(attack_files)}개")
    print(f"[INFO] window_size={args.window}, pkt_len={args.pkt_len}")
    print(f"[INFO] 출력 디렉토리: {args.out}\n")

    if len(benign_files) == 0:
        print("[ERROR] benign pcap 파일이 하나도 없습니다. 경로/패턴을 확인하세요.")
        sys.exit(1)

    # --- benign 처리 ---
    print("=== Benign 처리 ===")
    X_benign = pcap_to_windows(benign_files, args.window, args.pkt_len)
    y_benign = np.zeros(len(X_benign), dtype=np.int64)

    np.save(os.path.join(args.out, "X_benign.npy"), X_benign)
    np.save(os.path.join(args.out, "y_benign.npy"), y_benign)
    print(f"  저장 완료: X_benign {X_benign.shape}, y_benign {y_benign.shape}")

    # --- attack 처리 (선택) ---
    X_attack = np.empty((0, args.window, args.pkt_len), dtype=np.float32)
    y_attack = np.empty((0,), dtype=np.int64)

    if attack_files:
        print("\n=== Attack 처리 ===")
        X_attack = pcap_to_windows(attack_files, args.window, args.pkt_len)
        y_attack = np.ones(len(X_attack), dtype=np.int64)

        np.save(os.path.join(args.out, "X_attack.npy"), X_attack)
        np.save(os.path.join(args.out, "y_attack.npy"), y_attack)
        print(f"  저장 완료: X_attack {X_attack.shape}, y_attack {y_attack.shape}")

    # --- train 합치기 & shuffle ---
    print("\n=== Train 데이터셋 생성 ===")
    if len(X_attack) > 0:
        X_train = np.concatenate([X_benign, X_attack], axis=0)
        y_train = np.concatenate([y_benign, y_attack], axis=0)
    else:
        X_train = X_benign.copy()
        y_train = y_benign.copy()

    rng = np.random.default_rng(seed=42)
    idx = rng.permutation(len(X_train))
    X_train = X_train[idx]
    y_train = y_train[idx]

    np.save(os.path.join(args.out, "X_train.npy"), X_train)
    np.save(os.path.join(args.out, "y_train.npy"), y_train)
    print(f"  저장 완료: X_train {X_train.shape}, y_train {y_train.shape}")

    # --- stats.json ---
    stats = {
        "window_size": args.window,
        "pkt_len": args.pkt_len,
        "benign_files": len(benign_files),
        "attack_files": len(attack_files),
        "n_benign_samples": int(len(X_benign)),
        "n_attack_samples": int(len(X_attack)),
        "n_train_samples": int(len(X_train)),
        "output_dir": os.path.abspath(args.out),
    }
    stats_path = os.path.join(args.out, "stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\n[INFO] stats.json 저장: {stats_path}")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
