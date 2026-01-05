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

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set!")
if ADMIN_ID == 0:
    raise ValueError("❌ ADMIN_ID not set!")

# Verification settings
MIN_ACCOUNT_AGE_DAYS = 15
REQUIRE_PROFILE_PHOTO = False
CODE_EXPIRY_MINUTES = 5

VERIFICATION_THRESHOLDS = {
    'auto_approve_score': 70,
    'manual_review_score': 30,
    'auto_reject_score': 0
}

# Core data
VERIFIED_USERS = set([ADMIN_ID])
MANAGED_CHANNELS = {}
PENDING_POSTS = {}
PENDING_VERIFICATIONS = {}
VERIFIED_FOR_CHANNELS = {}
BLOCKED_USERS = set()
BULK_APPROVAL_MODE = {}

# Content storage
CHANNEL_IMAGES = {}
CHANNEL_VIDEOS = {}
CHANNEL_LINKS = {}
CHANNEL_PROMO_IMAGES = {}
UPLOADED_IMAGES = []
CHANNEL_SPECIFIC_IMAGES = {}

# Posting settings
CURRENT_IMAGE_INDEX = {}
CURRENT_PROMO_INDEX = {}
POST_COUNTER = {}
AUTO_POST_ENABLED = {}

# ========== NEW: SMART STAGGERED POSTING ==========
# New interval format: {base, variation_min, variation_max}
POSTING_INTERVALS = {}  # {channel_id: {'base': 20, 'var_min': 2, 'var_max': 15}}

# Global post tracking
LAST_POST_TIME = None  # Track when ANY channel last posted
STAGGER_MIN = 2  # Minimum minutes between channel posts
STAGGER_MAX = 8  # Maximum minutes between channel posts

# Promo settings
PROMO_FREQUENCY = {}
DEFAULT_PROMO_FREQUENCY = 5

# Content type
CHANNEL_CONTENT_TYPE = {}

# Preview channels
PREVIEW_CHANNELS = {}

# Other
USER_DATABASE = {}
USER_ACTIVITY_LOG = []
RECENT_ACTIVITY = []
DEFAULT_CAPTION = ""
CHANNEL_DEFAULT_CAPTIONS = {}
UNAUTHORIZED_ATTEMPTS = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    """Save all bot data"""
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
            'channel_images': CHANNEL_IMAGES,
            'channel_videos': CHANNEL_VIDEOS,
            'channel_links': CHANNEL_LINKS,
            'channel_promo_images': CHANNEL_PROMO_IMAGES,
            'posting_intervals': POSTING_INTERVALS,
            'promo_frequency': PROMO_FREQUENCY,
            'channel_content_type': CHANNEL_CONTENT_TYPE,
            'preview_channels': PREVIEW_CHANNELS,
            'current_promo_index': CURRENT_PROMO_INDEX,
            'post_counter': POST_COUNTER,
            'verification_thresholds': VERIFICATION_THRESHOLDS
        }
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        logger.info("✅ Data saved")
    except Exception as e:
        logger.error(f"Save failed: {e}")


def load_data():
    """Load all bot data"""
    global MANAGED_CHANNELS, UPLOADED_IMAGES, CHANNEL_SPECIFIC_IMAGES
    global DEFAULT_CAPTION, CHANNEL_DEFAULT_CAPTIONS, AUTO_POST_ENABLED
    global CURRENT_IMAGE_INDEX, BULK_APPROVAL_MODE, BLOCKED_USERS, USER_DATABASE
    global CHANNEL_IMAGES, CHANNEL_VIDEOS, CHANNEL_LINKS, CHANNEL_PROMO_IMAGES
    global POSTING_INTERVALS, PROMO_FREQUENCY, CHANNEL_CONTENT_TYPE, PREVIEW_CHANNELS
    global CURRENT_PROMO_INDEX, POST_COUNTER, VERIFICATION_THRESHOLDS

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
            CHANNEL_IMAGES = data.get('channel_images', {})
            CHANNEL_VIDEOS = data.get('channel_videos', {})
            CHANNEL_LINKS = data.get('channel_links', {})
            CHANNEL_PROMO_IMAGES = data.get('channel_promo_images', {})
            POSTING_INTERVALS = data.get('posting_intervals', {})
            PROMO_FREQUENCY = data.get('promo_frequency', {})
            CHANNEL_CONTENT_TYPE = data.get('channel_content_type', {})
            PREVIEW_CHANNELS = data.get('preview_channels', {})
            CURRENT_PROMO_INDEX = data.get('current_promo_index', {})
            POST_COUNTER = data.get('post_counter', {})
            
            saved_thresholds = data.get('verification_thresholds', {})
            VERIFICATION_THRESHOLDS.update(saved_thresholds)

            def convert_keys(d):
                return {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in d.items()}
            
            MANAGED_CHANNELS = convert_keys(MANAGED_CHANNELS)
            CHANNEL_SPECIFIC_IMAGES = convert_keys(CHANNEL_SPECIFIC_IMAGES)
            AUTO_POST_ENABLED = convert_keys(AUTO_POST_ENABLED)
            CURRENT_IMAGE_INDEX = convert_keys(CURRENT_IMAGE_INDEX)
            BULK_APPROVAL_MODE = convert_keys(BULK_APPROVAL_MODE)
            CHANNEL_DEFAULT_CAPTIONS = convert_keys(CHANNEL_DEFAULT_CAPTIONS)
            CHANNEL_IMAGES = convert_keys(CHANNEL_IMAGES)
            CHANNEL_VIDEOS = convert_keys(CHANNEL_VIDEOS)
            CHANNEL_LINKS = convert_keys(CHANNEL_LINKS)
            CHANNEL_PROMO_IMAGES = convert_keys(CHANNEL_PROMO_IMAGES)
            POSTING_INTERVALS = convert_keys(POSTING_INTERVALS)
            PROMO_FREQUENCY = convert_keys(PROMO_FREQUENCY)
            CHANNEL_CONTENT_TYPE = convert_keys(CHANNEL_CONTENT_TYPE)
            PREVIEW_CHANNELS = convert_keys(PREVIEW_CHANNELS)
            CURRENT_PROMO_INDEX = convert_keys(CURRENT_PROMO_INDEX)
            POST_COUNTER = convert_keys(POST_COUNTER)

            logger.info(f"✅ Loaded: {len(MANAGED_CHANNELS)} channels")
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


