"""The existing OpenAI-compatible chat endpoint, shared by decisions and display translation."""

from urllib.parse import urlsplit

import aiohttp

from tls_security import tls_context

# Validate once before the UI/CLI can send a request, including on HTTP-only
# setups. Outdated environments must be rebuilt, not silently kept alive.
TLS_CONTEXT = tls_context()


class ServerConnectionError(ConnectionError):
    """The configured server could not be reached before an experiment."""


async def ensure_server_reachable(session, *, base_url, timeout):
    """Check HTTP reachability without requesting a model generation."""
    validate_base_url(base_url)
    try:
        async with session.head(f"{base_url.rstrip('/')}/chat/completions",
                                timeout=aiohttp.ClientTimeout(total=min(timeout, 5)),
                                allow_redirects=False, ssl=TLS_CONTEXT):
            # Even 404/405 proves reachability when the provider has no HEAD
            # handler. Model/authentication checks remain in the normal POST.
            pass
    except (aiohttp.ClientError, TimeoutError) as error:
        raise ServerConnectionError("接続できません") from error


REASONING_MODES = ("default", "on", "off")
REASONING_FORMATS = ("openai", "chat_template")
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
TOKEN_LIMIT_PARAMETERS = ("max_tokens", "max_completion_tokens")
REQUEST_OPTION_DEFAULTS = {
    "send_temperature": True, "send_top_p": True, "reasoning_mode": "default",
    "reasoning_effort": "medium", "reasoning_format": "openai", "max_tokens_parameter": "max_tokens",
}


def request_options(settings):
    """Read explicit request controls, retaining legacy defaults for old records."""
    options = {name: settings.get(name, default) for name, default in REQUEST_OPTION_DEFAULTS.items()}
    for name in ("send_temperature", "send_top_p"):
        if type(options[name]) is not bool:
            raise ValueError(f"{name} must be a boolean")
    for name, choices in (("reasoning_mode", REASONING_MODES),
                          ("reasoning_format", REASONING_FORMATS),
                          ("reasoning_effort", REASONING_EFFORTS),
                          ("max_tokens_parameter", TOKEN_LIMIT_PARAMETERS)):
        if options[name] not in choices:
            raise ValueError(f"Unsupported {name}")
    return options


def validate_base_url(base_url):
    url = urlsplit(base_url)
    if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise ValueError("base_url must be an HTTP(S) API base without credentials, query or fragment")


def chat_completion_request(session, *, base_url, model, messages, api_key=None,
                            temperature=0.7, max_tokens=10000, top_p=1.0,
                            send_temperature=True, send_top_p=True, reasoning_mode="default",
                            reasoning_effort="medium", reasoning_format="openai", max_tokens_parameter="max_tokens"):
    validate_base_url(base_url)
    request_options({"send_temperature": send_temperature, "send_top_p": send_top_p,
                     "reasoning_mode": reasoning_mode, "reasoning_effort": reasoning_effort,
                     "reasoning_format": reasoning_format,
                     "max_tokens_parameter": max_tokens_parameter})
    payload = {"model": model, "messages": messages, max_tokens_parameter: max_tokens, "stream": False}
    if send_temperature:
        payload["temperature"] = temperature
    if send_top_p:
        payload["top_p"] = top_p
    if reasoning_mode != "default":
        if reasoning_format == "chat_template":
            payload["chat_template_kwargs"] = {"enable_thinking": reasoning_mode == "on"}
            if reasoning_mode == "on":
                payload["chat_template_kwargs"]["reasoning_effort"] = reasoning_effort
        else:
            payload["reasoning_effort"] = "none" if reasoning_mode == "off" else reasoning_effort
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return session.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers,
                        ssl=TLS_CONTEXT)
