"""
네트워크 오버헤드 벤치마크

사용법:
  # Sidecar 없는 경우 (기준):
  python overhead_benchmark.py --host http://<NODE_IP>:30080 --label baseline --count 500

  # Sidecar 있는 경우:
  python overhead_benchmark.py --host http://<NODE_IP>:30080 --label servicemesh --count 500

  # 두 결과 비교:
  python overhead_benchmark.py --compare evaluation/results/baseline.json evaluation/results/servicemesh.json
"""
import argparse
import requests
import time
import json
import statistics
import sys
import os
from dataclasses import dataclass, asdict


@dataclass
class BenchmarkResult:
    label: str
    count: int
    success: int
    failed: int
    latencies_ms: list
    p50: float
    p95: float
    p99: float
    mean: float
    stddev: float
    rps: float  # requests per second


def percentile(sorted_data: list, pct: float) -> float:
    """정렬된 리스트에서 백분위수 계산."""
    if not sorted_data:
        return 0.0
    idx = (pct / 100) * (len(sorted_data) - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= len(sorted_data):
        return sorted_data[-1]
    frac = idx - lower
    return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac


def run_benchmark(host: str, count: int, concurrency: int = 1, path: str = "/api/posts") -> BenchmarkResult:
    """
    GET {host}{path} 요청을 count회 순차 실행하여 레이턴시를 측정한다.

    Args:
        host: 대상 호스트 (예: http://192.168.1.100:30080)
        count: 총 요청 횟수
        concurrency: 동시 요청 수 (현재 순차 실행만 지원, 미래 확장용)
        path: 요청 경로

    Returns:
        BenchmarkResult: 측정 결과
    """
    url = host.rstrip("/") + path
    latencies_ms = []
    success = 0
    failed = 0

    print(f"벤치마크 시작: {url}")
    print(f"요청 수: {count}")
    print("-" * 40)

    session = requests.Session()
    start_total = time.perf_counter()

    for i in range(count):
        t0 = time.perf_counter()
        try:
            resp = session.get(url, timeout=10)
            t1 = time.perf_counter()
            latency_ms = (t1 - t0) * 1000
            latencies_ms.append(latency_ms)
            if resp.status_code < 400:
                success += 1
            else:
                failed += 1
        except Exception:
            t1 = time.perf_counter()
            latency_ms = (t1 - t0) * 1000
            latencies_ms.append(latency_ms)
            failed += 1

        if (i + 1) % 100 == 0 or (i + 1) == count:
            print(f"  진행: {i + 1}/{count} (성공: {success}, 실패: {failed})")

    end_total = time.perf_counter()
    total_time = end_total - start_total

    sorted_latencies = sorted(latencies_ms)
    p50_val = percentile(sorted_latencies, 50)
    p95_val = percentile(sorted_latencies, 95)
    p99_val = percentile(sorted_latencies, 99)
    mean_val = statistics.mean(latencies_ms) if latencies_ms else 0.0
    stddev_val = statistics.stdev(latencies_ms) if len(latencies_ms) > 1 else 0.0
    rps_val = count / total_time if total_time > 0 else 0.0

    return BenchmarkResult(
        label="",
        count=count,
        success=success,
        failed=failed,
        latencies_ms=latencies_ms,
        p50=round(p50_val, 3),
        p95=round(p95_val, 3),
        p99=round(p99_val, 3),
        mean=round(mean_val, 3),
        stddev=round(stddev_val, 3),
        rps=round(rps_val, 3),
    )


def save_result(result: BenchmarkResult, label: str, output_dir: str = "evaluation/results") -> str:
    """결과를 JSON 파일로 저장한다."""
    os.makedirs(output_dir, exist_ok=True)
    result.label = label
    output_path = os.path.join(output_dir, f"{label}_benchmark.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, ensure_ascii=False, indent=2)
    return output_path


def load_result(path: str) -> BenchmarkResult:
    """JSON 파일에서 BenchmarkResult를 로드한다."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return BenchmarkResult(**data)


def compare_results(baseline: BenchmarkResult, servicemesh: BenchmarkResult) -> None:
    """
    두 결과를 표로 출력한다.

    예시:
    === 오버헤드 분석 ===
    지표           Baseline    ServiceMesh  증가량
    ─────────────────────────────────────────────
    평균 레이턴시  5.2ms       6.8ms        +30.8%
    P50            4.9ms       6.1ms        +24.5%
    P95            8.3ms       11.2ms       +34.9%
    P99            12.1ms      16.8ms       +38.8%
    RPS            192.3       147.6        -23.2%
    """
    def pct_change(base: float, new: float) -> str:
        if base == 0:
            return "N/A"
        change = (new - base) / base * 100
        sign = "+" if change >= 0 else ""
        return f"{sign}{change:.1f}%"

    header = f"{'지표':<16} {'Baseline':>12} {'ServiceMesh':>12} {'증가량':>10}"
    sep = "─" * len(header)

    print()
    print("=== 오버헤드 분석 ===")
    print(header)
    print(sep)

    rows = [
        ("평균 레이턴시", baseline.mean, servicemesh.mean, "ms"),
        ("P50",          baseline.p50,  servicemesh.p50,  "ms"),
        ("P95",          baseline.p95,  servicemesh.p95,  "ms"),
        ("P99",          baseline.p99,  servicemesh.p99,  "ms"),
        ("RPS",          baseline.rps,  servicemesh.rps,  ""),
    ]

    for label, base_val, new_val, unit in rows:
        base_str = f"{base_val}{unit}"
        new_str  = f"{new_val}{unit}"
        change   = pct_change(base_val, new_val)
        print(f"{label:<16} {base_str:>12} {new_str:>12} {change:>10}")

    print(sep)
    print(f"  요청 수:  Baseline={baseline.count}  ServiceMesh={servicemesh.count}")
    print(f"  성공률:   Baseline={baseline.success/baseline.count*100:.1f}%  "
          f"ServiceMesh={servicemesh.success/servicemesh.count*100:.1f}%")
    print()


def print_summary(result: BenchmarkResult) -> None:
    """단일 결과 요약 출력."""
    print()
    print(f"=== 결과: {result.label} ===")
    print(f"  총 요청: {result.count}  성공: {result.success}  실패: {result.failed}")
    print(f"  평균 레이턴시: {result.mean}ms  (stddev: {result.stddev}ms)")
    print(f"  P50: {result.p50}ms  P95: {result.p95}ms  P99: {result.p99}ms")
    print(f"  RPS: {result.rps}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sidecar Proxy 네트워크 오버헤드 벤치마크",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", default="http://localhost:30080",
                        help="대상 호스트 URL (기본값: http://localhost:30080)")
    parser.add_argument("--path", default="/api/posts",
                        help="요청 경로 (기본값: /api/posts)")
    parser.add_argument("--count", type=int, default=500,
                        help="총 요청 횟수 (기본값: 500)")
    parser.add_argument("--label", default="benchmark",
                        help="결과 파일 레이블 (baseline / servicemesh 등)")
    parser.add_argument("--output-dir", default="evaluation/results",
                        help="결과 저장 디렉토리 (기본값: evaluation/results)")
    parser.add_argument("--compare", nargs=2, metavar=("BASELINE_JSON", "SERVICEMESH_JSON"),
                        help="두 JSON 결과 파일을 로드해 오버헤드 분석 출력")

    args = parser.parse_args()

    if args.compare:
        baseline_path, servicemesh_path = args.compare
        try:
            baseline = load_result(baseline_path)
            servicemesh = load_result(servicemesh_path)
        except FileNotFoundError as e:
            print(f"오류: 파일을 찾을 수 없습니다 — {e}", file=sys.stderr)
            sys.exit(1)
        compare_results(baseline, servicemesh)
    else:
        result = run_benchmark(host=args.host, count=args.count, path=args.path)
        print_summary(result)
        out_path = save_result(result, label=args.label, output_dir=args.output_dir)
        print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
