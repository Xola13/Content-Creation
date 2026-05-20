"""
ai.py — Groq API wrapper for topic selection, script generation, and caption creation.
Uses direct HTTP requests (no SDK dependency).
"""

import os
import json
import time
import logging
import requests

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama3-8b-8192"
MAX_RETRIES = 3


def _call_groq(messages: list, retries: int = MAX_RETRIES) -> str:
    """Send a chat completion request to Groq and return the raw text response."""
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set in environment")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content.strip()

        except requests.exceptions.HTTPError as exc:
            logger.warning(f"Groq HTTP error attempt {attempt}: {exc}")
        except Exception as exc:
            logger.warning(f"Groq call error attempt {attempt}: {exc}")

        if attempt < retries:
            time.sleep(2 ** attempt)  # Exponential back-off: 2s, 4s

    raise RuntimeError(f"Groq API failed after {retries} attempts")


def _safe_parse_json(raw: str, context: str = "") -> dict:
    """Extract and parse the first JSON object/array found in `raw`."""
    try:
        # Strip markdown code fences if present
        clean = raw.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if clean.endswith("```"):
            clean = "\n".join(clean.split("\n")[:-1])
        return json.loads(clean.strip())
    except json.JSONDecodeError:
        # Try to find a JSON block inside surrounding prose
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                pass
        logger.error(f"JSON parse failed [{context}]. Raw:\n{raw[:500]}")
        return {}


def pick_best_topic(topics: list) -> dict:
    """
    From a global trending list, choose the topic with the highest viral +
    monetisation potential that can be contextualised for a South African audience.

    Returns: {"topic": str, "title": str, "format": str, "sa_angle": str}
    """
    niche = os.getenv("PREFERRED_NICHE", "finance south africa")
    # Send the top 30 topics — model picks the single best one
    topics_str = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics[:30]))

    messages = [
        {
            "role": "system",
            "content": (
                "You are a YouTube growth strategist who creates viral finance content. "
                "Your channel targets South African viewers but covers GLOBAL trending topics, "
                "always giving them a South African angle (how it affects SA, rand, jobs, economy). "
                "Globally viral topics get far more impressions than local-only topics. "
                "You always respond with valid JSON only — no extra text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"These are the most trending topics WORLDWIDE right now:\n\n{topics_str}\n\n"
                f"Pick the ONE topic that:\n"
                f"1. Is trending globally (maximum search volume and virality)\n"
                f"2. Can be given a strong South African angle (how it impacts SA people, rand, jobs, cost of living)\n"
                f"3. Has high ad CPM potential in the {niche} niche\n"
                f"4. Will attract both SA viewers AND global English-speaking viewers\n\n"
                "Respond ONLY with this JSON structure:\n"
                "{\n"
                '  "topic": "<the chosen global topic>",\n'
                '  "title": "<YouTube title — include SA angle, numbers, urgency>",\n'
                '  "format": "<listicle|explainer|news|reaction|breakdown>",\n'
                '  "sa_angle": "<one sentence: how this global topic specifically impacts South Africans>"\n'
                "}"
            ),
        },
    ]

    raw = _call_groq(messages)
    result = _safe_parse_json(raw, "pick_best_topic")

    # Safe defaults
    if not result.get("topic"):
        result["topic"] = topics[0] if topics else "global economy impact on South Africa"
    if not result.get("title"):
        result["title"] = result["topic"]
    if not result.get("format"):
        result["format"] = "explainer"
    if not result.get("sa_angle"):
        result["sa_angle"] = f"How {result['topic']} affects South Africa"

    logger.info(f"Selected topic: {result['topic']}")
    return result


