from nanobot.agent.context import ContextBuilder


def test_context_builder_bootstrap_files(tmp_path):
    # Create mock bootstrap files in a temp directory
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    files = ["GUARDRAILS.md", "AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    for f in files:
        (workspace / f).write_text("Test content for " + f)

    cb = ContextBuilder(workspace)
    # Check if BOOTSTRAP_FILES list is correct
    assert cb.BOOTSTRAP_FILES == files

    # Verify that the generated context actually contains the content of those files
    context = cb.build_system_prompt()
    for f in files:
        assert f"Test content for {f}" in context
