# -*- coding: utf-8 -*-
"""
deepmesh Control Plane — Pod Info Provider + Request Verifier

master 노드에서 호스트 프로세스로 실행한다:
    python3 servicemesh/control-plane/control_plane.py

환경변수:
    NAMESPACE          감시할 네임스페이스           (기본: deepmesh)
    LISTEN_PORT        API 서버 포트                 (기본: 8080)
    POLL_INTERVAL      Pod 폴링·push 주기(초)        (기본: 10)
    PROXY_PORT         Proxy 주소록 수신 포트         (기본: 9011)
    SIDECAR_CONTAINER  sidecar 컨테이너 이름          (기본: reverse-proxy)
    SIGNATURE_TTL      시그니처 기록 만료(초)         (기본: 600)

API:
    POST /verify/request   outbound 내부 요청 검증 (Proxy → Control Plane)
    GET  /status           생존 여부 + Pod 레지스트리 스냅샷 (수동 점검·실험 스크립트용)
"""

import asyncio
import logging
import os
import time

import aiohttp
from aiohttp import web
from kubernetes import client, config


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("control-plane")


NAMESPACE = os.environ.get("NAMESPACE", "deepmesh")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8080"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
PROXY_PORT = int(os.environ.get("PROXY_PORT", "9011"))
SIDECAR_CONTAINER = os.environ.get("SIDECAR_CONTAINER", "reverse-proxy")
SIGNATURE_TTL = int(os.environ.get("SIGNATURE_TTL", "600"))

CLEANUP_INTERVAL = 60
PUSH_TIMEOUT = aiohttp.ClientTimeout(total=3)

