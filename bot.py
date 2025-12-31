import os
import logging
from datetime import datetime
import random
import string
import re
import asyncio
import json
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Poll
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatJoinRequestHandler, ContextTypes, filters
from telegram.constants import ChatMemberStatus
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import PyPDF2
import openpyxl

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

# NEW: Storage system
IMAGE_STORAGE_CHANNEL = None
VIDEO_STORAGE_CHANNEL = None
DUMMY_CHANNEL = None

STORAGE_IMAGES = []  # File IDs from image storage
STORAGE_VIDEOS = []  # File IDs from video storage (can include images)
STORAGE_LINKS = []   # Links from uploaded file

# Channel configuration
CHANNEL_CONFIG = {}  # {channel_id: {type, interval, caption, enabled, polls, poll_frequency}}
CHANNEL_PAUSE_STATUS = {}  # {channel_id: bool}
CHANNEL_POST_COUNT = {}  # {channel_id: count}

USER_DATABASE = {}
USER_ACTIVITY_LOG = []
RECENT_ACTIVITY = []
UNAUTHORIZED_ATTEMPTS = []

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Storage
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
            'channel_config': CHANNEL_CONFIG,
            'channel_pause_status': CHANNEL_PAUSE_STATUS,
            'channel_post_count': CHANNEL_POST_COUNT,
            'storage_images': STORAGE_IMAGES,
            'storage_videos': STORAGE_VIDEOS,
            'storage_links': STORAGE_LINKS,
            'image_storage_channel': IMAGE_STORAGE_CHANNEL,
            'video_storage_channel': VIDEO_STORAGE_CHANNEL,
            'dummy_channel': DUMMY_CHANNEL,
            'bulk_approval_mode': BULK_APPROVAL_MODE,
            'blocked_users': list(BLOCKED_USERS),
            'user_database': USER_DATABASE
        }
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("✅ Data saved")
    except Exception as e:
        logger.error(f"Save failed: {e}")


def load_data():
    """Load all bot data from file"""
    global MANAGED_CHANNELS, CHANNEL_CONFIG, CHANNEL_PAUSE_STATUS, CHANNEL_POST_COUNT
    global STORAGE_IMAGES, STORAGE_VIDEOS, STORAGE_LINKS
    global IMAGE_STORAGE_CHANNEL, VIDEO_STORAGE_CHANNEL, DUMMY_CHANNEL
    global BULK_APPROVAL_MODE, BLOCKED_USERS, USER_DATABASE

    try:
        if os.path.exists(STORAGE_FILE):
            with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            MANAGED_CHANNELS = data.get('managed_channels', {})
            CHANNEL_CONFIG = data.get('channel_config', {})
            CHANNEL_PAUSE_STATUS = data.get('channel_pause_status', {})
            CHANNEL_POST_COUNT = data.get('channel_post_count', {})
            STORAGE_IMAGES = data.get('storage_images', [])
            STORAGE_VIDEOS = data.get('storage_videos', [])
            STORAGE_LINKS = data.get('storage_links', [])
            IMAGE_STORAGE_CHANNEL = data.get('image_storage_channel')
            VIDEO_STORAGE_CHANNEL = data.get('video_storage_channel')
            DUMMY_CHANNEL = data.get('dummy_channel')
            BULK_APPROVAL_MODE = data.get('bulk_approval_mode', {})
            BLOCKED_USERS = set(data.get('blocked_users', []))
            USER_DATABASE = data.get('user_database', {})

            # Convert string keys to int
            MANAGED_CHANNELS = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in MANAGED_CHANNELS.items()
            }
            CHANNEL_CONFIG = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CHANNEL_CONFIG.items()
            }
            CHANNEL_PAUSE_STATUS = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CHANNEL_PAUSE_STATUS.items()
            }
            CHANNEL_POST_COUNT = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in CHANNEL_POST_COUNT.items()
            }
            BULK_APPROVAL_MODE = {
                int(k) if str(k).lstrip('-').isdigit() else k: v
                for k, v in BULK_APPROVAL_MODE.items()
            }

            logger.info(
                f"✅ Loaded: {len(MANAGED_CHANNELS)} channels, {len(STORAGE_IMAGES)} images, {len(STORAGE_LINKS)} links"
            )
        else:
            logger.info("No saved data")
    except Exception as e:
        logger.error(f"Load failed: {e}")


