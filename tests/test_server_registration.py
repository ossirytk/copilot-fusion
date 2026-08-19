import asyncio

from copilot_fusion.server import create_server
from copilot_fusion_shared import FusionConfig
from pytest import MonkeyPatch


def _tool_names() -> list[str]:
    async def _read() -> list[str]:
        server = create_server()
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    return asyncio.run(_read())


def test_unified_server_has_no_duplicate_tool_names() -> None:
    names = _tool_names()
    assert len(names) == len(set(names))


def test_unified_server_exposes_core_git_and_tools() -> None:
    names = _tool_names()
    assert "remember" in names
    assert "git_status" in names
    assert "fs_glob" in names
    assert "fusion_health" in names
    assert "fusion_api_compat" in names


def test_config_toggles_disable_domains() -> None:
    async def _read() -> list[str]:
        server = create_server(FusionConfig(enable_core=False, enable_git=False, enable_tools=True))
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    names = asyncio.run(_read())
    assert "fs_glob" in names
    assert "remember" not in names
    assert "git_status" not in names


def test_env_config_is_respected(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FUSION_ENABLE_CORE", "0")
    monkeypatch.setenv("FUSION_ENABLE_GIT", "0")
    monkeypatch.setenv("FUSION_ENABLE_TOOLS", "1")

    async def _read() -> list[str]:
        server = create_server()
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    names = asyncio.run(_read())
    assert "fs_glob" in names
    assert "remember" not in names
    assert "git_status" not in names


def _read_compat_matrix() -> dict[str, object]:
    async def _read() -> dict[str, object]:
        server = create_server()
        result = await server.call_tool("fusion_api_compat", {})
        return dict(result.structured_content)

    return asyncio.run(_read())


def test_api_compat_matrix_reports_known_gaps() -> None:
    matrix = _read_compat_matrix()
    domains = matrix["domains"]
    assert domains["contextwell"]["missing"] == []
    assert domains["gitpilot"]["missing"] == []
    assert domains["toolpilot"]["missing"] == []


def test_api_compat_matrix_preferred_surface() -> None:
    matrix = _read_compat_matrix()
    preferred = matrix["preferred_surface"]
    assert isinstance(preferred, list)
    # Core preferred tools are present.
    for tool in ("remember", "recall", "git_status", "fs_glob", "read_file", "diff_staged"):
        assert tool in preferred, f"expected {tool!r} in preferred_surface"


def test_api_compat_matrix_legacy_aliases() -> None:
    matrix = _read_compat_matrix()
    legacy = matrix["legacy_aliases"]
    assert isinstance(legacy, dict)
    # Legacy aliases that are registered must map to a preferred alternative string.
    for name, alt in legacy.items():
        assert isinstance(alt, str) and alt, f"empty alternative for legacy alias {name!r}"
    # git_diff is present and flagged as legacy.
    assert "git_diff" in legacy
