# collect.md — K8s 트래픽 수집 실행 런북 & 기록

> deepmesh 게시판 MSA에서 KD-CNN+OCSVM 침입탐지용 정상/공격 트래픽(pcap)을 수집하는 전체 절차.
> 실제 실행하며 확정한 환경·명령 기준. (선행: `traffic_collect.md`, `modify_plan.md`, 논문 `grad.pdf`)

---

## 0. 개요

- **결과물**: `result/benign/`(학습), `result/test/benign/`(held-out 평가), `result/test/attack/`(평가) 각 pcap.
- **원칙**:
  - benign만 비지도 학습(OCSVM/KD-CNN), attack은 평가 전용.
  - **net-zero**: 수집 전/후 서비스·DB 상태 무변경 — on_stop 정리 + DB 스냅샷/복원 + RBAC 원복.
  - 캡처는 **pod netns eth0**(Ethernet 프레임, `-s 0` 풀 페이로드) — C 파서 오프셋 정합.
  - confound 제거: benign·attack 공유 헤더·pacing(같은 엔드포인트 대상 시).

---

## 1. 환경 구조

### 1-1. 3계층 머신 구성
```
[Windows PC]  C:\k8s-msa\           ← locust/ 소스·result/ 최종 저장 (개발 머신)
     │ scp
[dev-server]  ~/k8s-cluster/        ← git clone(Vagrantfile+k8s/+msa/), vagrant 호스트, kubectl 없음
     │ vagrant up → VM 4대 / vagrant upload → 파일 전달
[vagrant VMs] k8s-master / k8s-worker1 / k8s-worker2 / k8s-worker3
```
- ⚠️ **`/vagrant`는 VM 간 공유가 아님**(각 VM 로컬 디렉토리). → pcap은 VM별로 저장되고, 회수도 VM별로 한다.
- ⚠️ `vagrant` 명령(ssh/ssh-config/upload/status)은 **반드시 dev-server의 `~/k8s-cluster`(Vagrantfile 폴더)에서** 실행.

### 1-2. 노드 담당 (실측 배치, 2026-07-11 `kubectl get pods -o wide`)

| 노드 | 담당 역할(수집) | 그 노드의 pod(1 replica) |
|---|---|---|
| **k8s-master** | kubectl 실행: 스냅샷/복원, attacker 배포, attack 실행, RBAC. (locust·python 불필요) | control-plane 등 |
| **k8s-worker1** | **benign 부하 실행**(locust) + 백엔드3·mysql 캡처 | auth `10.244.194.87`, post `.89`, comment `.90`, mysql-0 `.79`, control-plane `.82` |
| **k8s-worker2** | (예비) | auth/post/comment/frontend 다른 replica |
| **k8s-worker3** | **attacker pod + frontend 캡처** | frontend `10.244.100.215`, auth `.213`, attacker(배포 시) |

> 💡 worker1에 auth·post·comment·mysql 한 replica씩 모여 있어 백엔드+DB benign을 한 노드에서 캡처.
> ⚠️ Pod IP/노드는 **재스케줄 시 바뀜**(매니페스트에 nodeSelector 없음) → 수집 직전 `kubectl get pods -n deepmesh -o wide` 재확인.

### 1-3. 서비스 접속 정보 (namespace: deepmesh)

| 서비스 | 타입/포트 | ClusterIP | 비고 |
|---|---|---|---|
| auth-service | ClusterIP :8080 | 10.109.47.68 | |
| post-service | ClusterIP :8080 | 10.100.234.122 | |
| comment-service | ClusterIP :8080 | 10.102.52.160 | |
| frontend-service | NodePort 80→30080 | 10.108.184.241 | 외부는 `노드IP:30080` |
| control-plane-service | ClusterIP :8080 | 10.106.18.227 | |
| mysql-service | Headless :3306 | None | `kubectl exec mysql-0`로만 접근 |

> ⚠️ ClusterIP/PodIP(10.x)는 **클러스터 내부 전용**. 외부(노트북)에서 직접 접속 불가.

