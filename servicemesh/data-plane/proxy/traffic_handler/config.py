# -*- coding: utf-8 -*-
"""Traffic Handler 설정 — 전부 환경변수로 주입한다.

k8s deployment의 sidecar 컨테이너 env와 1:1로 대응한다.
"""

import os


def _int(name, default):
    return int(os.environ.get(name, str(default)))


def _float(name, default):
    return float(os.environ.get(name, str(default)))


def _bool(name, default):
    return os.environ.get(name, "true" if default else "false").lower() in ("1", "true", "yes")


# --- 네트워크 ---------------------------------------------------------------
TARGET_PORT = _int("TARGET_PORT", 8080)        # 메인 컨테이너(백엔드) 포트
PROXY_PORT = _int("PROXY_PORT", 9011)          # iptables가 리다이렉트하는 프록시 포트
POD_IP = os.environ.get("POD_IP", "127.0.0.1")
SERVICE_NAME = os.environ.get("SERVICE_NAME", "unknown")
# downward API로 주입받는 Pod 메타. 텔레메트리 이벤트의 출처 식별에 쓴다.
POD_NAME = os.environ.get("POD_NAME", "unknown")
NODE_NAME = os.environ.get("NODE_NAME", "unknown")
NAMESPACE = os.environ.get("NAMESPACE", "default")

# --- 텔레메트리 (프록시 → 대시보드 백엔드) ---------------------------------
# 비어 있으면 텔레메트리 발신이 통째로 비활성이다.
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TELEMETRY_INTERVAL = _float("TELEMETRY_INTERVAL", 1.0)
TELEMETRY_QUEUE_MAX = _int("TELEMETRY_QUEUE_MAX", 10000)
TELEMETRY_TIMEOUT = _float("TELEMETRY_TIMEOUT", 2.0)

# --- Control Plane ----------------------------------------------------------
CONTROL_PLANE_URL = os.environ.get("CONTROL_PLANE_URL", "http://127.0.0.1:8080").rstrip("/")
VERIFY_TIMEOUT = _float("VERIFY_TIMEOUT", 2.0)
# 검증 실패(타임아웃·오류) 시 동작. 기본은 fail-closed(Drop) — 이상 판정을 이미 받은
# 트래픽이므로 확인되지 않으면 보내지 않는다.
VERIFY_FAIL_OPEN = _bool("VERIFY_FAIL_OPEN", False)

# --- 탐지 경로 --------------------------------------------------------------
# 메인 컨테이너 트래픽(T_main)은 전부 loopback에서 프록시를 거치므로 lo만 캡처하면 된다.
# detection.py의 모듈 주석에 근거를 적어두었다.
SNIFF_IFACE = os.environ.get("SNIFF_IFACE", "lo")
# 세션 판정 유효 기간(초). 지나면 판정 없음(=Forward)으로 되돌아간다.
VERDICT_TTL = _float("VERDICT_TTL", 10.0)
# Converter가 max_sessions를 제공하지 않을 때 쓰는 기본값
DEFAULT_MAX_SESSIONS = _int("MAX_SESSIONS", 1024)

# 탐지 모듈 결합 지점. "패키지.모듈:팩토리" 형식이다.
#   · 분리형 — Converter와 Detector를 각각 지정한다
#   · 융합형 — DETECTION_ENGINE_FACTORY 하나만 지정한다 (변환·판정이 한 호출)
# 셋 다 비어 있으면 탐지 없이 Forward 전용으로 동작한다.
CONVERTER_FACTORY = os.environ.get("CONVERTER_FACTORY", "")
DETECTOR_FACTORY = os.environ.get("DETECTOR_FACTORY", "")
DETECTION_ENGINE_FACTORY = os.environ.get("DETECTION_ENGINE_FACTORY", "")

# --- 탐지 모델 --------------------------------------------------------------
# 위 팩토리가 traffic_handler.detection_binding을 가리킬 때만 읽힌다.
#
# 가중치 루트. <root>/<svc>/<svc>_model/ 구조를 기대한다(detection/README.md 참고).
# 가중치는 저장소에 없고 PVC를 여기에 마운트한다.
MODEL_ROOT = os.environ.get("MODEL_ROOT", "/app/model")
# 모델 디렉터리 이름. k8s는 SERVICE_NAME을 "auth-service"로 주는데 모델 쪽 이름은
# "auth"라 접미사를 뗀다. 이 규칙이 안 맞는 서비스가 생기면 값을 직접 준다.
DETECTION_SERVICE = os.environ.get("DETECTION_SERVICE", "") or SERVICE_NAME.removesuffix("-service")
# vendoring한 탐지 모듈 코드의 위치. 비워두면 detection_binding이 후보 경로에서 찾는다 —
# 리포지토리(data-plane/detection)와 이미지(/app/detection)의 깊이가 달라 하나로
# 고정할 수 없다.
DETECTION_CODE_ROOT = os.environ.get("DETECTION_CODE_ROOT", "")
# 윈도우 버퍼를 들고 있을 세션 수 상한. 세션 id 모듈로 값(max_sessions)과는 다른 수다.
DETECTION_WINDOW_CAP = _int("DETECTION_WINDOW_CAP", 4096)

# --- Relay ------------------------------------------------------------------
RELAY_TIMEOUT = _float("RELAY_TIMEOUT", 3.0)
# 형제 Pod 재요청은 멱등 메서드에만 허용한다. POST를 재실행하면 리소스가 중복 생성된다.
RELAY_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# --- 기타 -------------------------------------------------------------------
MAX_HEADER_BYTES = _int("MAX_HEADER_BYTES", 64 * 1024)
MAX_BODY_BYTES = _int("MAX_BODY_BYTES", 8 * 1024 * 1024)
