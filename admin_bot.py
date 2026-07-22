import os
import logging
import telebot
from pymongo import MongoClient
from flask import Flask
from threading import Thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_admin_bot")

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')


@app.route('/')
def home():
    return "IG admin bot is running."


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# --- CONFIGURATION ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
MONGO_URI = os.getenv('MONGO_URI')

_missing = [name for name, val in [
    ("BOT_TOKEN", BOT_TOKEN),
    ("ADMIN_ID", ADMIN_ID),
    ("MONGO_URI", MONGO_URI),
] if not val]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")

ADMIN_ID = int(ADMIN_ID)

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['ig_automation']
posts_col = db['posts']


@bot.message_handler(commands=['start'])
def start_handler(message):
    if message.from_user.id != ADMIN_ID:
        return
    bot.send_message(
        message.chat.id,
        "✅ Instagram Link Manager\n\n"
        "/setpost - Add or update a post's link\n"
        "/listposts - Show all configured posts\n"
        "/removepost - Remove a post's link"
    )


@bot.message_handler(commands=['setpost'], func=lambda m: m.from_user.id == ADMIN_ID)
def setpost_start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    msg = bot.send_message(
        message.chat.id,
        "Send the Instagram Media ID for this post.\n\n"
        "(You can get this from the Graph API Explorer, or from your webhook logs "
        "after someone comments on it.)"
    )
    bot.register_next_step_handler(msg, get_link)


def get_link(message):
    media_id = message.text.strip()
    if not media_id:
        bot.send_message(message.chat.id, "❌ Empty input. Use /setpost to retry.")
        return
    msg = bot.send_message(message.chat.id, "Now send the product link for this post.")
    bot.register_next_step_handler(msg, get_dm_text, media_id)


def get_dm_text(message, media_id):
    link = message.text.strip()
    if not link:
        bot.send_message(message.chat.id, "❌ Empty input. Use /setpost to retry.")
        return
    msg = bot.send_message(
        message.chat.id,
        "Now send the DM message text (the link will be added automatically after it)."
    )
    bot.register_next_step_handler(msg, finalize_post, media_id, link)


def finalize_post(message, media_id, link):
    dm_text = message.text.strip()
    if not dm_text:
        bot.send_message(message.chat.id, "❌ Empty input. Use /setpost to retry.")
        return

    try:
        posts_col.update_one(
            {"media_id": media_id},
            {"$set": {"media_id": media_id, "link": link, "message": dm_text}},
            upsert=True
        )
        bot.send_message(
            message.chat.id,
            f"✅ Saved!\n\nMedia ID: `{media_id}`\nLink: {link}\nMessage: {dm_text}",
            parse_mode="Markdown"
        )
    except Exception:
        logger.exception("Failed to save post link")
        bot.send_message(message.chat.id, "❌ Something went wrong saving this. Try /setpost again.")


@bot.message_handler(commands=['listposts'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_posts(message):
    posts = list(posts_col.find({}))
    if not posts:
        bot.send_message(message.chat.id, "No posts configured yet. Use /setpost to add one.")
        return

    lines = []
    for p in posts:
        lines.append(f"• `{p['media_id']}` → {p.get('link', '(no link)')}")
    bot.send_message(message.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=['removepost'], func=lambda m: m.from_user.id == ADMIN_ID)
def removepost_start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    msg = bot.send_message(message.chat.id, "Send the Media ID you want to remove.")
    bot.register_next_step_handler(msg, do_remove)


def do_remove(message):
    media_id = message.text.strip()
    result = posts_col.delete_one({"media_id": media_id})
    if result.deleted_count:
        bot.send_message(message.chat.id, f"✅ Removed `{media_id}`.", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "❌ No post found with that Media ID.")


if __name__ == '__main__':
    keep_alive()
    bot.remove_webhook()
    logger.info("IG admin bot is running...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
