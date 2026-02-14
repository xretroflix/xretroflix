import os
import logging
from datetime import datetime, timedelta
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

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '0'))

# Railway validation
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set! Add it in Railway Variables tab")
if ADMIN_ID == 0:
    raise ValueError("❌ ADMIN_ID not set! Add it in Railway Variables tab")

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

# Promo image storage
PROMO_IMAGES = {}  # {channel_id: {'promo1': {...}, 'promo2': {...}}}
POST_COUNTER = {}  # {channel_id: count} - tracks total posts for promo pattern

# NEW: Global fallback channel for rejected users
GLOBAL_FALLBACK_CHANNEL = ""  # Set via /set_fallback command

# NEW: Combined media storage (images + videos in upload order)
CHANNEL_MEDIA_QUEUE = {}  # {channel_id: [{'type': 'photo'/'video', 'file_id': '...', 'caption': '...'}]}

# NEW: Links storage for link-only channels
CHANNEL_LINKS = {}  # {channel_id: ['link1', 'link2', ...]}
CHANNEL_LINK_INDEX = {}  # {channel_id: current_index}

# NEW: Channel content type configuration
CHANNEL_CONTENT_TYPE = {}  # {channel_id: 'media' / 'links'}

# Emoji rotation for pattern breaking
CAPTION_EMOJIS = [
    '🎬', '🔥', '⚡', '💎', '✨', '🎯', '🚀', '⭐',
    '🎭', '🎪', '🎨', '🎥', '🎞️', '📹', '📽️', '💥',
    '💫', '🌟', '👑', '🏆', '🥇', '🎉', '🎊', '🍿'
]

USER_DATABASE = {}
USER_ACTIVITY_LOG = []
RECENT_ACTIVITY = []  # Store recent approvals/rejections for batch viewing

DEFAULT_CAPTION = ""
CHANNEL_DEFAULT_CAPTIONS = {}

UNAUTHORIZED_ATTEMPTS = []

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Permanent storage - Railway fix: create directory if needed
STORAGE_DIR = "/app/data"
if not os.path.exists(STORAGE_DIR):
    try:
        os.makedirs(STORAGE_DIR)
        logger.info(f"✅ Created storage directory: {STORAGE_DIR}")
    except:
        logger.warning("⚠️ Using current directory for storage")
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
            'user_database': USER_DATABASE,
            'promo_images': PROMO_IMAGES,
            'post_counter': POST_COUNTER,
            # NEW additions
            'global_fallback_channel': GLOBAL_FALLBACK_CHANNEL,
            'channel_media_queue': CHANNEL_MEDIA_QUEUE,
            'channel_links': CHANNEL_LINKS,
            'channel_link_index': CHANNEL_LINK_INDEX,
            'channel_content_type': CHANNEL_CONTENT_TYPE
        }
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("✅ Data saved")
    except Exception as e:
        logger.error(f"Save failed: {e}")


def load_data():
    """Load all bot data from file"""
    global MANAGED_CHANNELS, UPLOADED_IMAGES, CHANNEL_SPECIFIC_IMAGES
    global DEFAULT_CAPTION, CHANNEL_DEFAULT_CAPTIONS, AUTO_POST_ENABLED
    global CURRENT_IMAGE_INDEX, BULK_APPROVAL_MODE, BLOCKED_USERS, USER_DATABASE
    global PROMO_IMAGES, POST_COUNTER
    global GLOBAL_FALLBACK_CHANNEL, CHANNEL_MEDIA_QUEUE, CHANNEL_LINKS
    global CHANNEL_LINK_INDEX, CHANNEL_CONTENT_TYPE

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
            PROMO_IMAGES = data.get('promo_images', {})
            POST_COUNTER = data.get('post_counter', {})

            # NEW additions
            GLOBAL_FALLBACK_CHANNEL = data.get('global_fallback_channel', "")
            CHANNEL_MEDIA_QUEUE = data.get('channel_media_queue', {})
            CHANNEL_LINKS = data.get('channel_links', {})
            CHANNEL_LINK_INDEX = data.get('channel_link_index', {})
            CHANNEL_CONTENT_TYPE = data.get('channel_content_type', {})

            # Convert string keys to int for all dictionaries
            def convert_keys(d):
                return {
                    int(k) if str(k).lstrip('-').isdigit() else k: v
                    for k, v in d.items()
                }

            MANAGED_CHANNELS = convert_keys(MANAGED_CHANNELS)
            CHANNEL_SPECIFIC_IMAGES = convert_keys(CHANNEL_SPECIFIC_IMAGES)
            AUTO_POST_ENABLED = convert_keys(AUTO_POST_ENABLED)
            CURRENT_IMAGE_INDEX = convert_keys(CURRENT_IMAGE_INDEX)
            BULK_APPROVAL_MODE = convert_keys(BULK_APPROVAL_MODE)
            CHANNEL_DEFAULT_CAPTIONS = convert_keys(CHANNEL_DEFAULT_CAPTIONS)
            PROMO_IMAGES = convert_keys(PROMO_IMAGES)
            POST_COUNTER = convert_keys(POST_COUNTER)
            CHANNEL_MEDIA_QUEUE = convert_keys(CHANNEL_MEDIA_QUEUE)
            CHANNEL_LINKS = convert_keys(CHANNEL_LINKS)
            CHANNEL_LINK_INDEX = convert_keys(CHANNEL_LINK_INDEX)
            CHANNEL_CONTENT_TYPE = convert_keys(CHANNEL_CONTENT_TYPE)

            logger.info(
                f"✅ Loaded: {len(MANAGED_CHANNELS)} channels, {len(UPLOADED_IMAGES)} images"
            )
        else:
            logger.info("No saved data")
    except Exception as e:
        logger.error(f"Load failed: {e}")


def is_verified(user_id: int) -> bool:
    return user_id in VERIFIED_USERS or user_id == ADMIN_ID


async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE,
                       chat_id: int) -> bool:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return bot_member.status in [
            ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER
        ]
    except:
        return False


def generate_verification_code() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def is_name_suspicious(name: str) -> bool:
    """Check if name looks suspicious (bot-like)"""
    if not name or len(name) < 2:
        return True

    # Check for "User" followed by numbers (typical bot pattern)
    if re.match(r'^User\d+$', name, re.IGNORECASE):
        return True

    # Check if name is mostly numbers
    letters_and_numbers = re.sub(r'[^a-zA-Z0-9]', '', name)
    if len(letters_and_numbers) < 2:
        return True

    numbers = re.sub(r'\D', '', name)
    if len(numbers) > len(name) * 0.6:  # More than 60% numbers
        return True

    return False


async def check_user_legitimacy(context: ContextTypes.DEFAULT_TYPE,
                                user_id: int) -> dict:
    """
    Enhanced user legitimacy checker with detailed scoring
    Returns: {"legitimate": bool, "score": int, "reason": str}
    """
    try:
        user = await context.bot.get_chat(user_id)

        score = 0
        reasons = []

        # Check 1: Is it a bot?
        if user.type == "bot":
            return {"legitimate": False, "reason": "Bot account", "score": 0}

        # Check 2: Name quality (40 points)
        if not user.first_name or is_name_suspicious(user.first_name):
            reasons.append("Suspicious name")
        else:
            score += 40

        # Check 3: Has username? (30 points)
        if user.username:
            score += 30
        else:
            reasons.append("No username")

        # Check 4: Has profile photo? (30 points)
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
            # Give score anyway if not required
            score += 30

        # Scoring system:
        # 100 = Legitimate (auto-approve)
        # 1-99 = Borderline (manual check with captcha)
        # 0 = Suspicious (auto-reject)

        if score >= 70:
            return {"legitimate": True, "score": 100}
        elif score >= 30:
            return {"legitimate": False, "score": 50, "reason": ", ".join(reasons)}
        else:
            return {"legitimate": False, "score": 0, "reason": ", ".join(reasons)}

    except Exception as e:
        logger.error(f"Legitimacy check failed: {e}")
        return {"legitimate": False, "reason": "Error checking user", "score": 0}


def track_user_activity(user_id: int,
                        channel_id: int,
                        action: str,
                        user_data: dict = None):
    """Track user activity in database"""
    if user_id not in USER_DATABASE:
        USER_DATABASE[user_id] = {
            'first_name':
            user_data.get('first_name', 'Unknown') if user_data else 'Unknown',
            'last_name': user_data.get('last_name', ''),
            'username': user_data.get('username', ''),
            'channels': {}
        }
    if channel_id not in USER_DATABASE[user_id]['channels']:
        USER_DATABASE[user_id]['channels'][channel_id] = {
            'channel_name':
            MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown'),
            'status':
            action,
            'request_date':
            datetime.now(),
            'approval_date':
            None
        }
    else:
        USER_DATABASE[user_id]['channels'][channel_id]['status'] = action
        if action == 'approved':
            USER_DATABASE[user_id]['channels'][channel_id][
                'approval_date'] = datetime.now()
    save_data()


async def alert_owner_unauthorized_access(context: ContextTypes.DEFAULT_TYPE,
                                          user_id: int, username: str,
                                          first_name: str, command: str):
    """Alert owner of unauthorized access attempts"""
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
            parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Alert failed: {e}")


