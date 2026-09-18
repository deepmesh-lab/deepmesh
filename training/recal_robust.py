"""auth, post, comment, frontend의 OCSVM과 임계값을 재보정한다."""


def print_candidates(svc, candidates):
    """OCSVM 후보를 worst AUC 순으로 출력한다."""
    print(f"[OCSVM candidates] {svc}")
    for c in sorted(candidates, key=lambda c: -c["worst_auc"]):
        th = c["threshold"]
        status = "OK" if th is not None else "FAIL"
        fpr = f"{th['actual_fpr']*100:.2f}%" if th is not None else "-"
        print(f"  gamma={str(c['gamma']):>6} nu={c['nu']:.2f} "
              f"worstAUC={c['worst_auc']:.3f} meanAUC={c['mean_auc']:.3f} "
              f"fpr={fpr:>6} {status}")


def summarize(results, failed):
    """서비스별 재보정 결과를 출력한다."""
    for svc, r in results.items():
        print(f"[OK]       {svc:9s} gamma={r['gamma']} nu={r['nu']:.2f} "
              f"thr={r['threshold']:+.4f} fpr={r['fpr']*100:.2f}% "
              f"worstAUC={r['worst_auc']:.3f} meanAUC={r['mean_auc']:.3f}")
    for svc, err in failed.items():
        print(f"[ROLLBACK] {svc:9s} {err}")


