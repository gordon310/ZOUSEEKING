import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "staging_realtime_quota_acceptance.py"
SPEC = importlib.util.spec_from_file_location("staging_realtime_quota_acceptance", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_api_request_uses_browser_headers(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return Response()

    monkeypatch.setattr(MODULE, "urlopen", fake_urlopen)

    result = MODULE._request("https://api.zoubeacon.com", "/api/query")

    assert result == {"status": 200, "body": {}}
    assert captured["headers"]["User-agent"].startswith("Mozilla/5.0 (")
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["headers"]["Accept-language"]


def test_restore_limit_falls_back_to_required_final_limit_on_bad_before_response(monkeypatch):
    calls = []

    def fake_set_limit(base_url, key, entitlement_id, value):
        calls.append(value)
        return {"status": 200, "body": []}

    monkeypatch.setattr(MODULE, "_set_limit", fake_set_limit)

    result = MODULE._restore_limit("https://api.zoubeacon.com", "key", "entitlement", {"status": 403, "body": {"message": "forbidden"}})

    assert result == {"status": 200, "body": []}
    assert calls == [3]


def test_main_separates_api_and_supabase_base_urls(monkeypatch):
    calls = []

    monkeypatch.setenv("QUOTA_ACCEPTANCE_BASE_URL", "https://api.example")
    monkeypatch.setenv("QUOTA_ACCEPTANCE_SUPABASE_URL", "https://supabase.example")
    monkeypatch.setenv("QUOTA_ACCEPTANCE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("QUOTA_ACCEPTANCE_USER_A_TOKEN", "user-a")
    monkeypatch.setenv("QUOTA_ACCEPTANCE_USER_B_TOKEN", "user-b")
    monkeypatch.setenv("QUOTA_ACCEPTANCE_ENTITLEMENT_ID", "entitlement")

    def fake_entitlement(base_url, key, entitlement_id):
        calls.append(("entitlement", base_url))
        return {"status": 200, "body": [{"limit_units": 3}]}

    def fake_set_limit(base_url, key, entitlement_id, value):
        calls.append(("set", base_url))
        return {"status": 200, "body": []}

    def fake_query(base_url, token, month, username="", asset_type="塔楼"):
        calls.append(("query", base_url))
        return {"status": 200, "body": {}}

    monkeypatch.setattr(MODULE, "_entitlement", fake_entitlement)
    monkeypatch.setattr(MODULE, "_set_limit", fake_set_limit)
    monkeypatch.setattr(MODULE, "_query", fake_query)
    monkeypatch.setattr(MODULE, "_me", lambda *_args: {"status": 200, "body": {"user_id": "user-id"}})
    monkeypatch.setattr(MODULE, "_delete_owned_rows", lambda *_args: [])
    monkeypatch.setattr(MODULE, "_read_owned_rows", lambda *_args: [])
    monkeypatch.setattr(MODULE, "_delete_auth_user", lambda *_args: {"status": 204, "body": None})
    async def fake_parallel_queries(*_args):
        return []

    monkeypatch.setattr(MODULE, "_parallel_queries", fake_parallel_queries)

    assert MODULE.main() == 0
    assert calls[0] == ("entitlement", "https://supabase.example")
    assert all(base_url == "https://supabase.example" for kind, base_url in calls if kind in {"entitlement", "set"})
    assert all(base_url == "https://api.example" for kind, base_url in calls if kind == "query")


def test_request_rejects_missing_user_agent():
    try:
        MODULE._request("https://api.example", "/api/me", user_agent="")
    except ValueError as exc:
        assert "user-agent" in str(exc).lower()
    else:
        raise AssertionError("missing User-Agent must fail self-check")


def test_uncached_assertion_rejects_cached_response():
    try:
        MODULE._require_uncached({"status": 200, "body": {"cached": True}})
    except AssertionError as exc:
        assert "cached" in str(exc).lower()
    else:
        raise AssertionError("cached response must not count as an uncached call")


def test_delete_user_uses_supabase_base_url_and_reports_actual_response(monkeypatch):
    calls = []

    def fake_request(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {"status": 204, "body": None}

    monkeypatch.setattr(MODULE, "_request", fake_request)
    result = MODULE._delete_auth_user("https://supabase.example", "service", "user-id")

    assert result == {"status": 204, "body": None}
    assert calls == [("https://supabase.example", "/auth/v1/admin/users/user-id", {"method": "DELETE", "token": "service", "user_agent": MODULE.SERVER_USER_AGENT})]
