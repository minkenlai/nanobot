#!/usr/bin/env python3
"""Sidecar installer for the Studio Guide embeddable web chat widget & Caddy proxy.

Reads a specified nanobot guide config JSON (or CLI flags / interactive prompts)
and generates:
  1. Parameterized standalone widget.js
  2. Caddyfile reverse-proxy & static asset configuration snippet
  3. (Optional) Static asset upload receiver & systemd service with basic_auth
  4. Ready-to-use Squarespace embed script snippet
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any


def _hash_password_with_caddy(password: str) -> str:
    try:
        res = subprocess.run(
            ["caddy", "hash-password", "--plaintext", password],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        pass

    try:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    except ImportError:
        return "$2a$14$PLEASE_GENERATE_WITH_CADDY_HASH_PASSWORD"


def _read_config_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = pathlib.Path(path).expanduser().resolve()
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception as e:
            print(f"[!] Warning: Failed to parse config from {p}: {e}")
    return {}


def build_widget_js(
    domain: str,
    title: str,
    subtitle: str,
    welcome: str,
    chips: list[str],
    primary: str,
    accent: str,
) -> str:
    return f"""/**
 * Studio Guide Embeddable Chat Widget
 * Embed snippet for Squarespace / Web:
 * <script src="https://{domain}/widget.js" async defer></script>
 */
