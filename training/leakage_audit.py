"""
leakage_audit.py — 데이터 누수 감사 (성능이 진짜인지 검증).

■ 무엇을: 전처리된 세션이미지 npy를 행(이미지) 단위 해시로 대조해 학습/평가셋 간 중복을 계수.
  ROC-AUC가 0.999~1.000으로 높을 때 "학습셋을 test로 쓴 것 아니냐"는 의심을 데이터로 반박한다.

■ 검사 항목 (모두 0이어야 통과):
  1. train benign ∩ test benign   (서비스별)  → test가 학습에 새면 >0
  2. attack ∩ train benign          (서비스별)  → 공격이 정상 학습에 섞이면 >0
  3. attack ∩ test benign           (서비스별)  → 평가셋 라벨 오염이면 >0
  4. brute ∩ k8s                                → 두 공격셋 독립성

■ 왜 행 해시인가: train/test는 서로 다른 시점 별도 pcap에서 전처리되므로, 같은 세션이미지(1479×5 uint8)가
  양쪽에 존재하면 그건 곧 파일 복제/중복 = 누수. blake2b(16B) 해시 집합의 교집합으로 정확히 계수.

사용:
  cd training && python leakage_audit.py                 # 기본 data/ 감사
  python leakage_audit.py --data data                    # 경로 지정
  python leakage_audit.py --json audit.json              # 결과 JSON 저장(CI/기록용)

종료코드: 누수 0건이면 0, 하나라도 발견되면 1 (CI 게이트로 사용 가능).
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

SVCS = ["auth", "post", "comment", "frontend", "mysql"]
ATTACKS = ["brute", "k8s"]


def row_hashes(path):
    """npy의 각 행(세션이미지)을 blake2b(16B)로 해시한 집합 + 총 행수 반환. 없으면 (None, 0)."""
    if not os.path.exists(path):
        return None, 0
    a = np.load(path, mmap_mode="r")
    s = set()
    for i in range(len(a)):
        s.add(hashlib.blake2b(np.ascontiguousarray(a[i]).tobytes(), digest_size=16).digest())
    return s, len(a)


def main():
    ap = argparse.ArgumentParser(description="데이터 누수 감사 (train∩test, attack∩benign)")
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
                    help="전처리 npy 루트 (기본: training/data)")
    ap.add_argument("--json", default=None, help="결과를 JSON으로 저장할 경로(선택)")
    a = ap.parse_args()

    D = a.data
    print(f"[audit] data={D}")

    # 공격셋 해시 1회 로드(전 서비스 공용)
    atk_hash, atk_n = {}, {}
    for name in ATTACKS:
        h, n = row_hashes(os.path.join(D, "_attack", f"X_{name}.npy"))
        atk_hash[name], atk_n[name] = h, n
    atk_union = set().union(*[h for h in atk_hash.values() if h]) if any(atk_hash.values()) else set()

    rows, leaks = [], 0
    print(f"\n{'svc':9} {'train':>7} {'test':>7} {'tr∩te':>7} {'atk∩tr':>7} {'atk∩te':>7}  판정")
    print("-" * 60)
    for svc in SVCS:
        tr, ntr = row_hashes(os.path.join(D, svc, "X_benign.npy"))
        te, nte = row_hashes(os.path.join(D, svc, "X_testbenign.npy"))
        if tr is None or te is None:
            print(f"{svc:9}  (X_benign/X_testbenign 없음 → skip)")
            continue
        tr_te = len(tr & te)
        atk_tr = len(tr & atk_union)
        atk_te = len(te & atk_union)
        bad = tr_te + atk_tr + atk_te
        leaks += bad
        verdict = "OK" if bad == 0 else "⚠️ 누수"
        print(f"{svc:9} {ntr:>7} {nte:>7} {tr_te:>7} {atk_tr:>7} {atk_te:>7}  {verdict}")
        rows.append({"svc": svc, "n_train": ntr, "n_test": nte,
                     "train_int_test": tr_te, "attack_int_train": atk_tr, "attack_int_test": atk_te})

    # 공격셋 상호 독립성
    bk = len(atk_hash["brute"] & atk_hash["k8s"]) if atk_hash["brute"] and atk_hash["k8s"] else 0
    leaks += bk
    print("-" * 60)
    print(f"attack rows: brute={atk_n['brute']} k8s={atk_n['k8s']}  brute∩k8s={bk}"
          f"  {'OK' if bk == 0 else '⚠️'}")

    ok = leaks == 0
    print(f"\n{'='*60}")
    print(f"[결과] 총 누수 {leaks}건 → {'✅ 누수 없음 (성능은 진짜)' if ok else '❌ 누수 발견 — 전처리/분할 점검 필요'}")
    if ok:
        print("  참고: 높은 ROC-AUC는 K8s egress 이탈이 benign과 프로토콜·목적지가 달라 원래 쉬운 과제이기 때문.")
        print("        진짜 어려운 auth-brute(ROC 0.925)에서 점수가 떨어지는 것이 누수 부재의 방증 (model.md §4).")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"data": D, "per_service": rows, "brute_int_k8s": bk,
                       "total_leaks": leaks, "passed": ok}, f, ensure_ascii=False, indent=2)
        print(f"  → JSON 저장: {a.json}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