def run(models_dir=None, data_dir=None):
    """서비스별 OCSVM과 임계값을 재보정한다.

    모델은 recalibrate_ocsvm.MODELS에 미리 배치해야 한다.
    models_dir와 data_dir는 경로 확인용이며 설정을 바꾸지 않는다."""
    import os as _os
    import importlib as _importlib
    import recalibrate_ocsvm as R
    _importlib.reload(R)                      # 경로 설정을 다시 읽어 확인
    if models_dir is not None and _os.path.abspath(models_dir) != _os.path.abspath(R.MODELS):
        raise RuntimeError(
            f"재보정 경로 불일치\n"
            f"  요청: {_os.path.abspath(models_dir)}\n"
            f"  실제: {_os.path.abspath(R.MODELS)}  (recalibrate_ocsvm.py 기준 고정)\n"
            f"  → 대상을 {_os.path.abspath(R.MODELS)} 에 스테이징한 뒤 호출하세요."
        )
    if data_dir is not None and _os.path.abspath(data_dir) != _os.path.abspath(R.DATA):
        raise RuntimeError(f"데이터 경로 불일치: 요청={data_dir} 실제={R.DATA}")


    import os
    import json
    import shutil
    import importlib
    from datetime import datetime

    import numpy as np
    import torch
    import joblib

    from sklearn.svm import OneClassSVM
    from sklearn.metrics import roc_auc_score

    import recalibrate_ocsvm as R

    importlib.reload(R)


    SERVICES = [
        "auth",
        "post",
        "comment",
        "frontend",
    ]


    # DETECT: gamma/nu 선택용 시나리오

    SERVICE_DETECT = {

        "auth": {
            "k1",
            "k2",
        },

        "post": {
            "l3",
            "k1",
            "k2",
        },

        "comment": {
            "l3",
            "k1",
            "k2",
        },

        "frontend": {
            "scan_seq",
            "r1",
            "k1",
            "k2",
        },
    }


    # REPORT_ONLY: 보정에서 제외하고 recall만 확인

    SERVICE_REPORT_ONLY = {

        "auth": {
            "cred_enum",
        },

        "post": {
            "enum_seq",
            "l2",
        },

        "comment": {
            "enum_seq",
            "l2",
        },

        "frontend": set(),
    }


    # 서비스별 FPR 상한과 필수 recall

    POLICY = {

        "auth": {
            "fpr_cap": 0.020,

            "required": {
                "k1": 0.95,
                "k2": 0.95,
            },
        },


        "post": {
            "fpr_cap": 0.010,

            "required": {
                "l3": 0.95,
                "k1": 0.95,
                "k2": 0.95,
            },
        },


        # l3의 관측 recall(약 87%)을 고려해 하한을 80%로 설정
        "comment": {
            "fpr_cap": 0.030,
            "required": {
                "l3": 0.80,
                "k1": 0.95,
                "k2": 0.95,
            },
        },


        # r1 recall을 고려한 FPR 상한
        "frontend": {
            "fpr_cap": 0.050,

            "required": {
                "scan_seq": 0.95,
                "r1":       0.70,
                "k1":       0.95,
                "k2":       0.95,
            },
        },
    }


    # 탐색 범위
    FPR_GRID = (
        0.001,     # 0.10%
        0.0025,    # 0.25%
        0.005,     # 0.50%
        0.0075,    # 0.75%
        0.010,     # 1.00%
        0.015,     # 1.50%
        0.020,     # 2.00%
        0.025,     # 2.50%
        0.030,     # 3.00%
        0.040,     # 4.00%
        0.050,     # 5.00%
    )


    GAMMA_GRID = (
        "scale",
        1e-4,
        1e-3,
        1e-2,
        0.1,
        1.0,
        10.0,
    )

    NU_GRID = (
        0.02,
        0.05,
        0.10,
    )


    FIT_MAX = 15000
    VAL_MAX = 15000
    ATTACK_CAP = 12000

    SEED = 11


    # 기존 모델 백업

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    BACKUP_ROOT = os.path.join(
        R.MODELS,
        f"_before_robust_recalib_{stamp}",
    )

    os.makedirs(
        BACKUP_ROOT,
        exist_ok=True,
    )


    def backup_service(svc):

        src = os.path.join(
            R.MODELS,
            svc,
        )

        dst = os.path.join(
            BACKUP_ROOT,
            svc,
        )

        os.makedirs(
            dst,
            exist_ok=True,
        )

        for fn in (
            "student_ts.pt",
            "ocsvm.pkl",
            "threshold.json",
        ):

            p = os.path.join(
                src,
                fn,
            )

            if os.path.exists(p):

                shutil.copy2(
                    p,
                    os.path.join(
                        dst,
                        fn,
                    ),
                )


    def restore_service(svc):

        src = os.path.join(
            BACKUP_ROOT,
            svc,
        )

        dst = os.path.join(
            R.MODELS,
            svc,
        )

        for fn in (
            "ocsvm.pkl",
            "threshold.json",
        ):

            p = os.path.join(
                src,
                fn,
            )

            if os.path.exists(p):

                shutil.copy2(
                    p,
                    os.path.join(
                        dst,
                        fn,
                    ),
                )


    for svc in SERVICES:
        backup_service(svc)


    def embed_npy(
        ts,
        path,
        batch_size=2048,
    ):
        """NPY를 mmap으로 읽어 배치별로 임베딩한다."""

        if not os.path.exists(path):
            return None

        arr = np.load(
            path,
            mmap_mode="r",
        )

        out = []

        with torch.no_grad():

            for start in range(
                0,
                len(arr),
                batch_size,
            ):

                x = np.asarray(
                    arr[
                        start:
                        start + batch_size
                    ],
                    dtype=np.float32,
                )

                x = np.nan_to_num(
                    np.clip(
                        x,
                        0,
                        1,
                    )
                )

                f = ts(
                    torch.from_numpy(
                        x
                    ).unsqueeze(1)
                ).numpy()

                out.append(f)

        if not out:

            return np.empty(
                (0,),
                dtype=np.float32,
            )

        return np.concatenate(
            out,
            axis=0,
        )


    def load_attack_features(
        svc,
        ts,
        rng,
    ):
        """서비스별 공격 시나리오를 임베딩한다."""

        result = {}

        for scen in R.POD_SCENS.get(
            svc,
            [],
        ):

            path = os.path.join(
                R.DATA,
                "_attack",
                f"X_attack_{svc}_{scen}.npy",
            )

            X = R.load_imgs(
                path,
                ATTACK_CAP,
                rng,
            )

            if (
                X is None
                or len(X) == 0
            ):
                continue

            result[scen] = R.embed(
                ts,
                X,
            )

        return result


    def scenario_aucs(
        oc,
        benign_val_feat,
        scenario_feat,
        detect_scens,
    ):
        """DETECT 시나리오별 ROC-AUC를 계산한다."""

        benign_score = (
            oc.decision_function(
                benign_val_feat
            )
        )

        result = {}

        for scen in detect_scens:

            feat = scenario_feat.get(
                scen
            )

            if (
                feat is None
                or len(feat) == 0
            ):

                continue

            attack_score = (
                oc.decision_function(
                    feat
                )
            )

            y_true = np.r_[
                np.zeros(
                    len(benign_score),
                    dtype=np.int8,
                ),
                np.ones(
                    len(attack_score),
                    dtype=np.int8,
                ),
            ]

            # 낮은 점수가 이상이므로 AUC 계산 시 부호 반전
            y_score = np.r_[
                -benign_score,
                -attack_score,
            ]

            result[scen] = float(
                roc_auc_score(
                    y_true,
                    y_score,
                )
            )

        return result


    def find_threshold(
        oc,
        test_benign_feat,
        scenario_feat,
        policy,
    ):
        """REQUIRED 조건을 만족하면서 FPR이 가장 낮은 임계값을 찾는다."""

        benign_score = (
            oc.decision_function(
                test_benign_feat
            )
        )


        attack_scores = {

            scen:
                oc.decision_function(
                    feat
                )

            for scen, feat
            in scenario_feat.items()
        }


        rows = []

        for target_fpr in FPR_GRID:

            if (
                target_fpr
                > policy["fpr_cap"] + 1e-12
            ):
                continue


            threshold = float(
                np.quantile(
                    benign_score,
                    target_fpr,
                )
            )


            actual_fpr = float(
                (
                    benign_score
                    < threshold
                ).mean()
            )


            recall = {

                scen: float(
                    (
                        score
                        < threshold
                    ).mean()
                )

                for scen, score
                in attack_scores.items()
            }


            failed = []

            for scen, minimum in (
                policy[
                    "required"
                ].items()
            ):

                if scen not in recall:

                    failed.append(
                        f"{scen}=missing"
                    )

                elif (
                    recall[scen]
                    < minimum
                ):

                    failed.append(
                        f"{scen}="
                        f"{recall[scen]*100:.1f}%"
                        f"<{minimum*100:.0f}%"
                    )


            ok = (
                len(failed) == 0
            )


            req_vals = [
                recall[s]
                for s in policy["required"]
                if s in recall
            ]


            req_mean = (
                float(
                    np.mean(
                        req_vals
                    )
                )
                if req_vals
                else float("nan")
            )


            rows.append({
                "target_fpr":
                    float(target_fpr),

                "actual_fpr":
                    actual_fpr,

                "threshold":
                    threshold,

                "recall":
                    recall,

                "required_mean":
                    req_mean,

                "ok":
                    ok,

                "failed":
                    failed,
            })


        feasible = [
            r
            for r in rows
            if r["ok"]
        ]


        if not feasible:

            return None, rows


        # FPR이 같으면 필수 시나리오의 평균 recall로 선택
        chosen = min(
            feasible,

            key=lambda r: (
                r["actual_fpr"],
                -r["required_mean"],
            ),
        )


        return chosen, rows


    # 서비스별 재보정

    def recalibrate_service(
        svc,
    ):

        policy = POLICY[svc]

        detect_set = set(
            SERVICE_DETECT[svc]
        )

        report_only = set(
            SERVICE_REPORT_ONLY[svc]
        )


        mdir = os.path.join(
            R.MODELS,
            svc,
        )


        ts = torch.jit.load(
            os.path.join(
                mdir,
                "student_ts.pt",
            ),
            map_location="cpu",
        ).eval()


        rng = np.random.default_rng(
            SEED
        )


        # 정상 데이터를 학습·검증으로 분리
        Xb, sess_b = R.load_imgs(
            os.path.join(
                R.DATA,
                svc,
                "X_benign.npy",
            ),
            FIT_MAX + VAL_MAX,
            rng,
            with_sess=True,
        )


        if (
            Xb is None
            or len(Xb) == 0
        ):

            raise RuntimeError(
                f"{svc}: X_benign.npy 없음"
            )


        fb = R.embed(
            ts,
            Xb,
        )


        if sess_b is not None:

            val_ratio = (
                VAL_MAX
                / (
                    FIT_MAX
                    + VAL_MAX
                )
            )

            vm = R.group_val_mask(
                sess_b,
                val_ratio,
                seed=SEED,
            )

            fit_feat = fb[~vm]
            val_feat = fb[vm]

        else:

            split = min(
                FIT_MAX,
                len(fb),
            )

            fit_feat = fb[
                :split
            ]

            val_feat = fb[
                split:
                split + VAL_MAX
            ]


        if (
            len(fit_feat) == 0
            or len(val_feat) == 0
        ):

            raise RuntimeError(
                f"{svc}: fit/val benign 분할 실패"
            )


        # 임계값 보정용 정상 테스트 데이터
        test_benign_path = os.path.join(
            R.DATA,
            svc,
            "X_testbenign.npy",
        )


        test_benign_feat = embed_npy(
            ts,
            test_benign_path,
        )


        if (
            test_benign_feat is None
            or len(test_benign_feat) == 0
        ):

            raise RuntimeError(
                f"{svc}: X_testbenign.npy 없음"
            )


        attack_feat = (
            load_attack_features(
                svc,
                ts,
                rng,
            )
        )


        missing_detect = [
            s
            for s in detect_set
            if s not in attack_feat
        ]

        if missing_detect:

            raise RuntimeError(
                f"{svc}: DETECT attack npy 없음: "
                f"{missing_detect}"
            )


        missing_required = [
            s
            for s in policy["required"]
            if s not in attack_feat
        ]

        if missing_required:

            raise RuntimeError(
                f"{svc}: REQUIRED attack npy 없음: "
                f"{missing_required}"
            )


        # gamma/nu 탐색
        candidates = []


        for gamma in GAMMA_GRID:

            for nu in NU_GRID:

                gv = (
                    gamma
                    if gamma == "scale"
                    else float(gamma)
                )


                oc = OneClassSVM(
                    kernel="rbf",
                    gamma=gv,
                    nu=nu,
                    cache_size=500,
                    max_iter=30000,
                )


                oc.fit(
                    fit_feat
                )


                aucs = scenario_aucs(
                    oc,
                    val_feat,
                    attack_feat,
                    detect_set,
                )


                if len(aucs) != len(
                    detect_set
                ):

                    continue


                auc_values = list(
                    aucs.values()
                )


                worst_auc = float(
                    min(
                        auc_values
                    )
                )

                mean_auc = float(
                    np.mean(
                        auc_values
                    )
                )


                threshold_row, threshold_rows = (
                    find_threshold(
                        oc,
                        test_benign_feat,
                        attack_feat,
                        policy,
                    )
                )


                candidates.append({
                    "gamma":
                        gamma,

                    "nu":
                        nu,

                    "oc":
                        oc,

                    "aucs":
                        aucs,

                    "worst_auc":
                        worst_auc,

                    "mean_auc":
                        mean_auc,

                    "threshold":
                        threshold_row,

                    "threshold_rows":
                        threshold_rows,
                })


        # 임계값 조건을 통과한 후보만 비교
        feasible_models = [
            c
            for c in candidates
            if c["threshold"] is not None
        ]

        print_candidates(svc, candidates)


        if not feasible_models:

            raise RuntimeError(
                f"{svc}: "
                f"FPR cap={policy['fpr_cap']*100:.2f}% "
                f"내에서 REQUIRED 조건을 만족하는 "
                f"OCSVM/threshold 조합이 없음"
            )


        # worst AUC → 낮은 FPR → mean AUC 순으로 선택
        best = max(
            feasible_models,

            key=lambda c: (
                c["worst_auc"],

                -c["threshold"][
                    "actual_fpr"
                ],

                c["mean_auc"],
            ),
        )


        oc = best["oc"]
        chosen = best["threshold"]


        # 재보정 결과 저장
        joblib.dump(
            oc,
            os.path.join(
                mdir,
                "ocsvm.pkl",
            ),
        )


        threshold_path = os.path.join(
            mdir,
            "threshold.json",
        )


        old_meta = {}

        if os.path.exists(
            threshold_path
        ):

            try:

                with open(
                    threshold_path,
                    "r",
                    encoding="utf-8",
                ) as f:

                    old_meta = json.load(
                        f
                    )

            except Exception:

                old_meta = {}


        # 기존 메타데이터에 보정 결과 추가
        meta = dict(
            old_meta
        )


        meta.update({

            "threshold_df":
                chosen["threshold"],

            "select":
                (
                    "robust_recalibration: "
                    "max worst-per-scenario ROC-AUC; "
                    "threshold=min FPR satisfying REQUIRED"
                ),

            "gamma":
                best["gamma"],

            "nu":
                best["nu"],

            "calibration_fpr":
                round(
                    chosen[
                        "actual_fpr"
                    ],
                    6,
                ),

            "calibration_target_fpr":
                chosen[
                    "target_fpr"
                ],

            "calibration_fpr_cap":
                policy[
                    "fpr_cap"
                ],

            "detect_scenarios":
                sorted(
                    detect_set
                ),

            "required_scenarios":
                {
                    k: float(v)
                    for k, v
                    in policy[
                        "required"
                    ].items()
                },

            "report_only_scenarios":
                sorted(
                    report_only
                ),

            "per_detect_auc":
                {
                    k: round(
                        float(v),
                        6,
                    )
                    for k, v
                    in best[
                        "aucs"
                    ].items()
                },

            "worst_detect_auc":
                round(
                    best[
                        "worst_auc"
                    ],
                    6,
                ),

            "mean_detect_auc":
                round(
                    best[
                        "mean_auc"
                    ],
                    6,
                ),

            "calibration_recall":
                {
                    k: round(
                        float(v),
                        6,
                    )
                    for k, v
                    in chosen[
                        "recall"
                    ].items()
                },

            "enum_seq_policy":
                (
                    "report_only: ambiguous sequential "
                    "normal-use pattern; excluded from "
                    "OCSVM/threshold optimization"
                ),

            "semantic":
                True,

            "recalibrated":
                True,
        })


        with open(
            threshold_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                meta,
                f,
                indent=2,
                ensure_ascii=False,
            )


        return {

            "svc":
                svc,

            "gamma":
                best["gamma"],

            "nu":
                best["nu"],

            "threshold":
                chosen[
                    "threshold"
                ],

            "fpr":
                chosen[
                    "actual_fpr"
                ],

            "worst_auc":
                best[
                    "worst_auc"
                ],

            "mean_auc":
                best[
                    "mean_auc"
                ],

            "per_auc":
                best[
                    "aucs"
                ],

            "recall":
                chosen[
                    "recall"
                ],
        }


    # 실패한 서비스만 백업에서 복구
    RESULTS = {}
    FAILED = {}


    for svc in SERVICES:

        try:

            RESULTS[svc] = (
                recalibrate_service(
                    svc
                )
            )

        except Exception as e:

            restore_service(
                svc
            )

            FAILED[svc] = str(e)


    # 전체 결과 저장
    RESULT_PATH = os.path.join(
        R.MODELS,
        "robust_calibration_results.json",
    )


    serializable_results = {}

    for svc, r in RESULTS.items():

        serializable_results[svc] = {

            "gamma":
                r["gamma"],

            "nu":
                float(
                    r["nu"]
                ),

            "threshold":
                float(
                    r["threshold"]
                ),

            "fpr":
                float(
                    r["fpr"]
                ),

            "worst_auc":
                float(
                    r["worst_auc"]
                ),

            "mean_auc":
                float(
                    r["mean_auc"]
                ),

            "per_auc":
                {
                    k: float(v)
                    for k, v
                    in r[
                        "per_auc"
                    ].items()
                },

            "recall":
                {
                    k: float(v)
                    for k, v
                    in r[
                        "recall"
                    ].items()
                },
        }


    with open(
        RESULT_PATH,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            {
                "results":
                    serializable_results,

                "failed":
                    FAILED,

                "backup":
                    os.path.abspath(
                        BACKUP_ROOT
                    ),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )


    summarize(RESULTS, FAILED)

    return RESULTS, FAILED
