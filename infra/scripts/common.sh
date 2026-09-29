#!/bin/bash
# 모든 K8s 노드 공통 사전 설정 (Vagrant provision, root 실행)
set -e

echo "=== [1/6] swap 비활성화 ==="
swapoff -a
sed -ri '/\sswap\s/s/^/#/' /etc/fstab

echo "=== [2/6] 커널 모듈 + sysctl ==="
cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter
cat <<EOF | tee /etc/sysctl.d/99-kubernetes.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system >/dev/null

echo "=== [3/6] containerd 설치 + SystemdCgroup ==="
apt-get update -qq
apt-get install -y -qq containerd
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml >/dev/null
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sed -i 's#sandbox_image = .*#sandbox_image = "registry.k8s.io/pause:3.10"#' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd >/dev/null 2>&1

echo "=== [4/6] Kubernetes apt 저장소 (pkgs.k8s.io v1.33) ==="
apt-get install -y -qq apt-transport-https ca-certificates curl gpg
mkdir -p -m 755 /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/kubernetes-apt-keyring.gpg ]; then
  curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | \
    gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
fi
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /" | \
  tee /etc/apt/sources.list.d/kubernetes.list >/dev/null

echo "=== [5/6] kubelet / kubeadm / kubectl 설치 ==="
apt-get update -qq
apt-get install -y -qq kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl
systemctl enable kubelet >/dev/null 2>&1

echo "=== [6/6] NFS 클라이언트 ==="
# 탐지 모델은 dev-server(192.168.56.1)의 NFS export를 PVC로 마운트해 받는다.
# 이게 없으면 사이드카 Pod이 볼륨을 붙이지 못하고 ContainerCreating에서 멈춘다.
apt-get install -y -qq nfs-common

echo "=== 공통 설정 완료: $(hostname) ==="