def generate_script(topic_data: dict) -> dict:
    """
    Generate a full video script plus SEO metadata for the chosen topic.

    Returns:
        {
            "title": str,
            "description": str,
            "tags": list[str],
            "sections": list[str],
            "full_script": str,
        }
    """
    topic = topic_data.get("topic", "")
    title = topic_data.get("title", topic)
    fmt = topic_data.get("format", "explainer")
    sa_angle = topic_data.get("sa_angle", f"How {topic} affects South Africa")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert YouTube scriptwriter who creates viral finance content "
                "on GLOBAL trending topics with a South African lens. "
                "Your scripts hook global viewers with the trending topic, then deliver "
                "the SA-specific impact — maximising both reach and relevance. "
                "You always respond with valid JSON only — no extra text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Write a {fmt} YouTube video script about the globally trending topic: '{title}'\n\n"
                f"South African angle to weave throughout: {sa_angle}\n\n"
                "Script requirements:\n"
                "- 400-600 words total\n"
                "- Hook (first 15s): lead with the GLOBAL trend — make it urgent and relatable\n"
                "- Section 1: What is happening globally (the trend, the numbers, the stakes)\n"
                "- Section 2: How this directly impacts South Africans (rand, jobs, prices, economy)\n"
                "- Section 3: What experts / data say about where this is heading\n"
                "- Section 4: What South Africans can DO about it (actionable advice)\n"
                "- CTA: subscribe + like + comment what they think\n\n"
                "SEO metadata requirements:\n"
                "- title: include both the global keyword AND 'South Africa' for dual audience\n"
                "- description: 150-word SEO description — global keyword first, SA impact second\n"
                "- tags: 15 tags mixing global keywords (high volume) and SA-specific terms\n\n"
                "Respond ONLY with this JSON structure:\n"
                "{\n"
                '  "title": "<final YouTube title>",\n'
                '  "description": "<150-word SEO description>",\n'
                '  "tags": ["tag1", "tag2", ...],\n'
                '  "sections": ["Section 1 heading", "Section 2 heading", "Section 3 heading", "Section 4 heading"],\n'
                '  "full_script": "<complete 400-600 word script>"\n'
                "}"
            ),
        },
    ]

    raw = _call_groq(messages)
    result = _safe_parse_json(raw, "generate_script")

    # Safe defaults
    if not result.get("title"):
        result["title"] = title
    if not result.get("description"):
        result["description"] = f"Learn about {topic} in South Africa."
    if not result.get("tags"):
        result["tags"] = [topic, "south africa", "finance", "money", "investing"]
    if not result.get("sections"):
        result["sections"] = ["Introduction", "Main Content", "Key Takeaways", "Conclusion"]
    if not result.get("full_script"):
        result["full_script"] = result.get("description", "")

    logger.info(f"Script generated — {len(result['full_script'].split())} words")
    return result


def generate_captions(title: str, tags: list) -> dict:
    """
    Generate platform-optimised social captions for repurposed content.

    Returns:
        {
            "tiktok": str,
            "reels": str,
            "shorts": str,
            "spotify": str,
        }
    """
    tags_str = " ".join(f"#{t.replace(' ', '')}" for t in tags[:8])

    messages = [
        {
            "role": "system",
            "content": (
                "You are a social media copywriter. You write punchy, platform-native captions. "
                "You always respond with valid JSON only — no extra text."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Write social media captions for a video titled: '{title}'\n\n"
                f"Available hashtags: {tags_str}\n\n"
                "Platform requirements:\n"
                "- tiktok: Punchy 2-3 line caption, 3-5 trending hashtags, hook question\n"
                "- reels: Engaging caption with emojis, call to action, 4-6 hashtags\n"
                "- shorts: Ultra short (1-2 lines), 2-3 hashtags, high energy\n"
                "- spotify: Podcast-style description, 100 words, no hashtags\n\n"
                "Respond ONLY with this JSON structure:\n"
                '{"tiktok": "...", "reels": "...", "shorts": "...", "spotify": "..."}'
            ),
        },
    ]

    raw = _call_groq(messages)
    result = _safe_parse_json(raw, "generate_captions")

    defaults = {
        "tiktok": f"{title} {tags_str}",
        "reels": f"{title} — watch now! {tags_str}",
        "shorts": f"{title} #shorts",
        "spotify": f"In this episode we discuss {title}.",
    }
    for platform, default in defaults.items():
        if not result.get(platform):
            result[platform] = default

    logger.info("Platform captions generated")
    return result
