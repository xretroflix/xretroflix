import os
import logging
from datetime import datetime
import random
import string
import re
import asyncio
import json
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, ContextTypes, filters
from telegram.constants import ChatMemberStatus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Environment variables with defaults
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# Validation
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set in environment variables!")
if ADMIN_ID == 0:
    raise ValueError("❌ ADMIN_ID not set in environment variables!")

MIN_ACCOUNT_AGE_DAYS = 15
REQUIRE_PROFILE_PHOTO = False
CODE_EXPIRY_MINUTES = 5

VERIFIED_USERS = set([ADMIN_ID])
MANAGED_CHANNELS = {}
PENDING_POSTS = {}
PENDING_VERIFICATIONS = {}
VERIFIED_FOR_CHANNELS = {}
BLOCKED_USERS = set()
BULK_APPROVAL_MODE = {}

UPLOADED_IMAGES = []
CHANNEL_SPECIFIC_IMAGES = {}
CURRENT_IMAGE_INDEX = {}
AUTO_POST_ENABLED = {}
POSTING_INTERVAL_HOURS = 1

USER_DATABASE = {}
USER_ACTIVITY_LOG = []
RECENT_ACTIVITY = []

DEFAULT_CAPTION = ""
CHANNEL_DEFAULT_CAPTIONS = {}

UNAUTHORIZED_ATTEMPTS = []

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Storage - Create data directory if needed
STORAGE_DIR = "/app/data"
if not os.path.exists(STORAGE_DIR):
    try:
        os.makedirs(STORAGE_DIR)
        logger.info(f"✅ Created storage directory: {STORAGE_DIR}")
    except Exception as e:
        logger.warning(f"⚠️ Could not create {STORAGE_DIR}, using current directory: {e}")
        STORAGE_DIR = "."

STORAGE_FILE = os.path.join(STORAGE_DIR, "bot_data.json")


def save_data():
    """Save all bot data to file"""
    try:
        data = {
            'managed_channels': MANAGED_CHANNELS,
            'uploaded_images': UPLOADED_IMAGES,
            'channel_specific_images': CHANNEL_SPECIFIC_IMAGES,
            'default_caption': DEFAULT_CAPTION,
            'channel_default_captions': CHANNEL_DEFAULT_CAPTIONS,
            'auto_post_enabled': AUTO_POST_ENABLED,
            'current_image_index': CURRENT_IMAGE_INDEX,
            'bulk_approval_mode': BULK_APPROVAL_MODE,
            'blocked_users': list(BLOCKED_USERS),
            'user_database': USER_DATABASE
        }
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("✅ Data saved successfully")
    except Exception as e:
        logger.error(f"❌ Save failed: {e}")


def load_data():
    """Load all bot data from file"""
    global MANAGED_CHANNELS, UPLOADED_IMAGES, CHANNEL_SPECIFIC_IMAGES
    global DEFAULT_CAPTION, CHANNEL_DEFAULT_CAPTIONS, AUTO_POST_ENABLED
    global CURRENT_IMAGE_INDEX, BULK_APPROVAL_MODE, BLOCKED_USERS, USER_DATABASE

    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            MANAGED_CHANNELS = data.get('managed_channels', {})
            UPLOADED_IMAGES = data.get('uploaded_images', [])
            CHANNEL_SPECIFIC_IMAGES = data.get('channel_specific_images', {})
            DEFAULT_CAPTION = data.get('default_caption', "")
            CHANNEL_DEFAULT_CAPTIONS = data.get('channel_default_captions', {})
            AUTO_POST_ENABLED = data.get('auto_post_enabled', {})
            CURRENT_IMAGE_INDEX = data.get('current_image_index', {})
            BULK_APPROVAL_MODE = data.get('bulk_approval_mode', {})
            BLOCKED_USERS = set(data.get('blocked_users', []))
            USER_DATABASE = data.get('user_database', {})

            # Convert string keys to int
            MANAGED_CHANNELS = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in MANAGED_CHANNELS.items()
            }
            CHANNEL_SPECIFIC_IMAGES = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CHANNEL_SPECIFIC_IMAGES.items()
            }
            AUTO_POST_ENABLED = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in AUTO_POST_ENABLED.items()
            }
            CURRENT_IMAGE_INDEX = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CURRENT_IMAGE_INDEX.items()
            }
            BULK_APPROVAL_MODE = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in BULK_APPROVAL_MODE.items()
            }
            CHANNEL_DEFAULT_CAPTIONS = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CHANNEL_DEFAULT_CAPTIONS.items()
            }

            logger.info(f"✅ Loaded: {len(MANAGED_CHANNELS)} channels, {len(UPLOADED_IMAGES)} images")
        else:
            logger.info("ℹ️ No saved data found, starting fresh")
    except Exception as e:
        logger.error(f"❌ Load failed: {e}")


