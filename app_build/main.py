import asyncio
import logging
import re
from typing import Dict, Any, List, Optional
import httpx
import feedparser
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse

from config import get_settings

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("mantaw")

app = FastAPI(title="Mantaw News Radar", version="1.0.0")

# RSS Feeds to Monitor
FEEDS = {
    "TechCrunch": "https://feeds.feedburner.com/TechCrunch/",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "OpenAI": "https://openai.com/news/rss.xml",
    "Hacker News": "https://hnrss.org/frontpage",
    "GitHub Trending": "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"
}

# Keywords Configurations
ALLOWLIST = [
    "nvidia", "openai", "anthropic", "deepmind", "google ai", "meta ai",
    "robot", "robotics", "humanoid", "gpu", "ai agent", "agentic",
    "crypto", "bitcoin", "ethereum", "wallet", "drained", "exploit",
    "hack", "breach", "security", "github", "open source model",
    "startup", "llm", "cloud run", "google cloud", "model release", "ai model"
]

BLOCKLIST = [
    "sponsored", "giveaway", "coupon", "price prediction",
    "promo", "discount", "casino", "betting"
]

IMPORTANT_WORDS = [
    "announces", "launch", "released", "release", "research",
    "model", "security", "exploit", "hack", "breach", "vulnerability"
]

MONEY_INDICATORS = ["$", "million", "billion", "juta", "miliar", "trillion"]

# Category Classification Rules
CRYPTO_WORDS = ["crypto", "bitcoin", "ethereum", "wallet", "exploit", "hack", "drained"]
AI_ROBOT_WORDS = ["nvidia", "gpu", "robot", "robotics", "humanoid"]
AI_WORDS = ["openai", "anthropic", "deepmind", "model", "agent", "llm"]


