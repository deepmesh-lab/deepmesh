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
import functools
import json
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
# 레지스트리에 없는 Pod을 만났을 때 즉시 갱신을 허용하는 최소 간격(초).
REFRESH_MIN_INTERVAL = 2.0
PUSH_TIMEOUT = aiohttp.ClientTimeout(total=3)
dumps_kr = functools.partial(json.dumps, ensure_ascii=False)


class PodInfoProvider:
    """서비스별 Pod IP 레지스트리를 유지하고, 각 Proxy에 형제 Pod 목록을 push한다."""

    def __init__(self, v1):
        self._v1 = v1
        self.registry = {}          # {서비스: [{"name": ..., "ip": ...}, ...]}
        self._ip_to_service = {}    # {Pod IP: 서비스}
        self._last_snapshot = None  # 변경 시에만 로그를 남기기 위한 직전 상태
        self._last_refresh = 0.0    # refresh_if_stale 스로틀

    def service_of(self, pod_ip):
        return self._ip_to_service.get(pod_ip)

    async def refresh_if_stale(self, min_interval=REFRESH_MIN_INTERVAL):
        """모르는 Pod IP를 만났을 때만 부르는 즉시 갱신. 짧은 간격은 무시한다.

        폴링이 POLL_INTERVAL(기본 10초)마다 도는데, 그 사이에 뜬 Pod은 레지스트리에
        없어 검증이 통째로 실패한다. 재배포 직후가 정확히 그 구간이다. 매 요청마다
        K8s API를 때리지 않도록 최소 간격을 둔다.
        """
        now = time.monotonic()
        if now - self._last_refresh < min_interval:
            return False
        self._last_refresh = now
        await self.update_registry()
        return True

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

        **죽은 Pod의 IP를 이력에서 걷어내지 않는다.** 그렇게 해봤으나 근거가 없었다.
        IP가 바뀌었다는 것은 컨테이너가 이미지에서 새로 떴다는 뜻이고, 그러면 실행 중인
        프로세스에 붙어 있던 공격자의 발판도 사라진다. 다시 침투해야 하고, 그 정찰은
        어차피 첫 관측부터 시작한다. 이미지 자체가 오염된 경우라면 replica 둘 다
        장악돼 같은 요청을 보내므로 이 방식이 애초에 무력하다.

        반대로 이력을 지우면 손해가 있다. 드물게 일어나는 정상 요청의 기록까지 사라져
        재배포 직후 그 요청들이 한 번씩 다시 차단된다.
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


def build_app(provider, verifier):
    async def verify_request(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {
                    "allow": False, 
                    "reason": "요청 body 파싱 실패"
                }, 
                status=400,
                dumps=dumps_kr
            )

        source_ip = data.get("source_ip")
        signature = data.get("signature_data")
        if not source_ip or not signature:
            return web.json_response(
                {
                    "allow": False, 
                    "reason": "source_ip 또는 signature_data 누락"
                }, 
                status=400,
                dumps=dumps_kr
            )

        service = provider.service_of(source_ip)
        if service is None:
            # 폴링 주기 사이에 뜬 Pod일 수 있다. 한 번 즉시 갱신하고 다시 본다.
            await provider.refresh_if_stale()
            service = provider.service_of(source_ip)

        if service is None:
            return web.json_response(
                {
                    "allow": False,
                    "reason": "레지스트리에 없는 Pod: {}".format(source_ip)
                },
                status=400,
                dumps=dumps_kr
            )

        allow, reason = verifier.verify(service, source_ip, signature)
        logger.info(
            "verify: service=%s src=%s allow=%s sig=%s", service, source_ip, allow, signature
        )
        return web.json_response(
            {
                "allow": allow, 
                "reason": reason
            },
            dumps=dumps_kr
        )

    async def status(request):
        return web.json_response(
            {
                "status": "ok",
                "pods": {
                    svc: [p["ip"] for p in pods] for svc, pods in provider.registry.items()
                },
            },
            dumps=dumps_kr
        )

    app = web.Application()
    app.router.add_post("/verify/request", verify_request)
    app.router.add_get("/status", status)
    return app


async def main():
    # master 노드 호스트 프로세스 실행 전제 — kubeconfig(~/.kube/config)로 인증한다
    config.load_kube_config()
    v1 = client.CoreV1Api()

    provider = PodInfoProvider(v1)
    verifier = RequestVerifier()

    runner = web.AppRunner(build_app(provider, verifier))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", LISTEN_PORT)
    await site.start()
    logger.info(
        "Control Plane 시작 — :%d, namespace=%s, poll=%ds, ttl=%ds",
        LISTEN_PORT, NAMESPACE, POLL_INTERVAL, SIGNATURE_TTL,
    )

    tasks = [
        asyncio.create_task(provider.run()),
        asyncio.create_task(verifier.run_cleanup()),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("사용자 종료")
