# -*- coding: utf-8 -*-
"""최소한의 HTTP/1.1 메시지 파서.

Traffic Handler가 L7까지 보는 이유는 두 가지다.
  · Drop  — outbound 요청에서 시그니처를 만들려면 method/path/query/body 구조가 필요하다
  · Relay — outbound 응답을 형제 Pod 응답과 비교·교체하려면 메시지 경계를 알아야 한다

HTTP가 아닌 연결(MySQL 등)은 파싱하지 않고 원바이트 그대로 중계한다.
"""

import asyncio
from dataclasses import dataclass, field

CRLF = b"\r\n"
HEADER_END = b"\r\n\r\n"
_METHODS = (
    b"GET", b"POST", b"PUT", b"DELETE", b"HEAD", b"OPTIONS", b"PATCH", b"TRACE", b"CONNECT",
)


class BufferedReader:
    """asyncio.StreamReader 위에 peek 가능한 버퍼를 얹는다."""

    def __init__(self, reader, max_header_bytes):
        self._reader = reader
        self._max_header = max_header_bytes
        self._buf = bytearray()
        self._eof = False

    @property
    def buffered(self):
        return bytes(self._buf)

    async def _fill(self):
        if self._eof:
            return False
        chunk = await self._reader.read(65536)
        if not chunk:
            self._eof = True
            return False
        self._buf.extend(chunk)
        return True

    async def peek(self, size):
        while len(self._buf) < size and await self._fill():
            pass
        return bytes(self._buf[:size])

    async def read_until(self, delim):
        """구분자까지(포함) 읽어 소비한다. 못 찾고 EOF면 None."""
        start = 0
        while True:
            idx = self._buf.find(delim, start)
            if idx != -1:
                end = idx + len(delim)
                data = bytes(self._buf[:end])
                del self._buf[:end]
                return data
            if len(self._buf) > self._max_header:
                raise ValueError("헤더가 너무 큼")
            start = max(0, len(self._buf) - len(delim) + 1)
            if not await self._fill():
                return None

    async def read_exactly(self, size):
        while len(self._buf) < size:
            if not await self._fill():
                raise asyncio.IncompleteReadError(bytes(self._buf), size)
        data = bytes(self._buf[:size])
        del self._buf[:size]
        return data

    async def read_all(self):
        while await self._fill():
            pass
        data = bytes(self._buf)
        self._buf.clear()
        return data

    async def read_some(self):
        if self._buf:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        if not await self._fill():
            return b""
        data = bytes(self._buf)
        self._buf.clear()
        return data

    async def at_eof(self):
        if self._buf:
            return False
        return not await self._fill()


@dataclass
class HttpMessage:
    version: str = "HTTP/1.1"
    headers: list = field(default_factory=list)
    body: bytes = b""

    def header(self, name):
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None

    def set_header(self, name, value):
        lowered = name.lower()
        for i, (key, _) in enumerate(self.headers):
            if key.lower() == lowered:
                self.headers[i] = (key, value)
                return
        self.headers.append((name, value))

    def drop_header(self, name):
        lowered = name.lower()
        self.headers = [(k, v) for k, v in self.headers if k.lower() != lowered]

    def _render(self, start_line):
        lines = [start_line.encode("latin1")]
        for key, value in self.headers:
            lines.append("{}: {}".format(key, value).encode("latin1"))
        return CRLF.join(lines) + HEADER_END + self.body

    def wants_close(self):
        return (self.header("Connection") or "").lower() == "close"


@dataclass
class HttpRequest(HttpMessage):
    method: str = "GET"
    target: str = "/"

    def to_bytes(self):
        return self._render("{} {} {}".format(self.method, self.target, self.version))


@dataclass
class HttpResponse(HttpMessage):
    status: int = 200
    reason: str = "OK"

    def to_bytes(self):
        return self._render("{} {} {}".format(self.version, self.status, self.reason))


def looks_like_http_request(head):
    return any(head.startswith(m + b" ") for m in _METHODS)


def _parse_headers(raw):
    lines = raw.split(CRLF)
    start_line = lines[0].decode("latin1")
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        key, sep, value = line.decode("latin1").partition(":")
        if not sep:
            continue
        headers.append((key.strip(), value.strip()))
    return start_line, headers


async def _read_body(reader, message, max_body_bytes, read_to_eof):
    encoding = (message.header("Transfer-Encoding") or "").lower()
    if "chunked" in encoding:
        body = bytearray()
        while True:
            line = await reader.read_until(CRLF)
            if line is None:
                raise ValueError("chunked 본문이 끊김")
            size = int(line.strip().split(b";")[0] or b"0", 16)
            if size == 0:
                # 트레일러를 마지막 빈 줄까지 걷어낸다
                while True:
                    trailer = await reader.read_until(CRLF)
                    if trailer is None or trailer == CRLF:
                        break
                break
            if len(body) + size > max_body_bytes:
                raise ValueError("본문이 너무 큼")
            body.extend(await reader.read_exactly(size))
            await reader.read_exactly(len(CRLF))
        # 디코딩했으므로 길이 표현을 Content-Length로 바꿔 재직렬화해도 맞게 한다
        message.drop_header("Transfer-Encoding")
        message.body = bytes(body)
        message.set_header("Content-Length", str(len(message.body)))
        return

    length = message.header("Content-Length")
    if length is not None:
        size = int(length)
        if size > max_body_bytes:
            raise ValueError("본문이 너무 큼")
        message.body = await reader.read_exactly(size) if size else b""
        return

    if read_to_eof:
        message.body = await reader.read_all()
        message.set_header("Content-Length", str(len(message.body)))


async def read_request(reader, max_body_bytes):
    """요청 1개를 읽는다. 연결이 끝났으면 None, HTTP가 아니면 ValueError."""
    head = await reader.read_until(HEADER_END)
    if head is None:
        return None
    start_line, headers = _parse_headers(head[: -len(HEADER_END)])
    parts = start_line.split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/"):
        raise ValueError("HTTP 요청이 아님: {!r}".format(start_line[:40]))

    request = HttpRequest(version=parts[2], headers=headers, method=parts[0], target=parts[1])
    await _read_body(reader, request, max_body_bytes, read_to_eof=False)
    return request


async def read_response(reader, request_method, max_body_bytes):
    """응답 1개를 읽는다. 연결이 끝났으면 None."""
    head = await reader.read_until(HEADER_END)
    if head is None:
        return None
    start_line, headers = _parse_headers(head[: -len(HEADER_END)])
    parts = start_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise ValueError("HTTP 응답이 아님: {!r}".format(start_line[:40]))

    status = int(parts[1])
    response = HttpResponse(
        version=parts[0],
        headers=headers,
        status=status,
        reason=parts[2] if len(parts) > 2 else "",
    )
    # 1xx/204/304와 HEAD 응답은 본문이 없다
    if status < 200 or status in (204, 304) or request_method.upper() == "HEAD":
        return response
    await _read_body(reader, response, max_body_bytes, read_to_eof=True)
    return response
