# -*- coding: utf-8 -*-
"""시그니처 생성 규칙 v1 — Control Plane API 문서의 표와 예시를 그대로 검증한다."""

from traffic_handler.signature import (
    body_schema, http_signature, normalize_path, query_keys, tcp_signature,
)


class TestNormalizePath:
    def test_숫자_세그먼트는_id로_치환된다(self):
        assert normalize_path("/posts/123") == "/posts/{id}"
        assert normalize_path("/posts/123/comments") == "/posts/{id}/comments"

    def test_uuid_세그먼트는_uuid로_치환된다(self):
        path = "/users/550e8400-e29b-41d4-a716-446655440000"
        assert normalize_path(path) == "/users/{uuid}"

    def test_16자_이상_영숫자_토큰은_token으로_치환된다(self):
        assert normalize_path("/session/aB3dEf9hIjK2mN5p") == "/session/{token}"

    def test_긴_영문_경로명은_그대로_둔다(self):
        # 숫자가 없는 단어는 경로 이름이지 가변값이 아니다
        assert normalize_path("/api/notificationsettings") == "/api/notificationsettings"

    def test_짧은_영숫자는_그대로_둔다(self):
        assert normalize_path("/api/v1/pods") == "/api/v1/pods"


class TestQueryKeys:
    def test_key만_정렬해_남긴다(self):
        assert query_keys("page=2&sort=desc") == "page,sort"
        assert query_keys("sort=asc&page=1") == "page,sort"

    def test_빈_쿼리는_빈_문자열(self):
        assert query_keys("") == ""
        assert query_keys(None) == ""


class TestBodySchema:
    def test_json_body는_key_경로만_남긴다(self):
        body = b'{"content":"hi","authorId":7}'
        assert body_schema(body, "application/json") == "authorId,content"

    def test_중첩_key는_점으로_잇는다(self):
        body = b'{"author":{"id":1,"name":"a"}}'
        assert body_schema(body, "application/json") == "author.id,author.name"

    def test_배열은_대괄호로_표기한다(self):
        body = b'{"tags":["a","b"]}'
        assert body_schema(body, "application/json") == "tags[]"

    def test_json이_아니면_content_type을_쓴다(self):
        assert body_schema(b"a=1&b=2", "application/x-www-form-urlencoded") == \
            "application/x-www-form-urlencoded"

    def test_body가_없으면_빈_문자열(self):
        assert body_schema(b"", "application/json") == ""

    def test_json이라_선언했지만_깨진_경우_content_type으로_대체(self):
        assert body_schema(b"{not json", "application/json") == "application/json"


class TestHttpSignature:
    def test_문서의_예시와_일치한다(self):
        signature = http_signature(
            "POST", "post-service:8080", "/posts/123/comments?page=2&sort=desc",
            b'{"content":"hi","authorId":7}', "application/json",
        )
        assert signature == (
            "POST|post-service:8080|/posts/{id}/comments|q:page,sort|b:authorId,content"
        )

    def test_같은_종류의_요청은_id와_값이_달라도_같은_시그니처가_된다(self):
        a = http_signature("POST", "post-service:8080", "/posts/123/comments?page=2&sort=desc",
                           b'{"content":"hi","authorId":7}', "application/json")
        b = http_signature("POST", "post-service:8080", "/posts/456/comments?page=1&sort=asc",
                           b'{"content":"hello","authorId":9}', "application/json")
        assert a == b

    def test_k8s_api_호출은_다른_시그니처가_된다(self):
        normal = http_signature("GET", "post-service:8080", "/api/posts/1")
        attack = http_signature("GET", "10.96.0.1:443", "/api/v1/secrets")
        assert attack == "GET|10.96.0.1:443|/api/v1/secrets|q:|b:"
        assert attack != normal


def test_tcp_시그니처는_목적지만_담는다():
    assert tcp_signature("10.96.0.10", 3306) == "TCP|10.96.0.10:3306"
