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


class PodInfoProvider:
    """서비스별 Pod IP 레지스트리를 유지하고, 각 Proxy에 형제 Pod 목록을 push한다."""

    def __init__(self, v1):
        self._v1 = v1
        self.registry = {}          # {서비스: [{"name": ..., "ip": ...}, ...]}
        self._ip_to_service = {}    # {Pod IP: 서비스}
        self._last_snapshot = None  # 변경 시에만 로그를 남기기 위한 직전 상태

    def service_of(self, pod_ip):
        return self._ip_to_service.get(pod_ip)

    def _list_sidecar_pods(self):
        # kubernetes client는 동기 호출 — run_in_executor로 실행해 이벤트 루프를 막지 않는다
        pods = self._v1.list_namespaced_pod(namespace=NAMESPACE)
        registry = {}
        for pod in pods.items:
            if pod.status is None or pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            if SIDECAR_CONTAINER not in [c.name for c in pod.spec.containers]:
                continue
            service = (pod.metadata.labels or {}).get("app")
            if not service:
                continue
            registry.setdefault(service, []).append(
                {"name": pod.metadata.name, "ip": pod.status.pod_ip}
            )
        return registry

    async def update_registry(self):
        loop = asyncio.get_running_loop()
        try:
            registry = await loop.run_in_executor(None, self._list_sidecar_pods)
        except Exception as exc:
            # 일시적 API 오류로 레지스트리를 비우면 검증이 전부 400이 되므로 기존 상태를 유지한다
            logger.error("Pod 조회 실패 — 기존 레지스트리 유지: %s", exc)
            return

        snapshot = {svc: sorted(p["ip"] for p in pods) for svc, pods in registry.items()}
        if snapshot != self._last_snapshot:
            logger.info("레지스트리 갱신: %s", snapshot)
            self._last_snapshot = snapshot

        self.registry = registry
        self._ip_to_service = {
            p["ip"]: svc for svc, pods in registry.items() for p in pods
        }

    async def push_to_proxies(self, session):
        tasks = []
        for pods in self.registry.values():
            for pod in pods:
                siblings = [p for p in pods if p["ip"] != pod["ip"]]
                tasks.append(self._push_one(session, pod, siblings))
        if tasks:
            await asyncio.gather(*tasks)

    async def _push_one(self, session, pod, siblings):
        url = "http://{}:{}/receive/pods_ip".format(pod["ip"], PROXY_PORT)
        payload = {"name": pod["name"], "ip": pod["ip"], "pods_ip": siblings}
        try:
            async with session.post(url, json=payload, timeout=PUSH_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning("push 실패 %s → status %d", url, resp.status)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            # 기동·종료 중인 Pod은 흔한 경우 — 다음 주기에 자동 재시도되므로 조용히 넘어간다
            pass

    async def run(self):
        async with aiohttp.ClientSession() as session:
            while True:
                await self.update_registry()
                await self.push_to_proxies(session)
                await asyncio.sleep(POLL_INTERVAL)


class RequestVerifier:
    """outbound 내부 요청 시그니처를 서비스 단위로 교차 검증한다.

    판정 상태: {서비스: {시그니처: {"pods": 관측 Pod IP 집합, "last_seen": 단조시각}}}
    """

    def __init__(self, ttl=SIGNATURE_TTL):
        self._ttl = ttl
        self._records = {}

    def verify(self, service, source_ip, signature):
        """(allow, reason)을 반환한다.

        - 첫 관측               → deny (관측 기록만 남김)
        - 같은 Pod에서만 관측    → deny
        - 다른 replica 관측 이력 → allow
        """
        now = time.monotonic()
        signatures = self._records.setdefault(service, {})
        record = signatures.get(signature)

        if record is None:
            signatures[signature] = {"pods": {source_ip}, "last_seen": now}
            return False, "첫 관측 — 다른 replica의 관측 대기"

        record["last_seen"] = now
        if record["pods"] == {source_ip}:
            return False, "같은 Pod에서만 관측된 요청"

        record["pods"].add(source_ip)
        return True, "다른 replica에서 동일 요청 관측됨"

    def cleanup_expired(self):
        now = time.monotonic()
        removed = 0
        for signatures in self._records.values():
            expired = [s for s, r in signatures.items() if now - r["last_seen"] > self._ttl]
            for s in expired:
                del signatures[s]
            removed += len(expired)
        return removed

    async def run_cleanup(self):
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            removed = self.cleanup_expired()
            if removed:
                logger.info("만료 시그니처 %d건 정리", removed)