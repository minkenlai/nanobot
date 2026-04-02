from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import Address, InboundMessage
from nanobot.command.builtin import cmd_repl
from nanobot.command.router import CommandContext


@pytest.mark.asyncio
async def test_repl_disabled_by_default():
    loop = MagicMock()
    loop.config.repl.enable = False
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl 1 + 1",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="1 + 1", loop=loop)

    resp = await cmd_repl(ctx)
    assert "REPL is disabled" in resp.content


@pytest.mark.asyncio
async def test_repl_user_acl_denied():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = ["tg:boss"]
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="intruder",
        content="/repl 1 + 1",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="1 + 1", loop=loop)

    resp = await cmd_repl(ctx)
    assert "Access Denied" in resp.content


@pytest.mark.asyncio
async def test_repl_user_acl_allowed():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = ["test:boss"]
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="boss",
        content="/repl 1 + 1",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="1 + 1", loop=loop)

    resp = await cmd_repl(ctx)
    assert "2" in resp.content


@pytest.mark.asyncio
async def test_repl_eval_expression():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl 1 + 1",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="1 + 1", loop=loop)

    resp = await cmd_repl(ctx)
    assert "2" in resp.content
    assert "REPL Output" in resp.content


@pytest.mark.asyncio
async def test_repl_exec_statement():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl x = 10",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="x = 10", loop=loop)

    resp = await cmd_repl(ctx)
    assert "Done (no result variable set)" in resp.content


@pytest.mark.asyncio
async def test_repl_stdout_capture():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl print('hello world')",
    )
    ctx = CommandContext(
        msg=msg, session=None, key="test:c1", raw="print('hello world')", loop=loop
    )

    resp = await cmd_repl(ctx)
    assert "--- stdout ---" in resp.content
    assert "hello world" in resp.content


@pytest.mark.asyncio
async def test_repl_exec_with_result_variable():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl result = 100 * 2",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="result = 100 * 2", loop=loop)

    resp = await cmd_repl(ctx)
    assert "200" in resp.content


@pytest.mark.asyncio
async def test_repl_async_code():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl asyncio.sleep(0.01)",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="asyncio.sleep(0.01)", loop=loop)

    resp = await cmd_repl(ctx)
    assert "None" in resp.content  # sleep returns None


@pytest.mark.asyncio
async def test_repl_exception_handling():
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = Path("/tmp")
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl 1 / 0",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="1 / 0", loop=loop)

    resp = await cmd_repl(ctx)
    assert "ZeroDivisionError" in resp.content


@pytest.mark.asyncio
async def test_repl_logging(tmp_path):
    loop = MagicMock()
    loop.config.repl.enable = True
    loop.config.repl.allow_users = []
    loop.workspace = tmp_path
    msg = InboundMessage(
        address=Address(channel="test", segments=("c1",)),
        sender_id="u1",
        content="/repl 42",
    )
    ctx = CommandContext(msg=msg, session=None, key="test:c1", raw="42", loop=loop)

    await cmd_repl(ctx)

    log_file = tmp_path / "logs" / "repl.log"
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "REPL test://c1" in log_content
    assert "IN:  42" in log_content
    assert "OUT: 42" in log_content
