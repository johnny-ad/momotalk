import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

BOT_TOKENS = {
    "hina": os.getenv("HINA_TOKEN"),
    "arona": os.getenv("ARONA_TOKEN"),
    "rio": os.getenv("RIO_TOKEN"),
    "plana": os.getenv("PLANA_TOKEN"),
    "hoshino": os.getenv("HOSHINO_TOKEN"),
    "ako": os.getenv("AKO_TOKEN"),
    "yuuka": os.getenv("YUUKA_TOKEN"),
    "aru": os.getenv("ARU_TOKEN"),
    "mutsuki": os.getenv("MUTSUKI_TOKEN"),
    "kayoko": os.getenv("KAYOKO_TOKEN"),
    "alice": os.getenv("ALICE_TOKEN"),
    "momoi": os.getenv("MOMOI_TOKEN"),
    "midori": os.getenv("MIDORI_TOKEN"),
    "hanako": os.getenv("HANAKO_TOKEN"),
    "shioko": os.getenv("SHIOKO_TOKEN"),
    "reisa": os.getenv("REISA_TOKEN"),
    "ui": os.getenv("UI_TOKEN"),
    "yuzu": os.getenv("YUZU_TOKEN"),
}


def get_token(character: str) -> str:
    token = BOT_TOKENS.get(character.lower())
    if not token:
        raise ValueError(f"No token found for character: {character}")
    return token
