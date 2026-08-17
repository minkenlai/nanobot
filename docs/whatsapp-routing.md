# Design Document: WhatsApp Deterministic Dual-Instance Routing & Staff Management

## 1. Executive Summary

This document details the architectural design considerations for **WhatsApp Deterministic Dual-Instance Routing** and the **WhatsApp Staff Management Skill** in Nanobot.

The architecture decouples public, read-only visitor interactions from internal administrative staff operations at the WhatsApp channel boundary. Public messages are forwarded to an isolated Guide node via HTTP API without triggering local pairing prompts, while authorized staff members interact directly with the primary Nanobot agent loop.

---

## 2. Problem Statement & Architecture Goals

### Problem Statement
Running a single WhatsApp instance for both administrative staff operations and public studio guidance presents security and context challenges:
- Public users sending direct messages could trigger pairing code prompts or access administrative tools.
- Public conversations could pollute the administrative agent's session memory.
- Manually configuring allowed numbers and routing rules outside the workspace sandbox can be error-prone and restricted by sandbox file access boundaries.

### Design Goals
1. **Deterministic Transport Boundary Routing**: Intercept non-staff traffic at the channel transport layer before it reaches the message bus or pairing handler.
2. **Session Isolation**: Maintain per-user context isolation on the external Guide instance (`session_id: "whatsapp:<chat_jid>"`).
3. **Fail-Safe Fallbacks**: Provide maintenance and timeout responses when the Guide instance is unreachable or timing out.
4. **Out-of-Sandbox Staff Management**: Provide an automated skill and script to manage `~/.nanobot/config.json` safely with automatic backup generation (`config.json.bak`).

---

## 3. High-Level Architecture

```
                                  +-----------------------------+
                                  | WhatsApp Inbound Event      |
                                  +--------------+--------------+
                                                 |
                                                 v
                                  +--------------+--------------+
                                  | WhatsAppChannel             |
                                  | (_handle_neonize_message)   |
                                  +--------------+--------------+
                                                 |
                                     Is Sender Staff Member?
                                     (_is_staff_sender)
                                        /                \
                                    No /                  \ Yes
                                      v                    v
                        +-------------+------------+  +----+-----------------------+
                        | Guide Instance Forwarder |  | Local Agent Loop           |
                        | (POST /v1/chat/compl.)   |  | (MessageBus / AgentRunner) |
                        +-------------+------------+  +----------------------------+
                                      |
                                      v
                        +-------------+------------+
                        | External Guide Node      |
                        | (Session: whatsapp:jid)  |
                        +--------------------------+
```

---

## 4. Subsystem Details

### 4.1 Channel Boundary Routing (`nanobot/channels/whatsapp/runtime.py`)
- **Config Schema (`WhatsAppRoutingConfig`)**:
  ```python
  class WhatsAppRoutingConfig(Base):
      enabled: bool = True
      staff_numbers: list[str] = Field(default_factory=list)
      staff_groups: list[str] = Field(default_factory=list)
      guide_instance_url: str = "http://127.0.0.1:18791/v1/chat/completions"
      guide_model_name: str = "nanobot"
      forward_timeout_seconds: float = 45.0
  ```
- **Forwarder Logic (`_forward_to_guide_instance`)**:
  - Sends a streaming SSE `POST` request to `guide_instance_url`.
  - Sets typing presence indicators (`composing=True`) on the WhatsApp chat during response generation.
  - Formats user session as `whatsapp:<chat_jid>` to isolate context per public chat.
  - Catches `ConnectError` and `TimeoutException` to return friendly maintenance/fallback replies to WhatsApp users.

### 4.2 Non-Fatal API Model Validation (`nanobot/api/server.py`)
- `POST /v1/chat/completions` logs a warning when `requested_model` differs from the server's configured model, rather than rejecting the request with an HTTP 400 error.
- Ensures third-party scripts, forwarding nodes, and webhooks remain resilient when backend model presets are changed.

### 4.3 WhatsApp Staff Management Native Tool (`nanobot/agent/tools/whatsapp_staff.py`)
- **`whatsapp_staff` Tool**:
  - Native Python agent tool (`WhatsAppStaffTool`) auto-discovered via `pkgutil` scanning.
  - Runs in-process inside the Nanobot process (bypassing `exec` subprocess sandbox restrictions).
  - Safely reads, normalizes, and atomically updates `~/.nanobot/config.json`.
  - Automatically creates a backup (`~/.nanobot/config.json.bak`) prior to saving modifications.
  - Supports `action="add"`, `action="remove"`, and `action="list"` for phone numbers and JIDs.
  - Updates `channels.whatsapp.allow_from`, `channels.whatsapp.enabled`, `channels.whatsapp.routing.enabled`, and `channels.whatsapp.routing.staff_numbers`.

### 4.4 Unified Multi-Channel & Web Chat Architecture
The isolated Guide Node API server (`POST /v1/chat/completions`) serves as a unified, shared public assistant backend for multiple frontends simultaneously:
- **WhatsApp Public Traffic**: Routed via `WhatsAppRoutingConfig` forwarder with `session_id: "whatsapp:<chat_jid>"`.
- **Telegram Guide Identity**: Routed via Telegram dual-bot configuration with `session_id: "telegram:<chat_id>"`.
- **Embedded Web Chat Widgets**: Direct HTTP/SSE integration from public websites, landing pages, or embedded guest widgets using `session_id: "web:<visitor_uuid>"` or standard `x-session-key` header.
- **Session Isolation**: Each channel and visitor gets independent session history and compaction on the Guide node without polluting administrative memory or exposing internal studio tools.

---

## 5. Plugin vs. Built-in Architectural Trade-Offs

| Evaluation Criterion | Built-in Implementation (Selected) | External Plugin / Add-on |
| :--- | :--- | :--- |
| **Boundary Control** | Native control inside `WhatsAppChannel._handle_neonize_message` before bus dispatch. | Requires monkey-patching or complex event hook extensions into the WhatsApp channel package. |
| **User Setup** | Zero setup required; features are built-in and configurable via standard `config.json`. | Requires installing separate PyPI packages, entry points, and managing independent dependency trees. |
| **Configuration** | Unified Pydantic schema in `nanobot/channels/whatsapp/runtime.py`. | Requires managing dynamic extra models or secondary out-of-band config files. |
| **Maintenance** | Integrated directly into the main repository test suite (`pytest`). | Vulnerable to breaking API changes across core updates. |

**Conclusion**: Keeping WhatsApp dual-instance routing and the `whatsapp-staff` skill **native and built-in** provides maximum reliability, security, and developer convenience.
