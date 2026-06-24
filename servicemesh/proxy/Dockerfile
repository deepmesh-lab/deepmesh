FROM python:3.11-slim

WORKDIR /app

# iptables 설치 (init container에서 사용)
RUN apt-get update && apt-get install -y iptables && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# iptables OUTPUT 규칙에서 uid 1337로 루프백 제외
RUN groupadd -g 1337 proxy && useradd -u 1337 -g proxy -s /bin/sh proxy

# 모델 마운트 위치
VOLUME ["/app/model"]

EXPOSE 9011

USER proxy
CMD ["python", "main.py"]
