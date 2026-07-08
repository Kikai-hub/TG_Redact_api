"""Provider-agnostic AI client.

Supports OpenAI, Anthropic, and any OpenAI-compatible endpoint (self-hosted
models, YandexGPT-compatible gateways, etc.) selected via Settings.ai_provider
so the AI backend can be swapped from the web UI without a redeploy.
"""

import json

import httpx

REQUIRED_FIELDS = ("title", "intro", "body", "comment", "hashtags")


class AIProcessingError(Exception):
    pass


def build_user_prompt(prompt: str, example_format: dict, original_title: str, original_text: str) -> str:
    return (
        f"{prompt}\n\n"
        f"Пример формата ответа (JSON):\n{json.dumps(example_format, ensure_ascii=False, indent=2)}\n\n"
        f"Исходная новость:\nЗаголовок: {original_title}\nТекст: {original_text}\n\n"
        "Верни только JSON, без markdown-обрамления (без ```)."
    )


def _extract_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIProcessingError(f"AI response is not valid JSON: {exc}") from exc
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise AIProcessingError(f"AI response missing required fields: {missing}")
    return data


def _call_openai_compatible(base_url: str, api_key: str, model: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
    response = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def _call_anthropic(api_key: str, model: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


def process_with_ai(
    prompt: str,
    example_format: dict,
    original_title: str,
    original_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
    provider: str,
    api_key: str | None,
    api_base: str = "",
) -> dict:
    if not api_key:
        raise AIProcessingError("AI API key is not configured (Settings → AI API Key).")

    user_prompt = build_user_prompt(prompt, example_format, original_title, original_text)

    if provider == "anthropic":
        raw_text = _call_anthropic(api_key, model, user_prompt, temperature, max_tokens)
    elif provider == "custom_openai_compatible":
        base_url = api_base or "https://api.openai.com/v1"
        raw_text = _call_openai_compatible(base_url, api_key, model, user_prompt, temperature, max_tokens)
    else:  # openai
        raw_text = _call_openai_compatible("https://api.openai.com/v1", api_key, model, user_prompt, temperature, max_tokens)

    return _extract_json(raw_text)
