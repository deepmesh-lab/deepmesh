# 탐지 모델 볼륨

사이드카가 읽는 학습 모델을 담는 NFS 볼륨이다. 실체는 dev-server의
`/srv/deepmesh/model`이고, 네 서비스가 이 볼륨 하나를 공유한다.

```
/srv/deepmesh/model/
├── auth/auth_model/{student_ts.pt, ocsvm.pkl, threshold.json, eval_results.json}
├── post/post_model/...
├── comment/comment_model/...
└── frontend/frontend_model/...
```

사이드카는 이 볼륨을 `/app/model`에 읽기 전용으로 마운트하고, `MODEL_ROOT`가 그
경로를 가리킨다. `detector.Detector`가 `<MODEL_ROOT>/<svc>/<svc>_model/`을 찾는다
(`servicemesh/data-plane/detection/README.md`).

올릴 파일의 원본은 저장소에 있다 — `servicemesh/data-plane/model/`. 이 볼륨은 그
사본이고, 어긋나면 클러스터가 쓰는 것은 이쪽이다.

## 모델 교체

이미지 재빌드가 필요 없다. dev-server에서 파일만 덮어쓴 뒤 재시작한다.

```bash
scp -r auth capstone:/srv/deepmesh/model/
kubectl -n deepmesh rollout restart deploy/auth-service
```

재시작이 필요한 이유는 `Detector`가 기동 시 한 번 로드해 메모리에 들고 있기
때문이다. 파일만 바꾸면 이미 떠 있는 프로세스는 옛 모델을 계속 쓴다.

## 서버 쪽 구성

dev-server에서 한 번만 해두면 된다.

```bash
sudo apt-get install -y nfs-kernel-server
sudo mkdir -p /srv/deepmesh/model && sudo chown ubuntu:ubuntu /srv/deepmesh/model
echo '/srv/deepmesh/model 192.168.56.0/24(ro,sync,no_subtree_check)' | sudo tee -a /etc/exports
sudo exportfs -ra && sudo systemctl enable --now nfs-kernel-server
```

노드 쪽 `nfs-common`은 `k8s-cluster/scripts/common.sh`의 [6/6] 단계가 설치한다.
그게 빠지면 Pod이 볼륨을 붙이지 못하고 ContainerCreating에서 멈춘다.

export를 `ro`로 둔 것은 사이드카가 읽기만 하기 때문이다. 모델 적재는 NFS가 아니라
dev-server의 로컬 파일시스템에서 직접 한다.
