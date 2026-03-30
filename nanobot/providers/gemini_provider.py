"""Native Gemini provider for Google's Generative AI API."""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class GeminiNativeProvider(LLMProvider):
    """Native Gemini provider using Google's direct Generative AI API.

    Supports native grounding (search/maps) and direct citations.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gemini-2.0-flash",
        grounding: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.grounding = grounding

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        model_name = model or self.default_model
        if "/" in model_name:
            model_name = model_name.split("/")[-1]

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"

        system_instruction, contents = self._convert_messages(messages)
        gemini_tools = self._convert_tools(tools)

        # Inject native grounding if requested
        if self.grounding in ("google_search", "google_maps"):
            gemini_tools.append({"google_search_retrieval": {}})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if gemini_tools:
            payload["tools"] = gemini_tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(f"Gemini API Error: {resp.status_code} {resp.text}")
                return LLMResponse(
                    content=f"Error calling Gemini: {resp.status_code} {resp.text}",
                    finish_reason="error",
                )

            data = resp.json()
            return self._parse_response(data)

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Gemini format (systemInstruction + contents)."""
        system_parts = []
        mapped_msgs = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append({"text": content})
                elif isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            system_parts.append({"text": part.get("text")})
                continue

            g_role = "model" if role == "assistant" else "user"
            parts = []

            if isinstance(content, str) and content:
                parts.append({"text": content})
            elif isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"text": part.get("text")})

            if role == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    fn = tc.get("function") or {}
                    args_str = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args = {}

                    part_payload: dict[str, Any] = {
                        "functionCall": {
                            "name": fn.get("name") or tc.get("name") or "tc",
                            "args": args,
                        }
                    }

                    psf = fn.get("provider_specific_fields", {})
                    if isinstance(psf, dict):
                        ts = psf.get("thought_signature") or psf.get("thoughtSignature")
                        if ts:
                            part_payload["thought_signature"] = ts

                    parts.append(part_payload)

            if role == "tool":
                g_role = "user"
                resp = content if isinstance(content, dict) else {"result": content}
                parts.append(
                    {"functionResponse": {"name": msg.get("name") or "tc", "response": resp}}
                )

            if parts:
                mapped_msgs.append({"role": g_role, "parts": parts})

        # Merge consecutive same-role messages
        merged: list[dict[str, Any]] = []
        for m in mapped_msgs:
            if merged and merged[-1]["role"] == m["role"]:
                merged[-1]["parts"].extend(m["parts"])
            else:
                merged.append(m)

        sys_instr = {"parts": system_parts} if system_parts else None
        return sys_instr, merged

    def _convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Convert OpenAI tool definitions to Gemini format."""
        if not tools:
            return []

        declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                declarations.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                    }
                )

        return [{"function_declarations": declarations}] if declarations else []

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse Gemini response into LLMResponse."""
        if "candidates" not in data or not data["candidates"]:
            return LLMResponse(content="Error: Empty response from Gemini.", finish_reason="error")

        candidate = data["candidates"][0]
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])

        text = ""
        tool_calls = []

        for part in parts:
            if "text" in part:
                text += part["text"]
            if "functionCall" in part:
                fc = part["functionCall"]
                ts = part.get("thought_signature") or part.get("thoughtSignature")
                if not ts and isinstance(fc, dict):
                    ts = fc.get("thought_signature") or fc.get("thoughtSignature")

                tool_calls.append(
                    ToolCallRequest(
                        id=fc.get("name", "tc"),
                        name=fc["name"],
                        arguments=fc.get("args", {}),
                        function_provider_specific_fields={"thought_signature": ts} if ts else None,
                    )
                )

        # Capture grounding metadata
        grounding_text = ""
        if "groundingMetadata" in candidate:
            gm = candidate["groundingMetadata"]
            if "searchEntryPoint" in gm:
                html = gm["searchEntryPoint"].get("renderedContent", "")
                if "href" in html:
                    import re

                    match = re.search(r'href="([^"]+)"', html)
                    if match:
                        grounding_text = f"\n\n[Search Grounding Source]({match.group(1)})"

        full_content = (text + grounding_text) if (text or grounding_text) else None

        return LLMResponse(
            content=full_content,
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason", "STOP").lower(),
            usage=self._extract_usage(data),
        )

    def _extract_usage(self, data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usageMetadata", {})
        return {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

    def get_default_model(self) -> str:
        return self.default_model
