"""
llm_narrative_tool.py — Groq API wrapper for SCRIBE
Generates natural language narratives using Llama-3.1-8B via Groq.

WHY GROQ?
- 14,400 free calls/day (vs HuggingFace 1000/day)
- ~0.5 sec response (vs HF 2-10 sec + cold starts)
- Production-grade reliability — no DNS issues, no 503s
- Llama-3.1-8B — better instruction following than Phi-3-mini

ARCHITECTURE:
  SCRIBE calls generate_narrative(context, report_type)
       ↓
  Load prompt template from YAML
       ↓
  Fill template with context dict
       ↓
  POST to api.groq.com
       ↓
  Return narrative string
  (fallback if API fails — SCRIBE never crashes)
"""

import os
import logging
import requests
import yaml
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq pe best free model — fast aur instruction-following mein strong
GROQ_MODEL = "llama-3.1-8b-instant"

# YAML config path — is file se 2 levels upar backend/configs/
PROMPTS_PATH = Path(__file__).parent.parent / "configs" / "scribe_prompts.yaml"

# ── Prompt loader ──────────────────────────────────────────────────────────────

def _load_prompts() -> dict:
    """
    YAML se prompt templates load karo.
    Module level pe ek baar load hota hai — har call pe disk read nahi.
    """
    with open(PROMPTS_PATH, "r") as f:
        return yaml.safe_load(f)

# Module import hote hi ek baar load
_PROMPTS = _load_prompts()


# ── Fallback generator ─────────────────────────────────────────────────────────

def _generate_fallback(context: dict, report_type: str) -> str:
    """
    Jab Groq API fail ho — template-based fallback.
    WHY? Production system mein graceful degradation mandatory hai.
    SCRIBE kabhi empty string ya exception return nahi karega.
    
    format_map() use kiya — missing keys pe KeyError nahi aata,
    {key} as-is reh jaata hai. Safe for partial context.
    """
    template = _PROMPTS["fallbacks"].get(report_type, "")
    if not template:
        return f"[FALLBACK] {report_type} — {datetime.now(timezone.utc).isoformat()}"
    try:
        return template.strip().format_map(context)
    except Exception as e:
        logger.error(f"Fallback template error: {e}")
        return f"[FALLBACK ERROR] {report_type} — data unavailable"


# ── Main function ──────────────────────────────────────────────────────────────