def clean_html(text: str) -> str:
    """Removes HTML tags and normalizes whitespace."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    return " ".join(clean.split())


def process_feed_item(item: Dict[str, Any], source_name: str) -> Optional[Dict[str, Any]]:
    """Filters, scores, and categorizes a single RSS feed item."""
    title = item.get("title", "")
    summary = item.get("summary", "") or item.get("description", "") or ""
    link = item.get("link", "")
    published = item.get("published", "N/A")

    combined_text_lower = f"{title.lower()} {summary.lower()}"

    # 1. Blocklist Filter: Block the item if it contains any blocklist keyword
    for block_word in BLOCKLIST:
        if block_word in combined_text_lower:
            logger.debug(f"Item blocked due to blocklist keyword '{block_word}': {title}")
            return None

    # 2. Scoring Engine
    score = 0
    matched_keywords = []

    # +1 for every matched allowlist keyword
    for keyword in ALLOWLIST:
        if keyword in combined_text_lower:
            score += 1
            matched_keywords.append(keyword)

    # +2 if title or summary contains important words
    for word in IMPORTANT_WORDS:
        if word in combined_text_lower:
            score += 2
            break

    # +2 if title or summary contains money or large-scale indicators
    for indicator in MONEY_INDICATORS:
        if indicator in combined_text_lower:
            score += 2
            break

    # 3. Category Classification
    if any(word in combined_text_lower for word in CRYPTO_WORDS):
        category = "Crypto/Security"
    elif any(word in combined_text_lower for word in AI_ROBOT_WORDS):
        category = "AI/Robotics"
    elif any(word in combined_text_lower for word in AI_WORDS):
        category = "AI"
    else:
        category = "Tech"

    return {
        "title": title,
        "summary": summary,
        "link": link,
        "published": published,
        "score": score,
        "matched_keywords": matched_keywords,
        "category": category,
        "source": source_name
    }


async def fetch_and_parse_feed(client: httpx.AsyncClient, name: str, url: str) -> List[Dict[str, Any]]:
    """Fetches feed contents and parses it. Fault tolerant against feed failures."""
    try:
        logger.info(f"Fetching feed: {name} ({url})")
        response = await client.get(url, timeout=12.0, follow_redirects=True)
        response.raise_for_status()

        parsed = feedparser.parse(response.content)
        if parsed.bozo:
            logger.warning(f"Feed '{name}' parsed with potential XML malformations (bozo bit set).")

        return parsed.entries
    except Exception as e:
        logger.error(f"Failed to fetch or parse feed '{name}' from {url}: {e}")
        return []


def format_discord_embed(item: Dict[str, Any]) -> Dict[str, Any]:
    """Formats an item as a Discord rich embed."""
    emoji = "🔥" if item["score"] >= 6 else "👀"
    color = 0xFF5733 if item["score"] >= 6 else 0x3498DB  # Vibrant Orange vs Blue

    # Defensive limits: Title trimmed to max 180 characters
    title = item["title"]
    if len(title) > 180:
        title = title[:177] + "..."

    # Defensive limits: Snippet trimmed to max 250 characters
    snippet = clean_html(item["summary"])
    if len(snippet) > 250:
        snippet = snippet[:247] + "..."
    if not snippet:
        snippet = "No summary details available."

    keywords_str = ", ".join(item["matched_keywords"]) if item["matched_keywords"] else "None"

    return {
        "title": f"{emoji} [{item['category']}] {title}",
        "url": item["link"],
        "description": snippet,
        "color": color,
        "fields": [
            {"name": "Score", "value": str(item["score"]), "inline": True},
            {"name": "Matched Keywords", "value": f"`{keywords_str}`", "inline": True},
            {"name": "Published Date", "value": item["published"], "inline": False}
        ],
        "footer": {
            "text": f"Source: {item['source']}"
        }
    }


async def send_to_discord(webhook_url: str, selected_items: List[Dict[str, Any]]):
    """Sends embeds to Discord Webhook in chunks of 10."""
    if not selected_items:
        logger.info("No items to send to Discord.")
        return

    embeds = [format_discord_embed(item) for item in selected_items]

    # Discord limit is 10 embeds per webhook payload
    chunk_size = 10
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i in range(0, len(embeds), chunk_size):
            chunk = embeds[i:i + chunk_size]
            payload = {"embeds": chunk}
            try:
                response = await client.post(webhook_url, json=payload)
                if response.status_code >= 400:
                    logger.error(f"Discord API returned status {response.status_code}. Response body: {response.text}")
                response.raise_for_status()
                logger.info(f"Successfully sent batch of {len(chunk)} items to Discord webhook.")
            except Exception as e:
                logger.error(f"Failed to send webhook batch starting at index {i}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to post alerts to Discord Webhook: {e}"
                )


@app.get("/health")
def health():
    """Simple health check endpoint."""
    return {"ok": True}


@app.get("/run")
async def run(secret: Optional[str] = Query(None)):
    """Runs the news radar pipeline."""
    settings = get_settings()

    # 1. Verify RUN_SECRET if configured
    if settings.run_secret and secret != settings.run_secret:
        logger.warning("Unauthorized access attempt to /run: Secret token mismatch or missing.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing run secret."
        )

    # 2. Check if DISCORD_WEBHOOK_URL is configured
    if not settings.discord_webhook_url:
        logger.critical("DISCORD_WEBHOOK_URL is missing in the environment configurations.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration Error: DISCORD_WEBHOOK_URL environment variable is not set."
        )

    logger.info("Starting news radar retrieval pipeline...")

    # 3. Fetch feeds in parallel
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        tasks = [fetch_and_parse_feed(client, name, url) for name, url in FEEDS.items()]
        feeds_entries = await asyncio.gather(*tasks)

    # Combine results
    all_processed_items = []
    seen_links = set()

    for (name, url), entries in zip(FEEDS.items(), feeds_entries):
        for entry in entries:
            processed = process_feed_item(entry, name)
            if not processed:
                continue

            # Check threshold and deduplicate
            if processed["score"] >= settings.min_score:
                link = processed["link"]
                if link not in seen_links:
                    seen_links.add(link)
                    all_processed_items.append(processed)

    # Sort descending by score
    all_processed_items.sort(key=lambda x: x["score"], reverse=True)

    # Limit to MAX_ITEMS
    selected_items = all_processed_items[:settings.max_items]

    logger.info(f"Found {len(all_processed_items)} items exceeding threshold score of {settings.min_score}. "
                f"Selecting top {len(selected_items)} after deduplication and sorting.")

    # Send notifications
    await send_to_discord(settings.discord_webhook_url, selected_items)

    return {
        "status": "success",
        "processed_count": len(all_processed_items),
        "alerted_count": len(selected_items),
        "items": [
            {
                "title": item["title"],
                "score": item["score"],
                "category": item["category"],
                "source": item["source"],
                "link": item["link"]
            }
            for item in selected_items
        ]
    }
