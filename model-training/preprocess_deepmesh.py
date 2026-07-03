"""
pcap → (VEC_LEN, WIN_SIZE) 세션 시퀀스 이미지 전처리 (원본 C 파서 정합 버전)

논문: Lightweight Service Mesh for Intrusion Detection using KD-CNN

■ 왜 재작성했나 (CLAUDE.md §3 / develop.md §2-10)
  기존 버전은 bytes(pkt) 전체(IP/TCP 헤더 + IP/포트)를 pkt_len 으로 잘라 stride 윈도우를
  만들었다 → IP/포트가 픽셀로 혼입(모델이 "누가"를 외움) + 세션 개념 없음 → 런타임과 불일치.

■ 이 버전
  런타임 프록시(proxy_detection.py)와 **동일한 packet_parser_stack.so 를 ctypes 로 호출**한다.
    - 각 패킷을 19B 헤더(IP/포트 제외) + payload 로 변환
    - 세션(5-tuple XOR)별로 최근 WIN_SIZE 패킷을 슬라이딩 윈도우로 쌓아 이미지 emit
  → 전처리·추론이 같은 코드/같은 패딩 규칙을 공유하므로 학습-추론이 정합한다.
  payload 길이(resize) 도 .so 를 어떻게 빌드했느냐로 자동 반영된다(VEC_LEN getter).

사용법:
    # 먼저 파서 빌드 (예: 기본 1479, 또는 -DPAYLOAD_LEN=512 로 resize)
    gcc -shared -fPIC -O2 -o packet_parser_stack.so \
        ../servicemesh/proxy/packet_parser_stack.c
    python preprocess_deepmesh.py \
        --benign ./pcap/auth*.pcap --attack ./pcap/attacks/auth*.pcap \
        --out ./data/auth-service/ --parser-so ./packet_parser_stack.so
"""

import argparse
import ctypes
import glob
import json
import os
import struct
import sys

import numpy as np
from tqdm import tqdm

try:
    from scapy.all import rdpcap
except ImportError:
    print("[ERROR] scapy 미설치. pip install scapy 후 재시도.")
    sys.exit(1)

IPPROTO_TCP = 6


class Parser:
    """packet_parser_stack.so ctypes 래퍼 (런타임과 동일 로직)."""

    def __init__(self, so_path: str):
        if not os.path.exists(so_path):
            print(f"[ERROR] .so 없음: {so_path}. 먼저 gcc 로 빌드하세요.")
            sys.exit(1)
        self.c = ctypes.CDLL(so_path)
        for fn in ("get_vec_len", "get_win_size", "get_max_sessions",
                   "init_session_storage", "reset_session"):
            getattr(self.c, fn).restype = ctypes.c_int
        self.VEC_LEN = self.c.get_vec_len()
        self.WIN_SIZE = self.c.get_win_size()
        self.MAX_SESSIONS = self.c.get_max_sessions()
        self.c.parse_and_stack.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_uint32,
        ]
        self.c.parse_and_stack.restype = ctypes.c_int
        assert self.c.init_session_storage() == 0

    def session_id(self, frame: bytes) -> int | None:
        if len(frame) < 54 or frame[12] != 0x08 or frame[13] != 0x00 or frame[23] != IPPROTO_TCP:
            return None
        src_ip = int.from_bytes(frame[26:30], "big")
        dst_ip = int.from_bytes(frame[30:34], "big")
        src_port = struct.unpack("!H", frame[34:36])[0]
        dst_port = struct.unpack("!H", frame[36:38])[0]
        return (src_ip ^ dst_ip ^ src_port ^ dst_port ^ IPPROTO_TCP) % self.MAX_SESSIONS

    def frame_to_image(self, frame: bytes):
        """반환: (VEC_LEN, WIN_SIZE) float32 이미지(정규화됨) 또는 None(미충족/비TCP)."""
        sid = self.session_id(frame)
        if sid is None:
            return None
        out = (ctypes.c_float * (self.WIN_SIZE * self.VEC_LEN))()
        buf = (ctypes.c_uint8 * len(frame)).from_buffer_copy(frame)
        if self.c.parse_and_stack(buf, len(frame), out, sid) != 1:
            return None
        arr = np.ctypeslib.as_array(out, shape=(self.VEC_LEN * self.WIN_SIZE,)).copy()
        arr = arr.reshape(self.VEC_LEN, self.WIN_SIZE).astype(np.float32) / 255.0
        return arr


def pcap_to_images(pcap_files: list, parser: Parser) -> np.ndarray:
    images = []
    for path in tqdm(pcap_files, desc="pcap 처리", unit="file"):
        try:
            packets = rdpcap(path)
        except Exception as e:
            print(f"  [WARN] {path} 읽기 실패: {e}")
            continue
        for pkt in packets:
            img = parser.frame_to_image(bytes(pkt))
            if img is not None:
                images.append(img)
    if not images:
        return np.empty((0, parser.VEC_LEN, parser.WIN_SIZE), dtype=np.float32)
    return np.stack(images, axis=0)  # (N, VEC_LEN, WIN_SIZE)


def expand_globs(patterns: list) -> list:
    files = []
    for p in patterns:
        m = sorted(glob.glob(p))
        if not m:
            print(f"  [WARN] 매칭 없음: {p}")
        files.extend(m)
    return files


def main():
    ap = argparse.ArgumentParser(description="pcap → 세션 시퀀스 이미지(.npy) (C 파서 정합)")
    ap.add_argument("--benign", nargs="+", required=True, metavar="PCAP")
    ap.add_argument("--attack", nargs="*", default=[], metavar="PCAP")
    ap.add_argument("--out", required=True, metavar="DIR")
    ap.add_argument("--parser-so", required=True, metavar="SO",
                    help="packet_parser_stack.so 경로 (런타임과 동일 빌드여야 함)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    parser = Parser(args.parser_so)
    print(f"[INFO] VEC_LEN={parser.VEC_LEN}, WIN_SIZE={parser.WIN_SIZE} (parser={args.parser_so})")

    benign_files = expand_globs(args.benign)
    attack_files = expand_globs(args.attack) if args.attack else []
    if not benign_files:
        print("[ERROR] benign pcap 없음.")
        sys.exit(1)

    print("=== Benign ===")
    X_benign = pcap_to_images(benign_files, parser)
    y_benign = np.zeros(len(X_benign), dtype=np.int64)
    np.save(os.path.join(args.out, "X_benign.npy"), X_benign)
    np.save(os.path.join(args.out, "y_benign.npy"), y_benign)
    print(f"  X_benign {X_benign.shape}")

    X_attack = np.empty((0, parser.VEC_LEN, parser.WIN_SIZE), dtype=np.float32)
    if attack_files:
        print("=== Attack ===")
        # 세션 버퍼가 benign 과 섞이지 않도록 재초기화
        parser.c.init_session_storage()
        X_attack = pcap_to_images(attack_files, parser)
        np.save(os.path.join(args.out, "X_attack.npy"), X_attack)
        np.save(os.path.join(args.out, "y_attack.npy"), np.ones(len(X_attack), dtype=np.int64))
        print(f"  X_attack {X_attack.shape}")

    stats = {
        "vec_len": parser.VEC_LEN, "win_size": parser.WIN_SIZE,
        "n_benign": int(len(X_benign)), "n_attack": int(len(X_attack)),
        "benign_files": len(benign_files), "attack_files": len(attack_files),
        "note": "학습 시 (N,1,VEC_LEN,WIN_SIZE) 로 reshape. 런타임 proxy_detection._to_image 와 동일.",
    }
    with open(os.path.join(args.out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
