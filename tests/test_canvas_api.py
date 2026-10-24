"""Offline unit tests for Canvas pagination and inventory (no credentials required)."""
import pytest
from coursevault.backend import Session


class FakeResponse:
    def __init__(self, data, link=""):
        self.status = 200
        self.ok = True
        self._data = data
        self.headers = {"link": link}
    def json(self):
        return self._data


class FakeRequest:
    def __init__(self, pages):
        self.pages = pages
        self.seen = []
    def get(self, url, headers=None):
        self.seen.append(url)
        return self.pages[url]


def test_canvas_pagination(tmp_path):
    session = Session(state_file=tmp_path / "state.json")
    base = session.origin
    first = base + "/api/v1/courses?per_page=100"
    second = base + "/api/v1/courses?page=2"
    request = FakeRequest({
        first: FakeResponse([{"id":1}], f'<{second}>; rel="next"'),
        second: FakeResponse([{"id":2}]),
    })
    assert session._all(request, "/api/v1/courses") == [{"id":1},{"id":2}]
    assert request.seen == [first,second]


def test_cross_origin_pagination_rejected(tmp_path):
    session = Session(state_file=tmp_path / "state.json")
    request = FakeRequest({
        session.origin + "/api/v1/courses?per_page=100":
            FakeResponse([], '<https://evil.example/api/v1/courses>; rel="next"')
    })
    with pytest.raises(RuntimeError, match="cross-origin"):
        session._all(request, "/api/v1/courses")


def test_inventory_collects_partial_errors(tmp_path):
    session = Session(state_file=tmp_path / "state.json")
    class FakeSession(Session):
        def _all(self, request, path):
            if path.endswith("/files"): raise RuntimeError("403")
            return []
    result = FakeSession(state_file=tmp_path / "state.json").inventory(None, 42)
    assert result["files"] == []
    assert any("files" in message for message in result["errors"])
