"""
preprocess_k8s.py — 우리 result/ pcap을 논문 C 파서(.so)로 세션 시퀀스 이미지(npy)화.

■ 정합(train=serve): ServichMesh packet_parser_stack.c 와 동일 로직으로 각 패킷을
  19B 헤더(IP/포트 제외) + 1460B payload = 1479 벡터로 만들고, 세션(5-tuple XOR)별
  최근 5패킷 슬라이딩 윈도우 → (1479, 5) 이미지 emit.
■ 저장: uint8(0-255) raw. 마스킹은 학습/시각화 로드 시 data_utils(MASK_TRANSPORT)로 토글(=ablation).
■ 레이아웃/매핑(논문 아이디어):
  benign : result/benign/benign_<svc>.pcap           (auth/post/comment=req-port 8080, frontend/mysql=full)
  test   : result/test/benign/benign_<svc>.pcap
  attack : brute      → auth 모델용 (req-port 8080, auth 엔드포인트 공격)
           enum+manip → "앱 pod의 K8s API egress = 이탈" 세트(:443, full) — 전 서비스 공통 평가용

사용: cd training && bash build_parser.sh && python preprocess_k8s.py
"""
import ctypes
import os

import numpy as np
import dpkt

HERE = os.path.dirname(os.path.abspath(__file__))
SO = os.path.join(HERE, "packet_parser_stack.so")
RESULT = os.path.join(HERE, "..", "result")

# packet_parser_stack.c 상수와 반드시 일치
VEC_LEN, WIN_SIZE, MAX_SESSIONS = 1479, 5, 65536

BENIGN = {  # svc: (pcap basename, request_port(None=full))
    "auth":     ("benign_auth",     8080),
    "post":     ("benign_post",     8080),
    "comment":  ("benign_comment",  8080),
    "frontend": ("benign_frontend", None),
    "mysql":    ("benign_mysql",    None),
}
ATTACK = {  # name: ([basenames], request_port)
    "brute": (["attack_brute"], 8080),                      # auth 모델용
    "k8s":   (["attack_enum", "attack_manipulate"], None),  # 이탈 세트(전 서비스)
}

CAP_BENIGN, CAP_TEST, CAP_ATTACK = 60000, 30000, 30000

C = ctypes.CDLL(SO)
C.parse_and_stack.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_float), ctypes.c_uint32]
C.parse_and_stack.restype = ctypes.c_int
C.init_session_storage.restype = ctypes.c_int


def frame_info(buf: bytes):
    """(session_id, dst_port) 또는 None(비 IPv4/TCP/짧은 프레임). C 파서 오프셋 규약과 동일."""
    if len(buf) < 54 or buf[12] != 0x08 or buf[13] != 0x00 or buf[23] != 6:
        return None
    src_ip = int.from_bytes(buf[26:30], "big"); dst_ip = int.from_bytes(buf[30:34], "big")
    src_port = int.from_bytes(buf[34:36], "big"); dst_port = int.from_bytes(buf[36:38], "big")
    sid = (src_ip ^ dst_ip ^ src_port ^ dst_port ^ 6) % MAX_SESSIONS
    return sid, dst_port


def pcap_to_images(paths, req_port, cap):
    assert C.init_session_storage() == 0        # 세트마다 세션 초기화(교차오염 방지)
    out = (ctypes.c_float * (WIN_SIZE * VEC_LEN))()
    imgs, sids = [], []
    for p in paths:
        if not os.path.exists(p):
            print(f"  [WARN] 없음: {p}"); continue
        with open(p, "rb") as f:
            for _ts, buf in dpkt.pcap.Reader(f):
                fi = frame_info(buf)
                if fi is None:
                    continue
                sid, dport = fi
                if req_port is not None and dport != req_port:
                    continue
                raw = (ctypes.c_uint8 * len(buf)).from_buffer_copy(buf)
                if C.parse_and_stack(raw, len(buf), out, sid) == 1:
                    arr = np.ctypeslib.as_array(out, shape=(VEC_LEN * WIN_SIZE,)).copy()
                    imgs.append(arr.reshape(VEC_LEN, WIN_SIZE).astype(np.uint8))  # 0-255 raw
                    sids.append(sid)
                    if len(imgs) >= cap:
                        break
        if len(imgs) >= cap:
            print(f"  [cap] {cap} 도달 → 조기 종료")
            break
    if not imgs:
        return np.empty((0, VEC_LEN, WIN_SIZE), np.uint8), np.empty((0,), np.int64)
    return np.stack(imgs), np.asarray(sids, np.int64)


def save(outdir, name, X, sess):
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, f"X_{name}.npy"), X)
    np.save(os.path.join(outdir, f"sess_{name}.npy"), sess)
    print(f"  → X_{name} {X.shape} sessions={len(np.unique(sess)) if len(sess) else 0}")


def main():
    if not os.path.exists(SO):
        raise SystemExit(f"[ERROR] {SO} 없음 → 먼저 `bash build_parser.sh`")
    print(f"[parser] {SO}  VEC_LEN={VEC_LEN} WIN={WIN_SIZE}")

    for svc, (base, rp) in BENIGN.items():
        d = os.path.join(HERE, "data", svc)
        print(f"[{svc}] benign (req_port={rp})")
        Xb, sb = pcap_to_images([os.path.join(RESULT, "benign", base + ".pcap")], rp, CAP_BENIGN)
        save(d, "benign", Xb, sb)
        print(f"[{svc}] test benign")
        Xt, st = pcap_to_images([os.path.join(RESULT, "test", "benign", base + ".pcap")], rp, CAP_TEST)
        save(d, "testbenign", Xt, st)

    ad = os.path.join(HERE, "data", "_attack")
    for aname, (bases, rp) in ATTACK.items():
        paths = [os.path.join(RESULT, "test", "attack", b + ".pcap") for b in bases]
        print(f"[attack:{aname}] req_port={rp} files={bases}")
        Xa, sa = pcap_to_images(paths, rp, CAP_ATTACK)
        save(ad, aname, Xa, sa)

    print("[done] training/data/<svc>/{X_benign,X_testbenign} + training/data/_attack/{X_brute,X_k8s}")


if __name__ == "__main__":
    main()