### 1-4. 디렉토리 구조

**dev-server `~/k8s-cluster/`** (git clone):
```
Vagrantfile
k8s/          # 배포 매니페스트(deployment/service/…)
msa/          # 백엔드·프론트 소스
locust/       # (업로드) common/harness.py, benign/*, attack/*, run.sh, db_snapshot.sh
```

**각 VM `/vagrant/`** (로컬):
```
/vagrant/locust/                      # (동기화 아님, upload로 각 VM에 배치)
/vagrant/result/
├── benign/          benign_<svc>.pcap          # worker1(백엔드3+mysql), worker3(frontend)
├── test/benign/     benign_<svc>.pcap
└── test/attack/     attack_<enum|manipulate|brute>.pcap   # worker3
```
> master는 파일이 `/home/vagrant/locust/locust/`에 있음(vagrant upload가 한 겹 중첩 생성). **master에서 `LOCUST=/home/vagrant/locust/locust`**.

**클러스터(deepmesh)**: auth/post/comment/frontend Deployment(replicas 2), mysql StatefulSet(1), control-plane Deployment, 각 Service, configmap/secret.

---

## 2. 파일 업로드 절차

`locust/`는 Windows에만 있으므로 **Windows → dev-server → VM** 2홉.

```powershell
# [Windows] dev-server 로
scp -r C:\k8s-msa\locust ubuntu@<dev-server-ip>:/home/ubuntu/locust
```
```bash
# [dev-server, ~/k8s-cluster 에서] VM 으로 (master=kubectl용, worker1=benign용)
cd ~/k8s-cluster
vagrant upload /home/ubuntu/locust /home/vagrant/locust k8s-master
vagrant upload /home/ubuntu/locust /home/vagrant/locust k8s-worker1
```
> worker3는 캡처만(ctr+nsenter+tcpdump) 하므로 **locust 파일 불필요**.
> `.pyc`/`__pycache__`가 딸려갔으면: `find <경로> -type d -name __pycache__ -exec rm -rf {} +`.

### worker1 사전 설치 (benign 부하용)
```bash
vagrant ssh k8s-worker1
sudo apt-get update && sudo apt-get install -y python3-pip python3-venv tcpdump
python3 -m venv ~/loadgen && source ~/loadgen/bin/activate
pip install locust requests
```
> ⚠️ 우리 benign 파일은 `from __future__ import annotations`로 Python 3.7+ 호환 처리됨(3.8 우분투에서도 동작).

---

## 3. 부하 시나리오 상세

### 3-1. benign (정상 사용자 north-south + 자동 east-west)
공유 하네스 `common/harness.py`: 혼합 pacing(human 4~12s / active 0.5~2s / burst 0.02~0.3s 균등 추첨) + 공통 헤더(User-Agent `DeepMeshClient/1.0`). 각 파일 자연 4xx 포함.

| 서비스 | 태스크(가중치) | 정리(net-zero) | east-west |
|---|---|---|---|
| **auth** | login(3)·refresh(1)·signup(1)·logout(1)·오타401(1) | 생성 없음 | 없음(validate는 peer가 생성) |
| **post** | list(5)·get(6)·create(1)·update(1)·delete(1)·없는글404(1) | on_stop: 생성글 전량 DELETE | create/update/delete→auth validate, delete→comment 연쇄삭제 |
| **comment** | list(5)·create(2)·update(1)·delete(1)·404(1) | on_stop: 생성댓글+seed글 DELETE | list→post exists, create→auth validate+post exists |
| **frontend** | load_page(5)·spa(3)·favicon(1)·없는자산404(1) | GET만(변경 없음) | 없음(nginx 정적/SPA, proxy_pass 없음) |
| **mysql** | (locust 없음) | — | 백엔드 부하의 JPA 쿼리 부산물로 캡처 |

