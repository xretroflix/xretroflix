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

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not set! Add it in Railway Variables tab")
if ADMIN_ID == 0:
    raise ValueError("❌ ADMIN_ID not set! Add it in Railway Variables tab")

VERIFIED_USERS = set([ADMIN_ID])
MANAGED_CHANNELS = {}
PENDING_POSTS = {}
PENDING_VERIFICATIONS = {}  # {user_id: {questions, answers, current_q, chat_id, request}}
VERIFIED_FOR_CHANNELS = {}
BLOCKED_USERS = set()
BULK_APPROVAL_MODE = {}

# Storage system
IMAGE_STORAGE_CHANNEL = None
VIDEO_STORAGE_CHANNEL = None

STORAGE_IMAGES = []
STORAGE_VIDEOS = []
STORAGE_LINKS = []

# Channel configuration
CHANNEL_CONFIG = {}
CHANNEL_PAUSE_STATUS = {}
CHANNEL_POST_COUNT = {}

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

# VERIFICATION QUESTIONS BANK
VERIFICATION_QUESTIONS = [
    {
        "question": "What is 7 + 5?",
        "answers": ["12", "twelve"],
        "type": "math"
    },
    {
        "question": "What comes after Monday?",
        "answers": ["tuesday", "tues"],
        "type": "general"
    },
    {
        "question": "What color is the sky?",
        "answers": ["blue", "sky blue"],
        "type": "general"
    },
    {
        "question": "How many days in a week?",
        "answers": ["7", "seven"],
        "type": "general"
    },
    {
        "question": "What is 10 - 3?",
        "answers": ["7", "seven"],
        "type": "math"
    },
    {
        "question": "Capital of India?",
        "answers": ["delhi", "new delhi"],
        "type": "general"
    },
    {
        "question": "How many fingers on one hand?",
        "answers": ["5", "five"],
        "type": "general"
    },
    {
        "question": "What is 4 x 3?",
        "answers": ["12", "twelve"],
        "type": "math"
    }
]


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
    global IMAGE_STORAGE_CHANNEL, VIDEO_STORAGE_CHANNEL
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


def is_name_suspicious(name: str) -> bool:
    """
    NEW: RELAXED verification - Only block REALLY suspicious names
    ✅ Allow: Emojis, short names, non-English, numbers
    ❌ Block: Spam keywords, suspicious patterns
    """
    if not name or len(name.strip()) == 0:
        return True  # Empty name is suspicious

    name_lower = name.lower().strip()

    # DANGEROUS KEYWORDS - Immediate block
    dangerous_keywords = [
        'police', 'admin', 'administrator', 'moderator', 'support',
        'official', 'telegram', 'verified', 'staff', 'owner',
        'anonymous', 'deleted', 'account', 'crypto', 'bitcoin',
        'investment', 'trading', 'profit', 'earn', 'money',
        'casino', 'betting', 'forex', 'channel', 'group',
        'promotion', 'advertising', 'marketing', 'scam',
        'hack', 'hacker', 'spam', 'bot', 'automated'
    ]

    for keyword in dangerous_keywords:
        if keyword in name_lower:
            logger.warning(f"⚠️ Suspicious keyword detected: {keyword} in name: {name}")
            return True

    # Check for URL/link patterns in name
    if re.search(r'(https?://|www\.|\.com|\.net|\.org|t\.me)', name_lower):
        logger.warning(f"⚠️ URL detected in name: {name}")
        return True

    # Check for excessive symbols (more than 50% of name)
    symbols = re.findall(r'[^\w\s]', name)
    if len(symbols) > len(name) * 0.5 and len(name) > 5:
        logger.warning(f"⚠️ Too many symbols in name: {name}")
        return True

    # ✅ Everything else is OK - allow emojis, short names, non-English
    return False


