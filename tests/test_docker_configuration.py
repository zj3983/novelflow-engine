from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKER_FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def test_api_container_installs_and_configures_a_chinese_cover_font() -> None:
    dockerfile = (ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "fonts-noto-cjk" in dockerfile
    assert "--no-install-recommends" in dockerfile
    assert f"NOVEL_COVER_FONT_PATH={DOCKER_FONT_PATH}" in dockerfile
    assert f"NOVEL_COVER_FONT_PATH: {DOCKER_FONT_PATH}" in compose
