FROM python:3.11-slim

WORKDIR /app

# iptables(init container 용) + gcc(C 파서 빌드)
RUN apt-get update && apt-get install -y iptables gcc libc6-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 패킷 파서 빌드. payload 길이를 바꾸려면 --build-arg PAYLOAD_LEN=512 (모델도 재학습 필요)
ARG PAYLOAD_LEN=1460
RUN gcc -shared -fPIC -O2 -DPAYLOAD_LEN=${PAYLOAD_LEN} \
        -o /app/packet_parser_stack.so packet_parser_stack.c

# iptables OUTPUT owner 매칭용 uid 1337
RUN groupadd -f -g 1337 proxyuser && useradd -u 1337 -g proxyuser -s /bin/sh proxyuser

VOLUME ["/app/model"]
EXPOSE 9011

# raw 소켓(AF_PACKET) 캡처를 위해 k8s securityContext 에서 NET_RAW capability + runAsUser:1337 필요
USER proxyuser
CMD ["python", "main.py"]