async def check_user_legitimacy(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """
    NEW: Simplified legitimacy check
    Only checks: Is it a bot? Is name suspicious?
    Does NOT penalize: missing username, missing photo, short names
    """
    try:
        user = await context.bot.get_chat(user_id)

        # Check if it's a bot account
        if user.type == "bot":
            return {"legitimate": False, "reason": "Bot account", "score": 0}

        # Check name for suspicious patterns
        if not user.first_name:
            return {"legitimate": False, "reason": "No name", "score": 0}

        if is_name_suspicious(user.first_name):
            return {"legitimate": False, "reason": "Suspicious name pattern", "score": 0}

        # ✅ If passes above checks, consider legitimate
        # We'll use 3-question verification for extra security
        return {"legitimate": True, "score": 100}

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
            parse_mode='HTML')
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


# ========== 3-QUESTION VERIFICATION SYSTEM ==========
async def start_verification(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, request, reason: str):
    """Start 3-question verification process"""
    
    # Select 3 random questions
    selected_questions = random.sample(VERIFICATION_QUESTIONS, 3)
    
    PENDING_VERIFICATIONS[user_id] = {
        'chat_id': chat_id,
        'request': request,
        'questions': selected_questions,
        'current_question': 0,
        'correct_answers': 0,
        'failed_attempts': 0,
        'timestamp': datetime.now(),
        'reason': reason
    }

    track_user_activity(user_id, chat_id, 'verification', {
        'first_name': request.from_user.first_name,
        'last_name': request.from_user.last_name or '',
        'username': request.from_user.username or ''
    })

    # Send first question to user
    try:
        first_q = selected_questions[0]['question']
        await context.bot.send_message(
            user_id,
            f"🔐 *Verification Required*\n\n"
            f"Please answer 3 questions to join the channel.\n\n"
            f"**Question 1/3:**\n{first_q}\n\n"
            f"Reply with your answer:",
            parse_mode='HTML'
        )
        
        # Notify admin
        user_link = f"tg://user?id={user_id}"
        await context.bot.send_message(
            ADMIN_ID,
            f"🔐 *Verification Started*\n\n"
            f"User: [{request.from_user.first_name}]({user_link})\n"
            f"ID: `{user_id}`\n"
            f"Channel: {MANAGED_CHANNELS[chat_id]['name']}\n"
            f"Reason: {reason}\n\n"
            f"User is answering 3 questions...",
            parse_mode='HTML'
        )
        
        logger.info(f"🔐 Started verification for user {user_id}")
        
    except Exception as e:
        logger.error(f"Failed to send verification question: {e}")
        # If can't DM user, notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"⚠️ Cannot send verification to user {user_id}\n"
            f"User may have blocked the bot or restricted DMs.\n"
            f"Approving automatically...",
            parse_mode='HTML'
        )
        # Auto-approve if can't verify
        await request.approve()
        track_user_activity(user_id, chat_id, 'approved')
        del PENDING_VERIFICATIONS[user_id]


