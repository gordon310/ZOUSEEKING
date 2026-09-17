from pathlib import Path


def test_backend_image_contains_runtime_field_options_file():
    dockerfile = Path("deploy/Dockerfile.backend").read_text(encoding="utf-8")

    assert "COPY web/field-options.json /app/web/field-options.json" in dockerfile
