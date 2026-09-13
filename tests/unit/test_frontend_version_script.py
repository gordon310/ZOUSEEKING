import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "deploy" / "version-frontend-assets.py"
spec = importlib.util.spec_from_file_location("frontend_version", SCRIPT)
frontend_version = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(frontend_version)


def test_rewrite_module_imports_updates_existing_and_bare_versions():
    source = 'import "./api-client.js"; import "./core.js?v=old";'
    assert frontend_version.rewrite_module_imports(source, "new") == (
        'import "./api-client.js?v=new"; import "./core.js?v=new";'
    )
