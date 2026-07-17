#!/usr/bin/env bash
# 논문 C 파서 빌드 — 전처리(preprocess_k8s)·런타임(proxy_detection)이 공유.
# VEC_LEN=1479 (19B 헤더 + 1460B payload), WIN_SIZE=5. 마스킹은 파이썬 로드 시 토글(env MASK_TRANSPORT).
# ⚠️ .so 는 플랫폼 종속 → 로컬(Windows/MinGW)·Colab(Linux) 각각에서 빌드할 것.
set -e
cd "$(dirname "$0")"
gcc -shared -fPIC -O2 -o packet_parser_stack.so packet_parser_stack.c
echo "built: $(pwd)/packet_parser_stack.so"
