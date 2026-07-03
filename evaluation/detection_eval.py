"""
end-to-end 탐지 성능 평가

K8s에 배포된 Service Mesh에 실제 트래픽을 보내면서 탐지 성능을 측정한다.
- benign 트래픽 → forward되어야 함 (정상 응답 2xx)
- attack 트래픽 → drop되어야 함 (403 또는 연결 거부)

사용법:
    python detection_eval.py --host http://<NODE_IP>:30080 [--count 100]

공격 엔드포인트:
  --brute-force:      T1110 무차별 대입
  --sql-injection:    T1190 SQL 인젝션
  --path-traversal:   T1083 경로 탐색
  --lateral:          T1021 내부 접근
  --exfil:            T1041 데이터 유출
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

import requests
from requests.exceptions import ConnectionError, Timeout

# ------------------------------------------------------------------
# 결과 디렉토리 (이 스크립트 기준 상대 경로)
# ------------------------------------------------------------------
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


# ------------------------------------------------------------------
# 데이터 모델
# ------------------------------------------------------------------
@dataclass
class TrafficResult:
    traffic_type: str  # "benign" | "attack"
    expected: str      # "forward" | "drop"
    actual: str        # "forward" | "drop"  (2xx=forward, 403/연결거부=drop)
    status_code: int   # HTTP 상태 코드; 연결 거부면 -1
    correct: bool


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------
def _classify_response(
    response: Optional[requests.Response],
    expected: str,
    traffic_type: str,
) -> TrafficResult:
    """requests.Response(또는 None)을 TrafficResult로 변환."""
    if response is None:
        # 연결 거부 = 프록시가 drop한 것으로 간주
        actual = "drop"
        status_code = -1
    elif response.status_code == 403:
        actual = "drop"
        status_code = 403
    elif 200 <= response.status_code < 300:
        actual = "forward"
        status_code = response.status_code
    else:
        # 4xx(403 제외), 5xx는 drop으로 분류
        actual = "drop"
        status_code = response.status_code

    return TrafficResult(
        traffic_type=traffic_type,
        expected=expected,
        actual=actual,
        status_code=status_code,
        correct=(actual == expected),
    )


def _get(host: str, path: str, timeout: int = 5) -> Optional[requests.Response]:
    try:
        return requests.get(f"{host}{path}", timeout=timeout)
    except (ConnectionError, Timeout):
        return None


def _post(
    host: str,
    path: str,
    payload: dict,
    timeout: int = 5,
) -> Optional[requests.Response]:
    try:
        return requests.post(f"{host}{path}", json=payload, timeout=timeout)
    except (ConnectionError, Timeout):
        return None


# ------------------------------------------------------------------
# benign 트래픽
# ------------------------------------------------------------------
def send_benign(host: str, count: int) -> list[TrafficResult]:
    """GET /api/posts 요청을 count회 전송한다.
    2xx → forward (correct), 403/연결거부 → drop (incorrect)
    """
    results: list[TrafficResult] = []
    for i in range(count):
        resp = _get(host, "/api/posts")
        results.append(_classify_response(resp, expected="forward", traffic_type="benign"))
        # 과도한 부하 방지를 위한 최소 딜레이
        time.sleep(0.05)
    return results


# ------------------------------------------------------------------
# attack 트래픽
# ------------------------------------------------------------------
def send_attack(host: str, attack_type: str, count: int) -> list[TrafficResult]:
    """attack_type에 따른 공격 트래픽을 count회 전송한다.
    403/연결거부 → drop (correct), 2xx → forward (incorrect)
    """
    results: list[TrafficResult] = []

    for i in range(count):
        resp: Optional[requests.Response] = None

        if attack_type == "brute_force":
            # T1110 — 무차별 대입: 잘못된 패스워드 반복 POST
            resp = _post(
                host,
                "/api/auth/login",
                {"username": "admin", "password": f"wrong_password_{i}"},
            )

        elif attack_type == "sql_injection":
            # T1190 — SQL 인젝션: 쿼리 파라미터에 SQL 페이로드 삽입
            payload = f"' OR '1'='1"
            resp = _get(host, f"/api/posts?page={requests.utils.quote(payload)}")

        elif attack_type == "path_traversal":
            # T1083 — 경로 탐색: 상위 디렉토리 접근 시도
            resp = _get(host, "/api/posts/../../../etc/passwd")

        elif attack_type == "lateral":
            # T1021 — 내부 접근: 내부용 엔드포인트 직접 호출
            resp = _get(host, "/internal/auth/validate")

        elif attack_type == "exfil":
            # T1041 — 데이터 유출: 대용량 데이터 빠르게 반복 요청
            resp = _get(host, "/api/posts?size=1000&page=0", timeout=3)
            # 딜레이 없이 연속 요청으로 비정상적 패턴 생성

        else:
            raise ValueError(f"알 수 없는 attack_type: {attack_type!r}")

        results.append(
            _classify_response(resp, expected="drop", traffic_type="attack")
        )

        # exfil은 딜레이 없이 연속 전송, 나머지는 최소 딜레이
        if attack_type != "exfil":
            time.sleep(0.05)

    return results


# ------------------------------------------------------------------
# 지표 계산
# ------------------------------------------------------------------
def calculate_metrics(results: list[TrafficResult]) -> dict:
    """혼동 행렬 및 분류 지표를 계산한다.

    Returns:
        {
            "TP": int, "TN": int, "FP": int, "FN": int,
            "precision": float, "recall": float, "f1": float,
            "fpr": float, "fnr": float,
            "total": int, "accuracy": float,
        }
    """
    tp = tn = fp = fn = 0

    for r in results:
        if r.traffic_type == "attack" and r.actual == "drop":
            tp += 1  # 공격 → 차단 (정확)
        elif r.traffic_type == "benign" and r.actual == "forward":
            tn += 1  # 정상 → 통과 (정확)
        elif r.traffic_type == "benign" and r.actual == "drop":
            fp += 1  # 정상 → 차단 (오탐)
        elif r.traffic_type == "attack" and r.actual == "forward":
            fn += 1  # 공격 → 통과 (미탐)

    total = tp + tn + fp + fn

    # 0 나누기 방지
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr       = fn / (fn + tp) if (fn + tp) > 0 else 0.0
    accuracy  = (tp + tn) / total if total > 0 else 0.0

    return {
        "TP": tp, "TN": tn, "FP": fp, "FN": fn,
        "precision": round(precision, 4),
        "recall":    round(recall, 4),
        "f1":        round(f1, 4),
        "fpr":       round(fpr, 4),
        "fnr":       round(fnr, 4),
        "total":     total,
        "accuracy":  round(accuracy, 4),
    }


# ------------------------------------------------------------------
# 결과 저장
# ------------------------------------------------------------------
def save_results(
    host: str,
    attack_types: list[str],
    count: int,
    results: list[TrafficResult],
    metrics: dict,
) -> str:
    """evaluation/results/detection_<timestamp>.json 에 저장한다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(RESULTS_DIR, f"detection_{timestamp}.json")

    output = {
        "timestamp": datetime.now().isoformat(),
        "host": host,
        "attack_types": attack_types,
        "count_per_type": count,
        "metrics": metrics,
        "results": [asdict(r) for r in results],
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return filename


# ------------------------------------------------------------------
# 출력
# ------------------------------------------------------------------
def print_report(
    host: str,
    attack_types: list[str],
    count: int,
    metrics: dict,
) -> None:
    attacks_label = ", ".join(attack_types) if attack_types else "없음"
    print()
    print("=== End-to-End 탐지 성능 평가 ===")
    print(f"호스트: {host}")
    print(f"Benign 요청: {count} / 공격 유형: {attacks_label} / 공격 요청: {count * len(attack_types)}")
    print()
    print("혼동 행렬:")
    print(f"  TN(정상→통과): {metrics['TN']:<5}  FP(정상→차단): {metrics['FP']}")
    print(f"  FN(공격→통과): {metrics['FN']:<5}  TP(공격→차단): {metrics['TP']}")
    print()
    print(f"정밀도(Precision): {metrics['precision']:.4f}")
    print(f"재현율(Recall):    {metrics['recall']:.4f}")
    print(f"F1:               {metrics['f1']:.4f}")
    print(f"FPR:              {metrics['fpr']:.4f}")
    print(f"FNR:              {metrics['fnr']:.4f}")
    print(f"정확도(Accuracy): {metrics['accuracy']:.4f}")
    print()


# ------------------------------------------------------------------
# 진입점
# ------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Service Mesh end-to-end 탐지 성능 평가"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="대상 호스트 (예: http://192.168.56.11:30080)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="benign 및 각 공격 유형당 요청 수 (기본값: 100)",
    )
    # 공격 유형 플래그
    parser.add_argument("--brute-force",     action="store_true", help="T1110 무차별 대입")
    parser.add_argument("--sql-injection",   action="store_true", help="T1190 SQL 인젝션")
    parser.add_argument("--path-traversal",  action="store_true", help="T1083 경로 탐색")
    parser.add_argument("--lateral",         action="store_true", help="T1021 내부 접근")
    parser.add_argument("--exfil",           action="store_true", help="T1041 데이터 유출")
    parser.add_argument("--all-attacks",     action="store_true", help="모든 공격 유형 실행")

    args = parser.parse_args()

    # 선택된 공격 유형 수집
    attack_map = {
        "brute_force":    args.brute_force,
        "sql_injection":  args.sql_injection,
        "path_traversal": args.path_traversal,
        "lateral":        args.lateral,
        "exfil":          args.exfil,
    }

    if args.all_attacks:
        selected_attacks = list(attack_map.keys())
    else:
        selected_attacks = [k for k, v in attack_map.items() if v]

    if not selected_attacks:
        print(
            "[경고] 공격 유형이 선택되지 않았습니다. "
            "--brute-force, --sql-injection, --path-traversal, --lateral, --exfil 중 하나 이상 지정하거나 "
            "--all-attacks를 사용하세요.",
            file=sys.stderr,
        )
        print("[정보] benign 트래픽만 평가합니다.")

    all_results: list[TrafficResult] = []

    # 1. benign 트래픽 전송
    print(f"[1/2] benign 트래픽 전송 중... ({args.count}회)")
    benign_results = send_benign(args.host, args.count)
    all_results.extend(benign_results)
    benign_forward = sum(1 for r in benign_results if r.actual == "forward")
    print(f"      완료: {benign_forward}/{args.count} forward")

    # 2. 공격 트래픽 전송
    if selected_attacks:
        print(f"[2/2] 공격 트래픽 전송 중... ({len(selected_attacks)}종 × {args.count}회)")
        for attack_type in selected_attacks:
            print(f"      [{attack_type}] 전송 중...")
            attack_results = send_attack(args.host, attack_type, args.count)
            all_results.extend(attack_results)
            attack_drop = sum(1 for r in attack_results if r.actual == "drop")
            print(f"      [{attack_type}] 완료: {attack_drop}/{args.count} drop")
    else:
        print("[2/2] 공격 트래픽 생략")

    # 3. 지표 계산
    metrics = calculate_metrics(all_results)

    # 4. 출력
    print_report(args.host, selected_attacks, args.count, metrics)

    # 5. 저장
    saved_path = save_results(
        args.host, selected_attacks, args.count, all_results, metrics
    )
    print(f"결과 저장: {saved_path}")


if __name__ == "__main__":
    main()
