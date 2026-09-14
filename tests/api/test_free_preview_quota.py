from backend.app.auth import require_user
from backend.app.routes.intake import get_preview_quota


def test_preview_route_keeps_authentication_as_the_first_boundary(client, session, monkeypatch):
    from backend.app import main

    main.app.dependency_overrides.pop(require_user, None)
    response = client.post(
        f"/api/intake/sessions/{session['session_id']}/preview",
        headers={"X-Analysis-Session": session["session_token"]},
    )
    assert response.status_code == 401

