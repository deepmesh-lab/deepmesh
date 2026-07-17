"""
viz_attack_sessions.py — attack_session_images_5x1479.png(논문 그림) 재현.

논문 그림은 공격 기법별로 "세션 이미지 1장 = 한 세션의 연속 5패킷 (1479 x 5, grayscale)"
을 나란히 보여준다. 우리 result/ pcap으로 동일 전처리(packet_parser_stack.c 로직)를
파이썬으로 그대로 재현해, 우리가 보유한 기법(enum/manipulate/brute)만 panel로 그린다.
(escape/remote 는 논문 repo 전용 pcap이라 우리 데이터엔 없음 → 재현 대상 아님.)

전처리 정합(train=serve): packet_parser_stack.c / preprocess_k8s.py 와 동일.
  - 각 패킷 → 19B 헤더(IP/포트 제외) + 1460B payload = 1479 벡터
  - 세션(5-tuple XOR)별 최근 5패킷 슬라이딩 윈도우 → (1479, 5) 이미지 emit
사용: cd training && python viz_attack_sessions.py
"""
import os
import numpy as np
import dpkt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(HERE, "..", "result")
OUT = os.path.join(HERE, "..", "attack_session_images_ours_3x1479.png")

VEC_LEN, WIN_SIZE, MAX_SESSIONS = 1479, 5, 65536

# name: ([pcap basenames], request_port(None=full), 제목) — preprocess_k8s.ATTACK 와 정합
TECHNIQUES = [
    ("attack_enum",       None, "enum (T1613)"),
    ("attack_manipulate", None, "manipulate (T1609)"),
    ("attack_brute",      8080, "brute-force (T1110)"),
]


def frame_info(buf: bytes):
    """(session_id, dst_port) — C 파서/preprocess_k8s 와 동일 오프셋 규약. 비 IPv4/TCP면 None."""
    if len(buf) < 54 or buf[12] != 0x08 or buf[13] != 0x00 or buf[23] != 6:
        return None
    src_ip = int.from_bytes(buf[26:30], "big"); dst_ip = int.from_bytes(buf[30:34], "big")
    src_port = int.from_bytes(buf[34:36], "big"); dst_port = int.from_bytes(buf[36:38], "big")
    sid = (src_ip ^ dst_ip ^ src_port ^ dst_port ^ 6) % MAX_SESSIONS
    return sid, dst_port


def parse_tcp_packet(raw: bytes):
    """packet_parser_stack.c::parse_tcp_packet 파이썬 포팅 → (1479,) float 벡터 또는 None."""
    n = len(raw)
    if n < 54:
        return None
    ttl = raw[22]; proto = raw[23]
    flags_frag = (raw[20] << 8) | raw[21]
    ip_flags = (flags_frag >> 13) & 0x7
    frag_offset = flags_frag & 0x1FFF
    tcp_off = 34
    if n < tcp_off + 20:
        return None
    data_offset = (raw[tcp_off + 12] >> 4) & 0xF
    flags = raw[tcp_off + 13]
    window = (raw[tcp_off + 14] << 8) | raw[tcp_off + 15]
    urgptr = (raw[tcp_off + 18] << 8) | raw[tcp_off + 19]
    seq = raw[tcp_off + 4: tcp_off + 8]
    ack = raw[tcp_off + 8: tcp_off + 12]
    payload_start = tcp_off + data_offset * 4
    payload = raw[payload_start:] if payload_start < n else b""

    vec = np.zeros(VEC_LEN, dtype=np.float32)
    hdr = [ttl, proto, ip_flags, (frag_offset >> 8) & 0xFF, frag_offset & 0xFF,
           data_offset, flags, (window >> 8) & 0xFF, window & 0xFF,
           (urgptr >> 8) & 0xFF, urgptr & 0xFF]
    vec[0:11] = hdr
    vec[11:15] = list(seq)
    vec[15:19] = list(ack)
    plen = min(len(payload), 1460)
    if plen:
        vec[19:19 + plen] = np.frombuffer(payload[:plen], dtype=np.uint8).astype(np.float32)
    return vec