def is_verified(user_id: int) -> bool:
    return user_id in VERIFIED_USERS or user_id == ADMIN_ID


async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking bot admin status: {e}")
        return False


def generate_verification_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def is_name_suspicious(name: str) -> bool:
    """Check if name looks suspicious (bot-like)"""
    if not name or len(name) < 2:
        return True

    if re.match(r'^User\d+$', name, re.IGNORECASE):
        return True

    letters_and_numbers = re.sub(r'[^a-zA-Z0-9]', '', name)
    if len(letters_and_numbers) < 2:
        return True

    numbers = re.sub(r'\D', '', name)
    if len(numbers) > len(name) * 0.6:
        return True

    return False


async def check_user_legitimacy(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Enhanced user legitimacy checker"""
    try:
        user = await context.bot.get_chat(user_id)

        score = 0
        reasons = []

        if user.type == "bot":
            return {"legitimate": False, "reason": "Bot account", "score": 0}

        if not user.first_name or is_name_suspicious(user.first_name):
            reasons.append("Suspicious name")
        else:
            score += 40

        if user.username:
            score += 30
        else:
            reasons.append("No username")

        if REQUIRE_PROFILE_PHOTO:
            try:
                photos = await context.bot.get_user_profile_photos(user_id, limit=1)
                if photos.total_count > 0:
                    score += 30
                else:
                    reasons.append("No profile photo")
            except:
                reasons.append("Cannot check photo")
        else:
            score += 30

        if score >= 70:
            return {"legitimate": True, "score": 100}
        elif score >= 30:
            return {"legitimate": False, "score": 50, "reason": ", ".join(reasons)}
        else:
            return {"legitimate": False, "score": 0, "reason": ", ".join(reasons)}

    except Exception as e:
        logger.error(f"Legitimacy check failed: {e}")
        return {"legitimate": False, "reason": "Error checking user", "score": 0}


def track_user_activity(user_id: int, channel_id: int, action: str, user_data: dict = None):
    """Track user activity"""
    try:
        if user_id not in USER_DATABASE:
            USER_DATABASE[user_id] = {
                'first_name': user_data.get('first_name', 'Unknown') if user_data else 'Unknown',
                'last_name': user_data.get('last_name', ''),
                'username': user_data.get('username', ''),
                'channels': {}
            }
        if channel_id not in USER_DATABASE[user_id]['channels']:
            USER_DATABASE[user_id]['channels'][channel_id] = {
                'channel_name': MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown'),
                'status': action,
                'request_date': datetime.now(),
                'approval_date': None
            }
        else:
            USER_DATABASE[user_id]['channels'][channel_id]['status'] = action
            if action == 'approved':
                USER_DATABASE[user_id]['channels'][channel_id]['approval_date'] = datetime.now()
        save_data()
    except Exception as e:
        logger.error(f"Error tracking user activity: {e}")


async def alert_owner_unauthorized_access(context: ContextTypes.DEFAULT_TYPE, user_id: int, 
                                          username: str, first_name: str, command: str):
    """Alert owner of unauthorized access"""
    try:
        UNAUTHORIZED_ATTEMPTS.append({
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'command': command,
            'timestamp': datetime.now()
        })

        await context.bot.send_message(
            ADMIN_ID,
            f"🚨 *Unauthorized Access Attempt*\n\n"
            f"User: {first_name}\n"
            f"ID: `{user_id}`\n"
            f"Username: @{username or 'None'}\n"
            f"Command: `{command}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Alert failed: {e}")


async def owner_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is owner"""
    try:
        if not update.effective_user or update.effective_user.id != ADMIN_ID:
            if update.effective_user:
                await alert_owner_unauthorized_access(
                    context, 
                    update.effective_user.id,
                    update.effective_user.username,
                    update.effective_user.first_name,
                    update.message.text if update.message else "callback"
                )
            if update.message:
                await update.message.reply_text("❌ Unauthorized")
            return False
        return True
    except Exception as e:
        logger.error(f"Owner check error: {e}")
        return False


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Smart join request handler"""
    try:
        request = update.chat_join_request
        user = request.from_user
        chat_id = request.chat.id

        if chat_id not in MANAGED_CHANNELS:
            return

        if user.id == ADMIN_ID:
            await request.approve()
            logger.info(f"✅ Admin auto-approved: {user.id}")
            return

        if user.id in BLOCKED_USERS:
            await request.decline()
            logger.info(f"❌ Blocked user {user.id} tried to join")
            return

        if BULK_APPROVAL_MODE.get(chat_id, False):
            await request.approve()
            track_user_activity(user.id, chat_id, 'approved', {
                'first_name': user.first_name,
                'last_name': user.last_name or '',
                'username': user.username or ''
            })
            logger.info(f"✅ Bulk-approved user: {user.id}")
            return

        legitimacy = await check_user_legitimacy(context, user.id)

        if legitimacy['legitimate'] and legitimacy['score'] >= 100:
            try:
                await request.approve()
                track_user_activity(user.id, chat_id, 'approved', {
                    'first_name': user.first_name,
                    'last_name': user.last_name or '',
                    'username': user.username or ''
                })

                RECENT_ACTIVITY.append({
                    'type': 'auto_approved',
                    'user_id': user.id,
                    'user_name': user.first_name,
                    'username': user.username or 'None',
                    'channel': MANAGED_CHANNELS[chat_id]['name'],
                    'channel_id': chat_id,
                    'timestamp': datetime.now()
                })

                logger.info(f"✅ Auto-approved legitimate user: {user.id}")
                return
            except Exception as e:
                logger.error(f"Auto-approval failed: {e}")

        if not legitimacy['legitimate'] and legitimacy['score'] == 0:
            try:
                await request.decline()

                RECENT_ACTIVITY.append({
                    'type': 'auto_rejected',
                    'user_id': user.id,
                    'user_name': user.first_name or 'No Name',
                    'username': user.username or 'None',
                    'channel': MANAGED_CHANNELS[chat_id]['name'],
                    'channel_id': chat_id,
                    'reason': legitimacy.get('reason', 'Suspicious'),
                    'timestamp': datetime.now()
                })

                logger.info(f"❌ Auto-rejected suspicious user: {user.id}")
                return
            except Exception as e:
                logger.error(f"Auto-rejection failed: {e}")

        num1 = random.randint(1, 10)
        num2 = random.randint(1, 10)
        answer = num1 + num2

        PENDING_VERIFICATIONS[user.id] = {
            'code': str(answer),
            'chat_id': chat_id,
            'timestamp': datetime.now(),
            'captcha_question': f"{num1} + {num2}",
            'request': request
        }

        track_user_activity(user.id, chat_id, 'pending', {
            'first_name': user.first_name,
            'last_name': user.last_name or '',
            'username': user.username or ''
        })

        user_link = f"tg://user?id={user.id}"
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"enter_code_{user.id}")]]

        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ *Verification Needed*\n\n"
            f"Channel: {MANAGED_CHANNELS[chat_id]['name']}\n"
            f"User: [{user.first_name}]({user_link})\n"
            f"ID: `{user.id}`\n"
            f"Username: @{user.username or 'None'}\n"
            f"Status: Borderline - needs verification\n\n"
            f"Math Captcha: {num1} + {num2} = ?\n"
            f"Answer: {answer}\n\n"
            f"Reason: {legitimacy.get('reason', 'Unknown')}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        logger.info(f"⚠️ Sent verification request for user: {user.id}")

    except Exception as e:
        logger.error(f"Error in handle_join_request: {e}")


async def enter_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval"""
    try:
        query = update.callback_query

        if query.from_user.id != ADMIN_ID:
            await query.answer("Unauthorized", show_alert=True)
            return

        await query.answer()

        user_id = int(query.data.split('_')[-1])

        if user_id not in PENDING_VERIFICATIONS:
            await query.edit_message_text("❌ Verification expired or already processed")
            return

        verification = PENDING_VERIFICATIONS[user_id]
        chat_id = verification['chat_id']

        request = verification.get('request')
        if request:
            await request.approve()
        
        track_user_activity(user_id, chat_id, 'approved', {
            'first_name': USER_DATABASE.get(user_id, {}).get('first_name', 'Unknown')
        })

        del PENDING_VERIFICATIONS[user_id]

        await query.edit_message_text(
            f"✅ *User Approved*\n\n"
            f"User ID: `{user_id}`\n"
            f"Channel: {MANAGED_CHANNELS[chat_id]['name']}",
            parse_mode='Markdown'
        )

        logger.info(f"✅ Admin manually approved user: {user_id}")

    except Exception as e:
        logger.error(f"Manual approval error: {e}")
        try:
            await query.edit_message_text(f"❌ Approval failed\n\nError: {str(e)}", parse_mode='Markdown')
        except:
            pass


async def resend_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Unauthorized", show_alert=True)
        return
    await query.answer("Feature not applicable for this verification system")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    try:
        user = update.effective_user

        if user.id == ADMIN_ID:
            text = (
                "👋 *Welcome Owner!*\n\n"
                "🤖 Bot Status: Online\n"
                f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
                f"⚙️ Smart Verification: Enabled\n\n"
                "━━━ QUICK START ━━━\n"
                "/addchannel - Add channel\n"
                "/channels - List channels\n"
                "/stats - Statistics\n"
                "/help - Full command list"
            )
        else:
            text = "Hello! This bot manages channel memberships."

        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Start command error: {e}")


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add channel"""
    try:
        if not await owner_only_check(update, context):
            return

        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "Usage: `/addchannel CHANNEL_ID CHANNEL_NAME`\n\n"
                "Example: `/addchannel -1001234567890 My Premium Channel`",
                parse_mode='Markdown'
            )
            return

        channel_id = int(context.args[0])
        channel_name = ' '.join(context.args[1:])

        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        save_data()

        await update.message.reply_text(
            f"✅ Channel added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`\n"
            f"Smart Verification: Enabled",
            parse_mode='Markdown'
        )

        logger.info(f"✅ Channel added: {channel_name} ({channel_id})")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Add channel error: {e}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List channels"""
    try:
        if not await owner_only_check(update, context):
            return

        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "📢 *Managed Channels:*\n\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            bulk_status = "🔄 Bulk" if BULK_APPROVAL_MODE.get(channel_id, False) else "🛡️ Smart"
            text += f"{data['name']}\n"
            text += f"ID: `{channel_id}`\n"
            text += f"Mode: {bulk_status}\n\n"

        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"List channels error: {e}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistics"""
    try:
        if not await owner_only_check(update, context):
            return

        bulk_enabled = sum(1 for v in BULK_APPROVAL_MODE.values() if v)
        active_autoposts = sum(1 for v in AUTO_POST_ENABLED.values() if v)
        recent_approved = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_approved')
        recent_rejected = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_rejected')

        text = (
            f"📊 *Statistics*\n\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"🛡️ Smart Mode: {len(MANAGED_CHANNELS) - bulk_enabled}\n"
            f"🔄 Bulk Mode: {bulk_enabled}\n"
            f"⏳ Pending: {len(PENDING_VERIFICATIONS)}\n"
            f"✅ Recent Approved: {recent_approved}\n"
            f"❌ Recent Rejected: {recent_rejected}\n"
            f"🚫 Blocked: {len(BLOCKED_USERS)}\n"
            f"📂 Images: {len(UPLOADED_IMAGES)}\n"
            f"🤖 Auto-Posts: {active_autoposts} active\n"
            f"👥 Total Users: {len(USER_DATABASE)}\n\n"
            f"Status: ✅ Online"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Stats error: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Exception while handling an update: {context.error}")


def main():
    """Main function"""
    logger.info("🚀 Starting SMART VERIFICATION BOT...")
    logger.info(f"✅ Bot Token: {'Set' if BOT_TOKEN else 'NOT SET'}")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")
    logger.info(f"✅ Storage: {STORAGE_FILE}")

    load_data()

    try:
        app = Application.builder().token(BOT_TOKEN).build()

        # Core commands
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("addchannel", add_channel))
        app.add_handler(CommandHandler("channels", list_channels))
        app.add_handler(CommandHandler("stats", stats))

        # Callbacks
        app.add_handler(CallbackQueryHandler(enter_code_callback, pattern="^enter_code_"))
        app.add_handler(CallbackQueryHandler(resend_code_callback, pattern="^resend_code_"))

        # Join request handler
        app.add_handler(ChatJoinRequestHandler(handle_join_request))

        # Error handler
        app.add_error_handler(error_handler)

        logger.info(f"✅ Bot starting - Owner: {ADMIN_ID}")
        logger.info(f"✅ Loaded: {len(MANAGED_CHANNELS)} channels")

        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise


if __name__ == '__main__':
    main()