(function() {{
  if (document.getElementById('studio-guide-root')) return;

  const currentScript = document.currentScript || Array.from(document.querySelectorAll('script')).find(s => s.src && s.src.includes('widget.js'));
  const scriptData = currentScript ? currentScript.dataset : {{}};

  const CONFIG = {{
    apiEndpoint: scriptData.endpoint || 'https://{domain}/v1/chat/completions',
    title: scriptData.title || {json.dumps(title)},
    subtitle: scriptData.subtitle || {json.dumps(subtitle)},
    welcomeMessage: scriptData.welcome || {json.dumps(welcome)},
    quickChips: {json.dumps(chips)},
    primaryColor: scriptData.primaryColor || {json.dumps(primary)},
    accentColor: scriptData.accentColor || {json.dumps(accent)},
    storageKey: 'studio_guide_session_id',
    storageMsgKey: 'studio_guide_history_v1'
  }};

  function initWidget() {{
    if (document.getElementById('studio-guide-root')) return;

    const style = document.createElement('style');
    style.id = 'studio-guide-styles';
    style.textContent = `
      :root {{
        --sg-primary: ${{CONFIG.primaryColor}};
        --sg-primary-hover: #0f172a;
        --sg-accent: ${{CONFIG.accentColor}};
        --sg-accent-light: #eff6ff;
        --sg-bg: #ffffff;
        --sg-text: #1e293b;
        --sg-text-muted: #64748b;
        --sg-bubble-user: ${{CONFIG.accentColor}};
        --sg-bubble-user-text: #ffffff;
        --sg-bubble-bot: #f1f5f9;
        --sg-bubble-bot-text: #0f172a;
        --sg-border: #e2e8f0;
        --sg-radius: 16px;
        --sg-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
        --sg-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      }}

      #studio-guide-root {{
        font-family: var(--sg-font);
        font-size: 14px;
        line-height: 1.5;
        box-sizing: border-box;
        z-index: 999999;
        position: relative;
      }}

      #studio-guide-root *, #studio-guide-root *::before, #studio-guide-root *::after {{
        box-sizing: border-box;
      }}

      .sg-trigger {{
        position: fixed;
        bottom: 24px;
        right: 24px;
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: var(--sg-primary);
        color: #ffffff;
        border: none;
        box-shadow: var(--sg-shadow);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: transform 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        z-index: 999999;
        -webkit-tap-highlight-color: transparent;
      }}

      .sg-trigger:hover {{
        background: var(--sg-primary-hover);
        transform: scale(1.05);
      }}

      .sg-trigger svg {{
        width: 28px;
        height: 28px;
        fill: currentColor;
      }}

      .sg-greeting-badge {{
        position: fixed;
        bottom: 94px;
        right: 24px;
        background: #ffffff;
        color: var(--sg-text);
        padding: 10px 14px;
        border-radius: 12px;
        box-shadow: var(--sg-shadow);
        border: 1px solid var(--sg-border);
        font-size: 13px;
        font-weight: 500;
        max-width: 240px;
        display: flex;
        align-items: center;
        gap: 8px;
        animation: sg-fade-in 0.3s ease-out;
        z-index: 999998;
        cursor: pointer;
      }}

      .sg-greeting-badge-close {{
        background: none;
        border: none;
        color: var(--sg-text-muted);
        cursor: pointer;
        font-size: 16px;
        padding: 0 4px;
        line-height: 1;
      }}

      .sg-window {{
        position: fixed;
        bottom: 96px;
        right: 24px;
        width: 380px;
        max-width: calc(100vw - 32px);
        height: 580px;
        max-height: calc(100vh - 120px);
        background: var(--sg-bg);
        border-radius: var(--sg-radius);
        box-shadow: var(--sg-shadow);
        border: 1px solid var(--sg-border);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        opacity: 0;
        transform: translateY(20px) scale(0.96);
        pointer-events: none;
        transition: opacity 0.25s ease, transform 0.25s ease;
        z-index: 999999;
      }}

      .sg-window.sg-open {{
        opacity: 1;
        transform: translateY(0) scale(1);
        pointer-events: auto;
      }}

      .sg-header {{
        background: var(--sg-primary);
        color: #ffffff;
        padding: 14px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-shrink: 0;
        position: relative;
        z-index: 10;
      }}

      .sg-header-info {{
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 0;
      }}

      .sg-avatar {{
        width: 34px;
        height: 34px;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.18);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        flex-shrink: 0;
      }}

      .sg-header-title {{
        font-weight: 600;
        font-size: 15px;
        margin: 0;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      .sg-header-status {{
        font-size: 11px;
        color: #94a3b8;
        display: flex;
        align-items: center;
        gap: 4px;
        margin-top: 2px;
      }}

      .sg-status-dot {{
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #22c55e;
        flex-shrink: 0;
      }}

      .sg-header-actions {{
        display: flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
      }}

      .sg-icon-btn {{
        background: rgba(255, 255, 255, 0.12);
        border: none;
        color: #ffffff;
        cursor: pointer;
        width: 34px;
        height: 34px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s, transform 0.1s;
        -webkit-tap-highlight-color: transparent;
      }}

      .sg-icon-btn:hover {{ background: rgba(255, 255, 255, 0.25); }}
      .sg-icon-btn:active {{ transform: scale(0.95); }}

      .sg-close-btn {{ background: rgba(255, 255, 255, 0.2); }}
      .sg-close-btn:hover {{ background: rgba(239, 68, 68, 0.8); }}

      /* In-widget Confirmation Bar */
      .sg-confirm-bar {{
        background: #fef2f2;
        border-bottom: 1px solid #fee2e2;
        color: #991b1b;
        padding: 8px 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        font-size: 12.5px;
        font-weight: 500;
        animation: sg-fade-in 0.2s ease-out;
        flex-shrink: 0;
      }}

      .sg-confirm-btns {{
        display: flex;
        gap: 6px;
      }}

      .sg-confirm-yes {{
        background: #ef4444;
        color: #ffffff;
        border: none;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 11.5px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
      }}

      .sg-confirm-yes:hover {{ background: #dc2626; }}

      .sg-confirm-no {{
        background: #ffffff;
        color: #64748b;
        border: 1px solid #cbd5e1;
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 11.5px;
        cursor: pointer;
      }}

      .sg-confirm-no:hover {{ background: #f1f5f9; }}

      .sg-messages {{
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        scroll-behavior: smooth;
        background: #f8fafc;
        -webkit-overflow-scrolling: touch;
      }}

      .sg-msg {{
        display: flex;
        flex-direction: column;
        max-width: 84%;
        animation: sg-fade-in 0.2s ease-out;
      }}

      .sg-msg.sg-bot {{ align-self: flex-start; }}
      .sg-msg.sg-user {{ align-self: flex-end; }}

      .sg-bubble {{
        padding: 10px 14px;
        border-radius: 14px;
        font-size: 13.5px;
        line-height: 1.45;
        word-break: break-word;
      }}

      .sg-bot .sg-bubble {{
        background: var(--sg-bubble-bot);
        color: var(--sg-bubble-bot-text);
        border-bottom-left-radius: 4px;
        border: 1px solid var(--sg-border);
      }}

      .sg-user .sg-bubble {{
        background: var(--sg-bubble-user);
        color: var(--sg-bubble-user-text);
        border-bottom-right-radius: 4px;
      }}

      .sg-bubble p {{ margin: 0 0 6px 0; }}
      .sg-bubble p:last-child {{ margin-bottom: 0; }}
      .sg-bubble ul, .sg-bubble ol {{ margin: 4px 0 6px 18px; padding: 0; }}
      .sg-bubble li {{ margin-bottom: 2px; }}
      .sg-bubble a {{ color: var(--sg-accent); text-decoration: underline; font-weight: 500; }}
      .sg-user .sg-bubble a {{ color: #ffffff; }}
      .sg-bubble strong {{ font-weight: 600; }}
      .sg-bubble code {{ background: rgba(0,0,0,0.05); padding: 2px 4px; border-radius: 4px; font-size: 12px; }}

      .sg-chips-container {{
        padding: 4px 16px 10px 16px;
        background: #f8fafc;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        flex-shrink: 0;
      }}

      .sg-chip {{
        background: var(--sg-accent-light);
        color: var(--sg-accent);
        border: 1px solid #bfdbfe;
        padding: 6px 12px;
        border-radius: 18px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.15s ease;
        -webkit-tap-highlight-color: transparent;
      }}

      .sg-chip:hover {{
        background: #dbeafe;
        transform: translateY(-1px);
      }}

      .sg-typing {{
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 8px 12px;
      }}

      .sg-dot {{
        width: 6px;
        height: 6px;
        background: var(--sg-text-muted);
        border-radius: 50%;
        animation: sg-bounce 1.3s infinite ease-in-out;
      }}

      .sg-dot:nth-child(2) {{ animation-delay: 0.2s; }}
      .sg-dot:nth-child(3) {{ animation-delay: 0.4s; }}

      @keyframes sg-bounce {{
        0%, 80%, 100% {{ transform: scale(0); opacity: 0.4; }}
        40% {{ transform: scale(1); opacity: 1; }}
      }}

      @keyframes sg-fade-in {{
        from {{ opacity: 0; transform: translateY(6px); }}
        to {{ opacity: 1; transform: translateY(0); }}
      }}

      .sg-footer {{
        padding: 12px;
        background: var(--sg-bg);
        border-top: 1px solid var(--sg-border);
        display: flex;
        gap: 8px;
        align-items: flex-end;
        flex-shrink: 0;
      }}

      .sg-input {{
        flex: 1;
        border: 1px solid var(--sg-border);
        border-radius: 20px;
        padding: 9px 14px;
        font-family: inherit;
        font-size: 14px;
        outline: none;
        resize: none;
        max-height: 100px;
        min-height: 40px;
        line-height: 1.4;
        transition: border-color 0.15s;
        background: #ffffff;
        color: var(--sg-text);
      }}

      .sg-input:focus {{ border-color: var(--sg-accent); }}

      .sg-send-btn {{
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--sg-accent);
        color: #ffffff;
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s, transform 0.15s;
        flex-shrink: 0;
        -webkit-tap-highlight-color: transparent;
      }}

      .sg-send-btn:hover:not(:disabled) {{ background: #2563eb; transform: scale(1.04); }}
      .sg-send-btn:disabled {{ background: #cbd5e1; cursor: not-allowed; }}

      @media (max-width: 600px) {{
        .sg-window {{
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          width: 100vw;
          max-width: 100vw;
          height: 100dvh;
          height: 100vh;
          max-height: 100dvh;
          border-radius: 0;
          border: none;
          box-shadow: none;
          z-index: 1000000;
        }}

        .sg-header {{
          padding-top: max(14px, env(safe-area-inset-top, 14px));
          padding-left: max(14px, env(safe-area-inset-left, 14px));
          padding-right: max(14px, env(safe-area-inset-right, 14px));
          min-height: 60px;
        }}

        .sg-footer {{
          padding-bottom: max(12px, env(safe-area-inset-bottom, 12px));
          padding-left: max(12px, env(safe-area-inset-left, 12px));
          padding-right: max(12px, env(safe-area-inset-right, 12px));
        }}

        .sg-icon-btn {{ width: 38px; height: 38px; }}
        .sg-trigger {{ bottom: 16px; right: 16px; width: 56px; height: 56px; }}
      }}
    `;
    document.head.appendChild(style);

    const root = document.createElement('div');
    root.id = 'studio-guide-root';
    document.body.appendChild(root);

    function getSessionId() {{
      let sid = localStorage.getItem(CONFIG.storageKey);
      if (!sid) {{
        sid = 'web_' + (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 12) : Math.random().toString(36).substring(2, 14));
        localStorage.setItem(CONFIG.storageKey, sid);
      }}
      return sid;
    }}

    function resetSession() {{
      localStorage.removeItem(CONFIG.storageKey);
      localStorage.removeItem(CONFIG.storageMsgKey);
      state.messages = [{{ role: 'assistant', content: CONFIG.welcomeMessage }}];
      renderMessages();
    }}

    const state = {{
      isOpen: false,
      isLoading: false,
      messages: []
    }};

    try {{
      const saved = localStorage.getItem(CONFIG.storageMsgKey);
      if (saved) state.messages = JSON.parse(saved);
    }} catch (e) {{}}

    if (!state.messages || state.messages.length === 0) {{
      state.messages = [{{ role: 'assistant', content: CONFIG.welcomeMessage }}];
    }}

    function saveHistory() {{
      try {{
        localStorage.setItem(CONFIG.storageMsgKey, JSON.stringify(state.messages.slice(-30)));
      }} catch (e) {{}}
    }}

    function formatMarkdown(text) {{
      if (!text) return '';
      let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      html = html.replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>');
      html = html.replace(/\\*(.*?)\\*/g, '<em>$1</em>');
      html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
      html = html.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      html = html.replace(/(?:^|\\n)[-*]\\s+(.+)/g, '<li>$1</li>');
      html = html.replace(/(<li>.*<\\/li>)/gs, '<ul>$1</ul>');
      html = html.replace(/\\n/g, '<br>');
      return html;
    }}

    root.innerHTML = `
      <div class="sg-greeting-badge" id="sg-greeting" style="display: none;">
        <span>👋 Questions? Chat with our Studio Guide!</span>
        <button class="sg-greeting-badge-close" id="sg-greeting-close" aria-label="Dismiss greeting">&times;</button>
      </div>

      <button class="sg-trigger" id="sg-trigger-btn" aria-label="Open chat with studio guide">
        <svg id="sg-icon-chat" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
        <svg id="sg-icon-close" viewBox="0 0 24 24" style="display: none;"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>

      <div class="sg-window" id="sg-window" role="dialog" aria-modal="true" aria-label="Chat with Studio Guide">
        <div class="sg-header">
          <div class="sg-header-info">
            <div class="sg-avatar">🧘</div>
            <div>
              <div class="sg-header-title">${{CONFIG.title}}</div>
              <div class="sg-header-status"><span class="sg-status-dot"></span> ${{CONFIG.subtitle}}</div>
            </div>
          </div>
          <div class="sg-header-actions">
            <button class="sg-icon-btn" id="sg-reset-btn" title="New Conversation" aria-label="New Conversation">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
            </button>
            <button class="sg-icon-btn sg-close-btn" id="sg-close-btn" title="Close Chat" aria-label="Close Chat">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
            </button>
          </div>
        </div>

        <div class="sg-confirm-bar" id="sg-confirm-bar" style="display: none;">
          <span>Clear chat history?</span>
          <div class="sg-confirm-btns">
            <button class="sg-confirm-yes" id="sg-confirm-yes">Clear</button>
            <button class="sg-confirm-no" id="sg-confirm-no">Cancel</button>
          </div>
        </div>

        <div class="sg-messages" id="sg-messages-list"></div>

        <div class="sg-chips-container" id="sg-chips">
          ${{CONFIG.quickChips.map(chip => `<button class="sg-chip">${{chip}}</button>`).join('')}}
        </div>

        <div class="sg-footer">
          <textarea class="sg-input" id="sg-input" placeholder="Type your message..." rows="1"></textarea>
          <button class="sg-send-btn" id="sg-send-btn" disabled aria-label="Send message">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>
    `;

    const triggerBtn = document.getElementById('sg-trigger-btn');
    const windowEl = document.getElementById('sg-window');
    const iconChat = document.getElementById('sg-icon-chat');
    const iconClose = document.getElementById('sg-icon-close');
    const closeBtn = document.getElementById('sg-close-btn');
    const resetBtn = document.getElementById('sg-reset-btn');
    const confirmBar = document.getElementById('sg-confirm-bar');
    const confirmYes = document.getElementById('sg-confirm-yes');
    const confirmNo = document.getElementById('sg-confirm-no');
    const messagesList = document.getElementById('sg-messages-list');
    const chipsContainer = document.getElementById('sg-chips');
    const inputEl = document.getElementById('sg-input');
    const sendBtn = document.getElementById('sg-send-btn');
    const greetingEl = document.getElementById('sg-greeting');
    const greetingClose = document.getElementById('sg-greeting-close');

    function toggleChat(open) {{
      state.isOpen = (typeof open === 'boolean') ? open : !state.isOpen;
      if (state.isOpen) {{
        windowEl.classList.add('sg-open');
        iconChat.style.display = 'none';
        iconClose.style.display = 'block';
        greetingEl.style.display = 'none';
        scrollToBottom();
        setTimeout(() => inputEl.focus(), 150);
      }} else {{
        windowEl.classList.remove('sg-open');
        iconChat.style.display = 'block';
        iconClose.style.display = 'none';
        confirmBar.style.display = 'none';
      }}
    }}

    if (!sessionStorage.getItem('sg_greeting_dismissed') && state.messages.length <= 1) {{
      setTimeout(() => {{
        if (!state.isOpen) greetingEl.style.display = 'flex';
      }}, 2500);
    }}

    greetingClose.addEventListener('click', (e) => {{
      e.stopPropagation();
      greetingEl.style.display = 'none';
      sessionStorage.setItem('sg_greeting_dismissed', '1');
    }});

    greetingEl.addEventListener('click', () => toggleChat(true));
    triggerBtn.addEventListener('click', () => toggleChat());
    closeBtn.addEventListener('click', () => toggleChat(false));

    resetBtn.addEventListener('click', () => {{
      if (state.messages.length <= 1) return;
      confirmBar.style.display = confirmBar.style.display === 'none' ? 'flex' : 'none';
    }});

    confirmYes.addEventListener('click', () => {{
      confirmBar.style.display = 'none';
      resetSession();
    }});

    confirmNo.addEventListener('click', () => {{
      confirmBar.style.display = 'none';
    }});

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape' && state.isOpen) toggleChat(false);
    }});

    function renderMessages() {{
      messagesList.innerHTML = state.messages.map(msg => `
        <div class="sg-msg sg-${{msg.role === 'assistant' ? 'bot' : 'user'}}\">
          <div class="sg-bubble">${{formatMarkdown(msg.content)}}</div>
        </div>
      `).join('');

      if (state.isLoading) {{
        const typingEl = document.createElement('div');
        typingEl.className = 'sg-msg sg-bot';
        typingEl.innerHTML = `
          <div class="sg-bubble sg-typing">
            <div class="sg-dot"></div>
            <div class="sg-dot"></div>
            <div class="sg-dot"></div>
          </div>
        `;
        messagesList.appendChild(typingEl);
      }}

      chipsContainer.style.display = state.messages.length > 2 ? 'none' : 'flex';
      scrollToBottom();
      saveHistory();
    }}

    function scrollToBottom() {{
      messagesList.scrollTop = messagesList.scrollHeight;
    }}

    chipsContainer.addEventListener('click', (e) => {{
      if (e.target.classList.contains('sg-chip')) {{
        const text = e.target.textContent.replace(/[\\u{{1F300}}-\\u{{1F6FF}}]/gu, '').trim();
        inputEl.value = text;
        handleSend();
      }}
    }});

    inputEl.addEventListener('input', () => {{
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
      sendBtn.disabled = !inputEl.value.trim() || state.isLoading;
    }});

    inputEl.addEventListener('keydown', (e) => {{
      if (e.key === 'Enter' && !e.shiftKey) {{
        e.preventDefault();
        handleSend();
      }}
    }});

    sendBtn.addEventListener('click', handleSend);

    async function handleSend() {{
      const text = inputEl.value.trim();
      if (!text || state.isLoading) return;

      inputEl.value = '';
      inputEl.style.height = 'auto';
      sendBtn.disabled = true;

      state.messages.push({{ role: 'user', content: text }});
      state.isLoading = true;
      renderMessages();

      const sessionId = getSessionId();

      try {{
        const response = await fetch(CONFIG.apiEndpoint, {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/json',
            'X-Session-Id': sessionId
          }},
          body: JSON.stringify({{
            messages: [{{ role: 'user', content: text }}],
            session_id: sessionId,
            stream: true
          }})
        }});

        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);

        state.isLoading = false;
        const botMsg = {{ role: 'assistant', content: '' }};
        state.messages.push(botMsg);
        renderMessages();

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (true) {{
          const {{ value, done }} = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, {{ stream: true }});
          const lines = buffer.split('\\n');
          buffer = lines.pop() || '';

          for (const line of lines) {{
            const trimmed = line.trim();
            if (!trimmed || trimmed.startsWith(':') || trimmed === 'data: [DONE]') continue;

            if (trimmed.startsWith('data: ')) {{
              try {{
                const data = JSON.parse(trimmed.slice(6));
                const delta = data.choices?.[0]?.delta?.content;
                if (delta) {{
                  botMsg.content += delta;
                  renderMessages();
                }}
              }} catch (err) {{}}
            }}
          }}
        }}
      }} catch (err) {{
        console.error('Chat error:', err);
        state.isLoading = false;
        state.messages.push({{
          role: 'assistant',
          content: '⚠️ *Sorry, I am having trouble connecting to the guide service right now. Please try again in a moment or contact the studio directly.*'
        }});
        renderMessages();
      }} finally {{
        state.isLoading = false;
        sendBtn.disabled = !inputEl.value.trim();
        saveHistory();
      }}
    }}

    renderMessages();
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initWidget);
  }} else {{
    initWidget();
  }}
}})();
"""


def build_uploader_script(dest_dir: str, uploader_port: int) -> str:
    return f"""#!/usr/bin/env python3
