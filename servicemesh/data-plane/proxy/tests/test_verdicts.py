# -*- coding: utf-8 -*-
from traffic_handler.ports import Detection
from traffic_handler.verdicts import VerdictStore


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_기록한_판정을_조회한다():
    store = VerdictStore(ttl=10.0)
    store.put(7, Detection(is_malicious=True, score=-0.5))
    assert store.get(7).is_malicious


def test_없는_세션은_None():
    assert VerdictStore(ttl=10.0).get(7) is None


def test_ttl이_지나면_판정이_사라진다():
    clock = FakeClock()
    store = VerdictStore(ttl=10.0, clock=clock)
    store.put(7, Detection(is_malicious=True))

    clock.now = 9.9
    assert store.get(7) is not None
    clock.now = 10.1
    assert store.get(7) is None


def test_후보_id_중_이상_판정이_있으면_그것을_돌려준다():
    store = VerdictStore(ttl=10.0)
    store.put(1, Detection(is_malicious=False))
    store.put(2, Detection(is_malicious=True, score=-0.3))

    detection = store.get_any({1, 2})
    assert detection.is_malicious
    assert detection.score == -0.3


def test_모두_정상이면_정상_판정을_돌려준다():
    store = VerdictStore(ttl=10.0)
    store.put(1, Detection(is_malicious=False))
    assert store.get_any({1, 2}).is_malicious is False


def test_판정이_하나도_없으면_None():
    assert VerdictStore(ttl=10.0).get_any({1, 2}) is None


def test_만료된_판정을_일괄_정리한다():
    clock = FakeClock()
    store = VerdictStore(ttl=5.0, clock=clock)
    store.put(1, Detection(is_malicious=True))
    store.put(2, Detection(is_malicious=False))

    clock.now = 6.0
    assert store.purge_expired() == 2
    assert store.get(1) is None
