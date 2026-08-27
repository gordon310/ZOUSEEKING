import pytest

from backend.app.intake.storage import (
    StorageUnavailable,
    UnsupportedUpload,
    upload_private_file,
    validate_upload,
)


def test_upload_rejects_extension_content_type_mismatch():
    with pytest.raises(UnsupportedUpload):
        validate_upload("contract.pdf", "image/png", b"\x89PNG\r\n\x1a\n")


def test_upload_rejects_bad_magic_bytes():
    with pytest.raises(UnsupportedUpload):
        validate_upload("contract.pdf", "application/pdf", b"not-a-pdf")


def test_storage_error_never_contains_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-value")

    def fail(*args, **kwargs):
        raise OSError("network failure")

    monkeypatch.setattr("backend.app.intake.storage.urlopen", fail)
    with pytest.raises(StorageUnavailable) as error:
        upload_private_file("session-1", "a.pdf", "application/pdf", b"%PDF-broken")
    assert "secret-value" not in str(error.value)
    assert "network failure" not in str(error.value)


def test_valid_pdf_returns_a_server_generated_path(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-value")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    captured = {}

    def succeed(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("backend.app.intake.storage.urlopen", succeed)
    result = upload_private_file("session-1", "contract.pdf", "application/pdf", b"%PDF-1.7")

    assert result.path.startswith("session-1/")
    assert result.path.endswith(".pdf")
    assert captured["timeout"] == 8
    assert captured["request"].get_header("X-upsert") == "false"
