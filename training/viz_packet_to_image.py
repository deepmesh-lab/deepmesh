"""
viz_packet_to_image.py — "1 packet = 1479 bytes, 각 byte(0~255) = 회색 픽셀 하나" 개념 시각화.

benign 패킷 1개 / attack 패킷 1개를 뽑아:
  (a) 1479 바이트를 세로 1열로 픽셀화한 '패킷 이미지'
  (b) payload 앞부분 바이트를 확대해 '바이트 값(0~255) -> 회색 픽셀' 대응을 숫자로 표기
       (비트 0/1 이 아니라 바이트 값 단위임을 강조)

파서는 viz_attack_sessions.py(= packet_parser_stack.c 포팅) 재사용.
사용: cd training && python viz_packet_to_image.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from viz_attack_sessions import pcap_to_images, VEC_LEN, RESULT

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packet_to_image_benign_attack.png")
ZOOM = 24   # payload 앞 몇 바이트를 확대해 값 표기할지


def one_packet(pcap_rel, req_port):
    """pcap에서 세션 이미지 하나 뽑고, 그 중 '콘텐츠가 가장 많은 패킷 열' 1개(1479 벡터)를 반환."""
    path = os.path.join(RESULT, pcap_rel)
    X = pcap_to_images(path, req_port)
    if len(X) == 0:
        raise SystemExit(f"[ERROR] {path} 에서 이미지 생성 실패")
    # payload 콘텐츠가 가장 풍부한 (이미지, 패킷열) 선택
    payload_sum = X[:, 19:, :].astype(np.int64).sum(axis=1)   # (N, 5)
    n, c = np.unravel_index(int(np.argmax(payload_sum)), payload_sum.shape)
    return X[n, :, c].astype(np.uint8)                        # (1479,)


def draw_column(ax, vec, title):
    """1479 바이트를 세로 1열 픽셀 이미지로."""
    ax.imshow(vec.reshape(-1, 1), cmap="gray_r", aspect="auto", vmin=0, vmax=255,
              interpolation="nearest")
    ax.set_title(title, fontsize=11)
    ax.axhline(18.5, color="#e53e3e", lw=1.2)   # 헤더/payload 경계
    ax.set_xticks([])
    ax.set_yticks([0, 19, VEC_LEN - 1]); ax.set_yticklabels(["0", "19", str(VEC_LEN - 1)])


def draw_zoom(ax, vec, title):
    """payload 앞 ZOOM 바이트를 가로로 확대 + 각 셀에 바이트 값(0~255) 표기."""
    seg = vec[19:19 + ZOOM].astype(int)
    ax.imshow(seg.reshape(1, -1), cmap="gray_r", aspect="auto", vmin=0, vmax=255,
              interpolation="nearest")
    for i, v in enumerate(seg):
        ax.text(i, 0, str(v), ha="center", va="center", fontsize=7,
                color="white" if v > 140 else "black")
    ax.set_title(title, fontsize=9)
    ax.set_yticks([]); ax.set_xticks(range(0, ZOOM, 4))
    ax.set_xlabel(f"payload byte #19 ~ #{19+ZOOM-1}  (each cell = 1 byte value 0~255 = 1 gray pixel)",
                  fontsize=8)


def main():
    vb = one_packet("test/benign/benign_frontend.pcap", None)   # benign
    va = one_packet("test/attack/attack_enum.pcap", None)       # attack(k8s egress)

    fig = plt.figure(figsize=(11, 7))
    gs = fig.add_gridspec(2, 2, width_ratios=[1, 1], height_ratios=[6, 1.1],
                          hspace=0.35, wspace=0.25)
    fig.suptitle("1 packet = 1479 bytes;  each byte (0~255) -> one grayscale pixel "
                 "(256 shades, NOT a 0/1 bit)", fontsize=12)

    draw_column(fig.add_subplot(gs[0, 0]), vb, "benign packet  (frontend)")
    draw_column(fig.add_subplot(gs[0, 1]), va, "attack packet  (k8s enum)")
    draw_zoom(fig.add_subplot(gs[1, 0]), vb, "benign payload (zoom)")
    draw_zoom(fig.add_subplot(gs[1, 1]), va, "attack payload (zoom)")

    fig.text(0.5, 0.005,
             "left col of each = the whole 1479-byte packet as a 1-pixel-wide image; "
             "bottom = zoom of first 24 payload bytes with their values",
             ha="center", fontsize=8, color="#666")
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])
    plt.savefig(OUT, dpi=130)
    print(f"[done] -> {OUT}")
    print(f"  benign payload[19:19+8] = {vb[19:27].tolist()}")
    print(f"  attack payload[19:19+8] = {va[19:27].tolist()}")


if __name__ == "__main__":
    main()
