# DeepMesh 클러스터 환경

DeepMesh를 개발하고 검증한 Kubernetes 클러스터의 구성 정보다. [k8s/](../k8s/) 매니페스트가
아래 값들을 전제하므로, 다른 환경에 세울 때 무엇을 맞춰야 하는지 여기서 확인한다.

## 노드 구성

[Vagrantfile](Vagrantfile)이 정의하는 4노드다. provider는 **KVM/libvirt**이며
VirtualBox가 아니다.

| 노드 | IP | vCPU | RAM |
|---|---|---|---|
| k8s-master | 192.168.56.10 | 4 | 8GB |
| k8s-worker1 | 192.168.56.11 | 12 | 24GB |
| k8s-worker2 | 192.168.56.12 | 12 | 24GB |
| k8s-worker3 | 192.168.56.13 | 12 | 24GB |

합산 **40 vCPU / 80GB RAM**이다. 사이드카가 Pod마다 탐지 모델을 적재하기 때문에
worker 메모리 요구가 크다. 사양이 부족하면 `NODES` 배열에서 worker를 줄일 수 있으나,
Request Verifier가 같은 시그니처를 여러 Pod에서 관측했는지로 판정하므로 worker가
하나면 Pod 분산 시나리오 일부가 재현되지 않는다.

## 소프트웨어 버전

| 항목 | 값 |
|---|---|
| Box | bento/ubuntu-24.04 |
| OS / 커널 | Ubuntu 24.04.2 LTS / 6.8.0-64-generic |
| Kubernetes | v1.33.13 |
| 컨테이너 런타임 | containerd 2.2.1 (SystemdCgroup=true) |
| CNI | Calico v3.30.5 (단일 manifest 방식, operator 아님) |

## 네트워크

| 항목 | 값 | 설정 위치 |
|---|---|---|
| 노드 대역 | 192.168.56.0/24 | [Vagrantfile](Vagrantfile) `private_network` |
| Pod 대역 | 10.244.0.0/16 | `kubeadm init --pod-network-cidr` |
| Service 대역 | 10.96.0.0/12 | kubeadm 기본값 |
| API 서버 광고 주소 | 192.168.56.10 | `kubeadm init --apiserver-advertise-address` |

**노드 대역과 Pod 대역은 임의로 바꿀 수 없다.** 매니페스트가 노드 주소를 직접
참조하기 때문이다 - [k8s/configmap.yaml](../k8s/configmap.yaml)의
`CONTROL_PLANE_URL`, [k8s/model/pv.yaml](../k8s/model/pv.yaml)의 NFS 서버 주소,
[k8s/dashboard/backend-deployment.yaml](../k8s/dashboard/backend-deployment.yaml)의
control-plane 주소가 그렇다. 다른 대역을 쓰려면 이 세 곳을 함께 고쳐야 한다.

Pod 대역도 마찬가지다. 사이드카 텔레메트리가 Pod IP로 상대 서비스를 역매핑하므로,
대역이 어긋나면 대시보드 토폴로지의 간선이 전부 external로 뭉친다.

API 서버 광고 주소를 명시한 이유는 Vagrant VM의 첫 NIC가 NAT이고 기본 라우트를
그쪽이 쥐고 있어서다. 생략하면 API 서버가 NAT 주소를 광고해 worker가 붙지 못한다.

## 이 디렉터리가 하는 일

`vagrant up` 하면 [scripts/common.sh](scripts/common.sh)가 각 노드에서 실행되어
노드 사전 설정까지 마친다.

- swap 비활성화, `/etc/fstab` 정리
- 커널 모듈 `overlay`와 `br_netfilter`, sysctl(`bridge-nf-call-iptables`, `ip_forward`)
- containerd 설치 및 `SystemdCgroup=true`
- Kubernetes v1.33 apt 저장소 등록, kubelet, kubeadm, kubectl 설치 후 `apt-mark hold`
- `nfs-common` (모델 볼륨 마운트용)

**클러스터 초기화는 포함되지 않는다.** `kubeadm init`, Calico 설치, worker `join`은
위 네트워크 표의 값으로 수동 수행했다.

## 클러스터 밖에 있는 구성요소

재현할 때 놓치기 쉬운 두 가지다. 둘 다 Kubernetes 리소스가 아니라서
`kubectl get` 으로 보이지 않는다.

**탐지 모델 볼륨** - 모델은 이미지에 굽지 않고 NFS로 마운트한다. VM을 띄운 호스트
머신(노드 대역의 게이트웨이, 위 구성에서는 `192.168.56.1`)이 NFS 서버를 겸한다.
export 설정은 [k8s/model/README.md](../k8s/model/README.md)에 있다. 이게 없으면
사이드카 Pod이 볼륨을 붙이지 못하고 `ContainerCreating`에서 멈춘다.

**Control Plane** - master 노드의 호스트 프로세스로 실행한다.

```bash
pip3 install -r servicemesh/control-plane/requirements.txt
python3 servicemesh/control-plane/control_plane.py
```

`LISTEN_PORT`(기본 8080)가 [k8s/configmap.yaml](../k8s/configmap.yaml)의
`CONTROL_PLANE_URL`과 일치해야 한다. `kubernetes` 파이썬 클라이언트가
`~/.kube/config`를 읽으므로 kubeconfig가 배치된 계정에서 실행한다. 이 프로세스가
없으면 사이드카가 Pod 주소록과 요청 검증을 받지 못한다.
