"""Shared fixtures and helpers for Telegram channel tests."""

from types import SimpleNamespace

import pytest


class _FakeBot:
    """Minimal Telegram bot mock that records send/edit calls."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self.sent_media: list[dict] = []
        self.get_me_calls = 0

    async def get_me(self):
        self.get_me_calls += 1
        return SimpleNamespace(id=999, username="nanobot_test")

    async def set_my_commands(self, commands) -> None:
        self.commands = commands

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent_messages))

    async def edit_message_text(self, **kwargs):
        self.edited_messages.append(kwargs)
        return True

    async def send_photo(self, **kwargs) -> None:
        self.sent_media.append({"kind": "photo", **kwargs})

    async def send_voice(self, **kwargs) -> None:
        self.sent_media.append({"kind": "voice", **kwargs})

    async def send_audio(self, **kwargs) -> None:
        self.sent_media.append({"kind": "audio", **kwargs})

    async def send_document(self, **kwargs) -> None:
        self.sent_media.append({"kind": "document", **kwargs})

    async def send_chat_action(self, **kwargs) -> None:
        pass

    async def get_file(self, file_id: str):
        """Return a fake file that 'downloads' to a path."""

        async def _fake_download(path) -> None:
            pass

        return SimpleNamespace(download_to_drive=_fake_download)


class _FakeUpdater:
    def __init__(self, on_start_polling) -> None:
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:
        self._on_start_polling()


class _FakeApp:
    def __init__(self, on_start_polling) -> None:
        self.bot = _FakeBot()
        self.updater = _FakeUpdater(on_start_polling)
        self.handlers = []
        self.error_handlers = []

    def add_error_handler(self, handler) -> None:
        self.error_handlers.append(handler)

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)

    async def initialize(self) -> None:
        pass

    async def start(self) -> None:
        pass


class _FakeBuilder:
    def __init__(self, app: _FakeApp) -> None:
        self.app = app
        self.token_value = None
        self.request_value = None
        self.get_updates_request_value = None

    def token(self, token: str):
        self.token_value = token
        return self

    def request(self, request):
        self.request_value = request
        return self

    def get_updates_request(self, request):
        self.get_updates_request_value = request
        return self

    def proxy(self, _proxy):
        raise AssertionError("builder.proxy should not be called when request is set")

    def get_updates_proxy(self, _proxy):
        raise AssertionError("builder.get_updates_proxy should not be called when request is set")

    def build(self):
        return self.app


@pytest.fixture
def telegram_channel():
    """Create a TelegramChannel with a fake app."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.telegram import TelegramChannel, TelegramConfig

    config = TelegramConfig(enabled=True, token="fake:token", allow_from=["*"])
    ch = TelegramChannel(config, MessageBus())
    ch._app = _FakeApp(lambda: None)
    return ch


@pytest.fixture
def telegram_channel_with_thread():
    """Create a TelegramChannel pre-configured with a stream buffer."""
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.telegram import TelegramChannel, TelegramConfig

    config = TelegramConfig(enabled=True, token="fake:token", allow_from=["*"])
    ch = TelegramChannel(config, MessageBus())
    ch._app = _FakeApp(lambda: None)
    return ch
