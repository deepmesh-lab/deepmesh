"""
viz_benign_sessions.py — test/benign pcap을 서비스별로 '대표 세션 이미지 1장'씩 뽑아 시각화.

산출 2종 (attack 쪽 viz와 동일 포맷):
  1) benign_test_session_images_5svc.png  — 서비스 5개 panel(각 = 대표 (1479,5) gray 이미지)
  2) benign_one_image_5cols.png           — 한 서비스 이미지를 '5열이 합쳐진 1장'으로 해부

전처리 파서는 viz_attack_sessions.py(= packet_parser_stack.c 포팅) 재사용.
서비스/req_port 매핑은 preprocess_k8s.BENIGN 과 정합.
사용: cd training && python viz_benign_sessions.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from viz_attack_sessions import pcap_to_images, pick_representative, VEC_LEN, WIN_SIZE, RESULT

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_OUT = os.path.join(HERE, "..", "benign_test_session_images_5svc.png")
ONE_OUT = os.path.join(HERE, "..", "benign_one_image_5cols.png")

# svc: (pcap basename, request_port(None=full)) — preprocess_k8s.BENIGN 정합
SERVICES = [
    ("auth",     "benign_auth",     8080),
    ("post",     "benign_post",     8080),
    ("comment",  "benign_comment",  8080),
    ("frontend", "benign_frontend", None),
    ("mysql",    "benign_mysql",    None),
]
DEMO_SVC = "frontend"   # 5열 해부 데모에 쓸 서비스(full 트래픽이라 콘텐츠 풍부)


def collect():
    """각 서비스에서 대표 이미지 1장 추출. 반환: [(svc, img(1479,5), n_total, idx), ...]"""
    panels = []
    for svc, base, rp in SERVICES:
        path = os.path.join(RESULT, "test", "benign", base + ".pcap")
        X = pcap_to_images(path, rp)
        print(f"[{svc}] {base}.pcap (req_port={rp}) -> images={X.shape}")
        if len(X) == 0:
            continue
        idx = pick_representative(X)
        panels.append((svc, X[idx], len(X), idx))
    return panels


def style_axis(ax):
    """공통 축 스타일: 패킷 경계 파란선, 헤더 경계 빨간선, y 눈금."""
    for c in range(1, WIN_SIZE):
        ax.axvline(c - 0.5, color="#3b82f6", lw=0.8, alpha=0.7)
    ax.axhline(18.5, color="#e53e3e", lw=1.2)
    ax.set_xticks(range(WIN_SIZE))
    ax.set_xticklabels([f"p{c+1}" for c in range(WIN_SIZE)])
    ax.set_xlabel("5 packets (w=5)")
    ax.set_yticks([0, 19, VEC_LEN - 1])
    ax.set_yticklabels(["0", "19", str(VEC_LEN - 1)])


def make_panel(panels):
    fig, axes = plt.subplots(1, len(panels), figsize=(3.0 * len(panels), 6.2))
    if len(panels) == 1:
        axes = [axes]
    fig.suptitle("test/benign — one representative session image per service  "
                 "(1479 x 5, grayscale)", fontsize=13)
    for ax, (svc, img, n, idx) in zip(axes, panels):
        ax.imshow(img, cmap="gray_r", aspect="auto", vmin=0, vmax=255, interpolation="nearest")
        ax.set_title(svc, fontsize=11)
        style_axis(ax)
    axes[0].set_ylabel("byte  (0-18: header,  19-1478: payload)")
    plt.tight_layout(rect=[0, 0.0, 1, 0.96])
    plt.savefig(PANEL_OUT, dpi=130)
    print(f"[done] -> {PANEL_OUT}")


def make_one_image(panels):
    """DEMO_SVC 이미지 하나를 '패킷 5개 따로' vs '합친 1장'으로 해부 (one_image_5cols 포맷)."""
    match = [p for p in panels if p[0] == DEMO_SVC] or panels
    svc, img, n, idx = match[0]

    fig = plt.figure(figsize=(11, 6.4))
    gs = fig.add_gridspec(1, 2, width_ratios=[5, 2], wspace=0.28)
    fig.suptitle(f"benign '{svc}': one image = 5 consecutive packets stacked as columns  "
                 "(1479 x 5)", fontsize=13)

    # 왼쪽: 패킷 5개 따로 (열 사이 흰 간격)
    axL = fig.add_subplot(gs[0, 0])
    gap, stride = 1, 2
    canvas = np.full((VEC_LEN, WIN_SIZE * stride - gap), np.nan)
    for c in range(WIN_SIZE):
        canvas[:, c * stride] = img[:, c]
    axL.imshow(canvas, cmap="gray_r", aspect="auto", vmin=0, vmax=255, interpolation="nearest")
    axL.set_title("5 packets, separately  (each = one 1479-byte vector)", fontsize=10)
    axL.set_xticks([c * stride for c in range(WIN_SIZE)])
    axL.set_xticklabels([f"packet {c+1}" for c in range(WIN_SIZE)])
    axL.axhline(18.5, color="#e53e3e", lw=1.2)
    axL.set_yticks([0, 19, VEC_LEN - 1]); axL.set_yticklabels(["0", "19", str(VEC_LEN - 1)])
    axL.set_ylabel("byte  (0-18: header,  19-1478: payload)")

    # 오른쪽: 합친 1장
    axR = fig.add_subplot(gs[0, 1])
    axR.imshow(img, cmap="gray_r", aspect="auto", vmin=0, vmax=255, interpolation="nearest")
    axR.set_title("combined -> 1 image\n(the model input unit)", fontsize=10)
    style_axis(axR)

    fig.text(0.605, 0.5, "=>", fontsize=26, ha="center", va="center", color="#444")
    fig.text(0.5, 0.01,
             f"model input tensor shape: (1, {VEC_LEN}, {WIN_SIZE})  =  (channel, byte, packet)",
             ha="center", fontsize=9, color="#666")
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(ONE_OUT, dpi=130)
    print(f"[done] -> {ONE_OUT}   ({svc}, idx={idx} of {n})")


def main():
    panels = collect()
    if not panels:
        raise SystemExit("[ERROR] 생성된 이미지가 없습니다. result/test/benign/*.pcap 확인.")
    make_panel(panels)
    make_one_image(panels)
    print("\n[summary] 서비스별 대표 이미지:")
    for svc, _img, n, idx in panels:
        print(f"   {svc:10} idx={idx}  (전체 {n} 세션 이미지 중)")


if __name__ == "__main__":
    main()