async def handle_verification_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's answer to verification question"""
    user_id = update.effective_user.id
    
    if user_id not in PENDING_VERIFICATIONS:
        return  # Not in verification
    
    verification = PENDING_VERIFICATIONS[user_id]
    user_answer = update.message.text.strip().lower()
    
    current_q_index = verification['current_question']
    current_question = verification['questions'][current_q_index]
    correct_answers = current_question['answers']
    
    # Check if answer is correct
    is_correct = any(ans in user_answer for ans in correct_answers)
    
    if is_correct:
        verification['correct_answers'] += 1
        verification['current_question'] += 1
        
        # Check if all 3 questions answered
        if verification['current_question'] >= 3:
            # All questions answered - check pass/fail
            if verification['correct_answers'] >= 2:  # Need 2/3 correct
                # PASS - Approve user
                try:
                    await verification['request'].approve()
                    track_user_activity(user_id, verification['chat_id'], 'approved')
                    
                    RECENT_ACTIVITY.append({
                        'type': 'verification_passed',
                        'user_id': user_id,
                        'user_name': update.effective_user.first_name,
                        'username': update.effective_user.username or 'None',
                        'channel': MANAGED_CHANNELS[verification['chat_id']]['name'],
                        'channel_id': verification['chat_id'],
                        'score': f"{verification['correct_answers']}/3",
                        'timestamp': datetime.now()
                    })
                    
                    await update.message.reply_text(
                        f"✅ *Verification Passed!*\n\n"
                        f"Score: {verification['correct_answers']}/3\n"
                        f"You can now join the channel!",
                        parse_mode='HTML'
                    )
                    
                    # Notify admin
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"✅ *Verification Passed*\n\n"
                        f"User: {update.effective_user.first_name}\n"
                        f"ID: `{user_id}`\n"
                        f"Score: {verification['correct_answers']}/3\n"
                        f"Status: Approved",
                        parse_mode='HTML'
                    )
                    
                    logger.info(f"✅ User {user_id} passed verification: {verification['correct_answers']}/3")
                    
                except Exception as e:
                    logger.error(f"Approval failed: {e}")
                    await update.message.reply_text(f"❌ Error approving. Contact admin.")
                
                del PENDING_VERIFICATIONS[user_id]
                
            else:
                # FAIL - Block user
                BLOCKED_USERS.add(user_id)
                save_data()
                
                try:
                    await verification['request'].decline()
                except:
                    pass
                
                RECENT_ACTIVITY.append({
                    'type': 'verification_failed',
                    'user_id': user_id,
                    'user_name': update.effective_user.first_name,
                    'username': update.effective_user.username or 'None',
                    'channel': MANAGED_CHANNELS[verification['chat_id']]['name'],
                    'channel_id': verification['chat_id'],
                    'score': f"{verification['correct_answers']}/3",
                    'timestamp': datetime.now()
                })
                
                await update.message.reply_text(
                    f"❌ *Verification Failed*\n\n"
                    f"Score: {verification['correct_answers']}/3\n"
                    f"You need at least 2/3 correct answers.\n\n"
                    f"You have been blocked from joining.",
                    parse_mode='HTML'
                )
                
                # Notify admin
                await context.bot.send_message(
                    ADMIN_ID,
                    f"❌ *Verification Failed*\n\n"
                    f"User: {update.effective_user.first_name}\n"
                    f"ID: `{user_id}`\n"
                    f"Score: {verification['correct_answers']}/3\n"
                    f"Status: Blocked",
                    parse_mode='HTML'
                )
                
                logger.info(f"❌ User {user_id} failed verification: {verification['correct_answers']}/3 - BLOCKED")
                del PENDING_VERIFICATIONS[user_id]
        
        else:
            # Send next question
            next_q = verification['questions'][verification['current_question']]['question']
            await update.message.reply_text(
                f"✅ Correct!\n\n"
                f"**Question {verification['current_question'] + 1}/3:**\n{next_q}\n\n"
                f"Reply with your answer:",
                parse_mode='HTML'
            )
    
    else:
        # Wrong answer
        verification['failed_attempts'] += 1
        
        if verification['failed_attempts'] >= 5:  # Too many wrong attempts
            # Block user
            BLOCKED_USERS.add(user_id)
            save_data()
            
            try:
                await verification['request'].decline()
            except:
                pass
            
            await update.message.reply_text(
                f"❌ *Too Many Wrong Attempts*\n\n"
                f"You have been blocked.",
                parse_mode='HTML'
            )
            
            await context.bot.send_message(
                ADMIN_ID,
                f"❌ User {user_id} blocked - too many wrong attempts",
                parse_mode='HTML'
            )
            
            del PENDING_VERIFICATIONS[user_id]
        else:
            await update.message.reply_text(
                f"❌ Incorrect. Try again.\n\n"
                f"**Question {current_q_index + 1}/3:**\n{current_question['question']}",
                parse_mode='HTML'
            )


