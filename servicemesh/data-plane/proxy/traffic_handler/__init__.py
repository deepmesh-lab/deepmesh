# -*- coding: utf-8 -*-
"""deepmesh Traffic Handler — Proxy Container의 트래픽 처리부.

논문 Algorithm 1(Traffic Processing and Intrusion Detection)을 두 경로로 나눠 구현한다.

    detection.py  탐지 경로 — 프레임 → Traffic Converter → Anomaly Detector → 판정 기록
    proxy.py      집행 경로 — 판정을 조회해 Relay / Drop / Forward

Traffic Converter와 Anomaly Detector는 ports.py의 Protocol로만 참조하며, 실제 구현은
실행 시점에 주입한다(stubs.py가 기본 대역).
"""