async def check_user_legitimacy(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
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
        # 30-99 = Borderline (manual check with captcha)
        # 0-29 = Suspicious (auto-reject)

        auto_approve = VERIFICATION_THRESHOLDS['auto_approve_score']
        manual_review = VERIFICATION_THRESHOLDS['manual_review_score']

        if score >= auto_approve:
            return {"legitimate": True, "score": 100}
        elif score >= manual_review:
            return {"legitimate": False, "score": 50, "reason": ", ".join(reasons)}
        else:
            return {"legitimate": False, "score": 0, "reason": ", ".join(reasons)}

    except Exception as e:
        logger.error(f"Legitimacy check failed: {e}")
        return {"legitimate": False, "reason": "Error checking user", "score": 0}


def track_user_activity(user_id: int, channel_id: int, action: str, user_data: dict = None):
    """Track user activity"""
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
            f"🚨 *Unauthorized Access*\n\n"
            f"User: {first_name}\n"
            f"ID: `{user_id}`\n"
            f"Username: @{username or 'None'}\n"
            f"Command: `{command}`",
            parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Alert failed: {e}")


async def owner_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is owner"""
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
        logger.error(f"Owner check error: {e}")
        return False


# ========== SMART STAGGERED POSTING SYSTEM ==========

def get_next_post_interval(channel_id: int) -> int:
    """
    Calculate next posting interval with variation
    Returns: minutes until next post
    """
    intervals = POSTING_INTERVALS.get(channel_id)
    if not intervals:
        # Default: 20 base, ±2 to ±15 variation
        base = 20
        var_min = 2
        var_max = 15
    else:
        base = intervals.get('base', 20)
        var_min = intervals.get('var_min', 2)
        var_max = intervals.get('var_max', 15)
    
    # Random variation: can be positive or negative
    variation = random.randint(var_min, var_max)
    if random.choice([True, False]):
        variation = -variation
    
    interval = base + variation
    
    # Ensure minimum 5 minutes
    interval = max(5, interval)
    
    return interval


def get_stagger_delay() -> int:
    """
    Get random stagger delay to avoid posting at same time as other channels
    Returns: minutes to wait (2-8)
    """
    return random.randint(STAGGER_MIN, STAGGER_MAX)


def should_stagger_post() -> bool:
    """
    Check if we should add stagger delay
    Returns: True if another channel posted recently
    """
    global LAST_POST_TIME
    
    if LAST_POST_TIME is None:
        return False
    
    time_since_last = (datetime.now() - LAST_POST_TIME).total_seconds() / 60
    
    # If last post was within 10 minutes, add stagger
    if time_since_last < 10:
        return True
    
    return False


def should_post_promo(channel_id: int) -> bool:
    """Check if it's time to post promo"""
    if channel_id not in PROMO_FREQUENCY:
        return False
    
    if channel_id not in POST_COUNTER:
        POST_COUNTER[channel_id] = 0
    
    POST_COUNTER[channel_id] += 1
    frequency = PROMO_FREQUENCY[channel_id]
    
    if POST_COUNTER[channel_id] >= frequency:
        POST_COUNTER[channel_id] = 0
        return True
    
    return False


async def auto_post_job(bot, channel_id: int):
    """Enhanced auto-posting with smart staggering"""
    global LAST_POST_TIME
    
    try:
        if not AUTO_POST_ENABLED.get(channel_id):
            return

        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')
        
        # Check if we should add stagger delay
        if should_stagger_post():
            stagger = get_stagger_delay()
            logger.info(f"⏸️ Staggering post for channel {channel_id} by {stagger} mins")
            
            # Schedule with stagger delay
            next_run = datetime.now() + timedelta(minutes=stagger)
            scheduler.add_job(
                auto_post_job,
                trigger='date',
                run_date=next_run,
                args=[bot, channel_id],
                id=f'autopost_{channel_id}',
                replace_existing=True
            )
            return
        
        # Check if it's promo time
        is_promo_time = should_post_promo(channel_id)
        
        if is_promo_time and channel_id in CHANNEL_PROMO_IMAGES and CHANNEL_PROMO_IMAGES[channel_id]:
            # POST PROMO
            promos = CHANNEL_PROMO_IMAGES[channel_id]
            
            if channel_id not in CURRENT_PROMO_INDEX:
                CURRENT_PROMO_INDEX[channel_id] = 0
            
            idx = CURRENT_PROMO_INDEX[channel_id]
            promo = promos[idx]
            
            if isinstance(promo, dict):
                file_id = promo['file_id']
                caption = promo.get('caption', '')
            else:
                file_id = promo
                caption = ""
            
            await bot.send_photo(chat_id=channel_id, photo=file_id, caption=caption)
            
            logger.info(f"📢 Posted PROMO to channel {channel_id}")
            
            CURRENT_PROMO_INDEX[channel_id] = (idx + 1) % len(promos)
            save_data()
            
        else:
            # POST REGULAR CONTENT
            if content_type == 'image':
                await post_image_content(bot, channel_id)
            elif content_type == 'video':
                await post_video_content(bot, channel_id)
            elif content_type == 'link':
                await post_link_content(bot, channel_id)
            elif content_type == 'mixed':
                choice = random.choice(['image', 'video', 'link'])
                if choice == 'image':
                    await post_image_content(bot, channel_id)
                elif choice == 'video':
                    await post_video_content(bot, channel_id)
                else:
                    await post_link_content(bot, channel_id)

        # Update global last post time
        LAST_POST_TIME = datetime.now()

        # Schedule next post with smart interval
        next_interval = get_next_post_interval(channel_id)
        next_run = datetime.now() + timedelta(minutes=next_interval)
        
        scheduler.add_job(
            auto_post_job,
            trigger='date',
            run_date=next_run,
            args=[bot, channel_id],
            id=f'autopost_{channel_id}',
            replace_existing=True
        )
        
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        logger.info(f"⏰ Next post for {channel_name} in {next_interval} mins")

    except Exception as e:
        logger.error(f"❌ Auto-post failed for channel {channel_id}: {e}")


async def post_image_content(bot, channel_id: int):
    """Post image content"""
    images = CHANNEL_IMAGES.get(channel_id, [])
    if not images:
        images = CHANNEL_SPECIFIC_IMAGES.get(channel_id, UPLOADED_IMAGES)
    
    if not images:
        logger.warning(f"No images for channel {channel_id}")
        return
    
    if channel_id not in CURRENT_IMAGE_INDEX:
        CURRENT_IMAGE_INDEX[channel_id] = 0
    
    idx = CURRENT_IMAGE_INDEX[channel_id]
    image = images[idx]
    
    if isinstance(image, dict) and image.get('caption'):
        final_caption = image['caption']
    elif channel_id in CHANNEL_DEFAULT_CAPTIONS:
        final_caption = CHANNEL_DEFAULT_CAPTIONS[channel_id]
    elif DEFAULT_CAPTION:
        final_caption = DEFAULT_CAPTION
    else:
        final_caption = ""
    
    file_id = image['file_id'] if isinstance(image, dict) else image
    
    await bot.send_photo(chat_id=channel_id, photo=file_id, caption=final_caption)
    
    logger.info(f"✅ Posted image #{idx+1} to channel {channel_id}")
    
    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(images)
    save_data()


async def post_video_content(bot, channel_id: int):
    """Post video content"""
    videos = CHANNEL_VIDEOS.get(channel_id, [])
    if not videos:
        logger.warning(f"No videos for channel {channel_id}")
        return
    
    if channel_id not in CURRENT_IMAGE_INDEX:
        CURRENT_IMAGE_INDEX[channel_id] = 0
    
    idx = CURRENT_IMAGE_INDEX[channel_id]
    video = videos[idx]
    
    if isinstance(video, dict):
        file_id = video['file_id']
        caption = video.get('caption', CHANNEL_DEFAULT_CAPTIONS.get(channel_id, ''))
    else:
        file_id = video
        caption = CHANNEL_DEFAULT_CAPTIONS.get(channel_id, '')
    
    await bot.send_video(chat_id=channel_id, video=file_id, caption=caption)
    
    logger.info(f"✅ Posted video #{idx+1} to channel {channel_id}")
    
    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(videos)
    save_data()


async def post_link_content(bot, channel_id: int):
    """Post link content"""
    links = CHANNEL_LINKS.get(channel_id, [])
    if not links:
        logger.warning(f"No links for channel {channel_id}")
        return
    
    if channel_id not in CURRENT_IMAGE_INDEX:
        CURRENT_IMAGE_INDEX[channel_id] = 0
    
    idx = CURRENT_IMAGE_INDEX[channel_id]
    link = links[idx]
    
    if isinstance(link, dict):
        url = link['url']
        caption = link.get('caption', '')
        if caption:
            message = f"{caption}\n\n{url}"
        else:
            message = url
    else:
        message = link
    
    await bot.send_message(chat_id=channel_id, text=message, disable_web_page_preview=False)
    
    logger.info(f"✅ Posted link #{idx+1} to channel {channel_id}")
    
    CURRENT_IMAGE_INDEX[channel_id] = (idx + 1) % len(links)
    save_data()


# ========== JOIN REQUEST HANDLER ==========
async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced join handler"""
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

            logger.info(f"✅ Auto-approved: {user.id}")
            return
        except Exception as e:
            logger.error(f"Auto-approval failed: {e}")

    if not legitimacy['legitimate'] and legitimacy['score'] == 0:
        try:
            await request.decline()

            preview_channel = PREVIEW_CHANNELS.get(chat_id)
            if preview_channel:
                try:
                    invite_link = await context.bot.create_chat_invite_link(
                        preview_channel, 
                        member_limit=1,
                        name=f"Preview for {user.first_name}"
                    )
                    
                    await context.bot.send_message(
                        user.id,
                        f"👋 Hi {user.first_name}!\n\n"
                        f"Your request needs review.\n\n"
                        f"🎁 Check our preview:\n{invite_link.invite_link}\n\n"
                        f"💡 Improve chances:\n• Add username\n• Use recognizable name"
                    )
                    logger.info(f"✅ Sent preview to {user.id}")
                except Exception as e:
                    logger.error(f"Preview invite failed: {e}")

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

            logger.info(f"❌ Auto-rejected: {user.id}")
            return
        except Exception as e:
            logger.error(f"Auto-rejection failed: {e}")

    # Manual verification
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
        f"Username: @{user.username or 'None'}\n\n"
        f"Math: {num1} + {num2} = {answer}\n"
        f"Reason: {legitimacy.get('reason', 'Unknown')}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard))


async def enter_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval"""
    query = update.callback_query

    if query.from_user.id != ADMIN_ID:
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()
    user_id = int(query.data.split('_')[-1])

    if user_id not in PENDING_VERIFICATIONS:
        await query.edit_message_text("❌ Verification expired")
        return

    verification = PENDING_VERIFICATIONS[user_id]
    chat_id = verification['chat_id']

    try:
        request = verification.get('request')
        if request:
            await request.approve()
        
        track_user_activity(user_id, chat_id, 'approved')
        del PENDING_VERIFICATIONS[user_id]

        await query.edit_message_text(
            f"✅ *User Approved*\n\n"
            f"User ID: `{user_id}`\n"
            f"Channel: {MANAGED_CHANNELS[chat_id]['name']}",
            parse_mode='Markdown')

        logger.info(f"✅ Admin approved: {user_id}")

    except Exception as e:
        logger.error(f"Manual approval failed: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")


# Continue with rest of commands (keeping them minimal)...
# I'll add the key commands needed

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command with complete menu"""
    user = update.effective_user

    if user.id == ADMIN_ID:
        text = (
            "👋 *Welcome Owner! Smart Staggered Bot*\n\n"
            "🤖 Status: Online 24/7\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"⚙️ Smart Verification: Enabled\n\n"

            "━━━ SETUP & INFO ━━━\n"
            "/start - This menu\n"
            "/addchannel - Add new channel\n"
            "/channels - List all channels\n"
            "/stats - Full statistics\n"
            "/help - Detailed help\n\n"

            "━━━ CHANNEL CONFIG ━━━\n"
            "/set_content_type - Set type (image/video/link/mixed)\n"
            "/set_smart_interval - Set random intervals\n"
            "/set_promo_freq - Promo frequency\n\n"

            "━━━ CONTENT UPLOAD ━━━\n"
            "/upload_images - Upload content\n"
            "/upload_promo - Upload promos\n"
            "/replace_links - Replace all links (bulk update)\n"
            "/done_uploading - Finish upload\n"
            "/list_content - View all content\n"
            "/clear_images - Clear all images\n"
            "/clear_channel_media - Clear channel media\n\n"

            "━━━ CAPTIONS ━━━\n"
            "/set_default_caption - Set global caption\n"
            "/clear_default_caption - Clear global caption\n"
            "/set_channel_caption - Set channel caption\n"
            "/clear_channel_caption - Clear channel caption\n\n"

            "━━━ AUTO-POSTING ━━━\n"
            "/enable_autopost - Start auto-posting\n"
            "/disable_autopost - Stop auto-posting\n"
            "/autopost_status - Check status\n\n"

            "━━━ MANUAL POSTING ━━━\n"
            "/post - Post to channels\n"
            "/send_to_channel - Quick send\n"
            "/cancel - Cancel operation\n\n"

            "━━━ USER MANAGEMENT ━━━\n"
            "/recent_activity - Who joined\n"
            "/pending_users - Pending approvals\n"
            "/approve_user - Approve one user\n"
            "/approve_all_pending - Approve all\n"
            "/block_user - Block user\n"
            "/unblock_user - Unblock user\n"
            "/user_stats - User statistics\n"
            "/export_users - Export CSV\n\n"

            "━━━ VERIFICATION ━━━\n"
            "/verification_thresholds - Adjust thresholds\n"
            "/toggle_bulk - Toggle bulk mode\n"
            "/set_preview_channel - Set preview\n\n"

            "━━━ SECURITY ━━━\n"
            "/view_unauthorized - View attempts\n"
            "/clear_unauthorized - Clear log\n"
            "/clear_activity - Clear activity\n\n"

            "Type /help for detailed usage guide"
        )
    else:
        text = "Hello! This bot is for channel management."

    await update.message.reply_text(text, parse_mode='Markdown')


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addchannel CHANNEL_ID CHANNEL_NAME`\n"
            "Example: `/addchannel -1001234567890 My Channel`",
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
        
        # Default settings
        if channel_id not in POSTING_INTERVALS:
            POSTING_INTERVALS[channel_id] = {'base': 20, 'var_min': 2, 'var_max': 15}
        
        if channel_id not in CHANNEL_CONTENT_TYPE:
            CHANNEL_CONTENT_TYPE[channel_id] = 'image'
        
        save_data()
        
        await update.message.reply_text(
            f"✅ Channel added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`\n"
            f"Default interval: 20 base ± (2-15) mins\n\n"
            f"Configure: /set_smart_interval",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def set_smart_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set smart interval with base + variation"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: `/set_smart_interval CHANNEL_ID BASE VAR_MIN VAR_MAX`\n\n"
            "Example: `/set_smart_interval -1001234567890 20 2 15`\n"
            "Means: Base 20 mins ± (2-15) variation\n"
            "Result: Posts appear between 18-35 mins randomly\n\n"
            "Another: `/set_smart_interval -1001111111111 30 5 10`\n"
            "Means: Base 30 mins ± (5-10) variation\n"
            "Result: Posts appear between 25-40 mins randomly",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        base = int(context.args[1])
        var_min = int(context.args[2])
        var_max = int(context.args[3])

        if var_min >= var_max:
            await update.message.reply_text("❌ VAR_MIN must be less than VAR_MAX")
            return

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        POSTING_INTERVALS[channel_id] = {
            'base': base,
            'var_min': var_min,
            'var_max': var_max
        }
        save_data()

        min_time = base - var_max
        max_time = base + var_max

        await update.message.reply_text(
            f"✅ Smart interval set!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"Base: {base} mins\n"
            f"Variation: ±({var_min}-{var_max}) mins\n"
            f"Result: Posts every {min_time}-{max_time} mins\n\n"
            f"Plus 2-8 min stagger between channels! 🎯")

    except ValueError:
        await update.message.reply_text("❌ Invalid numbers")


async def set_content_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set content type"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_content_type CHANNEL_ID TYPE`\n\n"
            "Types: image, video, link, mixed",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        content_type = context.args[1].lower()

        if content_type not in ['image', 'video', 'link', 'mixed']:
            await update.message.reply_text("❌ Invalid type")
            return

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        CHANNEL_CONTENT_TYPE[channel_id] = content_type
        save_data()

        await update.message.reply_text(
            f"✅ Content type: {content_type}\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def set_promo_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set promo frequency"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_promo_freq CHANNEL_ID FREQUENCY`\n"
            "Example: `/set_promo_freq -1001234567890 5`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])
        frequency = int(context.args[1])

        if frequency < 1:
            await update.message.reply_text("❌ Frequency must be ≥1")
            return

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        PROMO_FREQUENCY[channel_id] = frequency
        POST_COUNTER[channel_id] = 0
        save_data()

        await update.message.reply_text(
            f"✅ Promo every {frequency} posts\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}")

    except ValueError:
        await update.message.reply_text("❌ Invalid numbers")


async def upload_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload promo"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/upload_promo CHANNEL_ID`",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['uploading_promo'] = channel_id
        context.user_data['uploading_mode'] = True

        await update.message.reply_text(
            f"📤 *Promo Upload*\n\n"
            f"Send promo images/links now\n"
            f"Use /done_uploading when finished",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def upload_images_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload content"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/upload_images CHANNEL_ID`\n"
            "Then send images/videos/links",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['uploading_for_channel'] = channel_id
        context.user_data['uploading_mode'] = True

        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')

        await update.message.reply_text(
            f"📤 *Upload: {MANAGED_CHANNELS[channel_id]['name']}*\n\n"
            f"Type: {content_type}\n"
            f"Send content now\n"
            f"/done_uploading when finished",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish upload"""
    if not await owner_only_check(update, context):
        return

    context.user_data['uploading_mode'] = False
    
    if context.user_data.get('uploading_promo'):
        channel_id = context.user_data['uploading_promo']
        count = len(CHANNEL_PROMO_IMAGES.get(channel_id, []))
        await update.message.reply_text(f"✅ Promos added: {count}")
        context.user_data['uploading_promo'] = None
    elif context.user_data.get('uploading_for_channel'):
        channel_id = context.user_data['uploading_for_channel']
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')
        
        if content_type == 'image':
            count = len(CHANNEL_IMAGES.get(channel_id, []))
        elif content_type == 'video':
            count = len(CHANNEL_VIDEOS.get(channel_id, []))
        elif content_type == 'link':
            count = len(CHANNEL_LINKS.get(channel_id, []))
        else:
            count = 0
            
        await update.message.reply_text(f"✅ Content added: {count}")
        context.user_data['uploading_for_channel'] = None
    else:
        await update.message.reply_text("✅ Upload complete!")


async def enable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable auto-posting"""
    if not await owner_only_check(update, context):
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
        save_data()

        # Start first post
        next_interval = get_next_post_interval(channel_id)
        next_run = datetime.now() + timedelta(minutes=next_interval)
        
        scheduler.add_job(
            auto_post_job,
            trigger='date',
            run_date=next_run,
            args=[context.bot, channel_id],
            id=f'autopost_{channel_id}',
            replace_existing=True
        )

        intervals = POSTING_INTERVALS.get(channel_id, {'base': 20, 'var_min': 2, 'var_max': 15})
        await update.message.reply_text(
            f"✅ Auto-post enabled!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"Base: {intervals['base']} mins\n"
            f"Variation: ±({intervals['var_min']}-{intervals['var_max']})\n"
            f"Stagger: 2-8 mins between channels\n\n"
            f"First post in: {next_interval} mins")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistics"""
    if not await owner_only_check(update, context):
        return

    active_autoposts = sum(1 for v in AUTO_POST_ENABLED.values() if v)
    
    total_images = sum(len(imgs) for imgs in CHANNEL_IMAGES.values())
    total_promos = sum(len(promos) for promos in CHANNEL_PROMO_IMAGES.values())
    total_links = sum(len(links) for links in CHANNEL_LINKS.values())

    text = (
        f"📊 *Smart Staggered Bot Stats*\n\n"
        f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
        f"🤖 Auto-Posts: {active_autoposts}\n"
        f"📸 Images: {total_images}\n"
        f"🔗 Links: {total_links}\n"
        f"📢 Promos: {total_promos}\n"
        f"👥 Users: {len(USER_DATABASE)}\n"
        f"⏳ Pending: {len(PENDING_VERIFICATIONS)}\n\n"
        f"⚡ Smart staggering active!"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List channels"""
    if not await owner_only_check(update, context):
        return

    if not MANAGED_CHANNELS:
        await update.message.reply_text("No channels")
        return

    text = "📢 *Channels:*\n\n"
    for channel_id, data in MANAGED_CHANNELS.items():
        intervals = POSTING_INTERVALS.get(channel_id, {'base': 20, 'var_min': 2, 'var_max': 15})
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')
        promo_freq = PROMO_FREQUENCY.get(channel_id, 'Not set')
        
        text += f"{data['name']}\n"
        text += f"ID: `{channel_id}`\n"
        text += f"Type: {content_type}\n"
        text += f"Base: {intervals['base']}m ±({intervals['var_min']}-{intervals['var_max']})\n"
        text += f"Promo: Every {promo_freq}\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')


async def extract_links_from_text(text: str) -> list:
    """Extract URLs from text"""
    import re
    url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    urls = re.findall(url_pattern, text)
    return urls


async def parse_link_document(file_path: str, file_extension: str) -> list:
    """Parse document and extract links"""
    links = []
    
    try:
        if file_extension == '.txt':
            # Read text file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                urls = await extract_links_from_text(content)
                links = [{'url': url, 'caption': ''} for url in urls]
        
        elif file_extension == '.xlsx' or file_extension == '.xls':
            # Read Excel file
            import openpyxl
            wb = openpyxl.load_workbook(file_path)
            sheet = wb.active
            
            for row in sheet.iter_rows(values_only=True):
                for cell in row:
                    if cell and isinstance(cell, str):
                        # Check if it's a URL
                        if cell.startswith('http://') or cell.startswith('https://'):
                            caption = ''
                            links.append({'url': cell, 'caption': caption})
                        else:
                            # Try to extract URLs from text
                            urls = await extract_links_from_text(cell)
                            links.extend([{'url': url, 'caption': ''} for url in urls])
        
        elif file_extension == '.pdf':
            # Read PDF file
            import PyPDF2
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                for page in pdf_reader.pages:
                    text = page.extract_text()
                    urls = await extract_links_from_text(text)
                    links.extend([{'url': url, 'caption': ''} for url in urls])
        
        elif file_extension == '.csv':
            # Read CSV file
            import csv
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_reader = csv.reader(f)
                for row in csv_reader:
                    for cell in row:
                        if cell and (cell.startswith('http://') or cell.startswith('https://')):
                            links.append({'url': cell, 'caption': ''})
                        else:
                            urls = await extract_links_from_text(cell)
                            links.extend([{'url': url, 'caption': ''} for url in urls])
    
    except Exception as e:
        logger.error(f"Failed to parse document: {e}")
        return []
    
    return links


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads for bulk link import"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    
    if not update.message.document:
        return
    
    # Check if in upload mode
    if not context.user_data.get('uploading_for_channel') and not context.user_data.get('uploading_promo'):
        return
    
    document = update.message.document
    file_name = document.file_name
    file_extension = os.path.splitext(file_name)[1].lower()
    
    # Check if it's a supported format
    supported_formats = ['.txt', '.xlsx', '.xls', '.pdf', '.csv']
    if file_extension not in supported_formats:
        await update.message.reply_text(
            f"❌ Unsupported format: {file_extension}\n"
            f"Supported: .txt, .xlsx, .xls, .csv, .pdf"
        )
        return
    
    try:
        # Download file
        file = await context.bot.get_file(document.file_id)
        file_path = f"/tmp/{file_name}"
        await file.download_to_drive(file_path)
        
        # Show processing message
        processing_msg = await update.message.reply_text("⏳ Processing document...")
        
        # Parse document
        links = await parse_link_document(file_path, file_extension)
        
        # Clean up temp file
        os.remove(file_path)
        
        if not links:
            await processing_msg.edit_text("❌ No links found in document")
            return
        
        # Add links to appropriate storage
        if context.user_data.get('uploading_promo'):
            channel_id = context.user_data['uploading_promo']
            if channel_id not in CHANNEL_PROMO_IMAGES:
                CHANNEL_PROMO_IMAGES[channel_id] = []
            CHANNEL_PROMO_IMAGES[channel_id].extend(links)
            logger.info(f"✅ {len(links)} promo links added from document")
        else:
            channel_id = context.user_data['uploading_for_channel']
            if channel_id not in CHANNEL_LINKS:
                CHANNEL_LINKS[channel_id] = []
            CHANNEL_LINKS[channel_id].extend(links)
            logger.info(f"✅ {len(links)} links added from document")
        
        save_data()
        
        await processing_msg.edit_text(
            f"✅ *Document Processed!*\n\n"
            f"File: {file_name}\n"
            f"Links extracted: {len(links)}\n\n"
            f"Sample links:\n" + 
            "\n".join([f"• {link['url'][:50]}..." for link in links[:5]]),
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
        await update.message.reply_text(f"❌ Error processing document: {str(e)}")


async def handle_image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploads"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not update.message.photo and not update.message.text:
        return

    # Check if uploading promo
    if context.user_data.get('uploading_promo'):
        channel_id = context.user_data['uploading_promo']
        
        if update.message.photo:
            photo = update.message.photo[-1]
            file_id = photo.file_id
            caption = update.message.caption or ""
            
            if channel_id not in CHANNEL_PROMO_IMAGES:
                CHANNEL_PROMO_IMAGES[channel_id] = []
            CHANNEL_PROMO_IMAGES[channel_id].append({'file_id': file_id, 'caption': caption})
            logger.info(f"✅ Promo image added to {channel_id}")
        elif update.message.text:
            # Promo link
            if channel_id not in CHANNEL_PROMO_IMAGES:
                CHANNEL_PROMO_IMAGES[channel_id] = []
            CHANNEL_PROMO_IMAGES[channel_id].append({'url': update.message.text, 'caption': ''})
            logger.info(f"✅ Promo link added to {channel_id}")
        
        save_data()
        return
    
    # Regular content upload
    if context.user_data.get('uploading_for_channel'):
        channel_id = context.user_data['uploading_for_channel']
        content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')
        
        if update.message.photo:
            photo = update.message.photo[-1]
            file_id = photo.file_id
            caption = update.message.caption or ""
            
            if channel_id not in CHANNEL_IMAGES:
                CHANNEL_IMAGES[channel_id] = []
            CHANNEL_IMAGES[channel_id].append({'file_id': file_id, 'caption': caption})
            logger.info(f"✅ Image added to {channel_id}")
            
        elif update.message.text and content_type == 'link':
            if channel_id not in CHANNEL_LINKS:
                CHANNEL_LINKS[channel_id] = []
            CHANNEL_LINKS[channel_id].append({'url': update.message.text, 'caption': ''})
            logger.info(f"✅ Link added to {channel_id}")
        
        save_data()


async def set_default_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set default caption for posts"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_default_caption Your caption here`\n\n"
            "This caption will be used for all posts without specific captions",
            parse_mode='Markdown')
        return

    global DEFAULT_CAPTION
    DEFAULT_CAPTION = ' '.join(context.args)
    save_data()

    await update.message.reply_text(
        f"✅ Default caption set!\n\n"
        f"Caption: {DEFAULT_CAPTION}")


async def clear_default_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear default caption"""
    if not await owner_only_check(update, context):
        return

    global DEFAULT_CAPTION
    DEFAULT_CAPTION = ""
    save_data()

    await update.message.reply_text("✅ Default caption cleared")


async def set_channel_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set channel-specific caption"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_channel_caption CHANNEL_ID Your caption`\n\n"
            "Example: `/set_channel_caption -1001234567890 ❤️ Like & Share`",
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
            f"Caption: {caption}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def clear_channel_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear channel-specific caption"""
    if not await owner_only_check(update, context):
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


async def list_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all uploaded content"""
    if not await owner_only_check(update, context):
        return

    text = "📂 *Content Library*\n\n"
    
    # Global content
    text += f"Global Images: {len(UPLOADED_IMAGES)}\n\n"

    # Per-channel content
    if CHANNEL_IMAGES or CHANNEL_VIDEOS or CHANNEL_LINKS or CHANNEL_PROMO_IMAGES:
        text += "━━━ PER CHANNEL ━━━\n\n"
        
        for channel_id in MANAGED_CHANNELS.keys():
            channel_name = MANAGED_CHANNELS[channel_id]['name']
            
            images = len(CHANNEL_IMAGES.get(channel_id, []))
            videos = len(CHANNEL_VIDEOS.get(channel_id, []))
            links = len(CHANNEL_LINKS.get(channel_id, []))
            promos = len(CHANNEL_PROMO_IMAGES.get(channel_id, []))
            
            if images or videos or links or promos:
                text += f"*{channel_name}*\n"
                if images:
                    text += f"  📸 Images: {images}\n"
                if videos:
                    text += f"  🎥 Videos: {videos}\n"
                if links:
                    text += f"  🔗 Links: {links}\n"
                if promos:
                    text += f"  📢 Promos: {promos}\n"
                text += "\n"
    
    if text == "📂 *Content Library*\n\n" + f"Global Images: {len(UPLOADED_IMAGES)}\n\n":
        text += "No channel-specific content uploaded yet"

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all images"""
    if not await owner_only_check(update, context):
        return

    UPLOADED_IMAGES.clear()
    CHANNEL_SPECIFIC_IMAGES.clear()
    CHANNEL_IMAGES.clear()
    save_data()

    await update.message.reply_text("✅ All images cleared")


async def clear_channel_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all media from a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "Clear channel media:\n\n"
        text += "Usage: `/clear_channel_media CHANNEL_ID`\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            text += f"{data['name']}: `{channel_id}`\n"

        await update.message.reply_text(text, parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        # Clear all content for this channel
        if channel_id in CHANNEL_IMAGES:
            del CHANNEL_IMAGES[channel_id]
        if channel_id in CHANNEL_VIDEOS:
            del CHANNEL_VIDEOS[channel_id]
        if channel_id in CHANNEL_LINKS:
            del CHANNEL_LINKS[channel_id]
        if channel_id in CHANNEL_PROMO_IMAGES:
            del CHANNEL_PROMO_IMAGES[channel_id]
        if channel_id in CHANNEL_SPECIFIC_IMAGES:
            del CHANNEL_SPECIFIC_IMAGES[channel_id]
        
        save_data()

        await update.message.reply_text(
            f"✅ All media cleared for {MANAGED_CHANNELS[channel_id]['name']}")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def disable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable auto-posting"""
    if not await owner_only_check(update, context):
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

            try:
                scheduler.remove_job(f'autopost_{channel_id}')
            except:
                pass

            await update.message.reply_text(
                f"✅ Auto-post disabled for {MANAGED_CHANNELS[channel_id]['name']}")
        else:
            await update.message.reply_text("❌ Auto-post not enabled for this channel")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def autopost_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show auto-post status"""
    if not await owner_only_check(update, context):
        return

    if not AUTO_POST_ENABLED:
        await update.message.reply_text("No auto-posts enabled")
        return

    text = "🤖 *Auto-Post Status*\n\n"
    active_count = 0
    
    for channel_id, enabled in AUTO_POST_ENABLED.items():
        if enabled:
            channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
            intervals = POSTING_INTERVALS.get(channel_id, {'base': 20, 'var_min': 2, 'var_max': 15})
            content_type = CHANNEL_CONTENT_TYPE.get(channel_id, 'image')
            
            text += f"✅ *{channel_name}*\n"
            text += f"   Type: {content_type}\n"
            text += f"   Interval: {intervals['base']}m ±({intervals['var_min']}-{intervals['var_max']})\n\n"
            active_count += 1

    if active_count == 0:
        text = "No active auto-posts"
    
    await update.message.reply_text(text, parse_mode='Markdown')


async def send_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick send media/text to channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        if not MANAGED_CHANNELS:
            await update.message.reply_text("No channels added yet")
            return

        text = "Send to channel:\n\n"
        text += "Usage: `/send_to_channel CHANNEL_ID`\n\n"
        text += "Your channels:\n"
        for channel_id, data in MANAGED_CHANNELS.items():
            text += f"{data['name']}: `{channel_id}`\n"
        text += "\nThen send your media/text"

        await update.message.reply_text(text, parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        context.user_data['quick_send_channel'] = channel_id
        context.user_data['quick_send_mode'] = True

        await update.message.reply_text(
            f"✅ Quick Send Mode: {MANAGED_CHANNELS[channel_id]['name']}\n\n"
            f"Send your media or text now.\n"
            f"Use /cancel to stop")

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current operation"""
    if not await owner_only_check(update, context):
        return

    context.user_data.clear()
    await update.message.reply_text("✅ All operations cancelled")


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start posting mode"""
    if not await owner_only_check(update, context):
        return

    context.user_data['posting_mode'] = True
    await update.message.reply_text(
        "📤 *Posting Mode Enabled*\n\n"
        "Send me content to post (text, photo, video, or document)",
        parse_mode='Markdown')


async def view_unauthorized_attempts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View unauthorized access attempts"""
    if not await owner_only_check(update, context):
        return

    if not UNAUTHORIZED_ATTEMPTS:
        await update.message.reply_text("No unauthorized attempts")
        return

    text = "🚨 *Unauthorized Attempts*\n\n"
    for attempt in UNAUTHORIZED_ATTEMPTS[-10:]:  # Last 10
        text += (f"User: {attempt['first_name']}\n"
                f"ID: `{attempt['user_id']}`\n"
                f"Username: @{attempt.get('username', 'None')}\n"
                f"Command: {attempt['command']}\n"
                f"Time: {attempt['timestamp'].strftime('%Y-%m-%d %H:%M')}\n\n")

    await update.message.reply_text(text, parse_mode='Markdown')


async def clear_unauthorized_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear unauthorized attempts log"""
    if not await owner_only_check(update, context):
        return

    count = len(UNAUTHORIZED_ATTEMPTS)
    UNAUTHORIZED_ATTEMPTS.clear()
    await update.message.reply_text(f"✅ Cleared {count} unauthorized attempts")


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
        text += "━━━━━━━━━━━━━━━━━━\n✅ Recently Approved:\n\n"
        for activity in approved[-10:]:
            text += f"• {activity['user_name']}\n"
            text += f"  @{activity['username']}\n"
            text += f"  Channel: {activity['channel']}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    if rejected:
        text += "━━━━━━━━━━━━━━━━━━\n❌ Recently Rejected:\n\n"
        for activity in rejected[-5:]:
            text += f"• {activity['user_name']}\n"
            text += f"  Reason: {activity['reason']}\n"
            text += f"  Time: {activity['timestamp'].strftime('%H:%M')}\n\n"

    await update.message.reply_text(text)


async def clear_recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear recent activity log"""
    if not await owner_only_check(update, context):
        return

    count = len(RECENT_ACTIVITY)
    RECENT_ACTIVITY.clear()
    await update.message.reply_text(f"✅ Cleared {count} activity records")


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


async def approve_all_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve all pending verifications"""
    if not await owner_only_check(update, context):
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
        f"✅ *Bulk Approval Complete*\n\nApproved: {approved}\nFailed: {failed}",
        parse_mode='Markdown')


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
            f"✅ User blocked!\n\nUser ID: `{user_id}`\n"
            f"They cannot join any managed channel",
            parse_mode='Markdown')

        logger.info(f"✅ User blocked: {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unblock a user"""
    if not await owner_only_check(update, context):
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
                f"✅ User unblocked!\n\nUser ID: `{user_id}`",
                parse_mode='Markdown')
            logger.info(f"✅ User unblocked: {user_id}")
        else:
            await update.message.reply_text("❌ User not in blocked list")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def export_users_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export user database"""
    if not await owner_only_check(update, context):
        return

    if not USER_DATABASE:
        await update.message.reply_text("No user data to export")
        return

    # Create CSV
    csv_text = "User ID,First Name,Last Name,Username,Channels\n"
    for user_id, data in USER_DATABASE.items():
        channels = ', '.join([ch['channel_name'] for ch in data['channels'].values()])
        first_name = data.get('first_name', '').replace(',', ' ')
        last_name = data.get('last_name', '').replace(',', ' ')
        username = data.get('username', '')
        csv_text += f"{user_id},{first_name},{last_name},{username},{channels}\n"

    # Send as file
    file = BytesIO(csv_text.encode('utf-8'))
    file.name = f"users_{datetime.now().strftime('%Y%m%d')}.csv"

    await update.message.reply_document(
        document=file,
        filename=file.name,
        caption=f"📊 User Database Export\n\nTotal Users: {len(USER_DATABASE)}")


async def user_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    if not await owner_only_check(update, context):
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


async def toggle_bulk_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle bulk approval mode for a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/toggle_bulk CHANNEL_ID`\n\n"
            "Toggles between:\n"
            "🛡️ Smart Verification\n"
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

        new_mode = "🔄 Bulk Mode" if BULK_APPROVAL_MODE[channel_id] else "🛡️ Smart Verification"

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


async def set_preview_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set preview channel for rejected users"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/set_preview_channel MAIN_CHANNEL_ID PREVIEW_CHANNEL_ID`\n\n"
            "Rejected users from main channel will get preview channel invite",
            parse_mode='Markdown')
        return

    try:
        main_channel_id = int(context.args[0])
        preview_channel_id = int(context.args[1])

        if main_channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Main channel not managed")
            return

        is_admin = await is_bot_admin(context, preview_channel_id)
        if not is_admin:
            await update.message.reply_text("❌ Bot is not admin in preview channel")
            return

        PREVIEW_CHANNELS[main_channel_id] = preview_channel_id
        save_data()

        await update.message.reply_text(
            f"✅ Preview channel set!\n\n"
            f"Main: {MANAGED_CHANNELS[main_channel_id]['name']}\n"
            f"Preview ID: `{preview_channel_id}`\n\n"
            f"Rejected users will receive preview invite",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel IDs")


async def verification_thresholds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View/set verification thresholds"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        text = (
            f"⚙️ *Verification Thresholds*\n\n"
            f"Auto-Approve: ≥{VERIFICATION_THRESHOLDS['auto_approve_score']}\n"
            f"Manual Review: ≥{VERIFICATION_THRESHOLDS['manual_review_score']}\n"
            f"Auto-Reject: <{VERIFICATION_THRESHOLDS['manual_review_score']}\n\n"
            f"**Scoring:**\n"
            f"• Real name: 40 pts\n"
            f"• Username: 30 pts\n"
            f"• Profile photo: 30 pts\n\n"
            f"To change: `/verification_thresholds approve manual reject`\n"
            f"Example: `/verification_thresholds 70 30 0`"
        )
        await update.message.reply_text(text, parse_mode='Markdown')
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/verification_thresholds AUTO_APPROVE MANUAL_REVIEW AUTO_REJECT`",
            parse_mode='Markdown')
        return

    try:
        auto_approve = int(context.args[0])
        manual_review = int(context.args[1])
        auto_reject = int(context.args[2])

        VERIFICATION_THRESHOLDS['auto_approve_score'] = auto_approve
        VERIFICATION_THRESHOLDS['manual_review_score'] = manual_review
        VERIFICATION_THRESHOLDS['auto_reject_score'] = auto_reject
        save_data()

        await update.message.reply_text(
            f"✅ Thresholds updated!\n\n"
            f"Auto-Approve: ≥{auto_approve}\n"
            f"Manual Review: {manual_review}-{auto_approve-1}\n"
            f"Auto-Reject: <{manual_review}")

    except ValueError:
        await update.message.reply_text("❌ Invalid numbers")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed help guide"""
    if not await owner_only_check(update, context):
        return

    text = (
        "📖 *Detailed Help Guide*\n\n"
        
        "**QUICK START:**\n"
        "1. `/addchannel -100XXX Name`\n"
        "2. `/set_content_type -100XXX image`\n"
        "3. `/set_smart_interval -100XXX 20 2 15`\n"
        "4. `/upload_images -100XXX` (send content)\n"
        "5. `/done_uploading`\n"
        "6. `/enable_autopost -100XXX`\n\n"
        
        "**SMART INTERVALS:**\n"
        "Base 20, Var ±(2-15) = posts 18-35 mins\n"
        "Each post time is random!\n\n"
        
        "**BULK LINKS:**\n"
        "Upload .xlsx/.txt/.csv/.pdf files\n"
        "Bot extracts all links automatically\n"
        "Update monthly: `/replace_links`\n\n"
        
        "**CAPTIONS:**\n"
        "Priority: Image caption > Channel caption > Global caption\n\n"
        
        "For full documentation, see bot files"
    )
    
    await update.message.reply_text(text, parse_mode='Markdown')


async def resend_code_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for resend code"""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Unauthorized", show_alert=True)
        return
    await query.answer("Feature not applicable")


async def replace_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replace all links in channel (for monthly updates)"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/replace_links CHANNEL_ID`\n\n"
            "This will REPLACE all existing links.\n"
            "Then send your document (.txt, .xlsx, .csv, .pdf)\n\n"
            "Perfect for weekly/monthly link updates!",
            parse_mode='Markdown')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        # Clear existing links
        CHANNEL_LINKS[channel_id] = []
        save_data()

        # Enter upload mode
        context.user_data['uploading_for_channel'] = channel_id
        context.user_data['uploading_mode'] = True
        context.user_data['replacing_links'] = True

        await update.message.reply_text(
            f"🔄 *Replace Links Mode*\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n\n"
            f"Old links cleared!\n\n"
            f"Send your document now:\n"
            f"✅ .txt file with links\n"
            f"✅ .xlsx/.xls Excel file\n"
            f"✅ .csv file\n"
            f"✅ .pdf file\n\n"
            f"Or send links one by one\n"
            f"Use /done_uploading when finished",
            parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")


async def handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle content"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    # Handle quick send mode
    if context.user_data.get('quick_send_mode'):
        channel_id = context.user_data.get('quick_send_channel')
        message = update.message

        try:
            if message.text:
                await context.bot.send_message(channel_id, message.text)
            elif message.photo:
                await context.bot.send_photo(channel_id, message.photo[-1].file_id,
                                             caption=message.caption)
            elif message.video:
                await context.bot.send_video(channel_id, message.video.file_id,
                                             caption=message.caption)
            elif message.document:
                await context.bot.send_document(channel_id, message.document.file_id,
                                                caption=message.caption)

            await update.message.reply_text(
                f"✅ Sent to {MANAGED_CHANNELS[channel_id]['name']}\n\n"
                f"Send more or use /cancel to stop")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed: {str(e)}")
        return

    # Handle posting mode
    if context.user_data.get('posting_mode'):
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
                InlineKeyboardButton(f"📢 {data['name']}", callback_data=f"post_{channel_id}")
            ])
        keyboard.append([InlineKeyboardButton("🔄 ALL CHANNELS", callback_data="post_all")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="post_cancel")])

        await update.message.reply_text(
            "🎯 Select Channel:",
            reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['posting_mode'] = False
        return

    # Handle upload mode
    if context.user_data.get('uploading_mode'):
        if update.message.document:
            await handle_document_upload(update, context)
        else:
            await handle_image_upload(update, context)
        return


async def post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle post selection"""
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

    channels = [int(action)] if action != "all" else list(MANAGED_CHANNELS.keys())

    await query.edit_message_text("⏳ Posting...")
    success = 0
    failed = 0

    for channel_id in channels:
        try:
            if pending['type'] == 'text':
                await context.bot.send_message(channel_id, original_msg.text)
            elif pending['type'] == 'photo':
                await context.bot.send_photo(channel_id, original_msg.photo[-1].file_id,
                                             caption=original_msg.caption)
            elif pending['type'] == 'video':
                await context.bot.send_video(channel_id, original_msg.video.file_id,
                                             caption=original_msg.caption)
            elif pending['type'] == 'document':
                await context.bot.send_document(channel_id, original_msg.document.file_id,
                                                caption=original_msg.caption)
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Post failed for {channel_id}: {e}")

    del PENDING_POSTS[ADMIN_ID]

    result_text = f"✅ *Posted!*\n\nSuccess: {success}\nFailed: {failed}"
    await query.message.reply_text(result_text, parse_mode='Markdown')


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Exception: {context.error}")


def main():
    """Main function"""
    logger.info("🚀 Starting SMART STAGGERED BOT...")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")

    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands - Setup
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("stats", stats))
    
    # Commands - Channel Config
    app.add_handler(CommandHandler("set_smart_interval", set_smart_interval))
    app.add_handler(CommandHandler("set_content_type", set_content_type))
    app.add_handler(CommandHandler("set_promo_freq", set_promo_frequency))
    
    # Commands - Content Upload
    app.add_handler(CommandHandler("upload_images", upload_images_command))
    app.add_handler(CommandHandler("upload_promo", upload_promo))
    app.add_handler(CommandHandler("replace_links", replace_links))
    app.add_handler(CommandHandler("done_uploading", done_uploading))
    app.add_handler(CommandHandler("list_content", list_content))
    app.add_handler(CommandHandler("clear_images", clear_images))
    app.add_handler(CommandHandler("clear_channel_media", clear_channel_media))
    
    # Commands - Captions
    app.add_handler(CommandHandler("set_default_caption", set_default_caption))
    app.add_handler(CommandHandler("clear_default_caption", clear_default_caption))
    app.add_handler(CommandHandler("set_channel_caption", set_channel_caption))
    app.add_handler(CommandHandler("clear_channel_caption", clear_channel_caption))
    
    # Commands - Auto-Posting
    app.add_handler(CommandHandler("enable_autopost", enable_autopost))
    app.add_handler(CommandHandler("disable_autopost", disable_autopost))
    app.add_handler(CommandHandler("autopost_status", autopost_status))
    
    # Commands - Manual Posting
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("send_to_channel", send_to_channel))
    app.add_handler(CommandHandler("cancel", cancel_command))
    
    # Commands - User Management
    app.add_handler(CommandHandler("recent_activity", view_recent_activity))
    app.add_handler(CommandHandler("pending_users", pending_users))
    app.add_handler(CommandHandler("approve_user", manual_approve_user))
    app.add_handler(CommandHandler("approve_all_pending", approve_all_pending))
    app.add_handler(CommandHandler("block_user", block_user))
    app.add_handler(CommandHandler("unblock_user", unblock_user))
    app.add_handler(CommandHandler("user_stats", user_stats_command))
    app.add_handler(CommandHandler("export_users", export_users_report))
    
    # Commands - Verification
    app.add_handler(CommandHandler("verification_thresholds", verification_thresholds_command))
    app.add_handler(CommandHandler("toggle_bulk", toggle_bulk_approval))
    app.add_handler(CommandHandler("set_preview_channel", set_preview_channel))
    
    # Commands - Security
    app.add_handler(CommandHandler("view_unauthorized", view_unauthorized_attempts))
    app.add_handler(CommandHandler("clear_unauthorized", clear_unauthorized_log))
    app.add_handler(CommandHandler("clear_activity", clear_recent_activity))

    # Callbacks
    app.add_handler(CallbackQueryHandler(enter_code_callback, pattern="^enter_code_"))
    app.add_handler(CallbackQueryHandler(resend_code_callback, pattern="^resend_code_"))
    app.add_handler(CallbackQueryHandler(post_callback, pattern="^post_"))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_content))
    app.add_handler(MessageHandler(filters.PHOTO, handle_content))
    app.add_handler(MessageHandler(filters.VIDEO, handle_content))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_content))

    # Join requests
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # Error handler
    app.add_error_handler(error_handler)

    # Start scheduler
    scheduler.start()

    # Restore auto-posting
    for channel_id, enabled in AUTO_POST_ENABLED.items():
        if enabled:
            try:
                next_interval = get_next_post_interval(channel_id)
                next_run = datetime.now() + timedelta(minutes=next_interval)
                
                scheduler.add_job(
                    auto_post_job,
                    trigger='date',
                    run_date=next_run,
                    args=[app.bot, channel_id],
                    id=f'autopost_{channel_id}',
                    replace_existing=True
                )
                logger.info(f"✅ Auto-post restored for {channel_id}")
            except Exception as e:
                logger.error(f"Failed to restore: {e}")

    logger.info(f"✅ Bot running with smart staggering!")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
