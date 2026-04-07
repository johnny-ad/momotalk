import anthropic
import base64
import logging
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from database import (
    get_message_history, save_message,
    get_pending_user_messages, clear_pending_user_messages,
    get_last_user_message_time,
)

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


async def get_response(character: str, system_prompt: str, user_messages: list[str], image_data: bytes = None, image_media_type: str = "image/jpeg") -> str:
    """
    Get a Claude response for a character.
    Accepts a LIST of user messages (to handle double/triple texting).
    Loads conversation history, sends to Claude, saves all messages, returns response.
    """
    # Get conversation history
    history = await get_message_history(character, limit=50)

    # Build messages array for Claude
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Combine all user messages into one (handles double texting)
    combined_text = "\n".join(user_messages)

    # Build the new user message content
    if image_data:
        b64 = base64.standard_b64encode(image_data).decode("utf-8")
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": b64,
                },
            },
        ]
        content.append({"type": "text", "text": combined_text or "Sensei sent you this image."})
        messages.append({"role": "user", "content": content})
        save_text = combined_text or "[sent an image]"
    else:
        messages.append({"role": "user", "content": combined_text})
        save_text = combined_text

    # Call Claude
    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        assistant_message = response.content[0].text
    except Exception as e:
        assistant_message = f"[System error: {e}]"

    # Save messages to database
    await save_message(character, "user", save_text)
    await save_message(character, "assistant", assistant_message)

    return assistant_message


async def _get_recency_note(character: str) -> str:
    """Check how recently Sensei messaged and return context for the prompt."""
    last_time_str = await get_last_user_message_time(character)
    if not last_time_str:
        return "\n[Sensei has never messaged you. This is your first contact attempt.]"

    from datetime import datetime
    try:
        last_time = datetime.fromisoformat(last_time_str)
        now = datetime.utcnow()
        minutes_ago = (now - last_time).total_seconds() / 60

        if minutes_ago < 30:
            return f"\n[Sensei messaged you {int(minutes_ago)} minutes ago. They ARE active. Do NOT say they forgot you or haven't talked to you.]"
        elif minutes_ago < 120:
            return f"\n[Sensei messaged you about {int(minutes_ago)} minutes ago. They've been around recently.]"
        elif minutes_ago < 480:
            return f"\n[Sensei last messaged you {int(minutes_ago / 60):.0f} hours ago.]"
        else:
            return f"\n[Sensei last messaged you {int(minutes_ago / 60):.0f} hours ago. It's been a while.]"
    except Exception:
        return ""


async def get_unprompted_message(character: str, system_prompt: str, context: str = "") -> str:
    """
    Generate an unprompted message from a character.
    Checks for any unread user messages first and responds to those instead.
    Now includes recency awareness so bots don't complain about being ignored
    when Sensei has been active recently.
    """
    history = await get_message_history(character, limit=30)

    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Check if there are pending user messages we haven't responded to
    pending = await get_pending_user_messages(character)

    # Get recency info
    recency_note = await _get_recency_note(character)

    if pending:
        # Respond to the pending messages instead of sending random prompt
        combined = "\n".join(pending)
        messages.append({"role": "user", "content": combined})
        await save_message(character, "user", combined)
        await clear_pending_user_messages(character)
    elif context:
        prompt = (
            f"Generate an unprompted message to Sensei based on the following. "
            f"You MUST use provided data — do not make up information. "
            f"Check your recent conversation history — if Sensei sent you something recently that you haven't addressed, respond to that instead. "
            f"This is NOT a reply — you're initiating contact. Stay in character.\n\n"
            f"{context}"
        )
        messages.append({"role": "user", "content": prompt})
    else:
        prompt = (
            "Generate a brief unprompted message to Sensei. "
            "This is NOT a reply — you're initiating contact. "
            "Check your recent conversation history — if Sensei sent you something recently that you haven't addressed, respond to that instead. "
            "Keep it natural, in-character, and short (1-3 sentences). "
            "Don't repeat anything you've said recently."
        )
        messages.append({"role": "user", "content": prompt})

    # Append recency note to system prompt so the model knows
    augmented_system = system_prompt + recency_note

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512 if not context else 1024,
            system=augmented_system,
            messages=messages,
        )
        assistant_message = response.content[0].text
    except Exception as e:
        logging.error(f"Error generating unprompted message: {e}")
        assistant_message = None

    if assistant_message:
        await save_message(character, "assistant", assistant_message)

    return assistant_message
