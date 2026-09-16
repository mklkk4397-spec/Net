import os
import zipfile
import tempfile
import requests
from dotenv import load_dotenv
import telebot
from telebot import types

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
NETLIFY_TOKEN = os.getenv("NETLIFY_TOKEN")

if not BOT_TOKEN or not NETLIFY_TOKEN:
    raise ValueError("❌ Please set TELEGRAM_BOT_TOKEN and NETLIFY_TOKEN in .env file")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# Store user session
user_data = {}

HEADERS = {
    "Authorization": f"Bearer {NETLIFY_TOKEN}",
    "User-Agent": "Premium-Netlify-Host-Bot/1.0"
}


# ─────────────────────────────
# Netlify API Functions
# ─────────────────────────────

def create_site(name=None):
    url = "https://api.netlify.com/api/v1/sites"
    payload = {}
    if name:
        payload["name"] = name

    response = requests.post(
        url,
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=30
    )

    if response.status_code in [200, 201]:
        return response.json()
    raise Exception(response.text)


def deploy_zip(site_id, zip_path):
    url = f"https://api.netlify.com/api/v1/sites/{site_id}/deploys"

    with open(zip_path, "rb") as f:
        response = requests.post(
            url,
            headers={**HEADERS, "Content-Type": "application/zip"},
            data=f,
            timeout=120
        )

    if response.status_code in [200, 201]:
        return response.json()
    raise Exception(response.text)


def update_site_name(site_id, new_name):
    url = f"https://api.netlify.com/api/v1/sites/{site_id}"
    response = requests.patch(
        url,
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"name": new_name},
        timeout=30
    )

    if response.status_code == 200:
        return response.json()
    raise Exception(response.text)


# ─────────────────────────────
# UI / Messages
# ─────────────────────────────

WELCOME_TEXT = """
✨ *Welcome to Netlify Host Bot*

Deploy your websites instantly from Telegram.

*Available Commands:*
├ /host — Deploy new site
├ /rename — Change site name
├ /mysites — View your site
└ /help — Show this message

*How it works:*
1. Send `/host`
2. Upload a ZIP file
3. Get live URL in seconds
"""

HOST_PROMPT = """
📤 *Ready to Deploy*

Please send a *ZIP file* containing your website.

• Single file → zip it first
• Full folder → zip the entire folder

Waiting for your file...
"""


# ─────────────────────────────
# Handlers
# ─────────────────────────────

@bot.message_handler(commands=['start', 'help'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("🚀 Host Site"),
        types.KeyboardButton("✏️ Rename Site"),
        types.KeyboardButton("🌐 My Site"),
        types.KeyboardButton("ℹ️ Help")
    )
    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=markup)


@bot.message_handler(commands=['host'])
@bot.message_handler(func=lambda m: m.text == "🚀 Host Site")
def host_command(message):
    user_data[message.chat.id] = {"state": "waiting_file"}
    bot.send_message(message.chat.id, HOST_PROMPT)


@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = message.chat.id
    state = user_data.get(chat_id, {}).get("state")

    if state != "waiting_file":
        bot.reply_to(message, "⚠️ Please click *🚀 Host Site* or send `/host` first.")
        return

    file_info = bot.get_file(message.document.file_id)
    file_size = message.document.file_size or 0

    if file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "❌ File is too large. Please keep ZIP under 20 MB.")
        return

    status_msg = bot.reply_to(message, "⏳ *Downloading file...*")

    try:
        downloaded = bot.download_file(file_info.file_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "site.zip")
            with open(zip_path, "wb") as f:
                f.write(downloaded)

            if not zipfile.is_zipfile(zip_path):
                bot.edit_message_text(
                    "❌ Invalid ZIP file. Please upload a valid `.zip` archive.",
                    chat_id,
                    status_msg.message_id
                )
                return

            bot.edit_message_text(
                "⏳ *Creating Netlify site...*",
                chat_id,
                status_msg.message_id
            )

            site = create_site()
            site_id = site["id"]
            site_name = site["name"]
            site_url = site.get("ssl_url") or site.get("url")

            bot.edit_message_text(
                "⏳ *Uploading & deploying files...*\nThis may take a few seconds.",
                chat_id,
                status_msg.message_id
            )

            deploy_zip(site_id, zip_path)

            user_data[chat_id] = {
                "state": "hosted",
                "site_id": site_id,
                "site_name": site_name,
                "site_url": site_url
            }

            success_text = f"""
✅ *Successfully Deployed!*

━━━━━━━━━━━━━━━━━━
🌐 *Live URL*
`{site_url}`

📛 *Site Name*
`{site_name}`

🆔 *Site ID*
`{site_id}`
━━━━━━━━━━━━━━━━━━

To change the name:
`/rename your-new-name`
or press ✏️ Rename Site
"""
            bot.edit_message_text(success_text, chat_id, status_msg.message_id)

    except Exception as e:
        error_msg = str(e)[:300]
        bot.edit_message_text(
            f"❌ *Deployment Failed*\n\n`{error_msg}`",
            chat_id,
            status_msg.message_id
        )