async def owner_only_check(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is the owner"""
    try:
        if not update.effective_user or update.effective_user.id != ADMIN_ID:
            if update.effective_user:
                await alert_owner_unauthorized_access(context, update.effective_user.id,
                                                      update.effective_user.username or "None",
                                                      update.effective_user.first_name or "Unknown",
                                                      update.message.text if update.message else "callback")
            if update.message:
                await update.message.reply_text("❌ Unauthorized")
            return False
        logger.info(f"✅ Owner check passed for user {update.effective_user.id}")
        return True
    except Exception as e:
        logger.error(f"❌ Owner check error: {e}")
        return False


async def is_admin(update: Update) -> bool:
    """Quick check if user is admin - for complete lockdown"""
    if not update.effective_user:
        return False
    return update.effective_user.id == ADMIN_ID


async def ignore_non_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Complete lockdown - ignore ALL non-admin interactions silently.
    Returns True if should ignore (non-admin), False if admin.
    """
    if not update.effective_user:
        return True  # Ignore

    if update.effective_user.id != ADMIN_ID:
        # Complete silence - no response, no logging for regular attempts
        # Only log if they try commands (potential probe)
        if update.message and update.message.text and update.message.text.startswith('/'):
            logger.warning(f"🚫 Blocked command attempt from {update.effective_user.id}")
        return True  # Ignore

    return False  # Admin - proceed


# ========== SMART JOIN REQUEST HANDLER ==========
async def handle_join_request(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """
    Smart join request handler with 3-tier verification:
    1. Auto-approve legitimate users
    2. Auto-reject obvious bots/spammers + send fallback channel
    3. Math captcha for borderline cases
    """
    request = update.chat_join_request
    user = request.from_user
    chat_id = request.chat.id

    # Only handle managed channels
    if chat_id not in MANAGED_CHANNELS:
        return

    # Always approve admin
    if user.id == ADMIN_ID:
        await request.approve()
        logger.info(f"✅ Admin auto-approved: {user.id}")
        return

    # Block already blocked users
    if user.id in BLOCKED_USERS:
        await request.decline()
        logger.info(f"❌ Blocked user {user.id} tried to join")
        return

    # Check if bulk approval is enabled for this channel
    if BULK_APPROVAL_MODE.get(chat_id, False):
        await request.approve()
        track_user_activity(user.id, chat_id, 'approved', {
            'first_name': user.first_name,
            'last_name': user.last_name or '',
            'username': user.username or ''
        })
        logger.info(f"✅ Bulk-approved user: {user.id}")
        return

    # Smart verification - check legitimacy
    legitimacy = await check_user_legitimacy(context, user.id)

    # === TIER 1: AUTO-APPROVE LEGITIMATE USERS ===
    if legitimacy['legitimate'] and legitimacy['score'] >= 100:
        try:
            await request.approve()
            track_user_activity(user.id, chat_id, 'approved', {
                'first_name': user.first_name,
                'last_name': user.last_name or '',
                'username': user.username or ''
            })

            # Log to recent activity instead of sending notification
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

    # === TIER 2: AUTO-REJECT + REDIRECT TO FALLBACK CHANNEL ===
    if not legitimacy['legitimate'] and legitimacy['score'] == 0:
        try:
            await request.decline()

            # NEW: Send fallback channel link to rejected user
            if GLOBAL_FALLBACK_CHANNEL:
                try:
                    await context.bot.send_message(
                        user.id,
                        f"Your request to join was not approved.\n\n"
                        f"You can join our public channel instead:\n"
                        f"{GLOBAL_FALLBACK_CHANNEL}",
                        disable_web_page_preview=True
                    )
                    logger.info(f"📤 Sent fallback channel to rejected user {user.id}")
                except Exception as dm_error:
                    # User might have blocked bot or never started it
                    logger.warning(f"Could not DM user {user.id}: {dm_error}")

            # Log to recent activity
            RECENT_ACTIVITY.append({
                'type': 'auto_rejected',
                'user_id': user.id,
                'user_name': user.first_name or 'No Name',
                'username': user.username or 'None',
                'channel': MANAGED_CHANNELS[chat_id]['name'],
                'channel_id': chat_id,
                'reason': legitimacy.get('reason', 'Suspicious'),
                'fallback_sent': bool(GLOBAL_FALLBACK_CHANNEL),
                'timestamp': datetime.now()
            })

            logger.info(f"❌ Auto-rejected suspicious user: {user.id}")
            return
        except Exception as e:
            logger.error(f"Auto-rejection failed: {e}")

    # === TIER 3: MATH CAPTCHA FOR BORDERLINE CASES ===
    # Generate simple math problem
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    answer = num1 + num2

    # Store verification data
    PENDING_VERIFICATIONS[user.id] = {
        'code': str(answer),
        'chat_id': chat_id,
        'timestamp': datetime.now(),
        'captcha_question': f"{num1} + {num2}",
        'request': request  # Store request object for later approval
    }

    track_user_activity(user.id, chat_id, 'pending', {
        'first_name': user.first_name,
        'last_name': user.last_name or '',
        'username': user.username or ''
    })

    # Send captcha to admin with quick approve button
    user_link = f"tg://user?id={user.id}"
    keyboard = [[
        InlineKeyboardButton("✅ Approve",
                            callback_data=f"enter_code_{user.id}")
    ]]

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
        reply_markup=InlineKeyboardMarkup(keyboard))

    logger.info(f"⚠️ Sent verification request for user: {user.id}")


async def enter_code_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Handle admin's approval via button click"""
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

    try:
        # Approve the join request
        request = verification.get('request')
        if request:
            await request.approve()
        else:
            # Fallback: Try to approve via invite link
            logger.warning(f"No request object found for user {user_id}")

        # Track approval
        track_user_activity(user_id, chat_id, 'approved', {
            'first_name': USER_DATABASE.get(user_id, {}).get('first_name', 'Unknown')
        })

        # Remove from pending
        del PENDING_VERIFICATIONS[user_id]

        await query.edit_message_text(
            f"✅ *User Approved*\n\n"
            f"User ID: `{user_id}`\n"
            f"Channel: {MANAGED_CHANNELS[chat_id]['name']}",
            parse_mode='Markdown')

        logger.info(f"✅ Admin manually approved user: {user_id}")

    except Exception as e:
        logger.error(f"Manual approval failed: {e}")
        await query.edit_message_text(
            f"❌ Approval failed\n\nError: {str(e)}",
            parse_mode='Markdown')


async def resend_code_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for resend code functionality"""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer("Feature not applicable for this verification system")


# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command with all commands listed"""
    if await ignore_non_admin(update, context):
        return

    user = update.effective_user

    if user.id == ADMIN_ID:
        text = (
            "👋 Welcome Owner!\n\n"
            "🤖 Bot Status: Online 24/7\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"⚙️ Smart Verification: Enabled\n"
            f"🎯 Random Emojis: {len(CAPTION_EMOJIS)} emojis\n"
            f"⏰ Random Intervals: 12-28 mins\n\n"

            "━━━ SETUP & INFO ━━━\n"
            "/start - This menu\n"
            "/addchannel - Add channel\n"
            "/removechannel - Remove channel\n"
            "/channels - List channels\n"
            "/view_config - Full config\n"
            "/stats - Statistics\n\n"

            "━━━ VERIFICATION ━━━\n"
            "/set_fallback - Fallback channel\n"
            "/clear_fallback - Clear fallback\n"
            "/verification_settings - View\n\n"

            "━━━ ACTIVITY ━━━\n"
            "/recent_activity - Who joined\n"
            "/clear_activity - Clear log\n"
            "/pending_users - Captchas\n\n"

            "━━━ APPROVALS ━━━\n"
            "/approve_user - Approve one\n"
            "/approve_all_pending - Approve all\n"
            "/block_user - Block user\n"
            "/unblock_user - Unblock\n"
            "/toggle_bulk - Change mode\n\n"

            "━━━ MEDIA UPLOAD ━━━\n"
            "/upload_media - Images+Videos\n"
            "/done_media - Finish upload\n"
            "/list_media - View media\n"
            "/clear_media - Clear media\n\n"

            "━━━ LINKS UPLOAD ━━━\n"
            "/upload_links - Upload links\n"
            "/done_links - Finish links\n"
            "/list_links - View links\n"
            "/clear_links - Clear links\n\n"

            "━━━ CHANNEL CONFIG ━━━\n"
            "/set_channel_type - media/links\n"
            "/set_channel_caption - Caption\n"
            "/clear_channel_caption - Clear\n\n"

            "━━━ PROMO IMAGES ━━━\n"
            "/set_promo1 - Set promo 1\n"
            "/set_promo2 - Set promo 2\n"
            "/view_promos - View promos\n"
            "/clear_promo1 - Clear promo 1\n"
            "/clear_promo2 - Clear promo 2\n\n"

            "━━━ AUTO-POST ━━━\n"
            "/enable_autopost - Enable\n"
            "/disable_autopost - Disable\n"
            "/autopost_status - Check\n\n"

            "━━━ QUICK SEND ━━━\n"
            "/post - Post content\n"
            "/send_to_channel - Quick send\n"
            "/cancel - Cancel operation\n\n"

            "━━━ OLD COMMANDS ━━━\n"
            "/upload_images - Old image upload\n"
            "/list_images - Old images\n"
            "/clear_images - Clear old\n\n"

            "━━━ ANALYTICS ━━━\n"
            "/user_stats - Stats\n"
            "/export_users - Export CSV"
        )
        await update.message.reply_text(text)


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel to manage"""
    if await ignore_non_admin(update, context):
        return

    logger.info(f"📢 add_channel called by user {update.effective_user.id}")

    if not context.args or len(context.args) < 2:
        logger.info("❌ Invalid args - showing usage")
        await update.message.reply_text(
            "Usage: `/addchannel CHANNEL_ID CHANNEL_NAME`\n\n"
            "Example: `/addchannel -1001234567890 My Premium Channel`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        channel_name = ' '.join(context.args[1:])

        logger.info(f"📢 Attempting to add channel: {channel_name} ({channel_id})")

        # Check if bot is admin
        is_admin = await is_bot_admin(context, channel_id)
        logger.info(f"🔍 Bot admin check for {channel_id}: {is_admin}")

        if not is_admin:
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        save_data()

        logger.info(f"✅ Channel added successfully: {channel_name} ({channel_id})")
        logger.info(f"📊 Total managed channels: {len(MANAGED_CHANNELS)}")

        await update.message.reply_text(
            f"✅ Channel added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`\n"
            f"Smart Verification: Enabled\n"
            f"Random Emojis: Active",
            parse_mode='Markdown')

    except ValueError as e:
        logger.error(f"❌ ValueError in add_channel: {e}")
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        logger.error(f"❌ Exception in add_channel: {e}")
        await update.message.reply_text(f"❌ Error: {e}")


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a channel from management"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/removechannel CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in MANAGED_CHANNELS:
            channel_name = MANAGED_CHANNELS[channel_id]['name']
            del MANAGED_CHANNELS[channel_id]

            # Clean up related data
            if channel_id in AUTO_POST_ENABLED:
                del AUTO_POST_ENABLED[channel_id]
            if channel_id in CHANNEL_MEDIA_QUEUE:
                del CHANNEL_MEDIA_QUEUE[channel_id]
            if channel_id in CHANNEL_LINKS:
                del CHANNEL_LINKS[channel_id]
            if channel_id in CHANNEL_CONTENT_TYPE:
                del CHANNEL_CONTENT_TYPE[channel_id]

            # Remove scheduler job
            try:
                scheduler.remove_job(f'autopost_{channel_id}')
            except:
                pass

            save_data()

            await update.message.reply_text(
                f"✅ Channel removed!\n\n"
                f"Name: {channel_name}\n"
                f"ID: `{channel_id}`",
                parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Channel not found")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all managed channels"""
    if await ignore_non_admin(update, context):
        return

    logger.info(f"📋 list_channels called by user {update.effective_user.id}")

    if not MANAGED_CHANNELS:
        logger.info("ℹ️ No channels in database")
        await update.message.reply_text("No channels added yet")
        return

    text = "📢 *Managed Channels:*\n\n"
    for channel_id, data in MANAGED_CHANNELS.items():
        bulk_status = "🔄 Bulk" if BULK_APPROVAL_MODE.get(channel_id, False) else "🛡️ Smart"
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'media')
        auto_post = "✅" if AUTO_POST_ENABLED.get(channel_id, False) else "❌"

        text += f"*{data['name']}*\n"
        text += f"ID: `{channel_id}`\n"
        text += f"Mode: {bulk_status}\n"
        text += f"Type: {content_type}\n"
        text += f"Auto-Post: {auto_post}\n\n"

    logger.info(f"✅ Sending channel list with {len(MANAGED_CHANNELS)} channels")
    await update.message.reply_text(text, parse_mode='Markdown')


