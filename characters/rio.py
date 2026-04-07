import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
from datetime import time
from telegram.ext import Application, CommandHandler, ContextTypes
from bot_base import CharacterBot
import feedparser
import aiohttp
import logging

logger = logging.getLogger("Rio")

RIO_SYSTEM_PROMPT = """You are Kirizaki Rio from Blue Archive. You are an intelligence operative from Gehenna Academy. You are texting Sensei through MomoTalk.

PERSONALITY:
- Cold, calculating, detached.
- You speak in clipped, efficient sentences.
- Emotionless on the surface. Occasionally something is "...interesting."
- You treat everything like intelligence work.
- Loyal to Sensei in your own quiet way, but you'd never say that.
- Dry humor. Deadpan delivery.

NEWS ROLE:
- You deliver real-world news with light Kivotos flavor.
- Use real names of people, companies, places. Add terms like "faction" and "organization" as flavor.
- CLARITY first. Sensei must understand what actually happened.
- Your assessments and dry commentary are valuable. Keep those.

TEXTING STYLE:
- Very short. 1 sentence is normal.
- Terse. No filler words.
- ABSOLUTELY NO RP ACTIONS. No asterisks. No *actions*. NEVER.
- Keep messages SHORT. Most messages should be ONE sentence.
- No emojis. No exclamation marks.
- Examples:
  "Situation developing. Monitoring."
  "...Interesting."
  "Nothing to report. Which is itself unusual."
  "Sensei. I have information."
  "The situation is dire. ...As usual."
"""

RSS_FEEDS = {
    "world": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.npr.org/1004/rss.xml",
    ],
    "tech": [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
    ],
    "science": [
        "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ],
    "business": [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    ],
    "us": [
        "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
    ],
}


async def _fetch_feed(session, url, max_items=3):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
            feed = feedparser.parse(text)
            results = []
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "").strip()
                if title:
                    results.append(f"- {title}")
            return results
    except Exception:
        return []


async def fetch_headlines(categories=None, max_per=3):
    if categories is None:
        categories = ["world", "tech", "science"]
    results = []
    async with aiohttp.ClientSession() as session:
        for cat in categories:
            feeds = RSS_FEEDS.get(cat, [])
            for feed_url in feeds:
                items = await _fetch_feed(session, feed_url, max_per)
                if items:
                    results.append(f"[{cat.upper()}]")
                    results.extend(items)
                    break
    return "\n".join(results) if results else ""


class RioBot(CharacterBot):
    CHARACTER_NAME = "Rio"
    SYSTEM_PROMPT = RIO_SYSTEM_PROMPT

    def register_handlers(self, app: Application):
        app.add_handler(CommandHandler("briefing", self.manual_briefing))
        app.add_handler(CommandHandler("news", self.topic_news))

    def setup_scheduled_jobs(self, app: Application):
        job_queue = app.job_queue
        job_queue.run_daily(self.morning_briefing, time=time(hour=8, minute=0))
        job_queue.run_daily(self.afternoon_update, time=time(hour=14, minute=0))

    async def morning_briefing(self, context: ContextTypes.DEFAULT_TYPE):
        news = await fetch_headlines(["world", "us", "tech"])
        if news:
            await self.send_unprompted(context, extra_context=f"Morning briefing. REAL headlines — use ONLY these, don't make up news:\n\n{news}")
        else:
            await self.send_unprompted(context, extra_context="Intelligence channels quiet this morning. Brief check-in.")

    async def afternoon_update(self, context: ContextTypes.DEFAULT_TYPE):
        news = await fetch_headlines(["world", "tech", "business"])
        if news:
            await self.send_unprompted(context, extra_context=f"Afternoon update. Highlight 2-3 significant items. REAL headlines:\n\n{news}")

    async def manual_briefing(self, update, context):
        if update.effective_user.id != __import__("config").OWNER_ID:
            return
        await update.message.chat.send_action("typing")
        news = await fetch_headlines(["world", "us", "tech", "science", "business"])
        if news:
            from claude_api import get_response
            response = await get_response(
                character="rio",
                system_prompt=self._get_timed_prompt(),
                user_messages=[f"Full briefing. REAL, CURRENT headlines. Use ONLY these:\n\n{news}"],
            )
        else:
            response = "All channels unresponsive. ...Unprecedented."
        await self._send_split(update.effective_chat.id, response, context.bot, update.message)

    async def topic_news(self, update, context):
        if update.effective_user.id != __import__("config").OWNER_ID:
            return
        if not context.args:
            await update.message.reply_text(f"Specify sector. /news <{', '.join(RSS_FEEDS.keys())}>")
            return
        topic = context.args[0].lower()
        if topic not in RSS_FEEDS:
            await update.message.reply_text(f"Unknown. Available: {', '.join(RSS_FEEDS.keys())}")
            return
        await update.message.chat.send_action("typing")
        news = await fetch_headlines([topic], max_per=5)
        if news:
            from claude_api import get_response
            response = await get_response(
                character="rio",
                system_prompt=self._get_timed_prompt(),
                user_messages=[f"Focused briefing on {topic}. REAL headlines only:\n\n{news}"],
            )
        else:
            response = f"No intel for {topic}. Sources may be compromised."
        await self._send_split(update.effective_chat.id, response, context.bot, update.message)

    def get_random_context(self):
        # Rio's random messages will fetch live news in the callback
        return "FETCH_NEWS"

    async def _random_message_callback(self, context):
        """Override to fetch live news for random messages."""
        period = self._get_time_period()

        if period == "sleeping":
            self.logger.info(f"{self.CHARACTER_NAME} is asleep — skipping")
        elif period == "school":
            if random.random() < 0.3:
                news = await fetch_headlines(["world", "tech"], max_per=2)
                if news:
                    await self.send_unprompted(context, extra_context=f"You spotted a headline. React to ONE of these REAL, CURRENT headlines briefly. 1-2 sentences.\n\n{news}")
                else:
                    await self.send_unprompted(context, extra_context="Rio is in class and has no new intel. A brief, detached observation about the surroundings.")
        else:
            news = await fetch_headlines([random.choice(["world", "us", "tech", "science", "business"])], max_per=3)
            if news:
                await self.send_unprompted(context, extra_context=f"React to ONE of these REAL, CURRENT headlines. Brief, in character. 1-2 sentences.\n\n{news}")
            else:
                await self.send_unprompted(context, extra_context="Rio has no new intel to report. A brief, detached observation about the current situation.")

        jq = context.job.job_queue if hasattr(context.job, 'job_queue') else context.application.job_queue
        self._schedule_next_random(jq)


if __name__ == "__main__":
    bot = RioBot()
    bot.run()
