"""Text restoration must emit one encoded document across transport chunks."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from .test_streaming_proxy import AUTH, _resp, proxy


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32", "utf-8"])
@pytest.mark.parametrize("chunk_size", [7, 31])
def test_restored_json_retains_one_encoding_stream(monkeypatch, encoding, chunk_size):
    email = "encoding.fixture@example.com"
    expected = {"reply": f"Hello 日本語 — {email}, goodbye."}

    def upstream_response(request):
        scrubbed = json.loads(request.content)["messages"][0]["content"]
        assert email not in scrubbed
        body = json.dumps({"reply": f"Hello 日本語 — {scrubbed}, goodbye."},
                          ensure_ascii=False).encode(encoding)
        return _resp(200, {"content-type": f"application/json; charset={encoding}"},
                     [body[offset:offset + chunk_size]
                      for offset in range(0, len(body), chunk_size)])

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(upstream_response))
    monkeypatch.setattr(proxy, "http_client", upstream)
    monkeypatch.setattr(proxy, "sessions", {})
    client = TestClient(proxy.app)
    try:
        response = client.post("/v1/chat/completions", headers=AUTH,
                               json={"messages": [{"role": "user", "content": email}]})
        assert response.status_code == 200
        restored = response.content.decode(encoding)
        assert restored == json.dumps(expected, ensure_ascii=False)
        assert json.loads(restored) == expected
        assert response.headers["content-type"] == f"application/json; charset={encoding}"
        assert "content-length" not in response.headers
    finally:
        client.close()
        asyncio.run(upstream.aclose())
