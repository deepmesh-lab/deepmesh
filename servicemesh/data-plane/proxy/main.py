# -*- coding: utf-8 -*-
"""Proxy Container 엔트리포인트.

    python3 main.py

환경변수는 traffic_handler/config.py 참고. 기본값은 탐지 모듈 없이(Forward 전용)
프록시 경로만 검증할 수 있게 맞춰져 있다.
"""

import asyncio
import time
import importlib
import logging

from traffic_handler import config
from traffic_handler.adapter import (
    DetectionAdapter, FusedDetectionAdapter, NullDetectionAdapter,
)
from traffic_handler.control_plane import ControlPlaneClient
from traffic_handler.detection import DetectionPipeline
from traffic_handler.original_dst import OriginalDstRegistry
from traffic_handler.packet_source import AfPacketSource
from traffic_handler.peers import PeerRegistry
from traffic_handler.proxy import HandlerConfig, TrafficHandler
from traffic_handler.relay import RelayClient
from traffic_handler.telemetry import TelemetryClient
from traffic_handler.verdicts import VerdictStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("traffic-handler")


def load_factory(spec):
    """"패키지.모듈:팩토리" 문자열로 실제 구현을 만든다."""
    module_name, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)()


def build_adapter():
    """환경변수를 보고 종단 어댑터를 고른다.

    융합형(DETECTION_ENGINE_FACTORY)이 지정돼 있으면 그쪽이 우선이다.
    """
    if config.DETECTION_ENGINE_FACTORY:
        return FusedDetectionAdapter(load_factory(config.DETECTION_ENGINE_FACTORY))
    if config.CONVERTER_FACTORY and config.DETECTOR_FACTORY:
        return DetectionAdapter(
            load_factory(config.CONVERTER_FACTORY), load_factory(config.DETECTOR_FACTORY)
        )
    return NullDetectionAdapter(config.DEFAULT_MAX_SESSIONS)


async def main():
    adapter = build_adapter()
    logger.info(
        "탐지 접점: %s (max_sessions=%d)", type(adapter).__name__, adapter.max_sessions
    )

    verdicts = VerdictStore(ttl=config.VERDICT_TTL)
    # 집행 경로가 원래 목적지를 등록하고 탐지 경로가 읽는다. TTL은 판정 유효기간과 같은
    # 척도로 두면 충분하다(연결 하나의 수명보다 길기만 하면 된다).
    original_dst_registry = OriginalDstRegistry(ttl=config.VERDICT_TTL, clock=time.monotonic)
    peers = PeerRegistry()
    control_plane = ControlPlaneClient(
        config.CONTROL_PLANE_URL, config.POD_IP, config.VERIFY_TIMEOUT, config.VERIFY_FAIL_OPEN
    )
    relay_client = RelayClient(
        peers, config.TARGET_PORT, config.RELAY_TIMEOUT, config.MAX_BODY_BYTES
    )
    telemetry = TelemetryClient(
        config.DASHBOARD_URL,
        proxy_meta={
            "serviceName": config.SERVICE_NAME,
            "podName": config.POD_NAME,
            "podIp": config.POD_IP,
            "nodeName": config.NODE_NAME,
            "namespace": config.NAMESPACE,
        },
        interval=config.TELEMETRY_INTERVAL,
        queue_max=config.TELEMETRY_QUEUE_MAX,
        timeout=config.TELEMETRY_TIMEOUT,
    )
    logger.info(
        "텔레메트리: %s", config.DASHBOARD_URL if telemetry.enabled else "비활성(DASHBOARD_URL 없음)"
    )

    handler_config = HandlerConfig(
        pod_ip=config.POD_IP,
        service_name=config.SERVICE_NAME,
        target_port=config.TARGET_PORT,
        proxy_port=config.PROXY_PORT,
        max_sessions=adapter.max_sessions,
        max_header_bytes=config.MAX_HEADER_BYTES,
        max_body_bytes=config.MAX_BODY_BYTES,
        verdict_wait=config.VERDICT_WAIT,
        verdict_poll=config.VERDICT_POLL,
        relay_safe_methods=config.RELAY_SAFE_METHODS,
    )
    handler = TrafficHandler(
        handler_config, verdicts, peers, control_plane, relay_client,
        telemetry=telemetry, original_dst_registry=original_dst_registry,
    )

    pipeline = DetectionPipeline(
        AfPacketSource(config.SNIFF_IFACE), adapter, verdicts,
        config.TARGET_PORT, config.PROXY_PORT,
        telemetry=telemetry, original_dst=original_dst_registry,
    )
    # 캡처를 시작하지 못하면(NET_RAW capability 없음 등) 탐지 스레드가 로그를 남기고
    # 종료한다. 프록시는 Forward 전용으로 계속 동작한다.
    pipeline.start()

    # 텔레메트리 배치 전송 루프 (DASHBOARD_URL 없으면 즉시 반환)
    telemetry_task = asyncio.create_task(telemetry.run())

    server = await asyncio.start_server(handler.handle, "0.0.0.0", config.PROXY_PORT)
    logger.info(
        "Traffic Handler 시작 — :%d (service=%s, pod=%s, target=:%d, control-plane=%s)",
        config.PROXY_PORT, config.SERVICE_NAME, config.POD_IP,
        config.TARGET_PORT, config.CONTROL_PLANE_URL,
    )
    try:
        async with server:
            await server.serve_forever()
    finally:
        telemetry_task.cancel()
        pipeline.stop()
        await control_plane.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("사용자 종료")