@bot.message_handler(commands=['rename'])
@bot.message_handler(func=lambda m: m.text == "✏️ Rename Site")
def rename_command(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)

    if not data or "site_id" not in data:
        bot.reply_to(message, "⚠️ You don't have any site yet.\nPlease deploy first using 🚀 Host Site")
        return

    if message.text == "✏️ Rename Site":
        user_data[chat_id]["state"] = "waiting_rename"
        bot.reply_to(
            message,
            "✏️ *Enter new site name*\n\n"
            "Only letters, numbers and hyphens allowed.\n"
            "Example: `my-awesome-site`",
        )
        return

    try:
        new_name = message.text.split(maxsplit=1)[1].strip().lower()
    except IndexError:
        user_data[chat_id]["state"] = "waiting_rename"
        bot.reply_to(
            message,
            "✏️ *Enter new site name*\n\n"
            "Usage: `/rename my-new-name`\n"
            "Example: `/rename portfolio-2025`"
        )
        return

    process_rename(chat_id, data["site_id"], new_name, message)


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get("state") == "waiting_rename")
def receive_new_name(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id)

    if not data or "site_id" not in data:
        bot.reply_to(message, "⚠️ Session expired. Please deploy again.")
        return

    new_name = message.text.strip().lower()
    process_rename(chat_id, data["site_id"], new_name, message)


def process_rename(chat_id, site_id, new_name, message):
    if not all(c.isalnum() or c == '-' for c in new_name) or len(new_name) < 2:
        bot.reply_to(
            message,
            "❌ Invalid name.\nOnly a-z, 0-9 and `-` allowed.\nMinimum 2 characters."
        )
        return

    status = bot.reply_to(message, f"⏳ Changing name to `{new_name}`...")

    try:
        updated = update_site_name(site_id, new_name)
        new_url = updated.get("ssl_url") or updated.get("url")

        user_data[chat_id]["site_name"] = new_name
        user_data[chat_id]["site_url"] = new_url
        user_data[chat_id]["state"] = "hosted"

        bot.edit_message_text(
            f"✅ *Name Updated Successfully!*\n\n"
            f"📛 New Name: `{new_name}`\n"
            f"🌐 New URL: `{new_url}`",
            chat_id,
            status.message_id
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ *Rename Failed*\n\n`{str(e)[:250]}`\n\n"
            "The name might already be taken by someone else.",
            chat_id,
            status.message_id
        )


@bot.message_handler(commands=['mysites'])
@bot.message_handler(func=lambda m: m.text == "🌐 My Site")
def my_sites(message):
    data = user_data.get(message.chat.id)

    if data and "site_id" in data:
        text = f"""
🌐 *Your Current Site*

━━━━━━━━━━━━━━━━━━
📛 *Name:* `{data['site_name']}`
🔗 *URL:* `{data['site_url']}`
🆔 *ID:* `{data['site_id']}`
━━━━━━━━━━━━━━━━━━
"""
        bot.reply_to(message, text)
    else:
        bot.reply_to(
            message,
            "📭 You don't have any site yet.\n\n"
            "Click 🚀 Host Site to deploy your first website."
        )


@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def help_button(message):
    start(message)


# ─────────────────────────────
# Start Bot
# ─────────────────────────────

if __name__ == "__main__":
    print("✅ Premium Netlify Host Bot is running...")
    print("Press Ctrl+C to stop")
    bot.infinity_polling(timeout=60, long_polling_timeout=40)