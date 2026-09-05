"""Tests for Jujutsu (jj) and Git colocation support."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

import pytest
from contextwell_git.detection import detect_vcs_backend, find_git_root, find_jj_root, is_jj_available
from copilot_fusion.server import create_server


def _call(tool: str, args: dict | None = None) -> object:
    async def _run() -> object:
        server = create_server()
        result = await server.call_tool(tool, args or {})
        payload = result.structured_content
        if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
            return payload["result"]
        return payload

    return asyncio.run(_run())


def _init_colocated_repo(tmp_path: str) -> None:
    """Initialize a colocated Git and Jujutsu repository."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["jj", "git", "init", "--colocate"], cwd=tmp_path, check=True, capture_output=True)


def test_detection_functions() -> None:
    """Test detection helpers in isolated environments."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        # Empty directory: no git, no jj
        assert find_jj_root(path) is None
        assert find_git_root(path) is None
        assert detect_vcs_backend(path) == "git"

        # Git only
        (path / ".git").mkdir()
        assert find_git_root(path) == path
        assert find_jj_root(path) is None
        assert detect_vcs_backend(path) == "git"

        # JJ + Git
        (path / ".jj").mkdir()
        assert find_jj_root(path) == path
        assert find_git_root(path) == path
        if is_jj_available():
            assert detect_vcs_backend(path) == "jj"


def test_detection_in_subdirectory() -> None:
    """Test finding roots from subdirectories."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        (path / ".jj").mkdir()
        sub = path / "a" / "b"
        sub.mkdir(parents=True)
        assert find_jj_root(sub) == path


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_health_check() -> None:
    """fusion_git_health reports jj availability and ready status."""
    health = _call("fusion_git_health")
    assert isinstance(health, dict)
    assert health.get("domain") == "git"
    assert health.get("status") == "ready"
    assert health.get("jj_available") is True
    assert health.get("default_backend") == "jj"


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_status_and_commit_flow() -> None:
    """Test git_status and git_commit in a colocated repo."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)

        # 1. Initial status on clean colocated repo
        st1 = _call("git_status", {"path": tmp})
        assert isinstance(st1, dict)
        assert st1.get("backend") == "jj"
        assert "change_id" in st1
        assert "commit_id" in st1
        assert st1.get("is_conflicted") is False

        # 2. Add file and commit
        (Path(tmp) / "hello.txt").write_text("hello jj\n")
        cm = _call("git_commit", {"path": tmp, "message": "feat: add hello.txt"})
        assert isinstance(cm, dict)
        assert cm.get("backend") == "jj"

        # 3. Status after commit
        st2 = _call("git_status", {"path": tmp})
        assert isinstance(st2, dict)
        assert st2.get("backend") == "jj"
        assert st2.get("is_empty") is True


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_diff_and_show() -> None:
    """Test git_diff and git_show in a colocated repo."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        file_path = Path(tmp) / "file.txt"
        file_path.write_text("line 1\n")
        _call("git_commit", {"path": tmp, "message": "initial"})

        # Make modifications
        file_path.write_text("line 1\nline 2\n")

        # Diff
        diff_res = _call("git_diff", {"path": tmp})
        assert isinstance(diff_res, dict)
        assert diff_res.get("backend") == "jj"
        assert "line 2" in str(diff_res.get("diff", ""))

        # Diff filtered by file
        diff_file = _call("git_diff", {"path": tmp, "file": "file.txt"})
        assert isinstance(diff_file, dict)
        assert "line 2" in str(diff_file.get("diff", ""))

        # Show HEAD (parent commit)
        show_res = _call("git_show", {"path": tmp, "ref": "HEAD"})
        assert isinstance(show_res, dict)
        assert show_res.get("backend") == "jj"
        assert "initial" in str(show_res.get("show", ""))


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_log_formatting() -> None:
    """Test git_log in a colocated repo with limit and filters."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        (Path(tmp) / "a.txt").write_text("a\n")
        _call("git_commit", {"path": tmp, "message": "commit one"})
        (Path(tmp) / "b.txt").write_text("b\n")
        _call("git_commit", {"path": tmp, "message": "commit two"})

        # Oneline log
        log_res = _call("git_log", {"path": tmp, "limit": 5, "oneline": True})
        assert isinstance(log_res, dict)
        assert log_res.get("backend") == "jj"
        raw = str(log_res.get("raw", ""))
        assert "commit one" in raw
        assert "commit two" in raw

        # File filtered log
        log_a = _call("git_log", {"path": tmp, "file": "a.txt", "oneline": True})
        assert isinstance(log_a, dict)
        assert "commit one" in str(log_a.get("raw", ""))


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_branch_operations() -> None:
    """Test git_branch (create, list, switch, delete) mapped to bookmarks."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        (Path(tmp) / "a.txt").write_text("a\n")
        _call("git_commit", {"path": tmp, "message": "base"})

        # Create branch (bookmark)
        create_res = _call("git_branch", {"path": tmp, "create": "feature-x"})
        assert isinstance(create_res, dict)
        assert "error" not in create_res

        # List branches
        list_res = _call("git_branch", {"path": tmp})
        assert isinstance(list_res, dict)
        assert list_res.get("backend") == "jj"
        branches = list_res.get("branches", [])
        assert "feature-x" in branches

        # Switch to branch
        switch_res = _call("git_branch", {"path": tmp, "switch": "feature-x"})
        assert isinstance(switch_res, dict)
        assert "error" not in switch_res

        # Delete branch
        del_res = _call("git_branch", {"path": tmp, "delete": "feature-x"})
        assert isinstance(del_res, dict)
        assert "error" not in del_res


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_reset_and_restore() -> None:
    """Test git_reset mapped to jj restore."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        target = Path(tmp) / "tracked.txt"
        target.write_text("original\n")
        _call("git_commit", {"path": tmp, "message": "initial"})

        # Mutate
        target.write_text("corrupted\n")

        # Reset specific file
        res = _call("git_reset", {"path": tmp, "ref": "HEAD", "files": ["tracked.txt"]})
        assert isinstance(res, dict)
        assert "error" not in res
        assert target.read_text() == "original\n"


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_tags_and_remotes() -> None:
    """Test git_tag and git_remote in colocated repo."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        (Path(tmp) / "a.txt").write_text("a\n")
        _call("git_commit", {"path": tmp, "message": "tagged commit"})

        # Tag create
        tag_c = _call("git_tag", {"path": tmp, "create": "v1.0.0"})
        assert isinstance(tag_c, dict)
        assert "error" not in tag_c

        # Tag list
        tag_l = _call("git_tag", {"path": tmp})
        assert isinstance(tag_l, dict)
        assert "v1.0.0" in str(tag_l.get("tags", []))

        # Tag delete
        tag_d = _call("git_tag", {"path": tmp, "delete": "v1.0.0"})
        assert isinstance(tag_d, dict)
        assert "error" not in tag_d

        # Remote add
        rem_a = _call(
            "git_remote", {"path": tmp, "add_name": "origin", "add_url": "https://github.com/example/colocated.git"}
        )
        assert isinstance(rem_a, dict)
        assert "error" not in rem_a

        # Remote list
        rem_l = _call("git_remote", {"path": tmp})
        assert isinstance(rem_l, dict)
        assert "origin" in str(rem_l.get("remotes", ""))

        # Remote remove
        rem_r = _call("git_remote", {"path": tmp, "remove": "origin"})
        assert isinstance(rem_r, dict)
        assert "error" not in rem_r


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_merge_and_conflict_handling() -> None:
    """Test git_merge with JJ and check conflict metadata."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        (Path(tmp) / "common.txt").write_text("base line\n")
        _call("git_commit", {"path": tmp, "message": "base commit"})
        _call("git_branch", {"path": tmp, "create": "main_bookmark"})

        # Branch 1
        (Path(tmp) / "common.txt").write_text("branch 1 line\n")
        _call("git_commit", {"path": tmp, "message": "b1 commit"})
        _call("git_branch", {"path": tmp, "create": "branch_1"})

        # Branch 2 from main_bookmark
        subprocess.run(["jj", "new", "main_bookmark"], cwd=tmp, check=True, capture_output=True)
        (Path(tmp) / "common.txt").write_text("branch 2 line\n")
        _call("git_commit", {"path": tmp, "message": "b2 commit"})
        _call("git_branch", {"path": tmp, "create": "branch_2"})

        # Merge branch_1 into current (@ which is on top of branch_2)
        merge_res = _call("git_merge", {"path": tmp, "branch": "branch_1", "message": "merge b1 and b2"})
        assert isinstance(merge_res, dict)
        assert merge_res.get("backend") == "jj"

        # Check status detects conflict safely without crashing
        status_res = _call("git_status", {"path": tmp})
        assert isinstance(status_res, dict)
        assert status_res.get("backend") == "jj"
        assert status_res.get("is_conflicted") is True


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_stash_flow() -> None:
    """Test git_stash push and pop in colocated repo."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        (Path(tmp) / "file.txt").write_text("clean\n")
        _call("git_commit", {"path": tmp, "message": "clean"})

        (Path(tmp) / "file.txt").write_text("wip modifications\n")
        push_res = _call("git_stash", {"path": tmp, "message": "wip stash"})
        assert isinstance(push_res, dict)
        assert "error" not in push_res

        pop_res = _call("git_stash", {"path": tmp, "pop": True})
        assert isinstance(pop_res, dict)
        assert "error" not in pop_res


@pytest.mark.skipif(not is_jj_available(), reason="jj executable not available")
def test_jj_reset_invalid_mode() -> None:
    """Test git_reset error handling for invalid mode in JJ."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_colocated_repo(tmp)
        res = _call("git_reset", {"path": tmp, "mode": "invalid-mode"})
        assert isinstance(res, dict)
        assert "error" in res
