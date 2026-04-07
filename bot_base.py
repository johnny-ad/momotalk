import asyncio
import logging
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram import error as telegram_error
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import OWNER_ID, get_token
from claude_api import get_response, get_unprompted_message
from database import init_db, add_pending_user_message

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Suppress httpx logging to avoid exposing tokens in logs
logging.getLogger("httpx").setLevel(logging.WARNING)

EST = ZoneInfo("America/New_York")

def _now():
    """Current time in EST."""
    return datetime.now(EST)


class CharacterBot:
    """
    Base class for all MomoTalk character bots.
    Realistic timing: characters behave like high schoolers on their phones.
    """

    CHARACTER_NAME: str = "Unknown"
    SYSTEM_PROMPT: str = "You are a helpful assistant."

    IS_NIGHT_OWL: bool = False
    IS_AI: bool = False

    # Message batching — wait for multiple messages before responding
    BATCH_WAIT_SECONDS: float = 8.0  # Wait this long after last message to batch double-texts

    def __init__(self):
        try:
            self.token = get_token(self.CHARACTER_NAME.lower())
        except ValueError as e:
            raise ValueError(f"Failed to initialize {self.CHARACTER_NAME}: {e}")
        self.app = None
        self.logger = logging.getLogger(self.CHARACTER_NAME)
        self._pending_messages = []
        self._batch_task = None

    # ─── TIMING SYSTEM ───

    def _is_late_night_ok(self):
        """Check if it's a Friday/Saturday night (no school tomorrow)."""
        now = _now()
        weekday = now.weekday()  # 0=Mon, 6=Sun
        # Friday = 4, Saturday = 5
        return weekday in (4, 5)

    def _get_time_period(self):
        """Determine what time period we're in for scheduling."""
        now = _now()
        hour = now.hour
        weekday = now.weekday()
        is_weekend = weekday >= 5
        late_night_ok = self._is_late_night_ok()

        if self.IS_AI:
            return "always_on"

        if is_weekend:
            if 2 <= hour < 10:
                if self.IS_NIGHT_OWL and hour < 4:
                    return "night_owl_active"
                return "sleeping"
            elif 10 <= hour < 13:
                return "weekend_morning"
            else:
                return "weekend_free"
        else:
            # Weekday
            if late_night_ok and 0 <= hour < 3:
                # Friday/Saturday late night — still up
                if self.IS_NIGHT_OWL:
                    return "night_owl_active"
                return "late_night_weekend"
            elif 0 <= hour < 7:
                if self.IS_NIGHT_OWL and hour < 3:
                    return "night_owl_active"
                return "sleeping"
            elif 7 <= hour < 8:
                return "waking_up"
            elif 8 <= hour < 15:
                return "school"
            elif 15 <= hour < 17:
                return "after_school"
            elif 17 <= hour < 21:
                return "evening"
            elif 21 <= hour < 24:
                if late_night_ok:
                    return "late_night_weekend"
                return "late_night"
            else:
                return "sleeping"

    def _get_response_delay(self):
        """Get a realistic delay before responding, based on time of day."""
        period = self._get_time_period()

        if period == "always_on":
            return random.uniform(1, 5)

        if period == "sleeping":
            return None  # asleep

        if period == "night_owl_active":
            return random.uniform(5, 120)

        if period == "late_night_weekend":
            # Friday/Saturday night — still active but slower
            roll = random.random()
            if roll < 0.40:
                return random.uniform(3, 60)
            elif roll < 0.70:
                return random.uniform(60, 300)
            else:
                return random.uniform(300, 600)

        if period == "school":
            roll = random.random()
            if roll < 0.3:
                return None  # doesn't see it — queue it
            elif roll < 0.6:
                return random.uniform(300, 1800)
            else:
                return random.uniform(60, 300)

        if period == "waking_up":
            roll = random.random()
            if roll < 0.5:
                return random.uniform(5, 60)
            else:
                return random.uniform(60, 300)

        if period == "weekend_morning":
            roll = random.random()
            if roll < 0.3:
                return random.uniform(5, 30)
            elif roll < 0.6:
                return random.uniform(30, 300)
            else:
                return random.uniform(300, 600)

        if period == "late_night":
            if self.IS_NIGHT_OWL:
                return random.uniform(5, 60)
            roll = random.random()
            if roll < 0.4:
                return random.uniform(5, 60)
            elif roll < 0.7:
                return random.uniform(60, 300)
            else:
                return random.uniform(300, 900)

        # after_school, evening, weekend_free — most active
        roll = random.random()
        if roll < 0.50:
            return random.uniform(3, 60)
        elif roll < 0.75:
            return random.uniform(60, 300)
        elif roll < 0.90:
            return random.uniform(300, 600)
        elif roll < 0.98:
            return random.uniform(600, 1800)
        else:
            return random.uniform(1800, 3600)

    def _get_random_interval(self):
        """Get seconds until next random message, based on time of day."""
        period = self._get_time_period()

        if period == "always_on":
            return random.uniform(3600, 7200)

        if period == "sleeping":
            return random.uniform(3600, 7200)

        if period == "night_owl_active":
            return random.uniform(3600, 10800)

        if period == "late_night_weekend":
            return random.uniform(2400, 5400)

        if period == "school":
            return random.uniform(5400, 10800)

        if period in ("after_school", "evening"):
            return random.uniform(2400, 5400)

        if period == "late_night":
            return random.uniform(3600, 7200)

        if period in ("weekend_free", "weekend_morning"):
            return random.uniform(1800, 7200)

        if period == "waking_up":
            return random.uniform(1800, 3600)

        return random.uniform(3600, 7200)

    # ─── PROMPT BUILDING ───

    def _get_timed_prompt(self):
        """System prompt with current time and bubble count injected."""
        now = _now()
        time_str = now.strftime("%-I:%M %p")
        day_str = now.strftime("%A")

        roll = random.random()
        if roll < 0.80:
            bubble_instruction = "Respond in exactly 1 message. No --- separator."
        elif roll < 0.95:
            bubble_instruction = "Respond in exactly 2 messages. Separate them with --- on its own line."
        else:
            bubble_instruction = "Respond in exactly 3 messages. Separate each with --- on its own line."

        return self.SYSTEM_PROMPT + f"\n\n[Current time: {time_str}, {day_str}. Use this naturally.]\n[{bubble_instruction}]"

    # ─── MESSAGE SENDING ───

    async def _send_split(self, chat_id, response, bot, reply_to_message=None):
        """Split response on --- and send as separate messages with typing delay."""
        bubbles = [b.strip() for b in response.split("---") if b.strip()]
        for i, bubble in enumerate(bubbles):
            if i > 0:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
                await asyncio.sleep(random.uniform(0.5, 1.5))
            if reply_to_message and i == 0:
                await reply_to_message.reply_text(bubble)
            else:
                await bot.send_message(chat_id=chat_id, text=bubble)

    # ─── HANDLERS ───

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            if update.effective_chat.type not in ("group", "supergroup"):
                await update.message.reply_text("You are not authorized.")
                return
        await update.message.reply_text(f"MomoTalk connected. {self.CHARACTER_NAME} online.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text — routes to DM or group handler."""
        # Group chat
        if update.effective_chat.type in ("group", "supergroup"):
            await self._handle_group_message(update, context)
            return

        # DM — only owner
        if update.effective_user.id != OWNER_ID:
            return

        user_message = update.message.text
        self.logger.info(f"Received: {user_message}")

        delay = self._get_response_delay()
        if delay is None:
            await add_pending_user_message(self.CHARACTER_NAME.lower(), user_message)
            self.logger.info(f"{self.CHARACTER_NAME} is asleep — queuing message")
            return

        self._pending_messages.append(user_message)

        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()

        self._batch_task = asyncio.create_task(
            self._delayed_response(update, context, delay)
        )

    async def _handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle a message in a group chat."""
        from group_chat import (
            save_group_message, get_group_history, format_group_history_for_prompt,
            should_respond_to_group, CHATTINESS, get_seconds_since_last_spoke, update_cooldown,
            get_seconds_since_group_last_response, update_group_last_response,
            claim_group_message_response, infer_reply_target,
        )

        msg = update.message
        if not msg or not msg.text:
            return

        chat_id = update.effective_chat.id
        sender_name = msg.from_user.first_name or "Unknown"

        if msg.from_user.is_bot:
            sender_name = msg.from_user.first_name or "Bot"
        if msg.from_user.id == OWNER_ID:
            sender_name = "Sensei"

        reply_to_sender = None
        reply_to_content = None
        if msg.reply_to_message:
            reply_to_sender = msg.reply_to_message.from_user.first_name or "Unknown"
            reply_to_content = msg.reply_to_message.text or ""

        await save_group_message(
            chat_id=chat_id, sender=sender_name, content=msg.text,
            message_id=msg.message_id, reply_to_sender=reply_to_sender, reply_to_content=reply_to_content,
        )

        if sender_name.lower() == self.CHARACTER_NAME.lower():
            return

        period = self._get_time_period()
        if period == "sleeping" and not self.IS_NIGHT_OWL and not self.IS_AI:
            return

        seconds_since = await get_seconds_since_last_spoke(self.CHARACTER_NAME.lower(), chat_id)
        if seconds_since is not None and seconds_since < 60:
            return

        chattiness = CHATTINESS.get(self.CHARACTER_NAME.lower(), 0.3)
        if period == "school":
            chattiness *= 0.3

        # Check if any bot recently responded in this group (prevents spam)
        group_seconds_since = await get_seconds_since_group_last_response(chat_id)
        if group_seconds_since is not None and group_seconds_since < 30:
            # Much less likely to respond if someone just spoke
            chattiness *= 0.2

        if not should_respond_to_group(self.CHARACTER_NAME, sender_name, msg.text, chattiness):
            return

        if msg.message_id is not None:
            claimed = await claim_group_message_response(chat_id, msg.message_id)
            if not claimed:
                return

        delay = self._get_response_delay()
        if delay is None:
            return
        delay = min(delay, 120)

        self.logger.info(f"{self.CHARACTER_NAME} responding in group in {delay:.0f}s")
        await asyncio.sleep(delay)

        history = await get_group_history(chat_id, limit=20, exclude_message_id=msg.message_id)
        history_text = format_group_history_for_prompt(history, self.CHARACTER_NAME)

        reply_target_name, reply_target_text = infer_reply_target(history, msg.text)
        reply_context = ""
        if msg.reply_to_message:
            reply_to_sender = msg.reply_to_message.from_user.first_name or "Unknown"
            reply_to_content = msg.reply_to_message.text or ""
            reply_context = f"Reply context: Sensei is directly replying to {reply_to_sender}. Their message was: \"{reply_to_content}\"\n\n"
        elif reply_target_name:
            reply_context = f"Reply context: Sensei is replying to {reply_target_name}. Their message was: \"{reply_target_text}\"\n\n"

        group_prompt = self._get_timed_prompt() + f"""

[GROUP CHAT]
You are in a group chat. Recent conversation:

{history_text}

{reply_context}Respond naturally as {self.CHARACTER_NAME}. Keep it SHORT — 1-2 sentences max.
If the conversation isn't relevant to you, respond with exactly \"SKIP\".
Do NOT use --- separators. Single message only.
You can reply to what was said, react, argue, agree, or add your own take.
"""

        try:
            from claude_api import client
            from config import CLAUDE_MODEL

            response = await client.messages.create(
                model=CLAUDE_MODEL, max_tokens=256, system=group_prompt,
                messages=[{"role": "user", "content": f"{sender_name} said: {msg.text}"}],
            )
            reply_text = response.content[0].text.strip()
        except Exception as e:
            self.logger.error(f"Group response error: {e}")
            return

        if reply_text.upper() == "SKIP" or not reply_text:
            return

        await save_group_message(chat_id=chat_id, sender=self.CHARACTER_NAME, content=reply_text)
        await update_cooldown(self.CHARACTER_NAME.lower(), chat_id)
        await update_group_last_response(chat_id)
        await msg.reply_text(reply_text)

    async def _delayed_response(self, update, context, delay):
        """Wait for batch window, then wait for realistic delay, then respond."""
        try:
            # Wait for more messages (batch window)
            await asyncio.sleep(self.BATCH_WAIT_SECONDS)

            # Grab all batched messages and clear
            messages = list(self._pending_messages)
            self._pending_messages.clear()

            if not messages:
                return

            # Realistic response delay (minus batch wait already spent)
            remaining_delay = max(0, delay - self.BATCH_WAIT_SECONDS)

            if remaining_delay > 60:
                await asyncio.sleep(remaining_delay)
            elif remaining_delay > 5:
                await asyncio.sleep(remaining_delay - 3)
                await update.message.chat.send_action("typing")
                await asyncio.sleep(3)
            else:
                await update.message.chat.send_action("typing")
                await asyncio.sleep(max(1, remaining_delay))

            response = await get_response(
                character=self.CHARACTER_NAME.lower(),
                system_prompt=self._get_timed_prompt(),
                user_messages=messages,
            )

            self.logger.info(f"Response: {response}")
            await self._send_split(update.effective_chat.id, response, context.bot, update.message)

        except asyncio.CancelledError:
            pass  # Batch was cancelled because more messages came in

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            return

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        caption = update.message.caption or ""

        self.logger.info(f"Received photo ({len(image_bytes)} bytes) with caption: {caption}")

        delay = self._get_response_delay()
        if delay is None:
            await add_pending_user_message(self.CHARACTER_NAME.lower(), caption or "[sent a photo]")
            return

        if delay > 60:
            await asyncio.sleep(delay)
        elif delay > 5:
            await asyncio.sleep(delay - 3)
            await update.message.chat.send_action("typing")
            await asyncio.sleep(3)
        else:
            await update.message.chat.send_action("typing")
            await asyncio.sleep(delay)

        response = await get_response(
            character=self.CHARACTER_NAME.lower(),
            system_prompt=self._get_timed_prompt(),
            user_messages=[caption or "Sensei sent a photo."],
            image_data=bytes(image_bytes),
            image_media_type="image/jpeg",
        )

        self.logger.info(f"Response: {response}")
        await self._send_split(update.effective_chat.id, response, context.bot, update.message)

    # ─── UNPROMPTED MESSAGES ───

    async def send_unprompted(self, context: ContextTypes.DEFAULT_TYPE, extra_context: str = "", bypass_quiet: bool = False):
        from crossbot import is_quiet_hours

        if not bypass_quiet and await is_quiet_hours():
            self.logger.info(f"Quiet hours active — suppressing {self.CHARACTER_NAME}")
            return

        period = self._get_time_period()
        if period == "sleeping":
            self.logger.info(f"{self.CHARACTER_NAME} is asleep — skipping unprompted")
            return

        message = await get_unprompted_message(
            character=self.CHARACTER_NAME.lower(),
            system_prompt=self._get_timed_prompt(),
            context=extra_context,
        )
        if message:
            await self._send_split(OWNER_ID, message, context.bot)

    # ─── RANDOM MESSAGE SCHEDULING ───

    def setup_scheduled_jobs(self, app: Application):
        pass

    def _schedule_next_random(self, job_queue):
        delay_seconds = self._get_random_interval()

        job_queue.run_once(
            self._random_message_callback,
            when=timedelta(seconds=delay_seconds),
            name=f"{self.CHARACTER_NAME}_random",
        )
        self.logger.info(f"Next random message in {delay_seconds / 60:.0f} minutes")

    async def _random_message_callback(self, context: ContextTypes.DEFAULT_TYPE):
        period = self._get_time_period()

        if period == "sleeping":
            self.logger.info(f"{self.CHARACTER_NAME} is asleep — skipping")
        elif period == "school":
            if random.random() < 0.3:
                await self.send_unprompted(context, extra_context=self.get_random_context())
            else:
                self.logger.info(f"{self.CHARACTER_NAME} is in class — skipping")
        else:
            await self.send_unprompted(context, extra_context=self.get_random_context())

        jq = context.job.job_queue if hasattr(context.job, 'job_queue') else context.application.job_queue
        self._schedule_next_random(jq)

    def get_random_context(self) -> str:
        return ""

    # ─── RUN ───

    def run(self):
        self.app = Application.builder().token(self.token).build()

        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        self.register_handlers(self.app)
        self.setup_scheduled_jobs(self.app)

        # Add error handler
        self.app.add_error_handler(self.error_handler)

        async def post_init(app: Application):
            await init_db()
            self._schedule_next_random(app.job_queue)
            self.logger.info(f"{self.CHARACTER_NAME} bot started.")

        self.app.post_init = post_init

        self.logger.info(f"Starting {self.CHARACTER_NAME}...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

    def register_handlers(self, app: Application):
        pass

    async def error_handler(self, update, context):
        """Handle errors from the Telegram API."""
        self.logger.error(f"Telegram error: {context.error}")
        if isinstance(context.error, telegram_error.Conflict):
            self.logger.warning(f"Conflict detected for {self.CHARACTER_NAME} - another instance may be running or token conflict. Continuing...")
            # Don't stop the app, just log the warning
        # Other errors are just logged
