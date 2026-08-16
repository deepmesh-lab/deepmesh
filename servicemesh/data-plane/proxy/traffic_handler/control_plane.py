# -*- coding: utf-8 -*-
"""Request Verifier 질의 클라이언트 (Proxy → Control Plane).

POST /verify/request  {"source_ip", "signature_data"} → {"allow", "reason"}
"""

import logging

import aiohttp

logger = logging.getLogger("traffic-handler.control-plane")


class ControlPlaneClient:
    def __init__(self, base_url, source_ip, timeout, fail_open=False):
        self._url = "{}/verify/request".format(base_url.rstrip("/"))
        self._source_ip = source_ip
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._fail_open = fail_open
        self._session = None

    async def start(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def verify(self, signature):
        """허용 여부를 반환한다.

        Control Plane에 닿지 못하면 fail_open 설정을 따른다. 기본은 fail-closed —
        이미 이상 판정을 받은 트래픽이므로 확인되지 않으면 내보내지 않는다.
        """
        payload = {"source_ip": self._source_ip, "signature_data": signature}
        try:
            await self.start()
            async with self._session.post(self._url, json=payload, timeout=self._timeout) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.warning("검증 응답 %d: %s", resp.status, data.get("reason"))
                    return bool(data.get("allow", False))
                return bool(data.get("allow", False))
        except Exception as exc:
            logger.error("Control Plane 검증 실패(%s) → %s", exc, "허용" if self._fail_open else "Drop")
            return self._fail_open
