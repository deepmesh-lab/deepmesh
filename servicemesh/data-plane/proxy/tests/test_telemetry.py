# -*- coding: utf-8 -*-
import asyncio

from traffic_handler.ports import Detection, SessionObservation
from traffic_handler.telemetry import (
    TelemetryClient, build_event, session_label,
)

PROXY_META = {"serviceName": "post", "podName": "post-a", "podIp": "10.244.1.5",
              "nodeName": "worker-1", "namespace": "default"}


def obs(direction="REQUEST"):
    return SessionObservation(
        detection=Detection(is_malicious=True, score=-0.41),
        direction=direction,
        src_ip="10.244.1.5", src_port=48812, dst_ip="10.96.0.1", dst_port=443,
    )


def test_url이_없으면_비활성():
    c = TelemetryClient("", PROXY_META)
    assert not c.enabled
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    c.incr("benign")
    # 비활성이면 아무것도 쌓이지 않는다
    assert not c._events and not any(c._counts.values())


def test_세션_라벨은_방향에_무관하다():
    fwd = session_label("10.0.0.1", 1000, "10.0.0.2", 2000)
    bwd = session_label("10.0.0.2", 2000, "10.0.0.1", 1000)
    assert fwd == bwd


def test_build_event가_명세_필드를_채운다():
    e = build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "GET|k:443|/x|q:|b:")
    assert e["direction"] == "REQUEST"
    assert e["verdict"] == "DROP" and e["category"] == "drop"
    assert e["verificationStage"] == "REQUEST_VERIFIER"
    assert e["verificationPassed"] is False
    assert e["modelVerdict"] == "ATTACK"
    assert e["ocsvmScore"] == -0.41
    assert e["srcIp"] == "10.244.1.5" and e["dstPort"] == 443
    # 백엔드가 채우는 필드는 넣지 않는다
    assert "peerServiceName" not in e and "eventId" not in e and "summary" not in e


def test_emit은_이벤트와_집계를_함께_쌓는다():
    c = TelemetryClient("http://backend", PROXY_META)
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    c.incr("benign")
    c.incr("benign")
    assert len(c._events) == 1
    assert c._counts["drop"] == 1
    assert c._counts["benign"] == 2


def test_flush가_페이로드를_구성하고_큐를_비운다():
    sent = {}

    class FakeResp:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def post(self, url, json, timeout):
            sent["url"] = url
            sent["payload"] = json
            return FakeResp()

    c = TelemetryClient("http://backend", PROXY_META)
    c._session = FakeSession()
    c.emit(build_event(obs("RESPONSE"), "RELAY", "relay", "RESPONSE_CONSISTENCY", False, "sig"))
    c.incr("benign")

    asyncio.run(c._flush())

    assert sent["url"] == "http://backend/ingest/events"
    p = sent["payload"]
    assert p["proxy"]["serviceName"] == "post"
    assert p["windowStats"]["relay"] == 1
    assert p["windowStats"]["benign"] == 1
    assert len(p["events"]) == 1
    assert p["events"][0]["category"] == "relay"
    # flush 후 비워진다
    assert not c._events and not any(c._counts.values())


def test_전송_실패해도_예외가_전파되지_않는다():
    class BoomSession:
        def post(self, *a, **k):
            raise RuntimeError("backend down")

    c = TelemetryClient("http://backend", PROXY_META)
    c._session = BoomSession()
    c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig"))
    # 예외 없이 반환 — 트래픽 중계를 막지 않는다
    asyncio.run(c._flush())


def test_큐가_상한을_넘으면_오래된_것부터_버린다():
    c = TelemetryClient("http://backend", PROXY_META, queue_max=3)
    for i in range(5):
        c.emit(build_event(obs(), "DROP", "drop", "REQUEST_VERIFIER", False, "sig-%d" % i))
    assert len(c._events) == 3
    # 가장 오래된 sig-0, sig-1이 밀려나고 최신 3개가 남는다
    assert c._events[0]["signature"] == "sig-2"
