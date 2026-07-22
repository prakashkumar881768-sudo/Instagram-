# Instagram Comment → DM Automation

Two separate services, deployed as two separate Render web services (like your Telegram bot setup):

## 1. `webhook_server.py` — the Instagram-facing service
Listens for comment notifications from Instagram and sends the DM automatically.

**Deploy this as its own Render web service.**
Start command: `python webhook_server.py`

Environment variables needed:
- `IG_VERIFY_TOKEN` — any string you make up yourself (e.g. `my_secret_verify_123`). You'll enter this same value in the Facebook Developer webhook setup screen.
- `IG_APP_SECRET` — from your Facebook App dashboard → App Settings → Basic → "App Secret" (click Show).
- `IG_ACCESS_TOKEN` — the access token you generated in the "Generate access tokens" step.
- `MONGO_URI` — same MongoDB connection string style as your Telegram bot (can be the same cluster, different database — it uses `ig_automation` database automatically, won't clash with your Telegram bot's `sub_management` database).

Once deployed, your webhook Callback URL (to paste into the Facebook Developer "Configure webhooks" section) will be:
```
https://your-service-name.onrender.com/webhook
```
And the Verify Token field there must match `IG_VERIFY_TOKEN` exactly.

## 2. `admin_bot.py` — your Telegram control panel
Lets you set which link/message goes out for each Instagram post.

**Deploy this as a separate Render web service.**
Start command: `python admin_bot.py`

Environment variables needed:
- `BOT_TOKEN` — a new Telegram bot token from BotFather (make a fresh bot for this, don't reuse your other one).
- `ADMIN_ID` — your Telegram numeric user ID (same as before).
- `MONGO_URI` — same connection string as above (both services must point to the same database so they can share the `posts` collection).

### Commands
- `/setpost` — walks you through: Media ID → link → DM message text
- `/listposts` — shows everything currently configured
- `/removepost` — deletes a post's configuration

## Getting a post's Media ID
You need each Reel/post's Instagram **Media ID** to link it to a product link. The easiest way: check the webhook_server logs after someone comments on a new post — the media_id will be printed there. You can then immediately go set it up with `/setpost` (the DM will start working for any comment made after that point on that post — comments made before you set the link won't retroactively get a DM).