import pathlib
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

DEST_DIR = pathlib.Path("{dest_dir}")
DEST_DIR.mkdir(parents=True, exist_ok=True)

class UploadHandler(BaseHTTPRequestHandler):
    def do_PUT(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Error: Empty body\\n")
                return

            clean_name = pathlib.Path(self.path).name or "widget.js"
            target_file = DEST_DIR / clean_name

            content = self.rfile.read(length)
            target_file.write_bytes(content)

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Successfully uploaded {{clean_name}} ({{len(content)}} bytes)\\n".encode())
            print(f"[Upload] Saved {{target_file}} ({{len(content)}} bytes)", flush=True)

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Server Error: {{e}}\\n".encode())

    def log_message(self, format, *args):
        print(f"[HTTP] {{self.address_string()}} - {{format % args}}", flush=True)

if __name__ == "__main__":
    port = {uploader_port}
    print(f"Starting Upload Receiver on 127.0.0.1:{{port}} -> {{DEST_DIR}}...")
    server = HTTPServer(("127.0.0.1", port), UploadHandler)
    server.serve_forever()
"""


def _find_caddy_domain_block(caddy_text: str, domain: str) -> tuple[int, int] | None:
    """Find start and end character offsets of a domain's block in Caddyfile."""
    import re
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:https?://)?{re.escape(domain)}(?::\d+)?(?:\s*,\s*[^\n{{]+)*\s*\{{",
        re.MULTILINE,
    )
    match = pattern.search(caddy_text)
    if not match:
        return None
    start_pos = match.start()
    if caddy_text[start_pos] == "\n":
        start_pos += 1

    brace_count = 0
    in_block = False
    for i in range(match.end() - 1, len(caddy_text)):
        char = caddy_text[i]
        if char == "{":
            brace_count += 1
            in_block = True
        elif char == "}":
            brace_count -= 1
            if in_block and brace_count == 0:
                return start_pos, i + 1
    return None


