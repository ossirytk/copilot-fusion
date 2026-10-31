import asyncio

import pytest
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
    assert "terminal_exec" in names
    assert "terminal_start" in names
    assert "terminal_status" in names
    assert "terminal_stop" in names
    assert "fusion_health" in names
    assert "symbol_search" in names
    assert "fusion_api_compat" not in names


def test_config_toggles_disable_domains() -> None:
    async def _read() -> list[str]:
        server = create_server(FusionConfig(enable_core=False, enable_git=False, enable_tools=True))
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    names = asyncio.run(_read())
    assert "fs_glob" in names
    assert "terminal_exec" in names
    assert "terminal_start" in names
    assert "terminal_status" in names
    assert "terminal_stop" in names
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
    assert "terminal_exec" in names
    assert "remember" not in names
    assert "git_status" not in names


def test_invalid_terminal_env_does_not_break_server_startup(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FUSION_EXEC_ALLOWLIST", "{not-json")
    names = _tool_names()
    assert "fs_glob" in names
    assert "terminal_exec" not in names
    assert "terminal_start" not in names
    assert "terminal_status" not in names
    assert "terminal_stop" not in names


def test_core_profile_registers_only_memory_and_navigation() -> None:
    server = create_server(FusionConfig(profile="core"))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"remember", "recall", "symbol_search", "fusion_health"} <= names
    assert not names & {"git_status", "fs_glob", "read_file", "diff_staged", "terminal_exec", "apply_text_patch"}


def test_core_profile_health_reports_only_available_domains() -> None:
    async def _read() -> dict:
        result = await create_server(FusionConfig(profile="core")).call_tool("fusion_health", {})
        payload = result.structured_content
        if isinstance(payload, dict) and set(payload) == {"result"}:
            payload = payload["result"]
        return payload

    health = asyncio.run(_read())
    assert health["domains"] == {"core": True, "git": False, "tools": True, "diff": False}


def test_profile_env_validation(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("FUSION_PROFILE", "core")
    assert FusionConfig.from_env().profile == "core"
    monkeypatch.setenv("FUSION_PROFILE", "bogus")
    with pytest.raises(ValueError):
        FusionConfig.from_env()


def test_removed_tools_stay_removed() -> None:
    names = set(_tool_names())
    removed = {
        "fs_tree",
        "json_select",
        "yaml_select",
        "file_hash",
        "remember_file",
        "remember_batch",
        "apply_text_patch_batch",
        "diff_files",
        "fusion_core_health",
        "fusion_tools_health",
        "fusion_diff_health",
    }
    assert not names & removed
