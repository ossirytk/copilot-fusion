import asyncio

from pytest import MonkeyPatch
from copilot_fusion.server import create_server
from copilot_fusion_shared import FusionConfig


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


def test_api_compat_matrix_reports_known_gaps() -> None:
    async def _read() -> dict[str, object]:
        server = create_server()
        result = await server.call_tool("fusion_api_compat", {})
        return dict(result.structured_content)

    matrix = asyncio.run(_read())
    domains = matrix["domains"]
    assert domains["contextwell"]["missing"] == []
    assert domains["gitpilot"]["missing"] == []
    assert domains["toolpilot"]["missing"] == []
