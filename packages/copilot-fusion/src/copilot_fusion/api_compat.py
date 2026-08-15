"""API compatibility matrix for merged tool domains."""

from __future__ import annotations

from dataclasses import dataclass

from copilot_fusion_shared import FusionConfig

CONTEXTWELL_TOOLS = {
    "remember",
    "recall",
    "forget",
    "list_memories",
    "update",
    "remember_file",
    "remember_batch",
    "compress_memories",
    "export_memories",
    "memory_stats",
    "purge_expired",
    "reembed_all",
}

GITPILOT_TOOLS = {
    "git_status",
    "git_diff",
    "git_commit",
    "git_log",
    "git_show",
    "git_branch",
    "git_merge",
    "git_stash",
    "git_reset",
    "git_tag",
    "git_remote",
    "git_fetch",
    "git_pull",
    "git_push",
    "gh_pr_create",
    "gh_pr_list",
    "gh_pr_view",
    "gh_issue_create",
    "gh_issue_list",
    "gh_issue_view",
}

TOOLPILOT_TOOLS = {
    "fs_glob",
    "fs_tree",
    "text_search",
    "read_file",
    "json_select",
    "yaml_select",
    "file_hash",
    "git_log",
    "server_stats",
}

CONTEXTWELL_DIFF_TOOLS = {
    "diff_staged",
    "diff_refs",
    "diff_files",
    "summarize_diff",
}


@dataclass(frozen=True, slots=True)
class DomainMatrix:
    expected: list[str]
    present: list[str]
    missing: list[str]


def active_tool_names(config: FusionConfig) -> set[str]:
    """Return expected active tool names for the provided fusion config."""

    names = {"fusion_health", "fusion_api_compat"}
    if config.enable_core:
        names.update(CONTEXTWELL_TOOLS)
        names.add("fusion_core_health")
    if config.enable_git:
        names.update(GITPILOT_TOOLS)
        names.add("fusion_git_health")
    if config.enable_tools:
        names.update(TOOLPILOT_TOOLS)
        names.add("fusion_tools_health")
        # git_log is provided by the git domain to avoid duplicate registration.
        if not config.enable_git:
            names.discard("git_log")
    if config.enable_diff:
        names.update(CONTEXTWELL_DIFF_TOOLS)
        names.add("fusion_diff_health")
    return names


def build_matrix(tool_names: set[str]) -> dict[str, object]:
    """Build compatibility matrix against source server surfaces."""

    domains = {
        "contextwell": CONTEXTWELL_TOOLS,
        "gitpilot": GITPILOT_TOOLS,
        "toolpilot": TOOLPILOT_TOOLS,
        "diffpilot": CONTEXTWELL_DIFF_TOOLS,
    }
    matrix: dict[str, DomainMatrix] = {}
    for domain, expected in domains.items():
        present = sorted(expected & tool_names)
        missing = sorted(expected - tool_names)
        matrix[domain] = DomainMatrix(expected=sorted(expected), present=present, missing=missing)
    return {
        "domains": {
            domain: {
                "expected": value.expected,
                "present": value.present,
                "missing": value.missing,
            }
            for domain, value in matrix.items()
        },
        "known_gaps": {domain: value.missing for domain, value in matrix.items() if value.missing},
    }