def is_verified(user_id: int) -> bool:
    return user_id in VERIFIED_USERS or user_id == ADMIN_ID


async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
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
    """Enhanced user legitimacy checker with detailed scoring"""
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
    """Track user activity in database"""
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


async def owner_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is the owner"""
    try:
        if not update.effective_user or update.effective_user.id != ADMIN_ID:
            if update.effective_user:
                await alert_owner_unauthorized_access(
                    context, update.effective_user.id,
                    update.effective_user.username or "None",
                    update.effective_user.first_name or "Unknown",
                    update.message.text if update.message else "callback")
            if update.message:
                await update.message.reply_text("❌ Unauthorized")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ Owner check error: {e}")
        return False


# ========== SMART JOIN REQUEST HANDLER WITH DUMMY REDIRECT ==========
async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Smart join request handler with dummy channel redirect"""
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

    # Auto-approve legitimate users
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

    # Redirect suspicious users to dummy channel
    if not legitimacy['legitimate'] and legitimacy['score'] == 0:
        try:
            await request.decline()

            # NEW: Redirect to dummy channel
            if DUMMY_CHANNEL:
                try:
                    invite_link = await context.bot.create_chat_invite_link(
                        DUMMY_CHANNEL,
                        member_limit=1
                    )
                    
                    await context.bot.send_message(
                        user.id,
                        f"⚠️ Your request was not approved.\n\n"
                        f"Please join our welcome channel first:\n"
                        f"{invite_link.invite_link}\n\n"
                        f"Follow the instructions there to get verified!",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send dummy channel invite: {e}")

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

            logger.info(f"❌ Auto-rejected suspicious user: {user.id} → redirected to dummy")
            return
        except Exception as e:
            logger.error(f"Auto-rejection failed: {e}")

    # Captcha for borderline cases
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
        reply_markup=InlineKeyboardMarkup(keyboard))

    logger.info(f"⚠️ Sent verification request for user: {user.id}")


async def enter_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        request = verification.get('request')
        if request:
            await request.approve()
        else:
            logger.warning(f"No request object found for user {user_id}")

        track_user_activity(user_id, chat_id, 'approved', {
            'first_name': USER_DATABASE.get(user_id, {}).get('first_name', 'Unknown')
        })

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


