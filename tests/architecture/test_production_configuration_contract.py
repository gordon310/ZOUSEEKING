"""Static checks for the Lightsail production-configuration contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/operations/production-configuration-contract.md"
ENV_EXAMPLE = ROOT / "deploy/.env.example"
COMPOSE = ROOT / "deploy/docker-compose.prod.yml"
RENDER = ROOT / "render.yaml"
SOURCE_ROOTS = (ROOT / "backend/app", ROOT / "scripts")
OPT_IN_ENV_FILE_EXCEPTIONS = {"jpsskill": "./jpsskill.env"}


def _contract_keys() -> set[str]:
    return set(re.findall(r"\| `([A-Z][A-Z0-9_]*)` \|", CONTRACT.read_text()))


def _code_read_keys() -> set[str]:
    keys: set[str] = set()
    patterns = (
        r'os\.(?:getenv|environ\.get)\("([A-Z][A-Z0-9_]*)"',
        r'(?:configured_limit|_configured_positive_float|_configured_positive_int)\("([A-Z][A-Z0-9_]*)"',
    )
    for source_root in SOURCE_ROOTS:
        for path in source_root.rglob("*.py"):
            contents = path.read_text()
            for pattern in patterns:
                keys.update(re.findall(pattern, contents))
    return keys


def test_every_contract_key_is_declared_in_env_example() -> None:
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    assert _contract_keys() <= declared


def test_contract_covers_every_code_read_key() -> None:
    assert _code_read_keys() <= _contract_keys()


def test_compose_services_use_the_production_env_file() -> None:
    compose = COMPOSE.read_text()
    services = set(re.findall(r"^  ([a-z-]+):$", compose, re.MULTILINE))
    assert services == {"api", "jpsskill", "worker", "report-worker", "scheduler", "nginx"}
    env_file_services: set[str] = set()

    for service in services:
        service_match = re.search(
            rf"^  {re.escape(service)}:\n(?P<block>.*?)(?=^  [a-z-]+:|\Z)",
            compose,
            re.MULTILINE | re.DOTALL,
        )
        assert service_match is not None
        service_block = service_match.group("block")
        env_file_match = re.search(r"^    env_file: (.+)$", service_block, re.MULTILINE)
        if env_file_match is None:
            continue

        env_file_services.add(service)
        env_file = env_file_match.group(1).strip()
        if service in OPT_IN_ENV_FILE_EXCEPTIONS:
            assert env_file == OPT_IN_ENV_FILE_EXCEPTIONS[service]
            assert "profiles" in service_block
            assert '"ai"' in service_block
        else:
            assert env_file == ".env"

    assert env_file_services == {"api", "jpsskill", "worker", "report-worker", "scheduler"}


def test_render_manifest_is_staging_only() -> None:
    manifest = RENDER.read_text()
    assert "zouseeking-api-staging" in manifest
    assert not re.search(r"\bproduction\b", manifest, re.IGNORECASE)


def test_contract_records_not_executed_deployment() -> None:
    assert "deployment status: NOT_EXECUTED" in CONTRACT.read_text()


def test_env_example_has_no_real_secret_shapes() -> None:
    example = ENV_EXAMPLE.read_text()
    forbidden = ("sk_live_", "sk_test_", "eyJ", "sb_secret_", "AMAZON")
    assert not any(value in example for value in forbidden)
    assert not re.search(r"https://(?!<project-ref>\.supabase\.co)[^\s/]+\.supabase\.co", example)