def generate_narrative(context: dict, report_type: str) -> dict:
    """
    Main entry point — SCRIBE is function ko call karta hai.

    Args:
        context     : dict with all template variables
        report_type : "hourly_snapshot" | "alert_narrative" | "daily_briefing"

    Returns:
        {
          "narrative"   : str,   # generated text
          "source"      : str,   # "llm" | "fallback" | "fallback_*"
          "report_type" : str,
          "timestamp"   : str
        }

    WHY return dict?
    Caller ko pata rehna chahiye — LLM se aaya ya fallback se.
    DB mein source field store karte hain — auditability ke liye.
    """

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set — using fallback")
        return {
            "narrative"  : _generate_fallback(context, report_type),
            "source"     : "fallback_no_key",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }

    # ── Prompt config fetch ────────────────────────────────────────────────────
    prompt_config = _PROMPTS["prompts"].get(report_type)
    if not prompt_config:
        logger.error(f"Unknown report_type: {report_type}")
        return {
            "narrative"  : _generate_fallback(context, report_type),
            "source"     : "fallback_unknown_type",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }

    system_prompt = prompt_config["system"].strip()
    max_tokens    = prompt_config.get("max_tokens", 300)

    # ── User prompt mein context inject karo ──────────────────────────────────
    # format_map() — context dict ke values template mein fill hote hain
    # Example: {anomaly_count} → 3
    try:
        user_prompt = prompt_config["user_template"].strip().format_map(context)
    except Exception as e:
        logger.error(f"Template formatting error: {e}")
        return {
            "narrative"  : _generate_fallback(context, report_type),
            "source"     : "fallback_template_error",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }

    # ── API call ───────────────────────────────────────────────────────────────
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type" : "application/json"
    }

    # Groq OpenAI-compatible format use karta hai
    payload = {
        "model"      : GROQ_MODEL,
        "messages"   : [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        "max_tokens" : max_tokens,
        "temperature": 0.3  # low = deterministic, good for factual reports
    }

    try:
        response = requests.post(
            GROQ_API_URL,
            headers=headers,
            json=payload,
            timeout=15  # Groq fast hai — 15 sec kaafi hai
        )

        # ── Rate limit ─────────────────────────────────────────────────────────
        if response.status_code == 429:
            logger.warning("Groq rate limit hit — using fallback")
            return {
                "narrative"  : _generate_fallback(context, report_type),
                "source"     : "fallback_rate_limit",
                "report_type": report_type,
                "timestamp"  : datetime.now(timezone.utc).isoformat()
            }

        response.raise_for_status()

        # ── Response parse ─────────────────────────────────────────────────────
        # Groq OpenAI-compatible response format:
        # {"choices": [{"message": {"content": "narrative text"}}]}
        result    = response.json()
        narrative = result["choices"][0]["message"]["content"].strip()

        if not narrative:
            raise ValueError("Empty narrative from Groq")

        logger.info(f"Groq narrative OK — type={report_type}, chars={len(narrative)}")

        return {
            "narrative"  : narrative,
            "source"     : "llm",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }

    except requests.exceptions.Timeout:
        logger.error("Groq API timeout — using fallback")
        return {
            "narrative"  : _generate_fallback(context, report_type),
            "source"     : "fallback_timeout",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Groq API error: {e} — using fallback")
        return {
            "narrative"  : _generate_fallback(context, report_type),
            "source"     : "fallback_error",
            "report_type": report_type,
            "timestamp"  : datetime.now(timezone.utc).isoformat()
        }


# ── Quick test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Dummy context — real data jaisi structure
    test_context = {
        "timestamp"          : datetime.now(timezone.utc).isoformat(),
        "health_score"       : 78,
        "anomaly_count"      : 3,
        "top_anomaly_sensor" : "temp_sensor_C",
        "threat_count"       : 1,
        "guardian_status"    : "ACTIVE",
        "failure_predictions": 2,
        "next_maintenance"   : "Machine_C in 4 hours",
        "optimus_action"     : "REDUCE_10",
        "energy_savings_eur" : "2.40",
        "inventory_alerts"   : 1,
        "reorder_count"      : 1
    }

    print("=" * 60)
    print("llm_narrative_tool.py — Groq Test")
    print("=" * 60)

    print("\n[TEST 1] Fallback test (no key):")
    original = os.environ.pop("GROQ_API_KEY", None)
    r1 = generate_narrative(test_context, "hourly_snapshot")
    print(f"  Source   : {r1['source']}")
    print(f"  Narrative:\n{r1['narrative']}")
    if original:
        os.environ["GROQ_API_KEY"] = original

    print("\n[TEST 2] Live Groq API:")
    if os.getenv("GROQ_API_KEY"):
        r2 = generate_narrative(test_context, "hourly_snapshot")
        print(f"  Source   : {r2['source']}")
        print(f"  Narrative:\n{r2['narrative']}")
    else:
        print("  SKIP — GROQ_API_KEY not set")

    print("\n[TEST 3] Alert narrative (live):")
    if os.getenv("GROQ_API_KEY"):
        alert_context = {
            "timestamp"          : datetime.now(timezone.utc).isoformat(),
            "agent_name"         : "SENTINEL",
            "severity"           : "CRITICAL",
            "event_description"  : "Temperature sensor C exceeded 850°C threshold",
            "affected_component" : "Machine_C furnace unit",
            "auto_action"        : "Thermal shutdown initiated, ORACLE notified",
            "system_status"      : "Machine_C offline, others nominal"
        }
        r3 = generate_narrative(alert_context, "alert_narrative")
        print(f"  Source   : {r3['source']}")
        print(f"  Narrative:\n{r3['narrative']}")

    print("\nOK llm_narrative_tool.py done")