# ========== SMART JOIN REQUEST HANDLER ==========
async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    NEW: Smart verification with 3-question system
    - Auto-approve clean users
    - 3-question verification for borderline users
    - Instant block for suspicious users
    """
    request = update.chat_join_request
    user = request.from_user
    chat_id = request.chat.id

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

    # Check if bulk approval is enabled
    if BULK_APPROVAL_MODE.get(chat_id, False):
        await request.approve()
        track_user_activity(user.id, chat_id, 'approved', {
            'first_name': user.first_name,
            'last_name': user.last_name or '',
            'username': user.username or ''
        })
        logger.info(f"✅ Bulk-approved user: {user.id}")
        return

    # Check legitimacy
    legitimacy = await check_user_legitimacy(context, user.id)

    # INSTANT BLOCK for truly suspicious users
    if not legitimacy['legitimate'] and legitimacy['score'] == 0:
        try:
            await request.decline()
            BLOCKED_USERS.add(user.id)
            save_data()
            
            RECENT_ACTIVITY.append({
                'type': 'auto_blocked',
                'user_id': user.id,
                'user_name': user.first_name or 'No Name',
                'username': user.username or 'None',
                'channel': MANAGED_CHANNELS[chat_id]['name'],
                'channel_id': chat_id,
                'reason': legitimacy.get('reason', 'Suspicious'),
                'timestamp': datetime.now()
            })

            logger.info(f"❌ Auto-blocked suspicious user: {user.id} - Reason: {legitimacy.get('reason')}")
            
            # Notify admin
            await context.bot.send_message(
                ADMIN_ID,
                f"🚫 *Auto-Blocked*\n\n"
                f"User: {user.first_name}\n"
                f"ID: `{user.id}`\n"
                f"Reason: {legitimacy.get('reason')}",
                parse_mode='HTML'
            )
            return
            
        except Exception as e:
            logger.error(f"Auto-block failed: {e}")

    # For all other users - Start 3-question verification
    await start_verification(
        context, 
        user.id, 
        chat_id, 
        request,
        "Standard verification"
    )


# ========== STORAGE MANAGEMENT (Same as before) ==========
async def set_image_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set image storage channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_image_storage CHANNEL_ID`",
            parse_mode='HTML')
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
            parse_mode='HTML')

    except ValueError:
        await update.message.reply_text("❌ Invalid channel ID")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def set_video_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set video storage channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/set_video_storage CHANNEL_ID`",
            parse_mode='HTML')
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
            parse_mode='HTML')

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
            offset = 0
            while True:
                messages = []
                async for message in context.bot.get_chat_history(IMAGE_STORAGE_CHANNEL, limit=100, offset=offset):
                    messages.append(message)
                
                if not messages:
                    break
                    
                for message in messages:
                    if message.photo:
                        STORAGE_IMAGES.append({
                            'file_id': message.photo[-1].file_id,
                            'caption': message.caption or ''
                        })
                        images_count += 1
                
                offset += 100
                
                if len(messages) < 100:
                    break
                    
        except Exception as e:
            logger.error(f"Failed to load from image storage: {e}")

    # Load from video storage
    if VIDEO_STORAGE_CHANNEL:
        try:
            offset = 0
            while True:
                messages = []
                async for message in context.bot.get_chat_history(VIDEO_STORAGE_CHANNEL, limit=100, offset=offset):
                    messages.append(message)
                
                if not messages:
                    break
                    
                for message in messages:
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
                
                offset += 100
                
                if len(messages) < 100:
                    break
                    
        except Exception as e:
            logger.error(f"Failed to load from video storage: {e}")

    save_data()

    await update.message.reply_text(
        f"✅ *Storage Loaded!*\n\n"
        f"📸 Images: {images_count}\n"
        f"🎥 Videos/Mixed: {videos_count}\n"
        f"🔗 Links: {len(STORAGE_LINKS)}",
        parse_mode='HTML')


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
    """Handle uploaded link file"""
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
            parse_mode='HTML')

        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Link file processing failed: {e}")


# ========== CHANNEL SETUP & MANAGEMENT (Same as before) ==========
async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """One-command channel setup"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 5:
        await update.message.reply_text(
            "Usage: /setup_channel CHANNEL_ID \"Name\" TYPE INTERVAL \"CAPTION\"\n\n"
            "Example:\n"
            "/setup_channel -1001234567890 \"Glamour\" images 30 \"💎 Premium Content\"\n\n"
            "Types: images, videos, links, mixed\n"
            "Interval: minutes (30, 45, 60, etc)")
        return

    try:
        channel_id = int(context.args[0])
        
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

        # FIX: Removed parse_mode to avoid Markdown errors
        await update.message.reply_text(
            f"✅ Channel Configured!\n\n"
            f"Name: {channel_name}\n"
            f"ID: {channel_id}\n"
            f"Type: {content_type}\n"
            f"Interval: {interval} min\n"
            f"Caption: {caption}\n\n"
            f"Use /enable_autopost {channel_id} to start!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logger.error(f"Setup channel failed: {e}")


async def change_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change channel caption"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /change_caption CHANNEL_ID \"New caption\"")
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

        # FIX: Removed parse_mode
        await update.message.reply_text(
            f"✅ Caption updated!\n\n"
            f"New: {new_caption}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change posting interval"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /change_interval CHANNEL_ID MINUTES")
        return

    try:
        channel_id = int(context.args[0])
        interval = int(context.args[1])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['interval'] = interval
        save_data()

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

        # FIX: Removed parse_mode
        await update.message.reply_text(
            f"✅ Interval updated to {interval} minutes!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_content_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change content type"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /change_content_type CHANNEL_ID TYPE\n\n"
            "Types: images, videos, links, mixed")
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

        # FIX: Removed parse_mode
        await update.message.reply_text(
            f"✅ Content type changed to: {content_type}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View channel info"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /channel_info CHANNEL_ID")
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

        # FIX: Removed Markdown formatting and parse_mode
        text = (
            f"━━━━━━━━━━━━━━━━\n"
            f"📢 {channel_name}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"ID: {channel_id}\n"
            f"Content: {config['type']}\n"
            f"Interval: {config['interval']} min\n"
            f"Caption: {config['caption']}\n"
            f"Status: {'⏸️ Paused' if paused else '▶️ Active'}\n"
            f"Auto-post: {'✅ Enabled' if config.get('enabled') else '❌ Disabled'}\n"
            f"Polls: {'✅ Every ' + str(config['poll_frequency']) + 'th' if config.get('polls') else '❌ Disabled'}\n"
            f"Total Posts: {post_count}\n"
            f"━━━━━━━━━━━━━━━━"
        )

        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# Continue with remaining functions from previous code...
# (change_caption, change_interval, etc. - keep exactly as before)

# Due to length, I'll provide the continuation in next response
# The rest of the code remains identical to the previous version

async def change_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change channel caption"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/change_caption CHANNEL_ID \"New caption\"`",
            parse_mode='HTML')
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
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change posting interval"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/change_interval CHANNEL_ID MINUTES`",
            parse_mode='HTML')
        return

    try:
        channel_id = int(context.args[0])
        interval = int(context.args[1])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['interval'] = interval
        save_data()

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
            parse_mode='HTML')

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
            parse_mode='HTML')
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
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def enable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable polls for channel"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/enable_polls CHANNEL_ID FREQUENCY`\n\n"
            "Example: `/enable_polls -1001234567890 5`",
            parse_mode='HTML')
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
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable polls"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/disable_polls CHANNEL_ID`",
            parse_mode='HTML')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['polls'] = False
        save_data()

        await update.message.reply_text("✅ Polls disabled!", parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def pause_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/pause CHANNEL_ID`",
            parse_mode='HTML')
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
            f"⏸️ Paused: {channel_name}",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def resume_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/resume CHANNEL_ID`",
            parse_mode='HTML')
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
            f"▶️ Resumed: {channel_name}",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def post_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Force post now"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/post_now CHANNEL_ID`",
            parse_mode='HTML')
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
    """Skip next post"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/skip_next CHANNEL_ID`",
            parse_mode='HTML')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_PAUSE_STATUS[channel_id] = True
        save_data()

        interval = CHANNEL_CONFIG[channel_id]['interval']
        
        async def resume_after_skip():
            await asyncio.sleep(interval * 60)
            CHANNEL_PAUSE_STATUS[channel_id] = False
            save_data()

        asyncio.create_task(resume_after_skip())

        await update.message.reply_text(
            f"⏭️ Next post skipped!\n\n"
            f"Will resume in {interval} minutes",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View channel info"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/channel_info CHANNEL_ID`",
            parse_mode='HTML')
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
            f"**Interval:** {config['interval']} min\n"
            f"**Caption:** {config['caption']}\n"
            f"**Status:** {'⏸️ Paused' if paused else '▶️ Active'}\n"
            f"**Auto-post:** {'✅ Enabled' if config.get('enabled') else '❌ Disabled'}\n"
            f"**Polls:** {'✅ Every ' + str(config['poll_frequency']) + 'th' if config.get('polls') else '❌ Disabled'}\n"
            f"**Total Posts:** {post_count}\n"
            f"━━━━━━━━━━━━━━━━"
        )

        await update.message.reply_text(text, parse_mode='HTML')

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

    await update.message.reply_text(text, parse_mode='HTML')


# ========== AUTO-POSTING JOB ==========
async def auto_post_job(bot, channel_id: int):
    """Auto-posting job"""
    try:
        if CHANNEL_PAUSE_STATUS.get(channel_id, False):
            logger.info(f"Channel {channel_id} is paused")
            return

        config = CHANNEL_CONFIG.get(channel_id)
        if not config or not config.get('enabled'):
            return

        content_type = config['type']
        caption = config['caption']
        
        CHANNEL_POST_COUNT[channel_id] = CHANNEL_POST_COUNT.get(channel_id, 0) + 1
        post_number = CHANNEL_POST_COUNT[channel_id]

        should_poll = config.get('polls', False) and (post_number % config.get('poll_frequency', 5) == 0)

        if should_poll:
            poll_questions = [
                ("Which content do you like? 💭", ["❤️ Love", "🔥 Amazing", "💎 Perfect", "👍 Good"]),
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
            if content_type == 'images':
                if not STORAGE_IMAGES:
                    logger.warning(f"No images for channel {channel_id}")
                    return
                media = random.choice(STORAGE_IMAGES)
                await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                
            elif content_type == 'videos':
                if not STORAGE_VIDEOS:
                    logger.warning(f"No videos for channel {channel_id}")
                    return
                media = random.choice(STORAGE_VIDEOS)
                if media['type'] == 'video':
                    await bot.send_video(chat_id=channel_id, video=media['file_id'], caption=caption)
                else:
                    await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                    
            elif content_type == 'links':
                if not STORAGE_LINKS:
                    logger.warning(f"No links for channel {channel_id}")
                    return
                link = random.choice(STORAGE_LINKS)
                text = f"{caption}\n\n{link['url']}"
                if link['caption']:
                    text = f"{caption}\n\n{link['caption']}\n\n{link['url']}"
                await bot.send_message(chat_id=channel_id, text=text)
                
            elif content_type == 'mixed':
                all_media = []
                if STORAGE_IMAGES:
                    all_media.extend([('image', m) for m in STORAGE_IMAGES])
                if STORAGE_VIDEOS:
                    all_media.extend([('video', m) for m in STORAGE_VIDEOS])
                if STORAGE_LINKS:
                    all_media.extend([('link', m) for m in STORAGE_LINKS])
                
                if not all_media:
                    logger.warning(f"No content for mixed channel {channel_id}")
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

            logger.info(f"✅ Auto-posted to channel {channel_id}")

        save_data()

    except Exception as e:
        logger.error(f"❌ Auto-post failed for channel {channel_id}: {e}")


async def enable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable auto-posting"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/enable_autopost CHANNEL_ID`",
            parse_mode='HTML')
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
            f"Bot will start posting! 🚀",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable auto-posting"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/disable_autopost CHANNEL_ID`",
            parse_mode='HTML')
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['enabled'] = False
        save_data()

        try:
            scheduler.remove_job(f'autopost_{channel_id}')
        except:
            pass

        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        await update.message.reply_text(
            f"✅ Auto-post disabled for {channel_name}",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ========== ORIGINAL COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user

    if user.id == ADMIN_ID:
        text = (
            "👋 *Welcome Owner!*\n\n"
            "🤖 Bot Status: Online 24/7\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
            f"🛡️ Smart Verification: Enabled\n\n"

            "━━━ STORAGE SETUP ━━━\n"
            "/set_image_storage - Image channel\n"
            "/set_video_storage - Video channel\n"
            "/reload_storage - Load media\n"
            "Send file - Upload links\n\n"

            "━━━ CHANNEL SETUP ━━━\n"
            "/setup_channel - Full setup\n"
            "/channel_info - View settings\n"
            "/all_channels - All channels\n\n"

            "━━━ MODIFICATIONS ━━━\n"
            "/change_caption - Caption\n"
            "/change_interval - Interval\n"
            "/change_content_type - Type\n"
            "/enable_polls - Polls\n"
            "/disable_polls - No polls\n\n"

            "━━━ CONTROL ━━━\n"
            "/enable_autopost - Start\n"
            "/disable_autopost - Stop\n"
            "/pause - Pause\n"
            "/resume - Resume\n"
            "/post_now - Post now\n"
            "/skip_next - Skip\n\n"

            "━━━ ACTIVITY ━━━\n"
            "/recent_activity - Activity\n"
            "/stats - Statistics\n"
            "/pending_users - Verifying\n\n"

            "━━━ APPROVALS ━━━\n"
            "/block_user - Block\n"
            "/unblock_user - Unblock\n"
            "/toggle_bulk - Bulk mode"
        )
    else:
        text = "Hello! This bot is for channel management."

    await update.message.reply_text(text, parse_mode='HTML')


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addchannel CHANNEL_ID CHANNEL_NAME`",
            parse_mode='HTML')
        return

    try:
        channel_id = int(context.args[0])
        channel_name = ' '.join(context.args[1:])

        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot is not admin")
            return

        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        save_data()

        await update.message.reply_text(
            f"✅ Channel added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: `{channel_id}`",
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List channels"""
    if not await owner_only_check(update, context):
        return

    if not MANAGED_CHANNELS:
        await update.message.reply_text("No channels added yet")
        return

    text = "📢 *Managed Channels:*\n\n"
    for channel_id, data in MANAGED_CHANNELS.items():
        text += f"{data['name']}\n"
        text += f"ID: `{channel_id}`\n\n"

    await update.message.reply_text(text, parse_mode='HTML')