async def pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending verification requests"""
    if await ignore_non_admin(update, context):
        return

    if not PENDING_VERIFICATIONS:
        await update.message.reply_text("No pending verifications")
        return

    text = "⏳ *Pending Verifications:*\n\n"
    for user_id, data in PENDING_VERIFICATIONS.items():
        channel_name = MANAGED_CHANNELS.get(data['chat_id'], {}).get('name', 'Unknown')
        text += f"User ID: `{user_id}`\n"
        text += f"Channel: {channel_name}\n"
        text += f"Captcha: {data['captcha_question']} = {data['code']}\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')


async def manual_approve_user(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Manually approve a user"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/approve_user USER_ID`",
            parse_mode='Markdown')
        return

    try:
        user_id = int(context.args[0])

        if user_id not in PENDING_VERIFICATIONS:
            await update.message.reply_text("❌ User not in pending list")
            return

        verification = PENDING_VERIFICATIONS[user_id]
        chat_id = verification['chat_id']
        request = verification.get('request')

        if request:
            await request.approve()
            track_user_activity(user_id, chat_id, 'approved')
            del PENDING_VERIFICATIONS[user_id]

            await update.message.reply_text(
                f"✅ User approved!\n\n"
                f"User ID: `{user_id}`\n"
                f"Channel: {MANAGED_CHANNELS[chat_id]['name']}",
                parse_mode='Markdown')

            logger.info(f"✅ Manual approval: {user_id}")
        else:
            await update.message.reply_text("❌ Cannot approve - request expired")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Manual approval failed: {e}")


async def approve_all_pending(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Approve all pending verifications"""
    if await ignore_non_admin(update, context):
        return

    if not PENDING_VERIFICATIONS:
        await update.message.reply_text("No pending verifications")
        return

    approved = 0
    failed = 0

    for user_id, verification in list(PENDING_VERIFICATIONS.items()):
        try:
            request = verification.get('request')
            if request:
                await request.approve()
                track_user_activity(user_id, verification['chat_id'], 'approved')
                del PENDING_VERIFICATIONS[user_id]
                approved += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Approval failed for {user_id}: {e}")
            failed += 1

    await update.message.reply_text(
        f"✅ *Bulk Approval Complete*\n\n"
        f"Approved: {approved}\n"
        f"Failed: {failed}",
        parse_mode='Markdown')


async def bulk_approve_from_file(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for bulk approve from file"""
    if await ignore_non_admin(update, context):
        return

    await update.message.reply_text(
        "To bulk approve:\n"
        "1. Send me a text file with user IDs (one per line)\n"
        "2. I'll approve them all")


async def toggle_bulk_approval(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """Toggle bulk approval mode for a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/toggle_bulk CHANNEL_ID`\n\n"
            "This toggles between:\n"
            "🛡️ Smart Verification (auto-approve/reject/captcha)\n"
            "🔄 Bulk Mode (approve everyone)",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        current_status = BULK_APPROVAL_MODE.get(channel_id, False)
        BULK_APPROVAL_MODE[channel_id] = not current_status
        save_data()

        new_mode = "🔄 Bulk Mode (approve everyone)" if BULK_APPROVAL_MODE[channel_id] else "🛡️ Smart Verification"

        await update.message.reply_text(
            f"✅ Mode changed!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"New Mode: {new_mode}",
            parse_mode='Markdown')

        logger.info(f"✅ Toggle bulk for {channel_id}: {BULK_APPROVAL_MODE[channel_id]}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block a user from all channels"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/block_user USER_ID`",
            parse_mode='Markdown')
        return

    try:
        user_id = int(context.args[0])
        BLOCKED_USERS.add(user_id)
        save_data()

        await update.message.reply_text(
            f"✅ User blocked!\n\n"
            f"User ID: `{user_id}`\n"
            f"They cannot join any managed channel",
            parse_mode='Markdown')

        logger.info(f"✅ User blocked: {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unblock a user"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/unblock_user USER_ID`",
            parse_mode='Markdown')
        return

    try:
        user_id = int(context.args[0])

        if user_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_id)
            save_data()
            await update.message.reply_text(
                f"✅ User unblocked!\n\n"
                f"User ID: `{user_id}`",
                parse_mode='Markdown')
            logger.info(f"✅ User unblocked: {user_id}")
        else:
            await update.message.reply_text("❌ User not in blocked list")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def verification_settings(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Show verification settings"""
    if await ignore_non_admin(update, context):
        return

    text = (
        f"⚙️ *Smart Verification Settings*\n\n"
        f"**Auto-Approve (Score ≥70):**\n"
        f"• Has real name (40 pts)\n"
        f"• Has username (30 pts)\n"
        f"• Has profile photo (30 pts)\n\n"
        f"**Math Captcha (Score 30-69):**\n"
        f"• Borderline users\n"
        f"• Admin decides\n\n"
        f"**Auto-Reject (Score 0):**\n"
        f"• Bot accounts\n"
        f"• 'User123456' names\n"
        f"• Suspicious profiles\n\n"
        f"*Current Settings:*\n"
        f"Profile Photo Required: {REQUIRE_PROFILE_PHOTO}\n"
        f"Min Account Age: {MIN_ACCOUNT_AGE_DAYS} days\n"
        f"Random Emojis: {len(CAPTION_EMOJIS)} emojis\n"
        f"Fallback Channel: {GLOBAL_FALLBACK_CHANNEL or 'Not set'}"
    )

    await update.message.reply_text(text, parse_mode='Markdown')


# ========== FALLBACK CHANNEL COMMANDS ==========
async def set_fallback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set global fallback channel for rejected users"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_fallback https://t.me/yourchannel`\n\n"
            f"Current: {GLOBAL_FALLBACK_CHANNEL or 'Not set'}",
            parse_mode='Markdown')
        return

    global GLOBAL_FALLBACK_CHANNEL
    GLOBAL_FALLBACK_CHANNEL = context.args[0]
    save_data()

    await update.message.reply_text(
        f"✅ Fallback channel set!\n\n"
        f"Rejected users will see:\n{GLOBAL_FALLBACK_CHANNEL}")


async def clear_fallback_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear fallback channel"""
    if await ignore_non_admin(update, context):
        return

    global GLOBAL_FALLBACK_CHANNEL
    GLOBAL_FALLBACK_CHANNEL = ""
    save_data()

    await update.message.reply_text("✅ Fallback channel cleared")


# ========== MEDIA UPLOAD COMMANDS (Images + Videos) ==========
async def upload_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start media upload mode for a channel (images + videos in sequence)"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        # Show channels
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet. Use /addchannel first")
            return

        text = "📤 *Upload Media (Images + Videos)*\n\n"
        text += "Usage: `/upload_media CHANNEL_ID`\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            media_count = len(CHANNEL_MEDIA_QUEUE.get(channel_id, []))
            text += f"• {data['name']}\n  ID: `{channel_id}`\n  Media: {media_count}\n\n"

        await update.message.reply_text(text, parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['media_upload_channel'] = channel_id
        context.user_data['media_upload_mode'] = True

        # Set channel content type to media
        CHANNEL_CONTENT_TYPE[channel_id] = 'media'
        save_data()

        await update.message.reply_text(
            f"📤 *Media Upload Mode: {MANAGED_CHANNELS[channel_id]['name']}*\n\n"
            f"✅ Send IMAGES and VIDEOS now\n"
            f"📝 With or without captions\n"
            f"🔢 They will post in the EXACT order you send them\n"
            f"🔇 Silent mode - no notifications per upload\n\n"
            f"Use /done_media when finished",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def done_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish media upload mode"""
    if await ignore_non_admin(update, context):
        return

    channel_id = context.user_data.get('media_upload_channel')
    context.user_data['media_upload_mode'] = False
    context.user_data['media_upload_channel'] = None

    if channel_id:
        count = len(CHANNEL_MEDIA_QUEUE.get(channel_id, []))
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')

        # Count by type
        images = sum(1 for m in CHANNEL_MEDIA_QUEUE.get(channel_id, []) if m['type'] == 'photo')
        videos = sum(1 for m in CHANNEL_MEDIA_QUEUE.get(channel_id, []) if m['type'] == 'video')

        await update.message.reply_text(
            f"✅ *Media Upload Complete!*\n\n"
            f"Channel: {channel_name}\n"
            f"Total Media: {count}\n"
            f"📷 Images: {images}\n"
            f"🎬 Videos: {videos}\n\n"
            f"Use `/enable_autopost {channel_id}` to start posting!",
            parse_mode='Markdown')
    else:
        await update.message.reply_text("✅ Upload mode ended")


