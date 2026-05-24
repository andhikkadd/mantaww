import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import re
import time
from typing import Dict, Any, List, Optional
import httpx
import feedparser
from fastapi import FastAPI, HTTPException, Query, status

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

# Combined Blocklist (including new v0.2 keywords)
BLOCKLIST = [
    "sponsored", "giveaway", "coupon", "price prediction",
    "promo", "discount", "casino", "betting",
    "wordpress plugin", "top 10", "top 7", "best wordpress",
    "nft", "non-fungible token", "review 2022", "review 2023"
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


# ==========================================
# Helper Functions (Recency & Freshness)
# ==========================================

def parse_published_date(item: Dict[str, Any]) -> Optional[datetime]:
    """Parses published_parsed or updated_parsed into a timezone-aware UTC datetime.

    Falls back to parsing the raw published string using RFC 2822 standard.
    """
    struct_time = item.get("published_parsed") or item.get("updated_parsed")
    if struct_time:
        try:
            # struct_time contains: tm_year, tm_mon, tm_mday, tm_hour, tm_min, tm_sec
            dt = datetime(*struct_time[:6], tzinfo=timezone.utc)
            return dt
        except Exception as e:
            logger.debug(f"Failed to convert struct_time to datetime: {e}")

    raw_pub = item.get("published") or item.get("updated")
    if raw_pub:
        try:
            dt = parsedate_to_datetime(raw_pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception as e:
            logger.debug(f"Failed to parse published date string '{raw_pub}': {e}")

    return None


def check_item_age(dt: Optional[datetime], max_age_days: int) -> bool:
    """Checks if the item is older than max_age_days.

    Returns True if the item age is within limits, and False if it exceeds max_age_days.
    If the date is missing or unparseable (dt is None), returns True (should not be discarded).
    """
    if dt is None:
        return True

    now = datetime.now(timezone.utc)
    age_seconds = (now - dt).total_seconds()
    return age_seconds <= (max_age_days * 86400)


def calculate_freshness_bonus(dt: Optional[datetime]) -> int:
    """Calculates freshness score bonus: +2 if <24 hours, +1 if <3 days (72 hours).

    Returns 0 if the date is missing, older, or unparseable.
    """
    if dt is None:
        return 0

    now = datetime.now(timezone.utc)
    age_seconds = (now - dt).total_seconds()

    if age_seconds < 86400:  # Within 24 hours
        return 2
    elif age_seconds < 259200:  # Within 3 days (72 hours)
        return 1

    return 0


def apply_source_caps(items: List[Dict[str, Any]], max_items: int, max_per_source: int) -> List[Dict[str, Any]]:
    """Applies a capping limit for how many items from the same source can be alerted."""
    selected = []
    source_counts = {}

    for item in items:
        if len(selected) >= max_items:
            break

        source = item["source"]
        current_count = source_counts.get(source, 0)

        if current_count < max_per_source:
            selected.append(item)
            source_counts[source] = current_count + 1

    return selected


# ==========================================
# Core Processing & Formatting Functions
# ==========================================

def clean_html(text: str) -> str:
    """Removes HTML tags and normalizes whitespace."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    return " ".join(clean.split())


def process_feed_item(item: Dict[str, Any], source_name: str, dt: Optional[datetime]) -> Optional[Dict[str, Any]]:
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

    # Freshness / Recency checks
    unparseable_date = False
    if dt is not None:
        freshness_bonus = calculate_freshness_bonus(dt)
        score += freshness_bonus
    else:
        # Penalty for missing or unparseable date
        score -= 2
        unparseable_date = True

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
        "source": source_name,
        "unparseable_date": unparseable_date
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

    published_display = item["published"]
    if item.get("unparseable_date"):
        published_display += " (Unparseable/Missing Date)"

    return {
        "title": f"{emoji} [{item['category']}] {title}",
        "url": item["link"],
        "description": snippet,
        "color": color,
        "fields": [
            {"name": "Score", "value": str(item["score"]), "inline": True},
            {"name": "Matched Keywords", "value": f"`{keywords_str}`", "inline": True},
            {"name": "Published Date", "value": published_display, "inline": False}
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

    # Combine and process results
    raw_processed_count = 0
    blocked_count = 0
    outdated_count = 0
    unparseable_date_count = 0
    filtered_count = 0
    
    all_processed_items = []
    seen_links = set()

    for (name, url), entries in zip(FEEDS.items(), feeds_entries):
        for entry in entries:
            raw_processed_count += 1
            
            # Age Filter: Check date freshness
            dt = parse_published_date(entry)
            
            if dt is None:
                unparseable_date_count += 1
            
            # Outdated check
            if dt is not None and not check_item_age(dt, settings.max_item_age_days):
                outdated_count += 1
                continue

            processed = process_feed_item(entry, name, dt)
            if not processed:
                blocked_count += 1
                continue

            # Check threshold and deduplicate
            if processed["score"] >= settings.min_score:
                link = processed["link"]
                if link not in seen_links:
                    seen_links.add(link)
                    all_processed_items.append(processed)
            else:
                filtered_count += 1

    # Sort descending by score
    all_processed_items.sort(key=lambda x: x["score"], reverse=True)

    # Apply Source Capping and Max limit limits
    selected_items = apply_source_caps(
        all_processed_items,
        settings.max_items,
        settings.max_items_per_source
    )

    logger.info(
        f"Pipeline Summary - Processed: {raw_processed_count}, Blocked: {blocked_count}, "
        f"Outdated: {outdated_count}, Unparseable: {unparseable_date_count}, "
        f"Filtered (Low Score): {filtered_count}, Qualified: {len(all_processed_items)}, "
        f"Alerted: {len(selected_items)}"
    )

    # Send notifications
    await send_to_discord(settings.discord_webhook_url, selected_items)

    return {
        "status": "success",
        "processed_count": raw_processed_count,
        "filtered_count": filtered_count,
        "blocked_count": blocked_count,
        "outdated_count": outdated_count,
        "unparseable_date_count": unparseable_date_count,
        "alerted_count": len(selected_items),
        "max_item_age_days": settings.max_item_age_days,
        "max_items_per_source": settings.max_items_per_source,
        "items": [
            {
                "title": item["title"],
                "score": item["score"],
                "category": item["category"],
                "source": item["source"],
                "published": item["published"],
                "link": item["link"],
                "matched_keywords": item["matched_keywords"]
            }
            for item in selected_items
        ]
    }