def pcap_to_images(path, req_port, cap=30000):
    """(N, 1479, 5) uint8 세션 이미지 스택. C 파서 sliding-window(count>=5→emit) 로직 재현."""
    if not os.path.exists(path):
        print(f"  [WARN] 없음: {path}")
        return np.empty((0, VEC_LEN, WIN_SIZE), np.uint8)
    buffers = {}   # sid -> list of vecs (최근 5개 유지)
    imgs = []
    with open(path, "rb") as f:
        for _ts, buf in dpkt.pcap.Reader(f):
            fi = frame_info(buf)
            if fi is None:
                continue
            sid, dport = fi
            if req_port is not None and dport != req_port:
                continue
            vec = parse_tcp_packet(buf)
            if vec is None:
                continue
            win = buffers.setdefault(sid, [])
            win.append(vec)
            if len(win) > WIN_SIZE:
                del win[0]
            if len(win) == WIN_SIZE:
                img = np.stack(win, axis=1)          # (1479, 5): 열=패킷, 행=바이트
                imgs.append(np.clip(img, 0, 255).astype(np.uint8))
                if len(imgs) >= cap:
                    break
    if not imgs:
        return np.empty((0, VEC_LEN, WIN_SIZE), np.uint8)
    return np.stack(imgs)


def pick_representative(X):
    """대표 이미지 1장: 콘텐츠 있는 패킷 열이 가장 많고(=꽉 찬 세션), 동률이면 총합 큰 것. 결정적."""
    payload = X[:, 19:, :].astype(np.int64)          # payload 영역만
    cols_used = (payload.sum(axis=1) > 0).sum(axis=1)   # 이미지별 non-empty 패킷 열 수
    total = payload.sum(axis=(1, 2))
    score = cols_used * (total.max() + 1) + total       # cols 우선, total 보조
    return int(np.argmax(score))


def main():
    panels = []
    for base, rp, title in TECHNIQUES:
        path = os.path.join(RESULT, "test", "attack", base + ".pcap")
        X = pcap_to_images(path, rp)
        print(f"[{title}] {base}.pcap (req_port={rp}) → images={X.shape}")
        if len(X) == 0:
            continue
        idx = pick_representative(X)
        panels.append((title, X[idx], len(X), idx))

    if not panels:
        raise SystemExit("[ERROR] 생성된 이미지가 없습니다. result/test/attack/*.pcap 확인.")

    fig, axes = plt.subplots(1, len(panels), figsize=(3.0 * len(panels), 6.2))
    if len(panels) == 1:
        axes = [axes]
    fig.suptitle("One image = one session's 5 consecutive packets  "
                 "(1479 x 5, grayscale) = the model input unit", fontsize=13)

    for ax, (title, img, n, idx) in zip(axes, panels):
        ax.imshow(img, cmap="gray_r", aspect="auto", vmin=0, vmax=255,
                  interpolation="nearest")
        ax.set_title(title, fontsize=11)
        # 패킷 열 경계(파란 세로선) + p1..p5 라벨
        for c in range(1, WIN_SIZE):
            ax.axvline(c - 0.5, color="#3b82f6", lw=0.8, alpha=0.7)
        ax.set_xticks(range(WIN_SIZE))
        ax.set_xticklabels([f"p{c+1}" for c in range(WIN_SIZE)])
        ax.set_xlabel("5 packets (w=5)")
        # 헤더(0-18) 경계 표시: 상단 빨간 밴드 + 19 눈금
        ax.axhline(18.5, color="#e53e3e", lw=1.2)
        ax.set_yticks([0, 19, VEC_LEN - 1])
        ax.set_yticklabels(["0", "19", str(VEC_LEN - 1)])

    axes[0].set_ylabel("byte (0-18: header, 19-1478: payload)")
    fig.text(0.5, 0.005,
             "escape / remote: paper-repo-only pcaps (not in our data) -> excluded",
             ha="center", fontsize=8, color="#666")
    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    plt.savefig(OUT, dpi=130)
    print(f"[done] → {OUT}")
    for title, _img, n, idx in panels:
        print(f"   {title:22} 대표 idx={idx}  (전체 {n} 세션 이미지 중)")


if __name__ == "__main__":
    main()
