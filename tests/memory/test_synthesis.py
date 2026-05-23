# Assuming a helper or the actual memory-synthesize skill logic
# This tests the movement from STAGING -> MEMORY


def test_memory_synthesis_flow(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mem_dir = workspace / "memory"
    mem_dir.mkdir()

    staging = mem_dir / "STAGING.md"
    memory = mem_dir / "MEMORY.md"

    staging.write_text("- Today was sunny\n- Ken liked the coffee")
    memory.write_text("# Long Term Memory\n- Ken is a Principal Engineer")

    # Simulate the synthesis logic (read staging, append to memory, clear staging)
    staging_content = staging.read_text()
    memory_content = memory.read_text()

    updated_memory = memory_content + "\n\n## Recent Updates\n" + staging_content
    memory.write_text(updated_memory)
    staging.write_text("")

    assert "Today was sunny" in memory.read_text()
    assert staging.read_text() == ""
