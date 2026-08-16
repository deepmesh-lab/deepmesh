# -*- coding: utf-8 -*-
import asyncio

import pytest

from traffic_handler import http_message


class FakeStream:
    """asyncio.StreamReader.read 인터페이스만 흉내낸다."""

    def __init__(self, data, chunk=7):
        self._data = data
        self._chunk = chunk

    async def read(self, _size):
        if not self._data:
            return b""
        head, self._data = self._data[: self._chunk], self._data[self._chunk :]
        return head


def reader_for(data):
    return http_message.BufferedReader(FakeStream(data), 64 * 1024)


def run(coro):
    return asyncio.run(coro)


def test_요청을_파싱한다():
    raw = (b"POST /api/posts HTTP/1.1\r\nHost: post-service:8080\r\n"
           b"Content-Length: 13\r\n\r\n{\"title\":\"a\"}")
    request = run(http_message.read_request(reader_for(raw), 1 << 20))

    assert request.method == "POST"
    assert request.target == "/api/posts"
    assert request.header("Host") == "post-service:8080"
    assert request.body == b'{"title":"a"}'


def test_본문_없는_요청을_파싱한다():
    request = run(http_message.read_request(reader_for(b"GET /api/posts HTTP/1.1\r\n\r\n"), 1 << 20))
    assert request.method == "GET"
    assert request.body == b""


def test_연결이_끝나면_None():
    assert run(http_message.read_request(reader_for(b""), 1 << 20)) is None


def test_http가_아니면_ValueError():
    with pytest.raises(ValueError):
        run(http_message.read_request(reader_for(b"\x05\x01\x00\r\n\r\n"), 1 << 20))


def test_요청을_원형에_가깝게_재직렬화한다():
    raw = b"GET /api/posts?page=1 HTTP/1.1\r\nHost: post-service:8080\r\n\r\n"
    request = run(http_message.read_request(reader_for(raw), 1 << 20))
    assert request.to_bytes() == raw


def test_응답을_파싱한다():
    raw = b'HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nhola'
    response = run(http_message.read_response(reader_for(raw), "GET", 1 << 20))
    assert response.status == 200
    assert response.body == b"hola"


def test_chunked_응답을_content_length로_바꿔_읽는다():
    raw = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
           b"5\r\nhello\r\n5\r\nworld\r\n0\r\n\r\n")
    response = run(http_message.read_response(reader_for(raw), "GET", 1 << 20))

    assert response.body == b"helloworld"
    assert response.header("Transfer-Encoding") is None
    assert response.header("Content-Length") == "10"
    assert b"helloworld" in response.to_bytes()


def test_길이_표시가_없으면_eof까지_읽는다():
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nbody-to-eof"
    response = run(http_message.read_response(reader_for(raw), "GET", 1 << 20))
    assert response.body == b"body-to-eof"


def test_204_응답에는_본문이_없다():
    raw = b"HTTP/1.1 204 No Content\r\n\r\n"
    response = run(http_message.read_response(reader_for(raw), "DELETE", 1 << 20))
    assert response.status == 204
    assert response.body == b""


def test_head_요청의_응답은_본문을_읽지_않는다():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 99\r\n\r\n"
    response = run(http_message.read_response(reader_for(raw), "HEAD", 1 << 20))
    assert response.body == b""


def test_본문이_한도를_넘으면_거부한다():
    raw = b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"x" * 100
    with pytest.raises(ValueError):
        run(http_message.read_response(reader_for(raw), "GET", 10))


def test_http_요청처럼_보이는지_판별한다():
    assert http_message.looks_like_http_request(b"GET /a HT")
    assert http_message.looks_like_http_request(b"POST /a H")
    assert not http_message.looks_like_http_request(b"\x0a\x00\x00\x01")