# ========== STORAGE MANAGEMENT ==========
async def set_image_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set image storage channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_image_storage CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        global IMAGE_STORAGE_CHANNEL
        channel_id = int(context.args[0])
        
        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        IMAGE_STORAGE_CHANNEL = channel_id
        save_data()

        await update.message.reply_text(
            f"✅ Image storage set!\n\n"
            f"Channel ID: `{channel_id}`\n"
            f"Upload images there, then use /reload_storage",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def set_video_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set video storage channel (can contain videos + images)"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_video_storage CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        global VIDEO_STORAGE_CHANNEL
        channel_id = int(context.args[0])
        
        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        VIDEO_STORAGE_CHANNEL = channel_id
        save_data()

        await update.message.reply_text(
            f"✅ Video storage set!\n\n"
            f"Channel ID: `{channel_id}`\n"
            f"Upload videos/images there, then use /reload_storage",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def set_dummy_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set dummy redirect channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_dummy_channel CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        global DUMMY_CHANNEL
        channel_id = int(context.args[0])
        
        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        DUMMY_CHANNEL = channel_id
        save_data()

        await update.message.reply_text(
            f"✅ Dummy channel set!\n\n"
            f"Channel ID: `{channel_id}`\n"
            f"Rejected users will be redirected here",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def reload_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reload media from storage channels"""
    if not await owner_only_check(update, context):
        return

    await update.message.reply_text("⏳ Loading media from storage channels...")

    global STORAGE_IMAGES, STORAGE_VIDEOS
    STORAGE_IMAGES.clear()
    STORAGE_VIDEOS.clear()

    images_count = 0
    videos_count = 0

    # Load from image storage
    if IMAGE_STORAGE_CHANNEL:
        try:
            async for message in context.bot.get_chat_history(IMAGE_STORAGE_CHANNEL, limit=1000):
                if message.photo:
                    STORAGE_IMAGES.append({
                        'file_id': message.photo[-1].file_id,
                        'caption': message.caption or ''
                    })
                    images_count += 1
        except Exception as e:
            logger.error(f"Failed to load from image storage: {e}")

    # Load from video storage (videos + images)
    if VIDEO_STORAGE_CHANNEL:
        try:
            async for message in context.bot.get_chat_history(VIDEO_STORAGE_CHANNEL, limit=1000):
                if message.video:
                    STORAGE_VIDEOS.append({
                        'file_id': message.video.file_id,
                        'type': 'video',
                        'caption': message.caption or ''
                    })
                    videos_count += 1
                elif message.photo:
                    STORAGE_VIDEOS.append({
                        'file_id': message.photo[-1].file_id,
                        'type': 'image',
                        'caption': message.caption or ''
                    })
                    videos_count += 1
        except Exception as e:
            logger.error(f"Failed to load from video storage: {e}")

    save_data()

    await update.message.reply_text(
        f"✅ *Storage Loaded!*\n\n"
        f"📸 Images: {images_count}\n"
        f"🎥 Videos/Mixed: {videos_count}\n"
        f"🔗 Links: {len(STORAGE_LINKS)}",
        parse_mode='Markdown')


def parse_links_from_text(text: str) -> list:
    """Parse links from text file"""
    links = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        if '|' in line:
            parts = line.split('|', 1)
            links.append({'url': parts[0].strip(), 'caption': parts[1].strip()})
        else:
            links.append({'url': line, 'caption': ''})
    
    return links


def parse_links_from_excel(file_path: str) -> list:
    """Parse links from Excel file"""
    links = []
    try:
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0]:
                links.append({
                    'url': str(row[0]).strip(),
                    'caption': str(row[1]).strip() if len(row) > 1 and row[1] else ''
                })
    except Exception as e:
        logger.error(f"Excel parse error: {e}")
    
    return links


def parse_links_from_pdf(file_path: str) -> list:
    """Parse links from PDF file"""
    links = []
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ''
            for page in pdf_reader.pages:
                text += page.extract_text()
            
            links = parse_links_from_text(text)
    except Exception as e:
        logger.error(f"PDF parse error: {e}")
    
    return links


async def handle_link_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded link file (TXT/Excel/PDF)"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not update.message.document:
        return

    document = update.message.document
    file_name = document.file_name.lower()

    if not any(file_name.endswith(ext) for ext in ['.txt', '.xlsx', '.xls', '.pdf']):
        return

    await update.message.reply_text("⏳ Processing link file...")

    try:
        file = await context.bot.get_file(document.file_id)
        file_path = os.path.join(STORAGE_DIR, document.file_name)
        await file.download_to_drive(file_path)

        global STORAGE_LINKS
        old_count = len(STORAGE_LINKS)
        STORAGE_LINKS.clear()

        if file_name.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                STORAGE_LINKS = parse_links_from_text(f.read())
        elif file_name.endswith(('.xlsx', '.xls')):
            STORAGE_LINKS = parse_links_from_excel(file_path)
        elif file_name.endswith('.pdf'):
            STORAGE_LINKS = parse_links_from_pdf(file_path)

        save_data()

        await update.message.reply_text(
            f"✅ *Links Imported!*\n\n"
            f"Old: {old_count}\n"
            f"New: {len(STORAGE_LINKS)}\n\n"
            f"Ready for posting!",
            parse_mode='Markdown')

        # Clean up
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Link file processing failed: {e}")


# ========== CHANNEL SETUP & MANAGEMENT ==========
async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-command channel setup"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 5:
        await update.message.reply_text(
            "Usage: `/setup_channel CHANNEL_ID \"Name\" TYPE INTERVAL \"CAPTION\"`\n\n"
            "Example:\n"
            "`/setup_channel -1001234567890 \"Glamour\" images 30 \"💎 Premium Content\"`\n\n"
            "Types: images, videos, links, mixed\n"
            "Interval: minutes (30, 45, 60, etc)",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        
        # Parse quoted name
        full_text = ' '.join(context.args[1:])
        if '"' in full_text:
            name_start = full_text.index('"') + 1
            name_end = full_text.index('"', name_start)
            channel_name = full_text[name_start:name_end]
            remaining = full_text[name_end+1:].strip().split()
        else:
            channel_name = context.args[1]
            remaining = context.args[2:]

        content_type = remaining[0].lower()
        interval = int(remaining[1])
        
        # Parse quoted caption
        caption_text = ' '.join(remaining[2:])
        if '"' in caption_text:
            cap_start = caption_text.index('"') + 1
            cap_end = caption_text.index('"', cap_start)
            caption = caption_text[cap_start:cap_end]
        else:
            caption = caption_text

        if content_type not in ['images', 'videos', 'links', 'mixed']:
            await update.message.reply_text("❌ Invalid type. Use: images, videos, links, or mixed")
            return

        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        # Save configuration
        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        CHANNEL_CONFIG[channel_id] = {
            'type': content_type,
            'interval': interval,
            'caption': caption,
            'enabled': False,
            'polls': False,
            'poll_frequency': 5
        }
        CHANNEL_POST_COUNT[channel_id] = 0
        save_data()

        await update.message.reply_text(
            f"✅ *Channel Configured!*\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`\n"
            f"Type: {content_type}\n"
            f"Interval: {interval} min\n"
            f"Caption: {caption}\n\n"
            f"Use `/enable_autopost {channel_id}` to start!",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Setup channel failed: {e}")


async def change_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change channel caption"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/change_caption CHANNEL_ID \"New caption\"`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        
        full_text = ' '.join(context.args[1:])
        if '"' in full_text:
            cap_start = full_text.index('"') + 1
            cap_end = full_text.index('"', cap_start)
            new_caption = full_text[cap_start:cap_end]
        else:
            new_caption = full_text

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['caption'] = new_caption
        save_data()

        await update.message.reply_text(
            f"✅ Caption updated!\n\n"
            f"New: {new_caption}",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change posting interval"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/change_interval CHANNEL_ID MINUTES`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        interval = int(context.args[1])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['interval'] = interval
        save_data()

        # Reschedule if enabled
        if CHANNEL_CONFIG[channel_id].get('enabled'):
            try:
                scheduler.remove_job(f'autopost_{channel_id}')
            except:
                pass
            
            scheduler.add_job(
                auto_post_job,
                trigger=CronTrigger(minute=f'*/{interval}'),
                args=[context.bot, channel_id],
                id=f'autopost_{channel_id}',
                replace_existing=True)

        await update.message.reply_text(
            f"✅ Interval updated to {interval} minutes!",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_content_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change content type"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/change_content_type CHANNEL_ID TYPE`\n\n"
            "Types: images, videos, links, mixed",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        content_type = context.args[1].lower()

        if content_type not in ['images', 'videos', 'links', 'mixed']:
            await update.message.reply_text("❌ Invalid type. Use: images, videos, links, or mixed")
            return

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['type'] = content_type
        save_data()

        await update.message.reply_text(
            f"✅ Content type changed to: {content_type}",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def enable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable polls for channel"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/enable_polls CHANNEL_ID FREQUENCY`\n\n"
            "Example: `/enable_polls -1001234567890 5` (every 5th post is a poll)",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        frequency = int(context.args[1])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['polls'] = True
        CHANNEL_CONFIG[channel_id]['poll_frequency'] = frequency
        save_data()

        await update.message.reply_text(
            f"✅ Polls enabled!\n\n"
            f"Every {frequency}th post will be a poll",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable polls for channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/disable_polls CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['polls'] = False
        save_data()

        await update.message.reply_text("✅ Polls disabled!", parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def pause_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause auto-posting for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/pause CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_PAUSE_STATUS[channel_id] = True
        save_data()

        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"⏸️ *Paused!*\n\n"
            f"Channel: {channel_name}\n"
            f"Use `/resume {channel_id}` to continue",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def resume_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume auto-posting for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/resume CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_PAUSE_STATUS[channel_id] = False
        save_data()

        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"▶️ *Resumed!*\n\n"
            f"Channel: {channel_name}\n"
            f"Auto-posting active",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def post_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force post immediately"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/post_now CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        await update.message.reply_text("⏳ Posting now...")
        await auto_post_job(context.bot, channel_id)
        await update.message.reply_text("✅ Posted!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def skip_next_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip next scheduled post"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/skip_next CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        # Temporarily pause for one cycle
        CHANNEL_PAUSE_STATUS[channel_id] = True
        save_data()

        # Schedule resume after interval
        interval = CHANNEL_CONFIG[channel_id]['interval']
        
        async def resume_after_skip():
            await asyncio.sleep(interval * 60)
            CHANNEL_PAUSE_STATUS[channel_id] = False
            save_data()

        asyncio.create_task(resume_after_skip())

        await update.message.reply_text(
            f"⏭️ *Next post skipped!*\n\n"
            f"Will resume in {interval} minutes",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View channel settings"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/channel_info CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        config = CHANNEL_CONFIG[channel_id]
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        paused = CHANNEL_PAUSE_STATUS.get(channel_id, False)
        post_count = CHANNEL_POST_COUNT.get(channel_id, 0)

        text = (
            f"━━━━━━━━━━━━━━━━\n"
            f"📢 *{channel_name}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"**ID:** `{channel_id}`\n"
            f"**Content:** {config['type']}\n"
            f"**Interval:** {config['interval']} minutes\n"
            f"**Caption:** {config['caption']}\n"
            f"**Status:** {'⏸️ Paused' if paused else '▶️ Active'}\n"
            f"**Auto-post:** {'✅ Enabled' if config.get('enabled') else '❌ Disabled'}\n"
            f"**Polls:** {'✅ Every ' + str(config['poll_frequency']) + 'th post' if config.get('polls') else '❌ Disabled'}\n"
            f"**Total Posts:** {post_count}\n"
            f"━━━━━━━━━━━━━━━━"
        )

        await update.message.reply_text(text, parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def all_channels_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all channels"""
    if not await owner_only_check(update, context):
        return

    if not CHANNEL_CONFIG:
        await update.message.reply_text("No channels configured yet")
        return

    text = "📊 *All Channels:*\n\n"

    for channel_id, config in CHANNEL_CONFIG.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        paused = CHANNEL_PAUSE_STATUS.get(channel_id, False)
        status = '⏸️' if paused else '▶️'
        
        text += (
            f"{status} **{channel_name}**\n"
            f"   Type: {config['type']} | {config['interval']}min\n"
            f"   Posts: {CHANNEL_POST_COUNT.get(channel_id, 0)}\n\n"
        )

    await update.message.reply_text(text, parse_mode='Markdown')


# ========== AUTO-POSTING JOB ==========
async def auto_post_job(bot, channel_id: int):
    """Auto-posting job - posts content based on channel config"""
    try:
        # Check if paused
        if CHANNEL_PAUSE_STATUS.get(channel_id, False):
            logger.info(f"Channel {channel_id} is paused, skipping post")
            return

        config = CHANNEL_CONFIG.get(channel_id)
        if not config or not config.get('enabled'):
            return

        content_type = config['type']
        caption = config['caption']
        
        # Increment post count
        CHANNEL_POST_COUNT[channel_id] = CHANNEL_POST_COUNT.get(channel_id, 0) + 1
        post_number = CHANNEL_POST_COUNT[channel_id]

        # Check if this should be a poll
        should_poll = config.get('polls', False) and (post_number % config.get('poll_frequency', 5) == 0)

        if should_poll:
            # Post a poll
            poll_questions = [
                ("Which content do you like most? 💭", ["❤️ Love it", "🔥 Amazing", "💎 Perfect", "👍 Good"]),
                ("Rate this channel! ⭐", ["⭐⭐⭐⭐⭐", "⭐⭐⭐⭐", "⭐⭐⭐", "⭐⭐"]),
                ("What should we post more? 🤔", ["Images 📸", "Videos 🎥", "Links 🔗", "Mixed 🎯"]),
            ]
            question, options = random.choice(poll_questions)
            
            await bot.send_poll(
                chat_id=channel_id,
                question=question,
                options=options,
                is_anonymous=True
            )
            logger.info(f"✅ Posted poll to channel {channel_id}")
        else:
            # Post regular content
            if content_type == 'images':
                if not STORAGE_IMAGES:
                    logger.warning(f"No images available for channel {channel_id}")
                    return
                media = random.choice(STORAGE_IMAGES)
                await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                
            elif content_type == 'videos':
                if not STORAGE_VIDEOS:
                    logger.warning(f"No videos available for channel {channel_id}")
                    return
                media = random.choice(STORAGE_VIDEOS)
                if media['type'] == 'video':
                    await bot.send_video(chat_id=channel_id, video=media['file_id'], caption=caption)
                else:
                    await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                    
            elif content_type == 'links':
                if not STORAGE_LINKS:
                    logger.warning(f"No links available for channel {channel_id}")
                    return
                link = random.choice(STORAGE_LINKS)
                text = f"{caption}\n\n{link['url']}"
                if link['caption']:
                    text = f"{caption}\n\n{link['caption']}\n\n{link['url']}"
                await bot.send_message(chat_id=channel_id, text=text)
                
            elif content_type == 'mixed':
                # Random from all sources
                all_media = []
                if STORAGE_IMAGES:
                    all_media.extend([('image', m) for m in STORAGE_IMAGES])
                if STORAGE_VIDEOS:
                    all_media.extend([('video', m) for m in STORAGE_VIDEOS])
                if STORAGE_LINKS:
                    all_media.extend([('link', m) for m in STORAGE_LINKS])
                
                if not all_media:
                    logger.warning(f"No content available for mixed channel {channel_id}")
                    return
                
                media_type, media = random.choice(all_media)
                
                if media_type == 'image':
                    await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                elif media_type == 'video':
                    if media['type'] == 'video':
                        await bot.send_video(chat_id=channel_id, video=media['file_id'], caption=caption)
                    else:
                        await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                elif media_type == 'link':
                    text = f"{caption}\n\n{media['url']}"
                    if media['caption']:
                        text = f"{caption}\n\n{media['caption']}\n\n{media['url']}"
                    await bot.send_message(chat_id=channel_id, text=text)

            logger.info(f"✅ Auto-posted {content_type} to channel {channel_id}")

        save_data()

    except Exception as e:
        logger.error(f"❌ Auto-post failed for channel {channel_id}: {e}")


async def enable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable auto-posting for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/enable_autopost CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured. Use /setup_channel first")
            return

        config = CHANNEL_CONFIG[channel_id]
        config['enabled'] = True
        CHANNEL_PAUSE_STATUS[channel_id] = False
        save_data()

        # Add scheduler job
        interval = config['interval']
        scheduler.add_job(
            auto_post_job,
            trigger=CronTrigger(minute=f'*/{interval}'),
            args=[context.bot, channel_id],
            id=f'autopost_{channel_id}',
            replace_existing=True)

        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"✅ *Auto-post enabled!*\n\n"
            f"Channel: {channel_name}\n"
            f"Interval: Every {interval} minutes\n"
            f"Content: {config['type']}\n\n"
            f"Bot will start posting automatically! 🚀",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable auto-posting for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/disable_autopost CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['enabled'] = False
        save_data()

        # Remove scheduler job
        try:
            scheduler.remove_job(f'autopost_{channel_id}')
        except:
            pass

        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"✅ Auto-post disabled for {channel_name}",
            parse_mode='Markdown')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ========== ORIGINAL COMMANDS (KEPT AS IS) ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command with all commands listed"""
    user = update.effective_user

    if user.id == ADMIN_ID:
        text = (
            "👋 Welcome Owner!\n\n"
            "🤖 Bot Status: Online 24/7\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"⚙️ Smart Verification: Enabled\n\n"

            "━━━ STORAGE SETUP ━━━\n"
            "/set_image_storage - Image channel\n"
            "/set_video_storage - Video channel\n"
            "/set_dummy_channel - Redirect channel\n"
            "/reload_storage - Load media\n"
            "Send file - Upload links (txt/excel/pdf)\n\n"

            "━━━ CHANNEL SETUP ━━━\n"
            "/setup_channel - Full setup\n"
            "/channel_info - View settings\n"
            "/all_channels - All channels\n\n"

            "━━━ MODIFICATIONS ━━━\n"
            "/change_caption - Change caption\n"
            "/change_interval - Change interval\n"
            "/change_content_type - Change type\n"
            "/enable_polls - Enable polls\n"
            "/disable_polls - Disable polls\n\n"

            "━━━ CONTROL ━━━\n"
            "/enable_autopost - Start posting\n"
            "/disable_autopost - Stop posting\n"
            "/pause - Pause channel\n"
            "/resume - Resume channel\n"
            "/post_now - Post immediately\n"
            "/skip_next - Skip next post\n\n"

            "━━━ ACTIVITY ━━━\n"
            "/recent_activity - Who joined\n"
            "/pending_users - Captchas\n"
            "/stats - Statistics\n\n"

            "━━━ APPROVALS ━━━\n"
            "/approve_user - Approve one\n"
            "/block_user - Block user\n"
            "/toggle_bulk - Change mode\n\n"

            "━━━ OLD COMMANDS ━━━\n"
            "/addchannel - Add channel\n"
            "/channels - List channels\n"
            "/post - Manual post"
        )
    else:
        text = "Hello! This bot is for channel management."

    await update.message.reply_text(text)


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel to manage"""
    if not await owner_only_check(update, context):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addchannel CHANNEL_ID CHANNEL_NAME`\n\n"
            "Example: `/addchannel -1001234567890 My Premium Channel`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        channel_name = ' '.join(context.args[1:])

        is_admin = await is_bot_admin(context, channel_id)
        
        if not is_admin:
            await update.message.reply_text("❌ Bot is not admin in that channel")
            return

        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        save_data()

        await update.message.reply_text(
            f"✅ Channel added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`\n"
            f"Smart Verification: Enabled",
            parse_mode='Markdown')

    except ValueError as e:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all managed channels"""
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


async def pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending verification requests"""
    if not await owner_only_check(update, context):
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


async def manual_approve_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually approve a user"""
    if not await owner_only_check(update, context):
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


async def toggle_bulk_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle bulk approval mode for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/toggle_bulk CHANNEL_ID`",
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

        new_mode = "🔄 Bulk Mode" if BULK_APPROVAL_MODE[channel_id] else "🛡️ Smart Verification"

        await update.message.reply_text(
            f"✅ Mode changed!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"New Mode: {new_mode}",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block a user from all channels"""
    if not await owner_only_check(update, context):
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
            f"User ID: `{user_id}`",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def view_recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent auto-approvals and auto-rejections"""
    if not await owner_only_check(update, context):
        return

    if not RECENT_ACTIVITY:
        await update.message.reply_text("No recent activity")
        return

    approved = [a for a in RECENT_ACTIVITY if a['type'] == 'auto_approved']
    rejected = [a for a in RECENT_ACTIVITY if a['type'] == 'auto_rejected']

    text = "📊 Recent Activity\n\n"
    text += f"✅ Auto-Approved: {len(approved)}\n"
    text += f"❌ Auto-Rejected: {len(rejected)}\n"
    text += f"⚠️ Pending Captcha: {len(PENDING_VERIFICATIONS)}\n\n"

    if approved:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "✅ Recently Approved:\n\n"
        for activity in approved[-10:]:
            text += f"• {activity['user_name']}\n"
            text += f"  @{activity['username']}\n"
            text += f"  Channel: {activity['channel']}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    if rejected:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "❌ Recently Rejected:\n\n"
        for activity in rejected[-5:]:
            text += f"• {activity['user_name']}\n"
            text += f"  Reason: {activity['reason']}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    if not await owner_only_check(update, context):
        return

    bulk_enabled = sum(1 for v in BULK_APPROVAL_MODE.values() if v)
    active_autoposts = sum(1 for v in CHANNEL_CONFIG.values() if v.get('enabled'))
    recent_approved = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_approved')
    recent_rejected = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'auto_rejected')
    total_posts = sum(CHANNEL_POST_COUNT.values())

    text = (
        f"📊 *Statistics*\n\n"
        f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
        f"🤖 Auto-posting: {active_autoposts} active\n"
        f"📝 Total Posts: {total_posts}\n\n"
        f"📦 Storage:\n"
        f"   📸 Images: {len(STORAGE_IMAGES)}\n"
        f"   🎥 Videos: {len(STORAGE_VIDEOS)}\n"
        f"   🔗 Links: {len(STORAGE_LINKS)}\n\n"
        f"👥 Users:\n"
        f"   ✅ Approved: {recent_approved}\n"
        f"   ❌ Rejected: {recent_rejected}\n"
        f"   ⏳ Pending: {len(PENDING_VERIFICATIONS)}\n"
        f"   🚫 Blocked: {len(BLOCKED_USERS)}\n\n"
        f"Status: Online 24/7 ✅"
    )
    await update.message.reply_text(text, parse_mode='Markdown')


# Keep other handlers minimal
async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual posting mode"""
    if not await owner_only_check(update, context):
        return
    
    context.user_data['posting_mode'] = True
    await update.message.reply_text(
        "📤 *Posting Mode Enabled*\n\n"
        "Send me content to post",
        parse_mode='Markdown')


async def handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle manual posting content"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get('posting_mode'):
        return

    message = update.message
    content_type = 'text'

    if message.photo:
        content_type = 'photo'
    elif message.video:
        content_type = 'video'

    PENDING_POSTS[ADMIN_ID] = {'message': message, 'type': content_type}

    keyboard = []
    for channel_id, data in MANAGED_CHANNELS.items():
        keyboard.append([InlineKeyboardButton(f"📢 {data['name']}", callback_data=f"post_{channel_id}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="post_cancel")])

    await update.message.reply_text(
        "🎯 Select Channel:",
        reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['posting_mode'] = False


async def post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle manual post selection"""
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
    channel_id = int(action)

    try:
        if pending['type'] == 'text':
            await context.bot.send_message(channel_id, original_msg.text)
        elif pending['type'] == 'photo':
            await context.bot.send_photo(channel_id, original_msg.photo[-1].file_id, caption=original_msg.caption)
        elif pending['type'] == 'video':
            await context.bot.send_video(channel_id, original_msg.video.file_id, caption=original_msg.caption)

        del PENDING_POSTS[ADMIN_ID]
        await query.edit_message_text("✅ Posted!")

    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Exception: {context.error}")


def main():
    """Main function to start the bot"""
    logger.info("🚀 Starting ENHANCED CHANNEL BOT...")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")

    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    # Storage commands
    app.add_handler(CommandHandler("set_image_storage", set_image_storage))
    app.add_handler(CommandHandler("set_video_storage", set_video_storage))
    app.add_handler(CommandHandler("set_dummy_channel", set_dummy_channel))
    app.add_handler(CommandHandler("reload_storage", reload_storage))

    # Channel setup commands
    app.add_handler(CommandHandler("setup_channel", setup_channel))
    app.add_handler(CommandHandler("change_caption", change_caption))
    app.add_handler(CommandHandler("change_interval", change_interval))
    app.add_handler(CommandHandler("change_content_type", change_content_type))
    app.add_handler(CommandHandler("enable_polls", enable_channel_polls))
    app.add_handler(CommandHandler("disable_polls", disable_channel_polls))

    # Control commands
    app.add_handler(CommandHandler("enable_autopost", enable_autopost))
    app.add_handler(CommandHandler("disable_autopost", disable_autopost))
    app.add_handler(CommandHandler("pause", pause_channel))
    app.add_handler(CommandHandler("resume", resume_channel))
    app.add_handler(CommandHandler("post_now", post_now_command))
    app.add_handler(CommandHandler("skip_next", skip_next_post))
    
    # Info commands
    app.add_handler(CommandHandler("channel_info", channel_info))
    app.add_handler(CommandHandler("all_channels", all_channels_info))

    # Original commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("pending_users", pending_users))
    app.add_handler(CommandHandler("approve_user", manual_approve_user))
    app.add_handler(CommandHandler("toggle_bulk", toggle_bulk_approval))
    app.add_handler(CommandHandler("block_user", block_user))
    app.add_handler(CommandHandler("recent_activity", view_recent_activity))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("stats", stats))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(enter_code_callback, pattern="^enter_code_"))
    app.add_handler(CallbackQueryHandler(post_callback, pattern="^post_"))

    # Message handlers
    app.add_handler(MessageHandler(filters.Document.ALL, handle_link_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_content))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_content))

    # Join request handler
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # Error handler
    app.add_error_handler(error_handler)

    # Start scheduler
    scheduler.start()

    # Restore auto-posting for enabled channels
    for channel_id, config in CHANNEL_CONFIG.items():
        if config.get('enabled'):
            try:
                interval = config['interval']
                scheduler.add_job(
                    auto_post_job,
                    trigger=CronTrigger(minute=f'*/{interval}'),
                    args=[app.bot, channel_id],
                    id=f'autopost_{channel_id}',
                    replace_existing=True)
                logger.info(f"✅ Auto-post restored for channel {channel_id} ({interval} min)")
            except Exception as e:
                logger.error(f"Failed to restore: {e}")

    logger.info(f"✅ Bot running - Owner: {ADMIN_ID}")
    logger.info(f"✅ Storage: {len(STORAGE_IMAGES)} images, {len(STORAGE_VIDEOS)} videos, {len(STORAGE_LINKS)} links")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
