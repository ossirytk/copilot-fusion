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

# Full toolpilot surface as registered in contextwell-tools.
# Note: git_log is routed via the git domain when both domains are active.
TOOLPILOT_TOOLS = {
    "fs_glob",
    "fs_tree",
    "text_search",
    "text_compact",
    "text_summarize",
    "apply_text_patch",
    "apply_text_patch_batch",
    "symbol_search",
    "read_file",
    "json_select",
    "yaml_select",
    "file_hash",
    "server_stats",
}

CONTEXTWELL_DIFF_TOOLS = {
    "diff_staged",
    "diff_refs",
    "diff_files",
    "summarize_diff",
}

# ---------------------------------------------------------------------------
# Preferred surface — the recommended minimal set for common workflows.
# Agents and users should reach for these tools first.
# ---------------------------------------------------------------------------
PREFERRED_SURFACE: set[str] = {
    # memory
    "remember",
    "recall",
    "list_memories",
    "forget",
    "update",  # memory update; registered as "update" in contextwell-core
    # file inspection
    "fs_glob",
    "fs_tree",
    "read_file",
    # search & navigation
    "text_search",
    "symbol_search",
    # text distillation
    "text_compact",
    "text_summarize",
    # editing
    "apply_text_patch",
    # git
    "git_status",
    "git_commit",
    "git_log",
    "git_show",
    "git_branch",
    "git_fetch",
    "git_pull",
    "git_push",
    # github
    "gh_pr_create",
    "gh_pr_list",
    "gh_pr_view",
    "gh_issue_create",
    "gh_issue_list",
    "gh_issue_view",
    # structured diff
    "diff_staged",
    "diff_refs",
    "summarize_diff",
    # server
    "fusion_health",
    "fusion_api_compat",
}

# ---------------------------------------------------------------------------
# Legacy aliases — retained for compatibility; prefer the listed alternative.
# ---------------------------------------------------------------------------
LEGACY_ALIASES: dict[str, str] = {
    # git_diff provides raw diff text; prefer the structured diff-domain tools
    # for workflows that need parsed hunks or summaries.
    "git_diff": "diff_staged or diff_refs",
    # diff_files is a less common variant; diff_refs with a path filter is clearer.
    "diff_files": "diff_refs",
    # remember_file is a convenience wrapper; read_file + remember is explicit.
    "remember_file": "read_file + remember",
    # remember_batch is useful for bulk imports but not a primary workflow tool.
    "remember_batch": "remember (for individual entries)",
    # apply_text_patch_batch is the multi-file variant; prefer the single-file
    # form unless batch semantics are explicitly needed.
    "apply_text_patch_batch": "apply_text_patch",
    # structured-data selectors overlap with read_file for most use cases.
    "json_select": "read_file",
    "yaml_select": "read_file",
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
        # git_log is NOT in TOOLPILOT_TOOLS; it is exclusively registered by the
        # git domain (GITPILOT_TOOLS) to avoid duplicate registration.
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

    preferred_present = sorted(PREFERRED_SURFACE & tool_names)
    legacy_present = {name: alt for name, alt in LEGACY_ALIASES.items() if name in tool_names}

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
        "preferred_surface": preferred_present,
        "legacy_aliases": legacy_present,
    }