async def pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending verifications"""
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
        text += f"Question: {data['current_question'] + 1}/3\n\n"

    await update.message.reply_text(text, parse_mode='HTML')


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block a user"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/block_user USER_ID`",
            parse_mode='HTML')
        return

    try:
        user_id = int(context.args[0])
        BLOCKED_USERS.add(user_id)
        save_data()

        await update.message.reply_text(
            f"✅ User blocked: `{user_id}`",
            parse_mode='HTML')

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unblock a user"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/unblock_user USER_ID`",
            parse_mode='HTML')
        return

    try:
        user_id = int(context.args[0])

        if user_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_id)
            save_data()
            await update.message.reply_text(f"✅ User unblocked: `{user_id}`", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ User not in blocked list")

    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")


async def toggle_bulk_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle bulk approval"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/toggle_bulk CHANNEL_ID`",
            parse_mode='HTML')
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
            parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def view_recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent activity"""
    if not await owner_only_check(update, context):
        return

    if not RECENT_ACTIVITY:
        await update.message.reply_text("No recent activity")
        return

    approved = [a for a in RECENT_ACTIVITY if a['type'] == 'verification_passed']
    blocked = [a for a in RECENT_ACTIVITY if a['type'] in ['auto_blocked', 'verification_failed']]

    text = "📊 *Recent Activity*\n\n"
    text += f"✅ Passed Verification: {len(approved)}\n"
    text += f"❌ Blocked: {len(blocked)}\n"
    text += f"⏳ Pending: {len(PENDING_VERIFICATIONS)}\n\n"

    if approved:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "✅ Recently Approved:\n\n"
        for activity in approved[-5:]:
            text += f"• {activity['user_name']}\n"
            text += f"  Score: {activity.get('score', 'N/A')}\n\n"

    if blocked:
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += "❌ Recently Blocked:\n\n"
        for activity in blocked[-5:]:
            text += f"• {activity['user_name']}\n"
            text += f"  Reason: {activity.get('reason', 'Failed verification')}\n\n"

    await update.message.reply_text(text, parse_mode='HTML')


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    if not await owner_only_check(update, context):
        return

    active_autoposts = sum(1 for v in CHANNEL_CONFIG.values() if v.get('enabled'))
    total_posts = sum(CHANNEL_POST_COUNT.values())
    recent_approved = sum(1 for a in RECENT_ACTIVITY if a['type'] == 'verification_passed')
    recent_blocked = sum(1 for a in RECENT_ACTIVITY if a['type'] in ['auto_blocked', 'verification_failed'])

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
        f"   ✅ Passed: {recent_approved}\n"
        f"   ❌ Blocked: {recent_blocked}\n"
        f"   ⏳ Pending: {len(PENDING_VERIFICATIONS)}\n"
        f"   🚫 Total Blocked: {len(BLOCKED_USERS)}\n\n"
        f"Status: Online 24/7 ✅"
    )
    await update.message.reply_text(text, parse_mode='HTML')