def _apply_caddyfile_update(caddy_dest: pathlib.Path, domain: str, caddy_snippet: str) -> None:
    import datetime
    import shutil

    caddy_dest.parent.mkdir(parents=True, exist_ok=True)
    if not caddy_dest.exists() or caddy_dest.stat().st_size == 0:
        caddy_dest.write_text(caddy_snippet, encoding="utf-8")
        print(f"[✓] Written new Caddyfile to: {caddy_dest}")
        return

    existing_content = caddy_dest.read_text("utf-8")
    existing_block_span = _find_caddy_domain_block(existing_content, domain)

    if existing_block_span is not None:
        start_pos, end_pos = existing_block_span
        current_block = existing_content[start_pos:end_pos].strip()

        if current_block == caddy_snippet.strip():
            print(f"[✓] Caddy block for '{domain}' is already present and up to date in {caddy_dest}")
            return

        # Create timestamped backup before modifying
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = caddy_dest.with_name(f"{caddy_dest.name}.bak.{timestamp}")
        shutil.copy2(caddy_dest, backup_path)
        print(f"[✓] Created Caddyfile backup: {backup_path}")

        # Replace only the matching block in place
        updated_content = (
            existing_content[:start_pos]
            + caddy_snippet.strip()
            + existing_content[end_pos:]
        )
        caddy_dest.write_text(updated_content, encoding="utf-8")
        print(f"[✓] Replaced existing '{domain}' block in {caddy_dest}")
    else:
        # Create timestamped backup before modifying
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = caddy_dest.with_name(f"{caddy_dest.name}.bak.{timestamp}")
        shutil.copy2(caddy_dest, backup_path)
        print(f"[✓] Created Caddyfile backup: {backup_path}")

        # Append block to end of file, preserving all other websites
        updated_content = existing_content.rstrip() + "\n\n" + caddy_snippet.strip() + "\n"
        caddy_dest.write_text(updated_content, encoding="utf-8")
        print(f"[✓] Appended '{domain}' block to existing {caddy_dest}")