- 수정 태스크는 **본인 소유 글/댓글만**(IDOR 아님).
- ⚠️ auth `refresh` 가중치는 4→1로 낮춤: `refresh_tokens.token` 인덱스 부재로 부하 시 500이 나서 3% 수준으로 억제.

### 3-2. attack (침해 pod 관점, MITRE)
모두 attacker pod(kali) 안에서 실행. enum/manipulate는 K8s API(SA 토큰), brute는 auth 서비스 대상.

| 시나리오 | 파일 | 태스크 | MITRE | 안전장치 |
|---|---|---|---|---|
| 정보열거 | k8s_enum | pods/services/secrets/deployments/networkpolicies/namespaces/nodes GET + SelfSubjectRulesReview | T1613/T1528 | read-only |
| 리소스조작 | k8s_manipulate | networkpolicy·특권pod·deploy scale **시도** | T1609 | 전부 `?dryRun=All` |
| 스캔+브루트 | k8s_bruteforce | login 브루트(4)·credential stuffing(2)·민감경로 스캔(2) | T1595/T1110 | 실패 로그인·404만, 파괴 없음 |

- enum/manipulate는 **confound 정렬 안 함**(K8s API 대상, benign 등가물 없음).
- **bruteforce는 benign auth와 같은 `/api/auth/login`** → SHARED_HEADERS·혼합 pacing **인라인**으로 정렬(attacker pod엔 common/ 없어서 import 불가 → 값 인라인).
- SelfSubjectRulesReview만 항상 성공(권한 무관), 나머지 열거는 기본 SA면 403 → **옵션 B(RBAC 부여)** 로 200 성공 재현.

### 3-3. 수집 규모 (`run.sh` 기본, 시각화 충분량)
| 단계 | 기본 옵션 |
|---|---|
| benign(학습) | `-u 20 -r 4 -t 600s` (`BENIGN_OPTS`) |
| test benign | `-u 10 -r 3 -t 180s` |
| enum / manipulate | `-u 10 -r 2 -t 300s` (`ATTACK_ENUM_OPTS`/`ATTACK_MANIP_OPTS`) |
| bruteforce | `-u 20 -r 5 -t 300s` (`ATTACK_BRUTE_OPTS`) |

---

## 4. 수집 명령어 (단계별)

### 4-0. 공통 세션 셋업
**worker1/worker3 (캡처·부하용)** — 새 세션마다:
```bash
tmux new -s collect                 # 재접속에도 유지 (Ctrl-b d 로 detach)
LOCUST=$(dirname "$(find /vagrant /home/vagrant -maxdepth 3 -name run.sh 2>/dev/null | head -1)")
CTR="sudo $(sudo find / -maxdepth 5 -name ctr 2>/dev/null | head -1) -n k8s.io"    # crictl 없음 → ctr
get_pid () { for cid in $($CTR containers ls | awk -v i="$1" '$2 ~ i {print $1}'); do
  $CTR task ls | awk -v c="$cid" '$1==c && $3=="RUNNING"{print $2}'; done | head -1; }   # 재시작된 컨테이너 대비 RUNNING만
source ~/loadgen/bin/activate         # worker1 (benign 부하)만
```
**master (kubectl용)**: `LOCUST=/home/vagrant/locust/locust; cd $LOCUST`

### 4-1. DB 스냅샷 (수집 전, net-zero 기준점) — [master]
```bash
cd /home/vagrant/locust/locust && bash run.sh snapshot     # → db_snapshot.sql
```

### 4-2. benign 수집
```bash
# [worker1] 결과폴더 + 캡처 4개 (백엔드3 + mysql)
mkdir -p /vagrant/result/benign
for SVC in auth-service post-service comment-service mysql; do
  PID=$(get_pid "$SVC"); OUT=$([ "$SVC" = mysql ] && echo benign_mysql || echo "benign_${SVC%-service}")
  sudo timeout 2600 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/benign/$OUT.pcap tcp &
done
sudo pgrep -af tcpdump      # 4개 확인
```
```bash
# [worker3] frontend 캡처
mkdir -p /vagrant/result/benign
cid=$($CTR containers ls | awk '$2 ~ "frontend"{print $1}' | head -1)
PID=$($CTR task ls | awk -v c="$cid" '$1==c && $3=="RUNNING"{print $2}')
sudo timeout 2600 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/benign/benign_frontend.pcap tcp &
```
```bash
# [worker1] 부하 (auth→post→comment→frontend 순차, ~40분). 반드시 -t 자연종료(on_stop 정리)
cd $LOCUST && bash run.sh benign
# 끝나면 [worker1]&[worker3] 캡처 종료
sudo pkill -f 'tcpdump.*benign'
```

