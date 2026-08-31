# 탐지 모델 가중치

사이드카가 읽는 학습된 가중치다. 서비스 하나가 디렉터리 하나를 쓰고, 배치는
`detector.Detector`가 기대하는 `<MODEL_ROOT>/<svc>/<svc>_model/` 그대로다.

```
model/
├── auth/auth_model/{student_ts.pt, ocsvm.pkl, threshold.json, eval_results.json}
├── post/post_model/...
├── comment/comment_model/...
└── frontend/frontend_model/...
```

| 항목 | 값 |
| --- | --- |
| 출처 브랜치 | `feat/models` |
| 출처 커밋 | `c4912054acc2049b8fb96122fedc983f60efa8a8` |
| 반입일 | 2026-08-28 |

반입 시점에 `/srv/deepmesh/model`(배포 중인 NFS)의 16개 파일과 md5가 전부 일치했다.

## 여기 있는데 왜 PVC로도 주입하나

**이 디렉터리는 이미지에 들어가지 않는다.** `.dockerignore`가 `model/`을 빼기 때문에
빌드 컨텍스트에도 오르지 않는다. 가중치를 이미지에 구우면 모델을 바꿀 때마다 사이드카
이미지를 다시 빌드해야 하고, 서비스 넷이 같은 이미지를 쓰므로 한 서비스의 모델 교체가
전체 재배포가 된다.

런타임에는 NFS PVC가 `/app/model`로 마운트된다(`k8s/model/README.md`). 그러니 여기 있는
파일은 **PVC에 올릴 원본**이고, 저장소는 그 원본의 보관처다. 둘이 어긋나면 클러스터가
쓰는 것은 PVC 쪽이다.

## 배포 (저장소 → NFS)

```sh
scp -r servicemesh/data-plane/model/* capstone:/srv/deepmesh/model/
kubectl -n deepmesh rollout restart deploy/auth-service   # 바꾼 서비스만
```

`Detector`가 기동 시 한 번 로드해 메모리에 들고 있어서, 파일만 바꾸면 이미 떠 있는
프로세스는 옛 모델을 계속 쓴다. 그래서 재시작이 필요하다.

## 모델이 갱신되면

`feat/models`에서 네 서비스의 `<svc>_model/` 네 파일을 그대로 덮어쓰고, 위 출처 표를
갱신한 뒤 배포한다. 컨버터·디텍터 코드가 함께 바뀌었다면
`servicemesh/data-plane/detection/README.md`의 재수입 절차도 같이 밟아야 한다 —
특징 길이가 바뀌면 기동 시 `ValueError`로 드러나지만, 축의 의미만 바뀐 경우는 조용히
틀린 판정이 된다.

`teacher.pth`와 `student.pth`(학습 산출물)는 가져오지 않는다. 사이드카가 로드하는 것은
TorchScript인 `student_ts.pt`뿐이고, 나머지는 재학습에서만 쓰여 `feat/models`에 남는다.
