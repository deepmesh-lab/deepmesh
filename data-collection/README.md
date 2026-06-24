# 데이터 수집 가이드

## 사전 조건
- K8s Pod 이미지에 tcpdump 설치 필요
- Locust: `pip install locust==2.29.1`

## 1. 정상 트래픽 생성

```bash
# auth-service 트래픽 (300초)
locust -f locust/auth_locustfile.py \
  --host http://<NODE_IP>:30080 \
  --users 20 --spawn-rate 4 --run-time 300s --headless

# post-service 트래픽
locust -f locust/post_locustfile.py \
  --host http://<NODE_IP>:30080 \
  --users 20 --spawn-rate 4 --run-time 300s --headless
```

## 2. 패킷 캡처 (별도 터미널에서 동시 실행)

```bash
./capture.sh auth-service 300
./capture.sh post-service 300
./capture.sh comment-service 300
```

## 3. 결과물
- `pcap/auth-service/*.pcap`
- `pcap/post-service/*.pcap`
- `pcap/comment-service/*.pcap`
