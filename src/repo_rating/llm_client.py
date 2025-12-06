"""OpenRouter LLM client with rate limiting, retries, and usage tracking."""

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .log import get_logger


OPENROUTER_API = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY_API = "https://openrouter.ai/api/v1/key"
OPENROUTER_MODELS_API = "https://openrouter.ai/api/v1/models"
MAMMOUTH_API = "https://api.mammouth.ai/v1/chat/completions"

# Cache for model prices (avoid repeated API calls)
_model_prices_cache: dict[str, dict] = {}


@dataclass
class ModelPrice:
    """Model pricing info (per million tokens)."""
    prompt: float | None = None   # $ per million input tokens
    completion: float | None = None  # $ per million output tokens


@dataclass
class LLMUsage:
    """Track LLM API usage."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0


class OpenRouterClient:
    """OpenRouter client with rate limiting and retries.
    
    Designed for both paid and free-tier models.
    """
    
    def __init__(
        self,
        api_key: str,
        min_delay_s: float = 1.0,      # min delay between calls
        max_retries: int = 3,
        backoff_base_s: float = 2.0,   # exponential: 2, 4, 8...
        timeout_s: float = 180.0,      # longer timeout for free models
    ):
        self.api_key = api_key
        self.min_delay_s = min_delay_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.timeout_s = timeout_s
        
        self._last_call_ts: float = 0.0
        self.usage = LLMUsage()
    
    def _respect_rate_limit(self) -> None:
        """Enforce min delay between requests."""
        now = time.monotonic()
        delta = now - self._last_call_ts
        if delta < self.min_delay_s:
            time.sleep(self.min_delay_s - delta)
    
    def _update_usage(self, usage_data: dict | None) -> None:
        if not usage_data:
            return
        self.usage.prompt_tokens += usage_data.get("prompt_tokens", 0)
        self.usage.completion_tokens += usage_data.get("completion_tokens", 0)
        self.usage.total_tokens += usage_data.get("total_tokens", 0)
        self.usage.calls += 1
    
    def call(
        self,
        prompt: str,
        model: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Call OpenRouter with retries and rate limiting.
        
        Returns the raw text response from the model.
        """
        log = get_logger()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "repo-rating",  # Shows in OpenRouter dashboard
        }
        
        # Detect provider from model prefix
        api_url = OPENROUTER_API
        api_model = model
        if model.startswith("mammouth/"):
            api_url = MAMMOUTH_API
            api_model = model.replace("mammouth/", "", 1)
            log.debug(f"Using Mammouth API for {api_model}")
        
        payload = {
            "model": api_model,
            "messages": messages,
            "temperature": temperature,
        }
        
        last_error: Exception | None = None
        
        for attempt in range(self.max_retries + 1):
            # Exponential backoff on retry
            if attempt > 0:
                delay = self.backoff_base_s * (2 ** (attempt - 1))
                log.info(f"Retry {attempt}/{self.max_retries} after {delay}s...")
                time.sleep(delay)
            
            self._respect_rate_limit()
            
            try:
                log.debug(f"Calling {model} (attempt {attempt + 1})")
                
                resp = httpx.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_s,
                )
                
                self._last_call_ts = time.monotonic()
                
                # Handle error responses
                if resp.status_code >= 400:
                    try:
                        err_json = resp.json()
                        err_msg = err_json.get("error", {}).get("message", resp.text)
                    except Exception:
                        err_msg = resp.text
                    
                    log.warning(f"OpenRouter HTTP {resp.status_code}: {err_msg}")
                    
                    # Retry on rate limit (429) or server error (5xx)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_error = httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}: {err_msg}",
                            request=resp.request,
                            response=resp,
                        )
                        continue
                    
                    # Non-retriable error
                    resp.raise_for_status()
                
                data = resp.json()
                self._update_usage(data.get("usage"))
                
                # Check for valid response structure
                if "choices" not in data or not data["choices"]:
                    err_msg = data.get("error", {}).get("message", "No choices in response")
                    log.warning(f"Invalid response from {model}: {err_msg}")
                    last_error = ValueError(f"LLM returned invalid response: {err_msg}")
                    continue
                
                content = data["choices"][0]["message"]["content"]
                log.debug(f"Response: {len(content)} chars")
                return content
                
            except httpx.TimeoutException as e:
                log.warning(f"Request timeout: {e}")
                last_error = e
                continue
                
            except httpx.RequestError as e:
                log.warning(f"Network error: {e}")
                last_error = e
                continue
        
        # All retries exhausted
        if last_error:
            raise last_error
        raise RuntimeError("LLM call failed without specific error")
    
    def get_credits(self) -> dict:
        """Check remaining API credits."""
        resp = httpx.get(
            OPENROUTER_KEY_API,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


# Module-level client instance (lazy initialized)
_client: OpenRouterClient | None = None


def get_client(api_key: str, free_tier: bool = False) -> OpenRouterClient:
    """Get or create the OpenRouter client.
    
    Args:
        api_key: OpenRouter API key
        free_tier: If True, use longer delays for rate limiting
    """
    global _client
    if _client is None or _client.api_key != api_key:
        min_delay = 6.0 if free_tier else 1.0
        _client = OpenRouterClient(
            api_key=api_key,
            min_delay_s=min_delay,
            timeout_s=300.0 if free_tier else 180.0,
        )
    return _client


def call_llm(
    prompt: str,
    model: str,
    api_key: str,
    system_prompt: str | None = None,
) -> str:
    """Call OpenRouter API with the given prompt.
    
    Returns the raw text response from the model.
    Special model "mock" returns a placeholder response without API call.
    
    This is the main entry point - wraps OpenRouterClient for simple usage.
    For Mammouth models (prefixed with "mammouth/"), pass mammouth key as api_key.
    """
    log = get_logger()
    
    # Mock model for testing pipeline without LLM calls
    if model == "mock":
        log.info("Using mock model - returning placeholder response")
        return _mock_response()
    
    if not api_key:
        provider = "Mammouth" if model.startswith("mammouth/") else "OpenRouter"
        raise ValueError(f"{provider} API key is required")
    
    # Check if using free-tier model (OpenRouter only)
    is_free = ":free" in model.lower() and not model.startswith("mammouth/")
    client = get_client(api_key, free_tier=is_free)
    
    provider_name = "Mammouth" if model.startswith("mammouth/") else "OpenRouter"
    log.info(f"Calling {model} ({provider_name})" + (" (free tier)" if is_free else ""))
    log.debug(f"Prompt length: {len(prompt)} chars")
    
    return client.call(prompt, model, system_prompt)


def _mock_response() -> str:
    """Return a placeholder response for mock model."""
    return json.dumps({
        "summary": "Mock analysis - pipeline test",
        "tech_stack": ["Python", "Mock"],
        "project_type": "test project",
        "complexity": "low",
        "code_quality_indicators": ["mock response"],
        "maturity": "test",
        "temporal_context": "Mock model used for testing",
        "notable_for_resume": ["pipeline testing"],
        "honest_assessment": "This is a mock response for testing the pipeline without LLM calls."
    })


def parse_json_response(response: str) -> dict:
    """Extract JSON from LLM response.
    
    Handles responses that may have markdown code fences or extra text.
    """
    log = get_logger()
    
    # Try to find JSON in code fence
    if "```json" in response:
        start = response.find("```json") + 7
        end = response.find("```", start)
        if end != -1:
            response = response[start:end]
    elif "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        if end != -1:
            response = response[start:end]
    
    # Try to find JSON object
    response = response.strip()
    if not response.startswith("{"):
        # Look for first { in the text
        brace_idx = response.find("{")
        if brace_idx != -1:
            response = response[brace_idx:]
    
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON: {e}")
        log.debug(f"Raw response: {response[:500]}")
        raise ValueError(f"Failed to parse LLM response as JSON: {e}")


def get_usage() -> LLMUsage:
    """Get current usage stats for the active client."""
    if _client:
        return _client.usage
    return LLMUsage()


def get_model_price(model: str) -> ModelPrice:
    """Get pricing for a model from OpenRouter.
    
    Returns ModelPrice with None values if:
    - Model is not found
    - API call fails
    - Model doesn't have pricing (local, mock, etc.)
    
    Prices are per million tokens.
    """
    global _model_prices_cache
    log = get_logger()
    
    # Mock model has no price
    if model == "mock":
        return ModelPrice()
    
    # Check cache first
    if model in _model_prices_cache:
        return _model_prices_cache[model]
    
    try:
        resp = httpx.get(OPENROUTER_MODELS_API, timeout=10)
        if resp.status_code != 200:
            log.debug(f"Failed to fetch models: HTTP {resp.status_code}")
            return ModelPrice()
        
        data = resp.json()
        
        # Build cache from all models
        for m in data.get("data", []):
            model_id = m.get("id", "")
            pricing = m.get("pricing", {})
            
            # Convert from per-token string to per-million float
            prompt_price = pricing.get("prompt")
            completion_price = pricing.get("completion")
            
            _model_prices_cache[model_id] = ModelPrice(
                prompt=float(prompt_price) * 1_000_000 if prompt_price else None,
                completion=float(completion_price) * 1_000_000 if completion_price else None,
            )
        
        return _model_prices_cache.get(model, ModelPrice())
        
    except Exception as e:
        log.debug(f"Failed to fetch model prices: {e}")
        return ModelPrice()


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 500) -> float | None:
    """Estimate cost for a given model and token counts.
    
    Args:
        model: Model ID
        input_tokens: Number of input tokens
        output_tokens: Estimated output tokens (default 500)
    
    Returns:
        Estimated cost in USD, or None if pricing unavailable
    """
    log = get_logger()
    price = get_model_price(model)
    
    if price.prompt is None:
        log.debug(f"No pricing info available for {model}")
        return None
    
    input_cost = (input_tokens / 1_000_000) * price.prompt
    output_cost = (output_tokens / 1_000_000) * (price.completion or 0)
    total = input_cost + output_cost
    
    log.debug(f"Price: ${price.prompt:.2f}/M in, ${price.completion or 0:.2f}/M out")
    log.debug(f"Est: {input_tokens} in × ${price.prompt:.2f}/M = ${input_cost:.4f}")
    log.debug(f"Est: {output_tokens} out × ${price.completion or 0:.2f}/M = ${output_cost:.4f}")
    
    return total
