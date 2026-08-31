FROM python:3.11-slim

WORKDIR /app

# iptables는 initContainer가 같은 이미지로 iptables.sh를 실행하기 위해 필요하다.
# libcap2-bin은 아래 setcap에 쓴다.
RUN apt-get update && apt-get install -y --no-install-recommends iptables libcap2-bin && \
    rm -rf /var/lib/apt/lists/*

# 빌드 컨텍스트는 data-plane/ 이다. 런타임 의존성과 iptables 스크립트는 data-plane/ 에,
# 프록시 코드는 proxy/ 하위에 있다.
COPY requirements.txt .
# torch는 CPU 전용 휠을 받는다 (requirements.txt의 +cpu 핀과 짝). 기본 PyPI만 보면
# 해당 버전을 찾지 못한다.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY proxy/ ./
COPY detection/ ./detection/
COPY iptables.sh ./

# 모델 가중치는 이미지에 굽지 않는다. PVC를 MODEL_ROOT(기본 /app/model)에 마운트한다 —
# 개선된 모델을 받았을 때 이미지 재빌드 없이 파일만 갈아 끼우기 위해서다.

# iptables OUTPUT의 owner 매칭 대상 uid. iptables.sh의 PROXY_UID와 같아야 한다.
# 이 uid로 '실행'하는 지정은 여기서 하지 않는다 — 같은 이미지를 initContainer가
# iptables 실행에 재사용하는데 그건 root여야 하기 때문이다. 컨테이너별 uid는
# 매니페스트의 securityContext.runAsUser로 정한다 (사이드카만 1337).
RUN groupadd -g 1337 proxyuser && useradd -u 1337 -g proxyuser -s /bin/sh proxyuser

# 패킷 캡처(AF_PACKET)에 필요한 NET_RAW를 python 바이너리에 파일 capability로 붙인다.
#
# securityContext.capabilities.add만으로는 부족하다. runAsUser로 비root 전환이 일어나면
# 커널이 effective set을 비우기 때문에, 컨테이너에 NET_RAW가 부여돼 있어도 uid 1337
# 프로세스는 raw 소켓을 열지 못한다(Operation not permitted). 파일 capability는 exec
# 시점에 bounding set에서 다시 채워주므로 비root에서도 동작한다.
#
# 주의: effective 비트(+e) 때문에 NET_RAW가 bounding set에 없으면 exec 자체가 EPERM으로
# 실패한다("exec /usr/local/bin/python: operation not permitted"). 즉 매니페스트에서
# NET_RAW를 drop하면 조용히 탐지만 꺼지는 게 아니라 사이드카가 기동하지 못한다.
# 탐지가 꺼진 채로 정상처럼 보이는 것보다 눈에 띄게 실패하는 편이 낫다고 보고 이대로 둔다.
RUN setcap cap_net_raw+ep "$(readlink -f "$(command -v python3)")"

EXPOSE 9011

CMD ["python", "main.py"]
