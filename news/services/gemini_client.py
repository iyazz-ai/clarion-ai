"""
One place for Gemini calls - built for FREE-TIER limits:

* RPM pacing   : never exceeds GEMINI_RPM_LIMIT requests per minute.
* Daily budget : counts requests per model per day in the database (GeminiUsage)
                 and stops BEFORE Google refuses (GEMINI_DAILY_REQUEST_LIMIT).
* Fallback     : GEMINI_MODELS=modelA:rpd:rpm,modelB:rpd:rpm - each model has
                 its own free quota, so when A is used up (or its ID is wrong),
                 B is tried. rpd/rpm are optional; defaults come from
                 GEMINI_DAILY_REQUEST_LIMIT / GEMINI_RPM_LIMIT.
* Quota errors : raise QuotaExceeded (callers stop cleanly, nothing is
                 counted as a story failure).
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

# Leave a little headroom under Google's real limit (check AI Studio > Rate Limit).
DAILY_LIMIT = int(os.getenv("GEMINI_DAILY_REQUEST_LIMIT", "18"))
RPM_LIMIT = int(os.getenv("GEMINI_RPM_LIMIT", "5"))


def _parse_models(raw):
    """'a:18:5,b:480:15' -> (['a','b'], {'a': (18,5), 'b': (480,15)})"""
    order, limits = [], {}
    for item in raw.split(","):
        parts = [p.strip() for p in item.strip().split(":")]
        if not parts[0]:
            continue
        rpd = int(parts[1]) if len(parts) > 1 and parts[1] else DAILY_LIMIT
        rpm = int(parts[2]) if len(parts) > 2 and parts[2] else RPM_LIMIT
        order.append(parts[0])
        limits[parts[0]] = (rpd, rpm)
    return order, limits


MODELS, MODEL_LIMITS = _parse_models(
    os.getenv("GEMINI_MODELS", os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
)
MODEL_NAME = MODELS[0]          # kept for older imports


def _rpd(model):
    return MODEL_LIMITS.get(model, (DAILY_LIMIT, RPM_LIMIT))[0]


def _rpm(model):
    return MODEL_LIMITS.get(model, (DAILY_LIMIT, RPM_LIMIT))[1]


DEFAULT_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "60000"))

_client = None
_last_request_at = 0.0

# After a project-level 429 a model is skipped for this long (this run only), so
# the next batches go straight to the fallback model instead of waiting again.
COOLDOWN_SECONDS = 15 * 60
BUSY_COOLDOWN_SECONDS = 10 * 60
_COOLDOWN_UNTIL = {}


class ModelUnavailable(RuntimeError):
    """The model ID does not exist / is not enabled for this key."""


class QuotaExceeded(RuntimeError):
    """Gemini rate/daily limit hit (HTTP 429 / RESOURCE_EXHAUSTED) or our own budget used up."""


class ServiceBusy(QuotaExceeded):
    """503 / "high demand" / timeout. Subclass of QuotaExceeded on purpose: callers
    already treat that as "stop, keep stories queued, do not count a failure"."""


def _is_quota_error(error):
    text = str(error).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


def _is_busy_error(error):
    text = str(error).lower()
    return any(k in text for k in (
        "503", "unavailable", "high demand", "overloaded", "timed out",
        "timeout", "deadline",
    ))


def _is_model_missing(error):
    text = str(error).lower()
    return "404" in text or "not_found" in text or "is not found" in text


def _is_daily_quota_error(error):
    return "perday" in str(error).lower().replace(" ", "").replace("_", "")


# ---------------------------------------------------------------- budget
def _quota_day():
    # Google resets free-tier daily quotas at midnight Pacific (AI Studio
    # shows UTC-8); a fixed -8h offset is close enough for a budget guard.
    return (datetime.now(timezone.utc) - timedelta(hours=8)).strftime("%Y-%m-%d")


def requests_today(model):
    from news.models import GeminiUsage      # lazy: keeps this module importable early

    row = GeminiUsage.objects.filter(day=_quota_day(), model=model).first()
    return row.count if row else 0


def _record_request(model, exhausted=False):
    from django.db.models import F
    from news.models import GeminiUsage

    row, _ = GeminiUsage.objects.get_or_create(day=_quota_day(), model=model)
    if exhausted:
        GeminiUsage.objects.filter(pk=row.pk).update(count=_rpd(model))
    else:
        GeminiUsage.objects.filter(pk=row.pk).update(count=F("count") + 1)


def usage_summary():
    parts = [f"{m}: {requests_today(m)}/{_rpd(m)}" for m in MODELS]
    return "Gemini requests today (local count) - " + ", ".join(parts)


def _pace(model):
    """Sleep just enough to stay under the requests-per-minute limit."""
    global _last_request_at
    min_gap = 60.0 / max(_rpm(model), 1) + 1.0
    wait = _last_request_at + min_gap - time.time()
    if wait > 0:
        print(f"  [gemini] pacing: waiting {wait:.0f}s (rate limit {_rpm(model)}/min)", flush=True)
        time.sleep(wait)
    _last_request_at = time.time()


# ---------------------------------------------------------------- client
def get_client():
    global _client
    if _client is None:
        from google import genai   # imported lazily

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set (check your .env).")

        # The SDK silently retries 429 errors with long waits, which made the
        # command look frozen. Turn that off: we handle quota errors here.
        try:
            from google.genai import types
            options = types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            )
            _client = genai.Client(api_key=api_key, http_options=options)
        except (ImportError, AttributeError, TypeError):
            _client = genai.Client(api_key=api_key)
    return _client


def parse_json_object(raw_text):
    """Parse JSON even if the model wrapped it in ``` fences or added prose."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object in model output: {raw_text[:200]!r}")
    return json.loads(text[start:end + 1])


def _call_model(model, prompt, retries, timeout):
    client = get_client()
    last_error = None

    if time.time() < _COOLDOWN_UNTIL.get(model, 0):
        raise QuotaExceeded(f"{model} is cooling down after a quota error.")

    for attempt in range(retries):
        if requests_today(model) >= _rpd(model):
            raise QuotaExceeded(f"Local daily budget for {model} used up "
                                f"({_rpd(model)}/day).")
        _pace(model)
        started = time.time()
        recorded = False
        print(f"  [gemini] {model}: request {requests_today(model) + 1}/{_rpd(model)} "
              f"today (attempt {attempt + 1}/{retries}) ...", flush=True)
        try:
            interaction = client.interactions.create(
                model=model, input=prompt, timeout=timeout,
            )
            _record_request(model)
            recorded = True
            result = parse_json_object(interaction.output_text)
            print(f"  [gemini] answered in {time.time() - started:.0f}s", flush=True)
            return result
        except Exception as error:
            last_error = error
            quota = _is_quota_error(error)
            if not recorded:          # the request itself failed: it still counts
                _record_request(model, exhausted=quota and _is_daily_quota_error(error))
            print(f"  [gemini] attempt {attempt + 1} failed after "
                  f"{time.time() - started:.0f}s: {str(error)[:120]}", flush=True)
            if _is_busy_error(error) and not _is_quota_error(error):
                # Google is overloaded (503 / timeout). Retrying the same model
                # just burns ~35s per attempt. Skip it for a while and let the
                # next model (or the next scheduled run) handle the stories.
                # This is NOT the stories' fault, so callers must not count it.
                _COOLDOWN_UNTIL[model] = time.time() + BUSY_COOLDOWN_SECONDS
                raise ServiceBusy(f"{model}: {str(error)[:150]}") from error
            if _is_model_missing(error):
                raise ModelUnavailable(f"{model}: {str(error)[:150]}") from error
            if quota:
                # Pacing already keeps us under the per-minute limit, so a 429
                # means the project's quota for this model is used up. Retrying
                # the same model only wastes time and requests: cool it down
                # and let generate_json try the next model.
                _COOLDOWN_UNTIL[model] = time.time() + COOLDOWN_SECONDS
                raise QuotaExceeded(str(error)) from error
            if attempt < retries - 1:
                time.sleep(3 * (2 ** attempt))

    raise last_error


def generate_json(prompt, retries=2, timeout=DEFAULT_TIMEOUT_MS):
    """
    Call Gemini and return a parsed dict, trying each model in GEMINI_MODELS
    in order. Raises QuotaExceeded when every model is used up.
    """
    last_quota_error = None
    for model in MODELS:
        try:
            return _call_model(model, prompt, retries, timeout)
        except (QuotaExceeded, ModelUnavailable, ServiceBusy) as error:
            last_quota_error = error
            print(f"  [gemini] {model} unavailable: {str(error)[:100]}", flush=True)
            continue
    raise QuotaExceeded(
        "No Gemini model is available right now (daily quota used up or service "
        f"busy). Stories stay queued. Last problem: {last_quota_error}"
    )
