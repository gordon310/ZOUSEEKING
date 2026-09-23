import importlib.util
import re
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "build_web_static_assets.py"
spec = importlib.util.spec_from_file_location("build_web_static_assets", SCRIPT)
build_web_static_assets = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_web_static_assets)


def test_build_command_uses_pinned_local_minifiers_and_keeps_sources_outside_web_root(tmp_path):
    source = tmp_path / "example.js"
    source.write_text("export const example = true;\n", encoding="utf-8")
    command = build_web_static_assets.build_commands(
        source=source,
        output=Path("web/js/example.js"),
        kind="js",
    )

    assert command[0:2] == ("npx", "--no-install")
    assert "terser" in command
    assert Path("web-source").parts[0] != Path("web").name


def test_vector_logo_is_not_passed_through_the_former_raster_alpha_filter():
    web_root = Path(__file__).parents[2] / "web"
    for path in web_root.glob("*.html"):
        source = path.read_text(encoding="utf-8")
        if "logoELE-beacon.svg" in source:
            assert not re.search(
                r'<image\s+href="assets/logoELE-beacon\.svg\?v=[^"]+"[^>]*\sfilter=',
                source,
            ), path