# Manual posting
async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual posting"""
    if not await owner_only_check(update, context):
        return
    
    context.user_data['posting_mode'] = True
    await update.message.reply_text(
        "📤 *Posting Mode*\n\nSend content to post",
        parse_mode='HTML')


async def handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle posting content"""
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
    """Main function"""
    logger.info("🚀 Starting BOT with 3-QUESTION VERIFICATION...")
    logger.info(f"✅ Admin ID: {ADMIN_ID}")

    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    # Storage
    app.add_handler(CommandHandler("set_image_storage", set_image_storage))
    app.add_handler(CommandHandler("set_video_storage", set_video_storage))
    app.add_handler(CommandHandler("reload_storage", reload_storage))

    # Channel setup
    app.add_handler(CommandHandler("setup_channel", setup_channel))
    app.add_handler(CommandHandler("change_caption", change_caption))
    app.add_handler(CommandHandler("change_interval", change_interval))
    app.add_handler(CommandHandler("change_content_type", change_content_type))
    app.add_handler(CommandHandler("enable_polls", enable_channel_polls))
    app.add_handler(CommandHandler("disable_polls", disable_channel_polls))

    # Control
    app.add_handler(CommandHandler("enable_autopost", enable_autopost))
    app.add_handler(CommandHandler("disable_autopost", disable_autopost))
    app.add_handler(CommandHandler("pause", pause_channel))
    app.add_handler(CommandHandler("resume", resume_channel))
    app.add_handler(CommandHandler("post_now", post_now_command))
    app.add_handler(CommandHandler("skip_next", skip_next_post))
    
    # Info
    app.add_handler(CommandHandler("channel_info", channel_info))
    app.add_handler(CommandHandler("all_channels", all_channels_info))

    # Original
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("pending_users", pending_users))
    app.add_handler(CommandHandler("block_user", block_user))
    app.add_handler(CommandHandler("unblock_user", unblock_user))
    app.add_handler(CommandHandler("toggle_bulk", toggle_bulk_approval))
    app.add_handler(CommandHandler("recent_activity", view_recent_activity))
    app.add_handler(CommandHandler("post", post_command))
    app.add_handler(CommandHandler("stats", stats))

    # Callbacks
    app.add_handler(CallbackQueryHandler(post_callback, pattern="^post_"))

    # Messages
    app.add_handler(MessageHandler(filters.Document.ALL, handle_link_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_verification_answer))  # NEW
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_content))

    # Join requests
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # Errors
    app.add_error_handler(error_handler)

    # Scheduler
    scheduler.start()

    # Restore auto-posting
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
                logger.info(f"✅ Auto-post restored: {channel_id} ({interval} min)")
            except Exception as e:
                logger.error(f"Failed to restore: {e}")

    logger.info(f"✅ Bot running - 3-Question Verification Active")
    logger.info(f"✅ Storage: {len(STORAGE_IMAGES)} images, {len(STORAGE_VIDEOS)} videos, {len(STORAGE_LINKS)} links")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
