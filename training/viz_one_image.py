"""
viz_one_image.py — "하나의 이미지 = 연속 5패킷(각 1479 바이트 벡터)이 열로 합쳐진 1장"임을 보여준다.

왼쪽:  같은 세션의 패킷 5개를 '따로' (사이 간격 있게) — 각 패킷 = 1479 벡터(1열)
오른쪽: 그 5열을 간격 없이 이어붙인 (1479, 5) 이미지 = 모델 입력 1장(the model input unit)

전처리 파서는 viz_attack_sessions.py(= packet_parser_stack.c 포팅) 재사용.
사용: cd training && python viz_one_image.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from viz_attack_sessions import pcap_to_images, pick_representative, VEC_LEN, WIN_SIZE, RESULT

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "one_image_5cols.png")


def main():
    # enum 세션 하나를 예시로 사용 (대표 = 가장 꽉 찬 세션, 결정적)
    path = os.path.join(RESULT, "test", "attack", "attack_enum.pcap")
    X = pcap_to_images(path, req_port=None)
    if len(X) == 0:
        raise SystemExit("[ERROR] attack_enum.pcap 에서 이미지를 만들지 못했습니다.")
    img = X[pick_representative(X)]          # (1479, 5) uint8: 열=패킷 p1..p5

    fig = plt.figure(figsize=(11, 6.4))
    gs = fig.add_gridspec(1, 2, width_ratios=[5, 2], wspace=0.28)
    fig.suptitle("One image = 5 consecutive packets stacked as columns  (1479 x 5, grayscale)",
                 fontsize=13)

    # ── 왼쪽: 패킷 5개를 '따로' 그리기 (열 사이 흰 간격) ─────────────────
    axL = fig.add_subplot(gs[0, 0])
    gap = 1                                   # 열 사이 간격(빈 칸)
    stride = 1 + gap
    canvas = np.full((VEC_LEN, WIN_SIZE * stride - gap), np.nan)  # nan=간격(흰색)
    for c in range(WIN_SIZE):
        canvas[:, c * stride] = img[:, c]
    axL.imshow(canvas, cmap="gray_r", aspect="auto", vmin=0, vmax=255,
               interpolation="nearest")
    axL.set_title("5 packets, separately  (each = one 1479-byte vector)", fontsize=10)
    axL.set_xticks([c * stride for c in range(WIN_SIZE)])
    axL.set_xticklabels([f"packet {c+1}" for c in range(WIN_SIZE)])
    axL.axhline(18.5, color="#e53e3e", lw=1.2)
    axL.set_yticks([0, 19, VEC_LEN - 1]); axL.set_yticklabels(["0", "19", str(VEC_LEN - 1)])
    axL.set_ylabel("byte  (0-18: header,  19-1478: payload)")

    # ── 오른쪽: 간격 없이 이어붙인 1장 = 모델 입력 ──────────────────────
    axR = fig.add_subplot(gs[0, 1])
    axR.imshow(img, cmap="gray_r", aspect="auto", vmin=0, vmax=255, interpolation="nearest")
    axR.set_title("combined -> 1 image\n(the model input unit)", fontsize=10)
    for c in range(1, WIN_SIZE):
        axR.axvline(c - 0.5, color="#3b82f6", lw=0.8, alpha=0.7)
    axR.axhline(18.5, color="#e53e3e", lw=1.2)
    axR.set_xticks(range(WIN_SIZE)); axR.set_xticklabels([f"p{c+1}" for c in range(WIN_SIZE)])
    axR.set_xlabel("5 packets (w=5)")
    axR.set_yticks([0, 19, VEC_LEN - 1]); axR.set_yticklabels(["0", "19", str(VEC_LEN - 1)])

    # 가운데 화살표(합쳐짐)
    fig.text(0.605, 0.5, "=>", fontsize=26, ha="center", va="center", color="#444")

    fig.text(0.5, 0.01,
             f"model input tensor shape: (1, {VEC_LEN}, {WIN_SIZE})  "
             "=  (channel, byte, packet)",
             ha="center", fontsize=9, color="#666")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(OUT, dpi=130)
    print(f"[done] -> {OUT}   img shape={img.shape} dtype={img.dtype}")


if __name__ == "__main__":
    main()