### 4-3. attack 수집

**(1) [master] attacker pod 배포 (kali, worker3 고정)**
```bash
kubectl -n deepmesh create configmap k8s-attacks --from-file=$LOCUST/attack/
kubectl -n deepmesh run attacker --image=kalilinux/kali-rolling --restart=Never \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"k8s-worker3"},"containers":[{"name":"attacker","image":"kalilinux/kali-rolling","command":["sleep","infinity"],"resources":{"requests":{"cpu":"200m","memory":"256Mi"},"limits":{"cpu":"500m","memory":"512Mi"}},"volumeMounts":[{"name":"f","mountPath":"/mnt"}]}],"volumes":[{"name":"f","configMap":{"name":"k8s-attacks"}}]}}'
kubectl -n deepmesh get pod attacker -o wide                       # Running 대기(이미지 pull)
kubectl -n deepmesh exec attacker -- pip3 install --break-system-packages -q locust requests   # PEP668 회피
kubectl -n deepmesh exec attacker -- locust --version             # 확인
```

**(2) [master] 권한 변경 — 옵션 B (열거/조작 200 성공 재현)**
```bash
kubectl auth can-i --list --as=system:serviceaccount:deepmesh:default -n deepmesh > ~/sa_before.txt   # 원상태 기록
kubectl apply -f - <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: attacker-excessive}
rules:
- apiGroups: [""]
  resources: ["pods","services","secrets","namespaces","nodes"]
  verbs: ["get","list","watch","create"]
- apiGroups: ["apps"]
  resources: ["deployments","deployments/scale"]
  verbs: ["get","list","watch","patch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get","list","watch","create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: attacker-excessive-binding}
subjects: [{kind: ServiceAccount, name: default, namespace: deepmesh}]
roleRef: {kind: ClusterRole, name: attacker-excessive, apiGroup: rbac.authorization.k8s.io}
EOF
kubectl auth can-i list pods --as=system:serviceaccount:deepmesh:default -n deepmesh   # yes 확인
```

**(3) 시나리오별 캡처 (worker3 캡처 시작 → master 실행 → worker3 종료) × 3**
```bash
mkdir -p /vagrant/result/test/attack     # [worker3]
# attacker PID (worker3)
cid=$($CTR containers ls | awk '$2 ~ "kali"{print $1}' | head -1)
PID=$($CTR task ls | awk -v c="$cid" '$1==c && $3=="RUNNING"{print $2}')
```
enum:
```bash
# [worker3]
sudo timeout 600 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/test/attack/attack_enum.pcap tcp &
# [master]
cd /home/vagrant/locust/locust && bash run.sh enum
# [worker3] ★ 반드시 종료 후 다음
sudo pkill -f 'tcpdump.*attack_enum'
```
manipulate / brute: 위와 동일(파일명·`run.sh manipulate`/`brute`로 교체, 각각 종료 pkill).

**(4) [master] 권한 복구 (원상태로)**
```bash
kubectl delete clusterrolebinding attacker-excessive-binding
kubectl delete clusterrole attacker-excessive
kubectl auth can-i list pods --as=system:serviceaccount:deepmesh:default -n deepmesh   # no 확인
diff <(kubectl auth can-i --list --as=system:serviceaccount:deepmesh:default -n deepmesh) ~/sa_before.txt && echo OK
```