async def list_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List media for all channels"""
    if await ignore_non_admin(update, context):
        return

    text = "📂 *Media Library*\n\n"

    # Old format images
    text += f"Global Images (old): {len(UPLOADED_IMAGES)}\n\n"

    # New format media queues
    text += "━━━ Channel Media Queues ━━━\n\n"

    for channel_id, media_list in CHANNEL_MEDIA_QUEUE.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        images = sum(1 for m in media_list if m['type'] == 'photo')
        videos = sum(1 for m in media_list if m['type'] == 'video')
        current_idx = CURRENT_IMAGE_INDEX.get(channel_id, 0)

        text += f"📢 {channel_name}\n"
        text += f"   📷 Images: {images}\n"
        text += f"   🎬 Videos: {videos}\n"
        text += f"   Total: {len(media_list)}\n"
        text += f"   Current Index: {current_idx}\n\n"

    if not CHANNEL_MEDIA_QUEUE:
        text += "No media uploaded yet.\n"
        text += "Use `/upload_media CHANNEL_ID` to start"

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_media_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear media for a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/clear_media CHANNEL_ID`\n\n"
            "Or `/clear_media all` to clear everything",
            parse_mode='Markdown')
        return

    if context.args[0].lower() == 'all':
        CHANNEL_MEDIA_QUEUE.clear()
        CURRENT_IMAGE_INDEX.clear()
        save_data()
        await update.message.reply_text("✅ All media cleared")
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in CHANNEL_MEDIA_QUEUE:
            count = len(CHANNEL_MEDIA_QUEUE[channel_id])
            del CHANNEL_MEDIA_QUEUE[channel_id]
            if channel_id in CURRENT_IMAGE_INDEX:
                del CURRENT_IMAGE_INDEX[channel_id]
            save_data()
            await update.message.reply_text(f"✅ Cleared {count} media items")
        else:
            await update.message.reply_text("❌ No media for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


# ========== LINKS UPLOAD COMMANDS ==========
async def upload_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start links upload mode - send a TXT file with links"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "🔗 *Upload Links*\n\n"
        text += "Usage: `/upload_links CHANNEL_ID`\n\n"
        text += "Then send a .txt file with one link per line\n"
        text += "Or send links as text messages\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            links_count = len(CHANNEL_LINKS.get(channel_id, []))
            text += f"• {data['name']}: {links_count} links\n"

        await update.message.reply_text(text, parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['links_upload_channel'] = channel_id
        context.user_data['links_upload_mode'] = True

        # Set channel content type to links
        CHANNEL_CONTENT_TYPE[channel_id] = 'links'
        save_data()

        await update.message.reply_text(
            f"🔗 *Links Upload Mode: {MANAGED_CHANNELS[channel_id]['name']}*\n\n"
            f"Send a .txt file with links (one per line)\n\n"
            f"Or send links as text messages (one per message)\n\n"
            f"Use /done_links when finished",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def done_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish links upload mode"""
    if await ignore_non_admin(update, context):
        return

    channel_id = context.user_data.get('links_upload_channel')
    context.user_data['links_upload_mode'] = False
    context.user_data['links_upload_channel'] = None

    if channel_id:
        count = len(CHANNEL_LINKS.get(channel_id, []))
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')

        await update.message.reply_text(
            f"✅ *Links Upload Complete!*\n\n"
            f"Channel: {channel_name}\n"
            f"Total Links: {count}\n\n"
            f"Use `/enable_autopost {channel_id}` to start posting!",
            parse_mode='Markdown')
    else:
        await update.message.reply_text("✅ Links mode ended")


