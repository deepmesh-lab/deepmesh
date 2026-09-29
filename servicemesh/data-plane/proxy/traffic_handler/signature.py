# -*- coding: utf-8 -*-
"""Request Verifier 질의용 시그니처 생성 (Control Plane API 문서의 생성 규칙 v1).

목표는 "replica 간에 같아야 할 요청은 같게, 낯선 요청은 다르게" 만드는 것이다.
타임스탬프·토큰·id·body 값 같은 가변값은 빼고 요청의 구조만 남긴다.

HTTP:     <METHOD>|<DST>|<PATH_NORM>|q:<QUERY_KEYS>|b:<BODY_SCHEMA>
비HTTP:   TCP|<원목적지 IP:port>
"""

import json
import re

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
TOKEN_RE = re.compile(r"^[0-9a-zA-Z._-]{16,}$")


def normalize_segment(segment):
    """경로 세그먼트 1개를 정규화한다. /posts/123과 /posts/456을 같게 만들기 위한 것."""
    if segment.isdigit():
        return "{id}"
    if UUID_RE.match(segment):
        return "{uuid}"
    if TOKEN_RE.match(segment) and any(ch.isdigit() for ch in segment):
        # 16자 이상 영숫자 토큰. 순수 영문 단어(예: notifications)는 경로 이름이므로 남긴다.
        return "{token}"
    return segment


def normalize_path(path):
    if not path.startswith("/"):
        path = "/" + path
    parts = path.split("/")
    return "/".join(normalize_segment(p) if p else p for p in parts)


def query_keys(query):
    """쿼리 파라미터의 key만 정렬해 join한다. 값은 가변이라 버린다."""
    if not query:
        return ""
    keys = set()
    for pair in query.split("&"):
        if not pair:
            continue
        keys.add(pair.split("=", 1)[0])
    return ",".join(sorted(keys))


def _json_key_paths(value, prefix=""):
    """JSON 값에서 key 경로만 뽑는다. 배열은 첫 요소만 보고 `[]`로 표기한다."""
    if isinstance(value, dict):
        paths = []
        for key in value:
            child = "{}.{}".format(prefix, key) if prefix else key
            nested = _json_key_paths(value[key], child)
            paths.extend(nested if nested else [child])
        return paths
    if isinstance(value, list):
        child = "{}[]".format(prefix)
        nested = _json_key_paths(value[0], child) if value else []
        return nested if nested else [child]
    return []


def body_schema(body, content_type):
    """body의 구조만 남긴다. JSON이 아니면 Content-Type을 대신 쓴다."""
    if not body:
        return ""
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype and "json" not in ctype:
        return ctype
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ctype
    return ",".join(sorted(set(_json_key_paths(parsed))))


def http_signature(method, host, target, body=b"", content_type=None):
    """HTTP 요청 시그니처.

    host는 Host 헤더(예: post-service:8080)를 쓴다. 목적지 Pod IP는 어느 replica로
    로드밸런싱됐는지에 따라 달라져 replica 간 비교가 깨지므로 쓰지 않는다.
    호출부가 Host 헤더가 없을 때만 원목적지 IP:port를 넘긴다.
    """
    path, _, query = target.partition("?")
    return "{}|{}|{}|q:{}|b:{}".format(
        method.upper(),
        host,
        normalize_path(path),
        query_keys(query),
        body_schema(body, content_type),
    )


def tcp_signature(dst_ip, dst_port):
    """비HTTP TCP(MySQL 등). '이 목적지와 통신하는 것이 정상인가'만 검증한다."""
    return "TCP|{}:{}".format(dst_ip, dst_port)