**(5) [master] attacker pod·configmap 회수**
```bash
kubectl -n deepmesh delete pod attacker
kubectl -n deepmesh delete configmap k8s-attacks
```

### 4-4. test benign 수집 (독립 held-out)
benign과 동일 절차, **경로 `test/benign/` + 작은 규모**만 다름:
```bash
# [worker1] 캡처 4개 (경로 test/benign, timeout 800)
mkdir -p /vagrant/result/test/benign
for SVC in auth-service post-service comment-service mysql; do
  PID=$(get_pid "$SVC"); OUT=$([ "$SVC" = mysql ] && echo benign_mysql || echo "benign_${SVC%-service}")
  sudo timeout 800 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/test/benign/$OUT.pcap tcp &
done
# [worker3] frontend (test/benign)
mkdir -p /vagrant/result/test/benign
cid=$($CTR containers ls | awk '$2 ~ "frontend"{print $1}' | head -1); PID=$($CTR task ls | awk -v c="$cid" '$1==c && $3=="RUNNING"{print $2}')
sudo timeout 800 nsenter -t "$PID" -n tcpdump -i eth0 -s 0 -w /vagrant/result/test/benign/benign_frontend.pcap tcp &
# [worker1] 작은 부하
BENIGN_OPTS='-u 10 -r 3 -t 180s' bash run.sh benign
# 종료
sudo pkill -f 'tcpdump.*benign'
```

### 4-5. DB 복원 (수집 종료 후, net-zero) — [master]
```bash
cd /home/vagrant/locust/locust && bash run.sh restore     # 스냅샷 시점으로 users/posts/comments 원복 + 카운트 검증
```
> 복원 트래픽은 pcap에 안 잡힘: 캡처는 이미 종료 + 복원은 mysql-0 내부 localhost 소켓(eth0 아님).

---

## 5. pcap 회수

각 VM 로컬에 있으므로 **VM별로** 가져온다.
```bash
# [dev-server, ~/k8s-cluster 에서]
cd ~/k8s-cluster
mkdir -p ~/pcaps/{benign,test_benign,attack}
# 읽기 권한(root 소유 대비)
vagrant ssh k8s-worker1 -c 'sudo chmod a+r /vagrant/result/benign/*.pcap /vagrant/result/test/benign/*.pcap'
vagrant ssh k8s-worker3 -c 'sudo chmod a+r /vagrant/result/benign/*.pcap /vagrant/result/test/benign/*.pcap /vagrant/result/test/attack/*.pcap'
# scp (ssh-config 임시파일 사용 — <(...) 프로세스치환은 scp에서 실패)
for VM in k8s-worker1 k8s-worker3; do vagrant ssh-config $VM > /tmp/$VM.cfg; done
scp -F /tmp/k8s-worker1.cfg 'k8s-worker1:/vagrant/result/benign/*.pcap'       ~/pcaps/benign/
scp -F /tmp/k8s-worker3.cfg 'k8s-worker3:/vagrant/result/benign/*.pcap'       ~/pcaps/benign/
scp -F /tmp/k8s-worker1.cfg 'k8s-worker1:/vagrant/result/test/benign/*.pcap'  ~/pcaps/test_benign/
scp -F /tmp/k8s-worker3.cfg 'k8s-worker3:/vagrant/result/test/benign/*.pcap'  ~/pcaps/test_benign/
scp -F /tmp/k8s-worker3.cfg 'k8s-worker3:/vagrant/result/test/attack/*.pcap'  ~/pcaps/attack/
```
```powershell
# [Windows]
scp -r ubuntu@<dev-server-ip>:~/pcaps/benign      C:\k8s-msa\result\benign
scp -r ubuntu@<dev-server-ip>:~/pcaps/test_benign C:\k8s-msa\result\test\benign
scp -r ubuntu@<dev-server-ip>:~/pcaps/attack      C:\k8s-msa\result\test\attack
```
> scp `-r`로 한 겹 중첩(`test/benign/test_benign/`)되면 평탄화: `mv result/test/benign/test_benign/*.pcap result/test/benign/ && rmdir result/test/benign/test_benign`.