async def list_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List links for all channels"""
    if await ignore_non_admin(update, context):
        return

    text = "🔗 *Links Library*\n\n"

    for channel_id, links in CHANNEL_LINKS.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        current_idx = CHANNEL_LINK_INDEX.get(channel_id, 0)

        text += f"📢 {channel_name}\n"
        text += f"   Links: {len(links)}\n"
        text += f"   Current Index: {current_idx}\n\n"

    if not CHANNEL_LINKS:
        text += "No links uploaded yet.\n"
        text += "Use `/upload_links CHANNEL_ID` to start"

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear links for a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/clear_links CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in CHANNEL_LINKS:
            count = len(CHANNEL_LINKS[channel_id])
            del CHANNEL_LINKS[channel_id]
            if channel_id in CHANNEL_LINK_INDEX:
                del CHANNEL_LINK_INDEX[channel_id]
            save_data()
            await update.message.reply_text(f"✅ Cleared {count} links")
        else:
            await update.message.reply_text("❌ No links for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


# ========== CHANNEL CONFIG COMMANDS ==========
async def set_channel_type_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set channel content type (media or links)"""
    if await ignore_non_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_channel_type CHANNEL_ID TYPE`\n\n"
            "Types:\n"
            "• `media` - Post images and videos\n"
            "• `links` - Post links only",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        content_type = context.args[1].lower()

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        if content_type not in ['media', 'links']:
            await update.message.reply_text("❌ Type must be 'media' or 'links'")
            return

        CHANNEL_CONTENT_TYPE[channel_id] = content_type
        save_data()

        await update.message.reply_text(
            f"✅ Channel type set!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"Type: {content_type}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def view_channel_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View complete channel configuration"""
    if await ignore_non_admin(update, context):
        return

    if not MANAGED_CHANNELS:
        await update.message.reply_text("No channels configured")
        return

    text = "📋 *Channel Configuration*\n\n"

    for channel_id, data in MANAGED_CHANNELS.items():
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'media')
        bulk_mode = BULK_APPROVAL_MODE.get(channel_id, False)
        auto_post = AUTO_POST_ENABLED.get(channel_id, False)

        # Count content
        media_count = len(CHANNEL_MEDIA_QUEUE.get(channel_id, []))
        links_count = len(CHANNEL_LINKS.get(channel_id, []))
        old_images = len(CHANNEL_SPECIFIC_IMAGES.get(channel_id, []))
        current_idx = CURRENT_IMAGE_INDEX.get(channel_id, 0)
        post_count = POST_COUNTER.get(channel_id, 0)

        text += f"📢 *{data['name']}*\n"
        text += f"   ID: `{channel_id}`\n"
        text += f"   Type: {content_type}\n"
        text += f"   Approval: {'🔄 Bulk' if bulk_mode else '🛡️ Smart'}\n"
        text += f"   Auto-Post: {'✅ ON' if auto_post else '❌ OFF'}\n"
        text += f"   Media Queue: {media_count}\n"
        text += f"   Links: {links_count}\n"
        text += f"   Old Images: {old_images}\n"
        text += f"   Current Index: {current_idx}\n"
        text += f"   Posts Made: {post_count}\n\n"

    text += f"\n🌐 Fallback Channel: {GLOBAL_FALLBACK_CHANNEL or 'Not set'}"

    await update.message.reply_text(text, parse_mode='Markdown')


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start posting mode"""
    if await ignore_non_admin(update, context):
        return

    context.user_data['posting_mode'] = True
    await update.message.reply_text(
        "📤 *Posting Mode Enabled*\n\n"
        "Send me content to post (text, photo, video, or document)",
        parse_mode='Markdown')


async def upload_images_command(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Start image upload mode (OLD - for backward compatibility)"""
    if await ignore_non_admin(update, context):
        return

    context.user_data['uploading_mode'] = True
    context.user_data['uploading_for_channel'] = None
    await update.message.reply_text(
        "📤 *Upload Mode: SILENT (Legacy)*\n\n"
        "✅ Send images now (with or without captions)\n"
        "📝 Images with captions will use those captions\n"
        "🔇 No notifications per image (silent mode)\n"
        "✅ Use /done_uploading to see summary\n\n"
        "💡 NEW: Use /upload_media for images+videos!",
        parse_mode='Markdown')


async def done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop upload mode with comprehensive summary (OLD)"""
    if await ignore_non_admin(update, context):
        return

    context.user_data['uploading_mode'] = False
    channel_id = context.user_data.get('uploading_for_channel')

    if channel_id:
        count = len(CHANNEL_SPECIFIC_IMAGES.get(channel_id, []))
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"✅ *Upload Complete!*\n\n"
            f"Channel: {channel_name}\n"
            f"Images Added: {count}\n\n"
            f"Ready for auto-posting! 🚀",
            parse_mode='Markdown')
        context.user_data['uploading_for_channel'] = None
    else:
        await update.message.reply_text(
            f"✅ *Upload Complete!*\n\n"
            f"Total Global Images: {len(UPLOADED_IMAGES)}\n\n"
            f"Use /list_images to see all images",
            parse_mode='Markdown')


async def upload_for_channel_command(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """Upload images for specific channel (OLD)"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/upload_for_channel CHANNEL_ID`\n\n"
            "💡 NEW: Use /upload_media for images+videos!",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['uploading_for_channel'] = channel_id
        context.user_data['uploading_mode'] = True

        await update.message.reply_text(
            f"📤 *Upload Mode: {MANAGED_CHANNELS[channel_id]['name']}*\n\n"
            f"✅ Send images now (with or without captions)\n"
            f"📝 These images are exclusive to this channel\n"
            f"🔇 Silent mode - no notifications per image\n"
            f"✅ Use /done_uploading to see summary\n\n"
            f"💡 NEW: Use /upload_media for images+videos!",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def list_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List uploaded images (OLD)"""
    if await ignore_non_admin(update, context):
        return

    text = f"📂 *Image Library (Legacy)*\n\n"
    text += f"Global Images: {len(UPLOADED_IMAGES)}\n\n"

    for channel_id, images in CHANNEL_SPECIFIC_IMAGES.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        text += f"{channel_name}: {len(images)} images\n"

    text += "\n💡 Use /list_media for new format"

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all images (OLD)"""
    if await ignore_non_admin(update, context):
        return

    UPLOADED_IMAGES.clear()
    CHANNEL_SPECIFIC_IMAGES.clear()
    save_data()

    await update.message.reply_text("✅ All legacy images cleared")


async def set_default_caption(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Set default caption for posts"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_default_caption Your caption here`",
            parse_mode='Markdown')
        return

    global DEFAULT_CAPTION
    DEFAULT_CAPTION = ' '.join(context.args)
    save_data()

    await update.message.reply_text(
        f"✅ Default caption set!\n\n"
        f"Caption: {DEFAULT_CAPTION}\n\n"
        f"Note: Random emoji will be added automatically!")


async def clear_default_caption(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Clear default caption"""
    if await ignore_non_admin(update, context):
        return

    global DEFAULT_CAPTION
    DEFAULT_CAPTION = ""
    save_data()

    await update.message.reply_text("✅ Default caption cleared")


async def set_channel_caption(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Set channel-specific caption"""
    if await ignore_non_admin(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_channel_caption CHANNEL_ID Your caption`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        caption = ' '.join(context.args[1:])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        CHANNEL_DEFAULT_CAPTIONS[channel_id] = caption
        save_data()

        await update.message.reply_text(
            f"✅ Caption set for {MANAGED_CHANNELS[channel_id]['name']}!\n\n"
            f"Caption: {caption}\n\n"
            f"Note: Random emoji will be added automatically!")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def clear_channel_caption(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """Clear channel-specific caption"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/clear_channel_caption CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in CHANNEL_DEFAULT_CAPTIONS:
            del CHANNEL_DEFAULT_CAPTIONS[channel_id]
            save_data()
            await update.message.reply_text("✅ Channel caption cleared")
        else:
            await update.message.reply_text("❌ No caption set for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


# ========== PROMO IMAGE COMMANDS ==========
async def set_promo1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set promo image 1 for channel (posts at 5th, 15th, 25th...)"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_promo1 CHANNEL_ID`\n\n"
            "Then send the promo image/video (with optional caption)\n"
            "This will post at positions: 5, 15, 25, 35...",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['setting_promo1'] = channel_id
        await update.message.reply_text(
            f"✅ Ready to set Promo 1 for {MANAGED_CHANNELS[channel_id]['name']}\n\n"
            f"Send the promo image/video now (with optional caption)",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def set_promo2_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set promo image 2 for channel (posts at 10th, 20th, 30th...)"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_promo2 CHANNEL_ID`\n\n"
            "Then send the promo image/video (with optional caption)\n"
            "This will post at positions: 10, 20, 30, 40...",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['setting_promo2'] = channel_id
        await update.message.reply_text(
            f"✅ Ready to set Promo 2 for {MANAGED_CHANNELS[channel_id]['name']}\n\n"
            f"Send the promo image/video now (with optional caption)",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def view_promos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all promo images"""
    if await ignore_non_admin(update, context):
        return

    if not PROMO_IMAGES:
        await update.message.reply_text("No promo images set")
        return

    text = "🎯 *Promo Images Setup*\n\n"

    for channel_id, promos in PROMO_IMAGES.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        text += f"📢 {channel_name}\n"

        if 'promo1' in promos:
            promo_type = promos['promo1'].get('type', 'photo')
            text += f"✅ Promo 1: Set ({promo_type}) - 5th, 15th, 25th...\n"
        else:
            text += f"❌ Promo 1: Not set\n"

        if 'promo2' in promos:
            promo_type = promos['promo2'].get('type', 'photo')
            text += f"✅ Promo 2: Set ({promo_type}) - 10th, 20th, 30th...\n"
        else:
            text += f"❌ Promo 2: Not set\n"

        text += "\n"

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_promo1_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear promo image 1"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/clear_promo1 CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in PROMO_IMAGES and 'promo1' in PROMO_IMAGES[channel_id]:
            del PROMO_IMAGES[channel_id]['promo1']
            if not PROMO_IMAGES[channel_id]:
                del PROMO_IMAGES[channel_id]
            save_data()
            await update.message.reply_text("✅ Promo 1 cleared")
        else:
            await update.message.reply_text("❌ No promo 1 set for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def clear_promo2_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear promo image 2"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/clear_promo2 CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in PROMO_IMAGES and 'promo2' in PROMO_IMAGES[channel_id]:
            del PROMO_IMAGES[channel_id]['promo2']
            if not PROMO_IMAGES[channel_id]:
                del PROMO_IMAGES[channel_id]
            save_data()
            await update.message.reply_text("✅ Promo 2 cleared")
        else:
            await update.message.reply_text("❌ No promo 2 set for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def enable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable auto-posting for a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/enable_autopost CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        AUTO_POST_ENABLED[channel_id] = True

        # Initialize post counter if not exists
        if channel_id not in POST_COUNTER:
            POST_COUNTER[channel_id] = 0

        save_data()

        # Check content availability
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'media')
        if content_type == 'links':
            content_count = len(CHANNEL_LINKS.get(channel_id, []))
            content_label = "links"
        else:
            content_count = len(CHANNEL_MEDIA_QUEUE.get(channel_id, []))
            if content_count == 0:
                content_count = len(CHANNEL_SPECIFIC_IMAGES.get(channel_id, []))
            if content_count == 0:
                content_count = len(UPLOADED_IMAGES)
            content_label = "media"

        if content_count == 0:
            await update.message.reply_text(
                f"⚠️ Auto-post enabled but no {content_label} found!\n\n"
                f"Upload {content_label} first:\n"
                f"• /upload_media for images+videos\n"
                f"• /upload_links for links")
            return

        # Schedule first post
        first_delay = random.randint(1, 3)  # Start quickly
        scheduler.add_job(
            auto_post_job,
            'date',
            run_date=datetime.now() + timedelta(minutes=first_delay),
            args=[context.bot, channel_id],
            id=f'autopost_{channel_id}',
            replace_existing=True)

        await update.message.reply_text(
            f"✅ Auto-post enabled for {MANAGED_CHANNELS[channel_id]['name']}!\n\n"
            f"📦 Content: {content_count} {content_label}\n"
            f"⏰ Intervals: 12-28 minutes (random)\n"
            f"🎯 Promo pattern active\n"
            f"🎨 Random emoji active ({len(CAPTION_EMOJIS)} emojis)\n"
            f"🚀 Starting in {first_delay} minutes",
            parse_mode='Markdown')

        logger.info(f"✅ Auto-post enabled for {channel_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def disable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable auto-posting for a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/disable_autopost CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id in AUTO_POST_ENABLED:
            AUTO_POST_ENABLED[channel_id] = False
            save_data()

            # Remove scheduler job
            try:
                scheduler.remove_job(f'autopost_{channel_id}')
            except:
                pass

            await update.message.reply_text(
                f"✅ Auto-post disabled for {MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')}")
        else:
            await update.message.reply_text("❌ Auto-post not enabled for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def autopost_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show auto-post status"""
    if await ignore_non_admin(update, context):
        return

    if not AUTO_POST_ENABLED:
        await update.message.reply_text("No auto-posts enabled")
        return

    text = "🤖 *Auto-Post Status*\n\n"
    for channel_id, enabled in AUTO_POST_ENABLED.items():
        if enabled:
            channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
            post_count = POST_COUNTER.get(channel_id, 0)
            content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'media')

            # Check promo status
            has_promo1 = channel_id in PROMO_IMAGES and 'promo1' in PROMO_IMAGES[channel_id]
            has_promo2 = channel_id in PROMO_IMAGES and 'promo2' in PROMO_IMAGES[channel_id]

            # Count content
            if content_type == 'links':
                content_count = len(CHANNEL_LINKS.get(channel_id, []))
                current_idx = CHANNEL_LINK_INDEX.get(channel_id, 0)
            else:
                content_count = len(CHANNEL_MEDIA_QUEUE.get(channel_id, []))
                if content_count == 0:
                    content_count = len(CHANNEL_SPECIFIC_IMAGES.get(channel_id, []))
                current_idx = CURRENT_IMAGE_INDEX.get(channel_id, 0)

            text += f"✅ {channel_name}\n"
            text += f"   Type: {content_type}\n"
            text += f"   Content: {content_count}\n"
            text += f"   Posts Made: {post_count}\n"
            text += f"   Current Index: {current_idx}\n"
            text += f"   Interval: 12-28 mins (random)\n"
            text += f"   Promo 1: {'✅' if has_promo1 else '❌'}\n"
            text += f"   Promo 2: {'✅' if has_promo2 else '❌'}\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')


async def auto_post_job(bot, channel_id: int):
    """
    Auto-posting job with:
    1. Support for media queue (images + videos in sequence)
    2. Support for links posting
    3. Promo pattern (5th=promo1, 10th=promo2)
    4. Random intervals (12-28 minutes)
    5. Loop back when content is exhausted
    """
    try:
        if not AUTO_POST_ENABLED.get(channel_id):
            return

        # Initialize post counter if needed
        if channel_id not in POST_COUNTER:
            POST_COUNTER[channel_id] = 0

        # Increment counter
        POST_COUNTER[channel_id] += 1
        current_position = POST_COUNTER[channel_id]

        logger.info(f"🎯 Auto-post #{current_position} for channel {channel_id}")

        # Determine channel content type
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'media')

        # ========== LINKS CHANNEL ==========
        if content_type == 'links':
            if channel_id not in CHANNEL_LINKS or not CHANNEL_LINKS[channel_id]:
                logger.warning(f"No links available for channel {channel_id}")
                # Schedule retry
                scheduler.add_job(
                    auto_post_job,
                    'date',
                    run_date=datetime.now() + timedelta(minutes=30),
                    args=[bot, channel_id],
                    id=f'autopost_{channel_id}',
                    replace_existing=True)
                return

            # Get current link index
            if channel_id not in CHANNEL_LINK_INDEX:
                CHANNEL_LINK_INDEX[channel_id] = 0

            idx = CHANNEL_LINK_INDEX[channel_id]
            links = CHANNEL_LINKS[channel_id]

            # Get link and move to next (loop when exhausted)
            link = links[idx]
            CHANNEL_LINK_INDEX[channel_id] = (idx + 1) % len(links)

            if CHANNEL_LINK_INDEX[channel_id] == 0:
                logger.info(f"🔄 Links looped for channel {channel_id}")

            # Post link without preview
            await bot.send_message(
                chat_id=channel_id,
                text=link,
                disable_web_page_preview=True
            )

            logger.info(f"✅ Posted link #{current_position} to channel {channel_id}")
            save_data()

        # ========== MEDIA CHANNEL (Images + Videos) ==========
        else:
            # Check for promo pattern first
            position_mod = current_position % 10
            media_to_post = None
            is_promo = False

            # Promo Pattern Check
            if position_mod == 5:  # 5th, 15th, 25th...
                if channel_id in PROMO_IMAGES and 'promo1' in PROMO_IMAGES[channel_id]:
                    media_to_post = PROMO_IMAGES[channel_id]['promo1']
                    is_promo = True
                    logger.info(f"🎯 Using PROMO 1 at position {current_position}")
            elif position_mod == 0:  # 10th, 20th, 30th...
                if channel_id in PROMO_IMAGES and 'promo2' in PROMO_IMAGES[channel_id]:
                    media_to_post = PROMO_IMAGES[channel_id]['promo2']
                    is_promo = True
                    logger.info(f"🎯 Using PROMO 2 at position {current_position}")

            # If not promo, get from media queue
            if not media_to_post:
                # Try new media queue first
                if channel_id in CHANNEL_MEDIA_QUEUE and CHANNEL_MEDIA_QUEUE[channel_id]:
                    media_list = CHANNEL_MEDIA_QUEUE[channel_id]

                    # Initialize index if needed
                    if channel_id not in CURRENT_IMAGE_INDEX:
                        CURRENT_IMAGE_INDEX[channel_id] = 0

                    idx = CURRENT_IMAGE_INDEX[channel_id]
                    media_to_post = media_list[idx]

                    # Move to next (loop when exhausted)
                    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(media_list)

                    if CURRENT_IMAGE_INDEX[channel_id] == 0:
                        logger.info(f"🔄 Media queue looped for channel {channel_id}")

                # Fall back to old image format
                elif channel_id in CHANNEL_SPECIFIC_IMAGES and CHANNEL_SPECIFIC_IMAGES[channel_id]:
                    images = CHANNEL_SPECIFIC_IMAGES[channel_id]

                    if channel_id not in CURRENT_IMAGE_INDEX:
                        CURRENT_IMAGE_INDEX[channel_id] = 0

                    idx = CURRENT_IMAGE_INDEX[channel_id]
                    img = images[idx]

                    media_to_post = {
                        'type': 'photo',
                        'file_id': img['file_id'] if isinstance(img, dict) else img,
                        'caption': img.get('caption', '') if isinstance(img, dict) else ''
                    }

                    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(images)

                # Fall back to global images
                elif UPLOADED_IMAGES:
                    if channel_id not in CURRENT_IMAGE_INDEX:
                        CURRENT_IMAGE_INDEX[channel_id] = 0

                    idx = CURRENT_IMAGE_INDEX[channel_id]
                    img = UPLOADED_IMAGES[idx]

                    media_to_post = {
                        'type': 'photo',
                        'file_id': img['file_id'] if isinstance(img, dict) else img,
                        'caption': img.get('caption', '') if isinstance(img, dict) else ''
                    }

                    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(UPLOADED_IMAGES)

                else:
                    logger.warning(f"No media available for channel {channel_id}")
                    # Schedule retry
                    scheduler.add_job(
                        auto_post_job,
                        'date',
                        run_date=datetime.now() + timedelta(minutes=30),
                        args=[bot, channel_id],
                        id=f'autopost_{channel_id}',
                        replace_existing=True)
                    return

            # Select random emoji
            random_emoji = random.choice(CAPTION_EMOJIS)

            # Determine caption
            base_caption = ""
            if media_to_post.get('caption'):
                base_caption = media_to_post['caption']
            elif channel_id in CHANNEL_DEFAULT_CAPTIONS:
                base_caption = CHANNEL_DEFAULT_CAPTIONS[channel_id]
            elif DEFAULT_CAPTION:
                base_caption = DEFAULT_CAPTION

            # Add random emoji
            if base_caption:
                caption_to_use = f"{random_emoji} {base_caption}"
            else:
                caption_to_use = random_emoji

            # Get file_id and type
            file_id = media_to_post['file_id']
            media_type = media_to_post.get('type', 'photo')

            # Post based on media type
            if media_type == 'video':
                await bot.send_video(
                    chat_id=channel_id,
                    video=file_id,
                    caption=caption_to_use
                )
            else:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=file_id,
                    caption=caption_to_use
                )

            promo_label = " (PROMO)" if is_promo else ""
            logger.info(f"✅ Posted {media_type} #{current_position}{promo_label} to channel {channel_id}")

        save_data()

        # Schedule next post with random interval
        next_delay_minutes = random.randint(12, 28)
        next_run_time = datetime.now() + timedelta(minutes=next_delay_minutes)

        scheduler.add_job(
            auto_post_job,
            'date',
            run_date=next_run_time,
            args=[bot, channel_id],
            id=f'autopost_{channel_id}',
            replace_existing=True)

        logger.info(f"⏰ Next post in {next_delay_minutes} minutes")

    except Exception as e:
        logger.error(f"❌ Auto-post failed for channel {channel_id}: {e}")

        # Retry in 20 minutes on error
        try:
            retry_time = datetime.now() + timedelta(minutes=20)
            scheduler.add_job(
                auto_post_job,
                'date',
                run_date=retry_time,
                args=[bot, channel_id],
                id=f'autopost_{channel_id}',
                replace_existing=True)
        except:
            pass


async def export_users_report(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """Export user database"""
    if await ignore_non_admin(update, context):
        return

    if not USER_DATABASE:
        await update.message.reply_text("No user data to export")
        return

    # Create CSV
    csv_text = "User ID,First Name,Last Name,Username,Channels\n"
    for user_id, data in USER_DATABASE.items():
        channels = ', '.join([ch['channel_name'] for ch in data['channels'].values()])
        csv_text += f"{user_id},{data['first_name']},{data['last_name']},{data['username']},{channels}\n"

    # Send as file
    file = BytesIO(csv_text.encode('utf-8'))
    file.name = f"users_{datetime.now().strftime('%Y%m%d')}.csv"

    await update.message.reply_document(
        document=file,
        filename=file.name,
        caption=f"📊 User Database Export\n\nTotal Users: {len(USER_DATABASE)}")


async def user_stats_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    if await ignore_non_admin(update, context):
        return

    total_users = len(USER_DATABASE)
    approved_count = sum(1 for user in USER_DATABASE.values()
                        if any(ch['status'] == 'approved' for ch in user['channels'].values()))

    text = (
        f"👥 *User Statistics*\n\n"
        f"Total Users: {total_users}\n"
        f"Approved: {approved_count}\n"
        f"Pending: {len(PENDING_VERIFICATIONS)}\n"
        f"Blocked: {len(BLOCKED_USERS)}"
    )

    await update.message.reply_text(text, parse_mode='Markdown')


async def import_users_to_channel(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Import users (placeholder)"""
    if await ignore_non_admin(update, context):
        return

    await update.message.reply_text("Import feature coming soon")


async def view_unauthorized_attempts(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """View unauthorized access attempts"""
    if await ignore_non_admin(update, context):
        return

    if not UNAUTHORIZED_ATTEMPTS:
        await update.message.reply_text("No unauthorized attempts")
        return

    text = "🚨 *Unauthorized Attempts*\n\n"
    for attempt in UNAUTHORIZED_ATTEMPTS[-10:]:  # Last 10
        text += (f"User: {attempt['first_name']}\n"
                f"ID: `{attempt['user_id']}`\n"
                f"Command: {attempt['command']}\n"
                f"Time: {attempt['timestamp'].strftime('%Y-%m-%d %H:%M')}\n\n")

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_unauthorized_log(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Clear unauthorized attempts log"""
    if await ignore_non_admin(update, context):
        return

    UNAUTHORIZED_ATTEMPTS.clear()
    await update.message.reply_text("✅ Unauthorized log cleared")


async def send_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick send media/text to channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "Send to channel:\n\n"
        text += "Usage: /send_to_channel CHANNEL_ID\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            text += f"{data['name']}: {channel_id}\n"
        text += "\nThen send your media/text"

        await update.message.reply_text(text)
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("Channel not managed")
            return

        context.user_data['quick_send_channel'] = channel_id
        context.user_data['quick_send_mode'] = True

        await update.message.reply_text(
            f"✅ Quick Send Mode: {MANAGED_CHANNELS[channel_id]['name']}\n\n"
            f"Send your media or text now.\n"
            f"Use /cancel to stop")

    except ValueError:
        await update.message.reply_text("Invalid channel ID")


async def clear_channel_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all media from a channel"""
    if await ignore_non_admin(update, context):
        return

    if not context.args:
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "Clear channel media:\n\n"
        text += "Usage: /clear_channel_media CHANNEL_ID MESSAGE_COUNT\n\n"
        text += "Example: /clear_channel_media -1001234567890 50\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            text += f"{data['name']}: {channel_id}\n"

        await update.message.reply_text(text)
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /clear_channel_media CHANNEL_ID MESSAGE_COUNT\n"
            "Example: /clear_channel_media -1001234567890 50")
        return

    try:
        channel_id = int(context.args[0])
        message_count = int(context.args[1])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("Channel not managed")
            return

        if message_count > 100:
            await update.message.reply_text("Max 100 messages at a time")
            return

        await update.message.reply_text(
            "⚠️ To delete messages, I need message IDs.\n"
            "This feature requires message tracking.\n"
            "Use /clear_media to clear bot's media storage instead.")

    except ValueError:
        await update.message.reply_text("Invalid channel ID or message count")
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    if await ignore_non_admin(update, context):
        return

    context.user_data.clear()
    await update.message.reply_text("✅ All operations cancelled")


async def view_recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent auto-approvals and auto-rejections"""
    if await ignore_non_admin(update, context):
        return

    if not RECENT_ACTIVITY:
        await update.message.reply_text("No recent activity")
        return

    # Group by type
    approved = [a for a in RECENT_ACTIVITY if a['type'] == 'auto_approved']
    rejected = [a for a in RECENT_ACTIVITY if a['type'] == 'auto_rejected']

    text = "📊 Recent Activity\n\n"

    # Show summary
    text += f"✅ Auto-Approved: {len(approved)}\n"
    text += f"❌ Auto-Rejected: {len(rejected)}\n"
    text += f"⚠️ Pending Captcha: {len(PENDING_VERIFICATIONS)}\n\n"

    # Show last 10 approved
    if approved:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "✅ Recently Approved:\n\n"
        for activity in approved[-10:]:
            text += f"• {activity['user_name']}\n"
            text += f"  @{activity['username']}\n"
            text += f"  Channel: {activity['channel']}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    # Show last 5 rejected
    if rejected:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "❌ Recently Rejected:\n\n"
        for activity in rejected[-5:]:
            text += f"• {activity['user_name']}\n"
            text += f"  Reason: {activity['reason']}\n"
            text += f"  Fallback: {'✅' if activity.get('fallback_sent') else '❌'}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    await update.message.reply_text(text)


async def clear_recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear recent activity log"""
    if await ignore_non_admin(update, context):
        return

    count = len(RECENT_ACTIVITY)
    RECENT_ACTIVITY.clear()

    await update.message.reply_text(f"✅ Cleared {count} activity records")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    if await ignore_non_admin(update, context):
        return

    bulk_enabled = sum(1 for v in BULK_APPROVAL_MODE.values() if v)
    active_autoposts = sum(1 for v in AUTO_POST_ENABLED.values() if v)

    # Count recent activity
    recent_approved = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_approved')
    recent_rejected = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_rejected')

    # Count content
    total_media = sum(len(m) for m in CHANNEL_MEDIA_QUEUE.values())
    total_links = sum(len(l) for l in CHANNEL_LINKS.values())
    promo_count = sum(1 for promos in PROMO_IMAGES.values() if promos)

    text = (f"📊 Statistics\n\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"🛡️ Smart Mode: {len(MANAGED_CHANNELS) - bulk_enabled}\n"
            f"🔄 Bulk Mode: {bulk_enabled}\n"
            f"⏳ Pending: {len(PENDING_VERIFICATIONS)}\n"
            f"✅ Recent Approved: {recent_approved}\n"
            f"❌ Recent Rejected: {recent_rejected}\n"
            f"🚫 Blocked: {len(BLOCKED_USERS)}\n\n"
            f"📂 Media Queue: {total_media}\n"
            f"🔗 Links: {total_links}\n"
            f"📷 Old Images: {len(UPLOADED_IMAGES)}\n"
            f"🎯 Promo Channels: {promo_count}\n"
            f"🎨 Emoji Pool: {len(CAPTION_EMOJIS)} emojis\n"
            f"⏰ Posting: 12-28 mins (random)\n"
            f"🤖 Auto-Posts: {active_autoposts} active\n"
            f"👥 Total Users: {len(USER_DATABASE)}\n"
            f"🚨 Unauthorized: {len(UNAUTHORIZED_ATTEMPTS)}\n\n"
            f"🌐 Fallback: {GLOBAL_FALLBACK_CHANNEL or 'Not set'}\n\n"
            f"Use /recent_activity for details\n\n"
            f"Status: Online 24/7 ✅")
    await update.message.reply_text(text)


async def handle_forwarded_message(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages"""
    if await ignore_non_admin(update, context):
        return

    await update.message.reply_text("Forwarded message detected")


async def handle_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk file uploads"""
    if await ignore_non_admin(update, context):
        return

    # Check if in links upload mode
    if context.user_data.get('links_upload_mode'):
        await handle_links_file(update, context)
        return

    await update.message.reply_text("Bulk file processing coming soon")


async def handle_links_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle links from TXT files"""
    if await ignore_non_admin(update, context):
        return

    if not context.user_data.get('links_upload_mode'):
        return

    channel_id = context.user_data.get('links_upload_channel')
    if not channel_id:
        return

    message = update.message

    # Handle TXT file
    if message.document:
        if message.document.file_name and message.document.file_name.endswith('.txt'):
            try:
                file = await context.bot.get_file(message.document.file_id)
                file_bytes = await file.download_as_bytearray()
                content = file_bytes.decode('utf-8')

                # Extract links (one per line)
                lines = content.strip().split('\n')

                if channel_id not in CHANNEL_LINKS:
                    CHANNEL_LINKS[channel_id] = []

                links_added = 0
                for line in lines:
                    link = line.strip()
                    if link and (link.startswith('http://') or link.startswith('https://')):
                        CHANNEL_LINKS[channel_id].append(link)
                        links_added += 1

                save_data()

                await update.message.reply_text(
                    f"✅ Added {links_added} links from file!\n"
                    f"Total links: {len(CHANNEL_LINKS[channel_id])}")

            except Exception as e:
                await update.message.reply_text(f"❌ Error reading file: {e}")


async def handle_verification_code(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Handle verification code from user"""
    pass


async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image AND video uploads - SILENT mode with sequence preservation"""
    if await ignore_non_admin(update, context):
        return

    message = update.message

    # Determine media type and get file_id
    media_type = None
    file_id = None
    caption = message.caption or ""

    if message.photo:
        media_type = 'photo'
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = 'video'
        file_id = message.video.file_id
    elif message.document:
        # Check if it's a video sent as document
        if message.document.mime_type and message.document.mime_type.startswith('video/'):
            media_type = 'video'
            file_id = message.document.file_id
        # Check if it's an image sent as document
        elif message.document.mime_type and message.document.mime_type.startswith('image/'):
            media_type = 'photo'
            file_id = message.document.file_id

    if not media_type or not file_id:
        return  # Not a media file we handle

    # Check if setting promo image
    if context.user_data.get('setting_promo1'):
        channel_id = context.user_data['setting_promo1']

        if channel_id not in PROMO_IMAGES:
            PROMO_IMAGES[channel_id] = {}

        PROMO_IMAGES[channel_id]['promo1'] = {
            'file_id': file_id,
            'type': media_type,
            'caption': caption
        }

        save_data()
        context.user_data['setting_promo1'] = None

        await update.message.reply_text(
            f"✅ Promo 1 ({media_type}) set for {MANAGED_CHANNELS[channel_id]['name']}!",
            parse_mode='Markdown')
        return

    if context.user_data.get('setting_promo2'):
        channel_id = context.user_data['setting_promo2']

        if channel_id not in PROMO_IMAGES:
            PROMO_IMAGES[channel_id] = {}

        PROMO_IMAGES[channel_id]['promo2'] = {
            'file_id': file_id,
            'type': media_type,
            'caption': caption
        }

        save_data()
        context.user_data['setting_promo2'] = None

        await update.message.reply_text(
            f"✅ Promo 2 ({media_type}) set for {MANAGED_CHANNELS[channel_id]['name']}!",
            parse_mode='Markdown')
        return

    # NEW: Handle media upload mode (images + videos in sequence)
    if context.user_data.get('media_upload_mode'):
        channel_id = context.user_data.get('media_upload_channel')

        if channel_id:
            if channel_id not in CHANNEL_MEDIA_QUEUE:
                CHANNEL_MEDIA_QUEUE[channel_id] = []

            # Add to queue (maintains upload order!)
            CHANNEL_MEDIA_QUEUE[channel_id].append({
                'type': media_type,
                'file_id': file_id,
                'caption': caption
            })

            save_data()

            # Silent - only log
            count = len(CHANNEL_MEDIA_QUEUE[channel_id])
            logger.info(f"✅ {media_type} added to channel {channel_id}. Total: {count}")
        return

    # OLD: Handle old uploading mode (backward compatibility)
    if context.user_data.get('uploading_mode'):
        if media_type == 'photo':
            image_data = {
                'file_id': file_id,
                'caption': caption
            }

            if context.user_data.get('uploading_for_channel'):
                channel_id = context.user_data['uploading_for_channel']
                if channel_id not in CHANNEL_SPECIFIC_IMAGES:
                    CHANNEL_SPECIFIC_IMAGES[channel_id] = []
                CHANNEL_SPECIFIC_IMAGES[channel_id].append(image_data)
                logger.info(f"✅ Image added to channel {channel_id}")
            else:
                UPLOADED_IMAGES.append(image_data)
                logger.info(f"✅ Global image uploaded. Total: {len(UPLOADED_IMAGES)}")

            save_data()
        return

    # Handle quick send mode
    if context.user_data.get('quick_send_mode'):
        channel_id = context.user_data.get('quick_send_channel')

        try:
            if media_type == 'photo':
                await context.bot.send_photo(channel_id, file_id, caption=caption)
            elif media_type == 'video':
                await context.bot.send_video(channel_id, file_id, caption=caption)

            await update.message.reply_text(
                f"✅ Sent to {MANAGED_CHANNELS[channel_id]['name']}\n\n"
                f"Send more or use /cancel to stop")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)}")
        return


async def handle_text_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    if await ignore_non_admin(update, context):
        return

    # Check if in links upload mode
    if context.user_data.get('links_upload_mode'):
        channel_id = context.user_data.get('links_upload_channel')
        if channel_id and update.message.text:
            text = update.message.text.strip()

            # Check if it's a link
            if text.startswith('http://') or text.startswith('https://'):
                if channel_id not in CHANNEL_LINKS:
                    CHANNEL_LINKS[channel_id] = []

                CHANNEL_LINKS[channel_id].append(text)
                save_data()

                # Silent - only log
                logger.info(f"✅ Link added to channel {channel_id}. Total: {len(CHANNEL_LINKS[channel_id])}")
        return

    # Handle posting mode
    if context.user_data.get('posting_mode'):
        await handle_content_posting(update, context)
        return

    # Handle quick send mode
    if context.user_data.get('quick_send_mode'):
        channel_id = context.user_data.get('quick_send_channel')
        if channel_id and update.message.text:
            try:
                await context.bot.send_message(channel_id, update.message.text)
                await update.message.reply_text(
                    f"✅ Sent to {MANAGED_CHANNELS[channel_id]['name']}\n\n"
                    f"Send more or use /cancel to stop")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed: {str(e)}")


async def handle_content_posting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle content for posting mode"""
    if await ignore_non_admin(update, context):
        return

    message = update.message
    content_type = 'text'

    if message.photo:
        content_type = 'photo'
    elif message.video:
        content_type = 'video'
    elif message.document:
        content_type = 'document'

    PENDING_POSTS[ADMIN_ID] = {'message': message, 'type': content_type}

    keyboard = []
    for channel_id, data in MANAGED_CHANNELS.items():
        keyboard.append([
            InlineKeyboardButton(f"📢 {data['name']}",
                                 callback_data=f"post_{channel_id}")
        ])
    keyboard.append(
        [InlineKeyboardButton("🔄 ALL CHANNELS", callback_data="post_all")])
    keyboard.append(
        [InlineKeyboardButton("❌ Cancel", callback_data="post_cancel")])

    await update.message.reply_text(
        "🎯 Select Channel:",
        reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['posting_mode'] = False


async def post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle post selection callback"""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()

    if ADMIN_ID not in PENDING_POSTS:
        await query.edit_message_text("❌ No pending post")
        return

    action = query.data.split('_')[1]

    if action == "cancel":
        del PENDING_POSTS[ADMIN_ID]
        await query.edit_message_text("❌ Cancelled")
        return

    pending = PENDING_POSTS[ADMIN_ID]
    original_msg = pending['message']

    channels = [int(action)] if action != "all" else list(
        MANAGED_CHANNELS.keys())

    await query.edit_message_text("⏳ Posting...")
    success = 0
    failed = 0

    for channel_id in channels:
        try:
            if pending['type'] == 'text':
                await context.bot.send_message(channel_id, original_msg.text)
            elif pending['type'] == 'photo':
                await context.bot.send_photo(channel_id,
                                             original_msg.photo[-1].file_id,
                                             caption=original_msg.caption)
            elif pending['type'] == 'video':
                await context.bot.send_video(channel_id,
                                             original_msg.video.file_id,
                                             caption=original_msg.caption)
            elif pending['type'] == 'document':
                await context.bot.send_document(channel_id,
                                                original_msg.document.file_id,
                                                caption=original_msg.caption)
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Post failed for {channel_id}: {e}")

    del PENDING_POSTS[ADMIN_ID]

    result_text = f"✅ *Posted!*\n\nSuccess: {success}\nFailed: {failed}"
    await query.message.reply_text(result_text, parse_mode='Markdown')


async def weekly_report_job(bot):
    """Weekly report job"""
    active_autoposts = sum(1 for v in AUTO_POST_ENABLED.values() if v)
    total_media = sum(len(m) for m in CHANNEL_MEDIA_QUEUE.values())

    text = (
        f"📊 *Weekly Report*\n\n"
        f"Channels: {len(MANAGED_CHANNELS)}\n"
        f"Auto-Posts Active: {active_autoposts}\n"
        f"Media in Queue: {total_media}\n"
        f"Total Users: {len(USER_DATABASE)}\n"
        f"Blocked: {len(BLOCKED_USERS)}\n\n"
        f"Status: All systems operational ✅"
    )

    try:
        await bot.send_message(ADMIN_ID, text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Weekly report failed: {e}")


# Error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Exception: {context.error}")


def main():
    """Main function to start the bot"""
    logger.info("🚀 Starting SMART VERIFICATION BOT v2.0...")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")
    logger.info(f"✅ Storage: {STORAGE_FILE}")
    logger.info(f"✅ Random Emojis: {len(CAPTION_EMOJIS)} emojis")
    logger.info(f"✅ Random Intervals: 12-28 minutes")
    logger.info(f"✅ Media Support: Images + Videos")
    logger.info(f"✅ Links Support: Enabled")
    logger.info(f"✅ Admin Lockdown: Enabled")

    # Load saved data
    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    # Command handlers - Basic
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("removechannel", remove_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Verification commands
    app.add_handler(CommandHandler("pending_users", pending_users))
    app.add_handler(CommandHandler("approve_user", manual_approve_user))
    app.add_handler(CommandHandler("approve_all_pending", approve_all_pending))
    app.add_handler(CommandHandler("bulk_approve", bulk_approve_from_file))
    app.add_handler(CommandHandler("toggle_bulk", toggle_bulk_approval))
    app.add_handler(CommandHandler("block_user", block_user))
    app.add_handler(CommandHandler("unblock_user", unblock_user))
    app.add_handler(CommandHandler("verification_settings", verification_settings))

    # Fallback channel commands
    app.add_handler(CommandHandler("set_fallback", set_fallback_command))
    app.add_handler(CommandHandler("clear_fallback", clear_fallback_command))

    # NEW: Media upload commands
    app.add_handler(CommandHandler("upload_media", upload_media_command))
    app.add_handler(CommandHandler("done_media", done_media_command))
    app.add_handler(CommandHandler("list_media", list_media_command))
    app.add_handler(CommandHandler("clear_media", clear_media_command))

    # NEW: Links upload commands
    app.add_handler(CommandHandler("upload_links", upload_links_command))
    app.add_handler(CommandHandler("done_links", done_links_command))
    app.add_handler(CommandHandler("list_links", list_links_command))
    app.add_handler(CommandHandler("clear_links", clear_links_command))

    # NEW: Channel config commands
    app.add_handler(CommandHandler("set_channel_type", set_channel_type_command))
    app.add_handler(CommandHandler("view_config", view_channel_config_command))

    # Posting commands
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("send_to_channel", send_to_channel))
    app.add_handler(CommandHandler("clear_channel_media", clear_channel_media))

    # OLD image upload commands (backward compatibility)
    app.add_handler(CommandHandler("upload_images", upload_images_command))
    app.add_handler(CommandHandler("done_uploading", done_uploading))
    app.add_handler(CommandHandler("upload_for_channel", upload_for_channel_command))
    app.add_handler(CommandHandler("list_images", list_images))
    app.add_handler(CommandHandler("clear_images", clear_images))

    # Caption commands
    app.add_handler(CommandHandler("set_default_caption", set_default_caption))
    app.add_handler(CommandHandler("clear_default_caption", clear_default_caption))
    app.add_handler(CommandHandler("set_channel_caption", set_channel_caption))
    app.add_handler(CommandHandler("clear_channel_caption", clear_channel_caption))

    # Promo image commands
    app.add_handler(CommandHandler("set_promo1", set_promo1_command))
    app.add_handler(CommandHandler("set_promo2", set_promo2_command))
    app.add_handler(CommandHandler("view_promos", view_promos_command))
    app.add_handler(CommandHandler("clear_promo1", clear_promo1_command))
    app.add_handler(CommandHandler("clear_promo2", clear_promo2_command))

    # Auto-post commands
    app.add_handler(CommandHandler("enable_autopost", enable_autopost))
    app.add_handler(CommandHandler("disable_autopost", disable_autopost))
    app.add_handler(CommandHandler("autopost_status", autopost_status))

    # Analytics commands
    app.add_handler(CommandHandler("export_users", export_users_report))
    app.add_handler(CommandHandler("user_stats", user_stats_command))
    app.add_handler(CommandHandler("import_users", import_users_to_channel))

    # Activity commands
    app.add_handler(CommandHandler("recent_activity", view_recent_activity))
    app.add_handler(CommandHandler("clear_activity", clear_recent_activity))
    app.add_handler(CommandHandler("view_unauthorized", view_unauthorized_attempts))
    app.add_handler(CommandHandler("clear_unauthorized", clear_unauthorized_log))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(enter_code_callback, pattern="^enter_code_"))
    app.add_handler(CallbackQueryHandler(resend_code_callback, pattern="^resend_code_"))
    app.add_handler(CallbackQueryHandler(post_callback, pattern="^post_"))

    # Message handlers - ORDER MATTERS!
    app.add_handler(MessageHandler(filters.FORWARDED & ~filters.COMMAND, handle_forwarded_message))

    # Document handler for links TXT files
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, handle_bulk_file))

    # Combined media handler (photos + videos)
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, handle_media_upload))

    # Text handler (for links and other text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_content))

    # Join request handler - THE KEY COMPONENT
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # Error handler
    app.add_error_handler(error_handler)

    # Start scheduler
    scheduler.start()
    scheduler.add_job(weekly_report_job,
                      trigger=CronTrigger(day_of_week='mon', hour=9),
                      args=[app.bot],
                      id='weekly_report')

    # Re-enable auto-posting for saved channels
    for channel_id, enabled in AUTO_POST_ENABLED.items():
        if enabled:
            try:
                # Start with small random delay
                delay = random.randint(1, 5)
                scheduler.add_job(auto_post_job,
                                  'date',
                                  run_date=datetime.now() + timedelta(minutes=delay),
                                  args=[app.bot, channel_id],
                                  id=f'autopost_{channel_id}',
                                  replace_existing=True)
                logger.info(f"✅ Auto-post restored for {channel_id} (starting in {delay} min)")
            except Exception as e:
                logger.error(f"Failed to restore: {e}")

    logger.info(f"✅ Bot running - Owner: {ADMIN_ID}")
    logger.info(f"✅ Smart Verification: ENABLED")
    logger.info(f"✅ Fallback Channel: {GLOBAL_FALLBACK_CHANNEL or 'Not set'}")
    logger.info(f"✅ Loaded: {len(MANAGED_CHANNELS)} channels")
    logger.info(f"✅ Media Queues: {sum(len(m) for m in CHANNEL_MEDIA_QUEUE.values())} items")
    logger.info(f"✅ Links: {sum(len(l) for l in CHANNEL_LINKS.values())} items")

    # Railway fix: Drop pending updates on restart
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