def _parse_existing_widget_js(widget_path: pathlib.Path) -> dict[str, Any]:
    """Extract configured parameter values from an existing widget.js file."""
    import re
    if not widget_path.exists():
        return {}
    try:
        text = widget_path.read_text("utf-8")
        extracted: dict[str, Any] = {}

        # 1. Extract endpoint / domain
        m_endpoint = re.search(r"apiEndpoint:\s*scriptData\.endpoint\s*\|\|\s*'https?://([^/]+)/v1/chat/completions'", text)
        if m_endpoint:
            extracted["domain"] = m_endpoint.group(1)

        # 2. Extract title
        m_title = re.search(r"title:\s*scriptData\.title\s*\|\|\s*(\".*?\"|'.*?')", text)
        if m_title:
            try:
                extracted["studio_name"] = json.loads(m_title.group(1))
            except Exception:
                extracted["studio_name"] = m_title.group(1).strip("\"'")

        # 3. Extract subtitle
        m_subtitle = re.search(r"subtitle:\s*scriptData\.subtitle\s*\|\|\s*(\".*?\"|'.*?')", text)
        if m_subtitle:
            try:
                extracted["subtitle"] = json.loads(m_subtitle.group(1))
            except Exception:
                extracted["subtitle"] = m_subtitle.group(1).strip("\"'")

        # 4. Extract welcome message
        m_welcome = re.search(r"welcomeMessage:\s*scriptData\.welcome\s*\|\|\s*(\".*?\"|'.*?')", text)
        if m_welcome:
            try:
                extracted["welcome"] = json.loads(m_welcome.group(1))
            except Exception:
                extracted["welcome"] = m_welcome.group(1).strip("\"'")

        # 5. Extract quick chips
        m_chips = re.search(r"quickChips:\s*(\[.*?\])", text, re.DOTALL)
        if m_chips:
            try:
                extracted["quick_chips"] = json.loads(m_chips.group(1))
            except Exception:
                pass

        # 6. Extract colors
        m_primary = re.search(r"primaryColor:\s*scriptData\.primaryColor\s*\|\|\s*(\".*?\"|'.*?')", text)
        if m_primary:
            extracted["primary_color"] = m_primary.group(1).strip("\"'")

        m_accent = re.search(r"accentColor:\s*scriptData\.accentColor\s*\|\|\s*(\".*?\"|'.*?')", text)
        if m_accent:
            extracted["accent_color"] = m_accent.group(1).strip("\"'")

        return extracted
    except Exception as e:
        print(f"[!] Warning: Failed to parse existing widget values from {widget_path}: {e}")
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sidecar installer for Studio Guide web widget & Caddy proxy")
    parser.add_argument("--config", "-c", help="Path to guide nanobot config JSON")
    parser.add_argument("--domain", "-d", help="Public domain name for the guide (e.g. guide.mystudio.com)")
    parser.add_argument("--guide-port", "-p", type=int, help="Local guide API port (default: from config or 8900)")
    parser.add_argument("--studio-name", help="Studio Guide title displayed in chat header")
    parser.add_argument("--primary-color", help="Brand primary color (hex, e.g. #1e293b)")
    parser.add_argument("--accent-color", help="Brand accent color (hex, e.g. #3b82f6)")
    parser.add_argument("--out-dir", "-o", help="Directory where widget.js & configurations are placed")
    parser.add_argument("--enable-uploader", action="store_true", default=None, help="Generate upload receiver script & basic_auth endpoint")
    parser.add_argument("--upload-password", help="Password for basic_auth upload endpoint")
    parser.add_argument("--uploader-port", type=int, default=8905, help="Port for local upload receiver (default: 8905)")
    parser.add_argument("--write-caddyfile", help="Path to write generated Caddyfile snippet")

    args = parser.parse_args()

    # Resolve Output Directory first to inspect for existing widget.js
    out_dir_str = args.out_dir
    if not out_dir_str:
        if os.path.exists("/var/www/static") or os.access("/var/www", os.W_OK):
            out_dir_str = "/var/www/static"
        else:
            out_dir_str = os.path.expanduser("~/.nanobot/static")
    out_dir = pathlib.Path(out_dir_str).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Inspect existing widget.js to use known parameters as defaults
    existing_widget = out_dir / "widget.js"
    existing_cfg = _parse_existing_widget_js(existing_widget)
    if existing_cfg:
        print(f"[i] Detected existing widget at {existing_widget} — reusing configured defaults.")

    cfg = _read_config_json(args.config)
    api_cfg = cfg.get("api", {})

    guide_port = args.guide_port or api_cfg.get("port") or 8900

    default_domain = existing_cfg.get("domain") or "guide.example.com"
    domain = args.domain
    if not domain:
        if sys.stdin.isatty():
            domain = input(f"Enter public domain for the guide [default: {default_domain}]: ").strip() or default_domain
        else:
            domain = default_domain
    if not domain:
        domain = default_domain

    default_studio_name = existing_cfg.get("studio_name") or "Studio Guide"
    studio_name = args.studio_name
    if not studio_name and sys.stdin.isatty():
        studio_name = input(f"Enter Studio Guide title [default: {default_studio_name}]: ").strip() or default_studio_name
    studio_name = studio_name or default_studio_name

    primary_color = args.primary_color or existing_cfg.get("primary_color") or "#1e293b"
    accent_color = args.accent_color or existing_cfg.get("accent_color") or "#3b82f6"
    welcome_message = existing_cfg.get("welcome") or "Hi! 👋 Welcome to our studio. I can help answer questions about class schedules, pricing, location, or bookings. How can I assist you today?"
    subtitle = existing_cfg.get("subtitle") or "Online • Ask anything"
    quick_chips = existing_cfg.get("quick_chips") or [
        "Class Schedule 📅",
        "Pricing & Passes 🏷️",
        "Location & Parking 📍",
        "First-Time Visitor ✨",
    ]

    widget_code = build_widget_js(
        domain=domain,
        title=studio_name,
        subtitle=subtitle,
        welcome=welcome_message,
        chips=quick_chips,
        primary=primary_color,
        accent=accent_color,
    )

    widget_file = out_dir / "widget.js"
    widget_file.write_text(widget_code, encoding="utf-8")
    print(f"\n[✓] Generated widget: {widget_file}")

    enable_uploader = args.enable_uploader
    upload_password = args.upload_password
    if enable_uploader is None and sys.stdin.isatty():
        ans = input("Enable secure HTTP PUT upload receiver for widget updates? [y/N]: ").strip().lower()
        enable_uploader = ans in ("y", "yes")

    caddy_upload_block = ""
    password_hash = ""
    if enable_uploader:
        if not upload_password and sys.stdin.isatty():
            upload_password = input("Enter password for upload authentication: ").strip()
        upload_password = upload_password or "ChangeMeSecret123"
        password_hash = _hash_password_with_caddy(upload_password)

        uploader_script = out_dir / "widget-uploader.py"
        uploader_script.write_text(
            build_uploader_script(dest_dir=str(out_dir), uploader_port=args.uploader_port),
            encoding="utf-8",
        )
        os.chmod(uploader_script, 0o755)
        print(f"[✓] Generated upload receiver script: {uploader_script}")

        systemd_unit = f"""[Unit]
Description=Static Asset Upload Receiver ({domain})
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 {uploader_script}
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
        unit_file = out_dir / "widget-uploader.service"
        unit_file.write_text(systemd_unit, encoding="utf-8")
        print(f"[✓] Generated systemd unit: {unit_file}")

        caddy_upload_block = f"""
    # Protected upload endpoint
    handle /upload/* {{
        basic_auth {{
            admin {password_hash}
        }}
        reverse_proxy 127.0.0.1:{args.uploader_port}
    }}"""

    caddy_snippet = f"""{domain} {{
    header Access-Control-Allow-Origin *

    # Serve the cached widget script
    handle /widget.js {{
        root * {out_dir}
        file_server
        header Cache-Control "public, max-age=300"
    }}{caddy_upload_block}

    # Nanobot Guide Chat API
    handle /v1/* {{
        reverse_proxy 127.0.0.1:{guide_port} {{
            flush_interval -1
        }}
    }}
}}
"""
    caddy_out = out_dir / "Caddyfile.snippet"
    caddy_out.write_text(caddy_snippet, encoding="utf-8")
    if args.write_caddyfile:
        _apply_caddyfile_update(pathlib.Path(args.write_caddyfile).expanduser().resolve(), domain, caddy_snippet)

    print("\n" + "=" * 70)
    print("🚀 SETUP COMPLETE!")
    print("=" * 70)
    print("\n1. Squarespace Embed Snippet (Settings -> Advanced -> Code Injection -> Footer):")
    print(f'   <script src="https://{domain}/widget.js" async defer></script>')

    print("\n2. Caddy Configuration (/etc/caddy/Caddyfile):")
    print("-" * 50)
    print(caddy_snippet.strip())
    print("-" * 50)

    if enable_uploader:
        print("\n3. Start the Upload Receiver on your VM:")
        print(f"   sudo cp {out_dir}/widget-uploader.service /etc/systemd/system/")
        print("   sudo systemctl daemon-reload && sudo systemctl enable --now widget-uploader")
        print("\n4. Test Uploading Updates from anywhere:")
        print(f"   curl -u admin:{upload_password} -T widget.js https://{domain}/upload/widget.js")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
