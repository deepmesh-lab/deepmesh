"""
sweep_sizes.py — 한 서비스에 대해 학생 5종(1x8/1x16/2x8/2x16/2x32) KD+OCSVM 학습 후 성능 비교(논문 Table 5 대응).

■ 공정 비교: teacher를 **한 번만** 학습하고 5개 학생이 모두 **동일 teacher**로 증류(첫 arch가 teacher.pth 저장 → 나머지 재사용).
■ 출력: 크기별 params + val ROC-AUC / FPR@thr / Recall@thr 표.

사용(Colab):
  python sweep_sizes.py --data data/auth --out models/auth_sweep --teacher deep
"""
import argparse
import json
import os
import subprocess
import sys

from student_cnn import make_student

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHS = ["1x8", "1x16", "2x8", "2x16", "2x32"]


def nparams(a):
    return sum(p.numel() for p in make_student(a).parameters())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--teacher", default="shallow", choices=["shallow", "deep"],
                    help="논문 공개 코드가 2x8/2x16/2x32/1x16에 쓴 teacher = shallow(314.69K). "
                         "1x8만 deep(3.31M) 사용. 공정 비교 위해 shallow 고정 권장.")
    ap.add_argument("--limit", type=int, default=50000)
    ap.add_argument("--epochs-teacher", type=int, default=30, dest="et")
    ap.add_argument("--epochs-student", type=int, default=20, dest="es")
    ap.add_argument("--target-fpr", type=float, default=0.01, dest="tfpr")
    ap.add_argument("--l2", action="store_true")
    a = ap.parse_args()

    teacher_pth = None
    rows = []
    for arch in ARCHS:
        out = os.path.join(a.out, arch)
        cmd = [sys.executable, os.path.join(HERE, "train_kd_pipeline.py"),
               "--data", a.data, "--out", out, "--arch", arch, "--teacher", a.teacher,
               "--limit", str(a.limit), "--epochs-teacher", str(a.et),
               "--epochs-student", str(a.es), "--target-fpr", str(a.tfpr)]
        if a.l2:
            cmd.append("--l2")
        if teacher_pth:                      # 2번째부터 동일 teacher 재사용
            cmd += ["--teacher-pth", teacher_pth]
        print(f"\n{'='*64}\n[sweep] student {arch}  ({nparams(arch)/1000:.2f}K params)\n{'='*64}")
        subprocess.run(cmd, check=False)
        if teacher_pth is None:              # 첫 run의 teacher를 이후 재사용
            cand = os.path.join(out, "teacher.pth")
            if os.path.exists(cand):
                teacher_pth = cand
        try:
            rows.append((arch, nparams(arch),
                         json.load(open(os.path.join(out, "eval_results.json"), encoding="utf-8"))))
        except Exception as e:
            print(f"[warn] {arch} 결과 로드 실패: {e}")

    print(f"\n{'='*72}\n=== 크기별 비교 (논문 Table 5 대응)  teacher={a.teacher} ===\n{'='*72}")
    print(f"{'arch':6} {'params':>9}  {'valROC':>7} {'FPR@thr':>8} {'Rec@thr':>8}")
    f = lambda v: f"{v:.3f}" if v is not None else "  N/A  "
    for arch, n, r in rows:
        print(f"{arch:6} {n/1000:>7.2f}K  {f(r.get('val_roc_auc')):>7} "
              f"{f(r.get('val_fpr_at_thr')):>8} {f(r.get('val_recall_at_thr')):>8}")
    print("\n※ 배포 후보는 논문과 동일하게 2x8(5.69K) 권장 — 정확도/지연 균형. 최종 지연은 단일 vCPU 벤치로.")


if __name__ == "__main__":
    main()
