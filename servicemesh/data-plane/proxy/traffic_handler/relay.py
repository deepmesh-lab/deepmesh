# -*- coding: utf-8 -*-
"""Relay — 형제 Pod에서 참조 응답을 받아온다 (Algorithm 1 line 11).

Pod Info Provider가 push한 주소록의 형제 Pod에 같은 요청을 다시 보내고, 그 응답을
호출부(proxy.py)가 원 응답과 비교해 교체 여부를 정한다.
"""

import asyncio
import logging

from . import http_message

logger = logging.getLogger("traffic-handler.relay")

# 재요청이 형제 Pod에서 또 Relay를 유발해 연쇄하지 않도록 표시한다
RELAY_MARKER = "X-Deepmesh-Relay"


class RelayClient:
    def __init__(self, peers, target_port, timeout, max_body_bytes):
        self._peers = peers
        self._target_port = target_port
        self._timeout = timeout
        self._max_body = max_body_bytes

    async def fetch_reference(self, request):
        """형제 Pod 중 응답한 첫 번째의 응답을 돌려준다. 못 받으면 None."""
        for peer in self._peers.list():
            response = await self._request_one(peer["ip"], request)
            if response is not None:
                return response
        return None

    async def _request_one(self, ip, request):
        try:
            return await asyncio.wait_for(self._exchange(ip, request), timeout=self._timeout)
        except Exception as exc:
            logger.warning("형제 Pod %s 재요청 실패: %s", ip, exc)
            return None

    async def _exchange(self, ip, request):
        reader, writer = await asyncio.open_connection(ip, self._target_port)
        try:
            probe = http_message.HttpRequest(
                version=request.version,
                headers=list(request.headers),
                body=request.body,
                method=request.method,
                target=request.target,
            )
            probe.set_header(RELAY_MARKER, "1")
            probe.set_header("Connection", "close")
            writer.write(probe.to_bytes())
            await writer.drain()

            buffered = http_message.BufferedReader(reader, self._max_body)
            return await http_message.read_response(buffered, request.method, self._max_body)
        finally:
            writer.close()
