# 탐지 모듈 (Traffic Converter + Anomaly Detector)

모델 학습 쪽 산출물을 **무수정으로 반입한 것**이다. 프록시가 직접 부르지 않고,
`proxy/traffic_handler/detection_binding.py`의 래퍼를 거쳐 어댑터 규약에 연결된다.

## 출처

| 항목 | 값 |
| --- | --- |
| 브랜치 | `feat/models` |
| 커밋 | `c4912054acc2049b8fb96122fedc983f60efa8a8` |
| 반입일 | 2026-08-27 |

반입한 파일은 아래가 전부다.

```
converter_common.py            특징 추출 + BaseConverter
detector.py                    KD-CNN 인코더 + OCSVM 판정
<svc>/<svc>_converter.py       서비스별 라우팅 (auth, post, comment, frontend)
```

`handler.py`와 `pipeline_sweep.ipynb`는 반입하지 않는다. 전자는 프록시의 Traffic
Handler와 역할이 겹치는 데모이고, 후자는 학습 스윕 노트북이다.

## 수정 금지

**이 디렉터리의 파일을 고치지 않는다.**

`converter_common.py` 머리말이 특징 추출 블록을 수정 금지로 못박고 있다 — 모델이 정확히
그 특징으로 학습됐기 때문에, 한 축의 의미가 바뀌면 가중치가 통째로 무의미해진다.
그리고 모델이 재학습될 때마다 이 디렉터리를 다시 반입해야 하는데, 여기에 수정이 쌓여
있으면 반입할 때마다 그 수정을 되살려야 한다.

프록시 규약과 어긋나는 부분은 전부 `detection_binding.py`가 흡수한다. 맞춰야 할 것이
생기면 그쪽을 고친다.

## 재수입 절차

```bash
D=servicemesh/data-plane/detection
for f in converter_common.py detector.py; do git show <출처커밋>:$f > $D/$f; done
for s in auth post comment frontend; do
  git show <출처커밋>:$s/${s}_converter.py > $D/$s/${s}_converter.py
done
```

반입 후 이 문서의 출처 표와 아래 모델 표를 갱신하고, 프록시 테스트를 돌린다.

```bash
cd servicemesh/data-plane/proxy && python -m pytest -q
```

`detector.py`가 `threshold.json`의 `vec_len`과 컨버터의 `FEAT_LEN`을 대조하므로,
특징 길이가 바뀐 채 반입되면 기동 시점에 `ValueError`로 드러난다. 다만 길이는 그대로인데
축의 **의미**만 바뀐 경우는 잡지 못하니, 학습 쪽 변경 내역을 함께 확인해야 한다.

## 모델 (2026-08-27 기준)

가중치는 이 저장소에 없다. PVC로 주입한다 — 아래 "가중치 배치" 참고.

| 서비스 | 표현 | arch | threshold | 재보정 | OCSVM SV |
| --- | --- | --- | --- | --- | --- |
| auth | `flow_features` | 2x16 | -44.6464 | ✅ | 1,287 |
| post | `http_features` (이중 라우팅) | 2x8 | -13.9601 | ✅ | 329 |
| comment | `http_features` (이중 라우팅) | 2x32 | -0.1430 | ✅ | 9,489 |
| frontend | `fe_features` (요청·응답 모두) | 2x16 | -0.0352 | ✅ | 1,114 |

공통으로 `vec_len = 20`, 윈도우 `w = 5`, 이미지 `(20, 5)`, 임베딩 128차원이다.
인코더는 4개 모두 `student_ts.pt`(TorchScript)로 로드된다 — `student_model.py`가 없어도
된다는 뜻이고, 반대로 `student.pth`(state_dict)만으로는 로드되지 않는다.

## 가중치 배치

`detector.Detector`가 기대하는 구조는 다음과 같다.

```
<MODEL_ROOT>/<svc>/<svc>_model/
├── student_ts.pt        TorchScript 인코더   (필수)
├── ocsvm.pkl            OCSVM               (필수)
├── threshold.json       판정 임계값·메타      (필수)
└── eval_results.json    학습 시점 지표        (선택, 판정에 쓰지 않음)
```

`MODEL_ROOT`는 사이드카 환경변수이고 기본값은 `/app/model`이다. 여기에 서비스별 PVC를
마운트한다. `teacher.pth`(KD 교사)와 `student.pth`는 추론에 쓰이지 않으므로 적재할
필요가 없다.

## 런타임 의존성

이 코드는 `numpy`, `torch`, `scikit-learn`, `joblib`을 요구한다. 사이드카
`requirements.txt`에는 아직 들어 있지 않다 — 배포 배선 단계에서 추가한다. 그 전까지
프록시는 `NullDetectionAdapter`로 Forward 전용으로 동작한다.

`ocsvm.pkl`은 scikit-learn 1.6.1로 저장돼 있다. 다른 버전으로 로드하면
`InconsistentVersionWarning`이 뜨는데(`detector.py`가 억제한다) 동작이 달라질 수
있으므로 버전을 고정하는 편이 안전하다.
