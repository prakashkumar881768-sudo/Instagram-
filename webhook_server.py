import os
import logging
import hmac
import hashlib
from flask import Flask, request, jsonify
from pymongo import MongoClient
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ig_webhook_bot")

# --- CONFIGURATION ---
VERIFY_TOKEN = os.getenv('IG_VERIFY_TOKEN')
APP_SECRET = os.getenv('IG_APP_SECRET')
PAGE_ACCESS_TOKEN = os.getenv('IG_ACCESS_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')

_missing = [name for name, val in [
    ("IG_VERIFY_TOKEN", VERIFY_TOKEN),
    ("IG_APP_SECRET", APP_SECRET),
    ("IG_ACCESS_TOKEN", PAGE_ACCESS_TOKEN),
    ("MONGO_URI", MONGO_URI),
] if not val]
if _missing:
    raise RuntimeError(f"Missing required environment variables: {', '.join(_missing)}")

client = MongoClient(MONGO_URI)
db = client['ig_automation']
posts_col = db['posts']  # documents: {media_id, link, message}

GRAPH_API_BASE = "https://graph.instagram.com/v21.0"

app = Flask(__name__)


@app.route('/')
def home():
    return "Instagram automation bot is running."


@app.route('/webhook', methods=['GET'])
def verify_webhook():
    """Meta calls this once when you set up the webhook, to confirm you own the endpoint."""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode == 'subscribe' and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return challenge, 200

    logger.warning("Webhook verification failed")
    return "Verification failed", 403


def verify_signature(request_data: bytes, signature_header: str) -> bool:
    """Confirms the request really came from Meta, using the app secret."""
    if not signature_header or not signature_header.startswith('sha256='):
        return False
    expected_sig = signature_header.split('sha256=')[-1]
    computed_sig = hmac.new(
        APP_SECRET.encode('utf-8'),
        request_data,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_sig, computed_sig)


@app.route('/webhook', methods=['POST'])
def receive_webhook():
    signature = request.headers.get('X-Hub-Signature-256', '')
    if not verify_signature(request.data, signature):
        logger.warning("Invalid webhook signature - rejecting request")
        return jsonify({"status": "invalid signature"}), 403

    data = request.get_json(silent=True) or {}
    logger.info("Webhook received: %s", data)

    try:
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                if change.get('field') == 'comments':
                    handle_comment(change.get('value', {}))
    except Exception:
        logger.exception("Error processing webhook payload")

    # Always acknowledge quickly so Meta doesn't retry/backoff on us
    return jsonify({"status": "ok"}), 200


def handle_comment(comment_data: dict):
    media_id = comment_data.get('media', {}).get('id')
    commenter_id = comment_data.get('from', {}).get('id')
    comment_id = comment_data.get('id')

    if not media_id or not commenter_id:
        logger.warning("Comment payload missing media_id or commenter_id: %s", comment_data)
        return

    post = posts_col.find_one({"media_id": media_id})
    if not post:
        logger.info("No link configured for media_id %s - skipping DM", media_id)
        return

    if not is_follower(commenter_id):
        logger.info("Commenter %s is not a follower - skipping DM", commenter_id)
        return

    dm_text = post.get('message') or "Thanks for your comment! Here's the link:"
    link = post.get('link', '')
    full_message = f"{dm_text}\n{link}".strip()

    send_dm(commenter_id, full_message)
    logger.info("Sent DM to %s for media %s (comment %s)", commenter_id, media_id, comment_id)


def is_follower(user_id: str) -> bool:
    """
    Checks whether the given Instagram user follows our account.
    NOTE: The Instagram Graph API does not provide a direct "is this person
    following me" lookup for arbitrary users. This uses the conversation
    participant field as a best-effort proxy where available. If your app's
    permissions don't support this check, it will log the API response and
    default to NOT sending the DM (fails safe/closed) - see logs to confirm
    whether this is working for your account.
    """
    url = f"{GRAPH_API_BASE}/{user_id}"
    params = {
        "fields": "is_user_follow_business",
        "access_token": PAGE_ACCESS_TOKEN
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning("Follower check failed for %s: %s - %s", user_id, resp.status_code, resp.text)
            return False
        data = resp.json()
        return bool(data.get('is_user_follow_business', False))
    except Exception:
        logger.exception("Exception while checking follower status for %s", user_id)
        return False


def send_dm(recipient_id: str, message_text: str):
    url = f"{GRAPH_API_BASE}/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    try:
        resp = requests.post(url, params=params, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error("Failed to send DM to %s: %s - %s", recipient_id, resp.status_code, resp.text)
    except Exception:
        logger.exception("Exception while sending DM to %s", recipient_id)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
