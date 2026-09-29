# -*- coding: utf-8 -*-
"""RequestVerifier 판정 케이스 단위 테스트.

실행: python3 servicemesh/control-plane/test_verifier.py
"""

import time

from control_plane import RequestVerifier


def test_first_observation_denied():
    v = RequestVerifier()
    allow, reason = v.verify("auth-service", "10.244.1.15", "POST|post-service:8080|/posts/{id}|q:|b:content")
    assert allow is False, reason


def test_same_pod_repeat_denied():
    v = RequestVerifier()
    v.verify("auth-service", "10.244.1.15", "sig-a")
    allow, reason = v.verify("auth-service", "10.244.1.15", "sig-a")
    assert allow is False, reason


def test_cross_replica_allowed():
    v = RequestVerifier()
    v.verify("auth-service", "10.244.1.15", "sig-a")             # Pod A 첫 관측 → deny
    allow, _ = v.verify("auth-service", "10.244.2.20", "sig-a")  # Pod B 관측 → allow
    assert allow is True
    allow, _ = v.verify("auth-service", "10.244.1.15", "sig-a")  # 이후 A도 계속 allow
    assert allow is True


def test_services_are_isolated():
    # 다른 서비스의 Pod이 같은 시그니처를 관측해도 교차 검증에 포함되면 안 된다
    v = RequestVerifier()
    v.verify("auth-service", "10.244.1.15", "sig-a")
    allow, _ = v.verify("post-service", "10.244.1.16", "sig-a")
    assert allow is False


def test_ttl_cleanup():
    v = RequestVerifier(ttl=0)
    v.verify("auth-service", "10.244.1.15", "sig-a")
    time.sleep(0.01)
    assert v.cleanup_expired() == 1
    # 만료 후에는 다시 첫 관측으로 취급된다
    allow, _ = v.verify("auth-service", "10.244.2.20", "sig-a")
    assert allow is False


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for f in tests:
        f()
        print("OK  {}".format(f.__name__))
    print("{}개 테스트 통과".format(len(tests)))