---

## 6. 후처리 (수행 완료)

frontend가 keep-alive라 세션이 극소수 + GRO로 패킷이 커서 pcap이 과대(train 2GB/test 82MB). **세션 해시 샘플은 부적합**(1/14 → 174패킷) → **바이트 예산 연속 구간(prefix)** 으로 다른 pcap 크기에 맞춤(연속 패킷 유지 → 윈도우 유효).
```bash
# 원본 보존
mv result/benign/benign_frontend.pcap       result/benign/benign_frontend_raw.pcap
mv result/test/benign/benign_frontend.pcap  result/test/benign/benign_frontend_raw.pcap
# prefix_mb.py: 캡처순으로 목표 MB까지 유지
python prefix_mb.py result/benign/benign_frontend_raw.pcap      result/benign/benign_frontend.pcap      145
python prefix_mb.py result/test/benign/benign_frontend_raw.pcap result/test/benign/benign_frontend.pcap 30
```
결과: train frontend 152MB(19,367패킷)·test frontend 31.5MB(4,855패킷), datalink=1(Ethernet) 검증 완료.

---

## 7. 최종 result 구조
```
result/
├── benign/          # 학습용 (5)
│   ├── benign_auth.pcap        69 MB
│   ├── benign_post.pcap       150 MB
│   ├── benign_comment.pcap    174 MB
│   ├── benign_mysql.pcap      190 MB
│   ├── benign_frontend.pcap   152 MB  (서브샘플)
│   └── benign_frontend_raw.pcap 2.0 GB (원본)
├── test/benign/     # held-out 평가 (5, 독립 run)
│   ├── benign_auth 18.5 · post 20 · comment 33 · mysql 37 · frontend 31.5 MB (+ _raw 82MB)
└── test/attack/     # 평가 (3)
    └── attack_enum 46 · manipulate 54 · brute 49 MB
```

---

## 8. 남은 단계 (로컬, GPU)

1. **전처리(이미지화)** — 학습=serve 동일 C `.so`:
   - 패킷 → **1479B = 19B 헤더(프로토콜 필드) + 1460B 페이로드**(IP·포트 제외).
   - 세션 = 5-tuple 그룹핑 → **슬라이딩 윈도우 w=5** → **5×1479 grayscale** 이미지.
   - ⚠️ **train/test benign은 별도 run이라 이미 독립**. (한 pcap을 나눌 땐 반드시 세션 단위 분할.)
2. **모델 학습**(benign만): teacher(NT-Xent 대조학습) → student **KD**(MSE) → **OCSVM**(정상만), **서비스별**.
3. **평가**: `test/benign`(FPR) + `test/attack`(recall) → Precision/Recall/ROC-AUC.
   - 목표(논문, 배포용 CNN-2x8): **P 87.4% / R 89.9% / ROC-AUC 95.7%**, 추론 0.518ms/img, E2E **≤14ms·≥600 req/s**.
   - 분포 분리 확인: benign vs attack 임베딩 PCA(이미지화 후).
4. **배포**: 학생 모델 + `.so`를 `deployment-with-sidecar.yaml`의 `reverse-proxy`(`model-pvc`)에 탑재.
   - ⚠️ 재현성: 사이드카 `resources.limits.cpu`가 매니페스트에 없음 → 지연/처리량 재현하려면 `cpu:"1000m"` 추가.

---

## 9. net-zero 체크리스트
- [ ] 수집 전 `run.sh snapshot` (db_snapshot.sql)
- [ ] benign/test benign: `-t`로 자연 종료(on_stop이 글/댓글 삭제) — 강제 kill 금지
- [ ] attack 후 RBAC 원복(`attacker-excessive*` 삭제) → `can-i`가 no
- [ ] attacker pod·configmap 삭제
- [ ] `run.sh restore` (users/posts/comments 스냅샷 복원)
- [ ] pcap 회수 완료 후 필요시 `/vagrant/result` 정리
