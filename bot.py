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
    raise ValueError("❌ BOT_TOKEN not set!")
if ADMIN_ID == 0:
    raise ValueError("❌ ADMIN_ID not set!")

VERIFIED_USERS = set([ADMIN_ID])
MANAGED_CHANNELS = {}
PENDING_POSTS = {}
PENDING_VERIFICATIONS = {}
BLOCKED_USERS = set()
BULK_APPROVAL_MODE = {}

# SIMPLIFIED STORAGE - No channels needed!
STORAGE_IMAGES = []  # All images uploaded to bot
STORAGE_VIDEOS = []  # All videos uploaded to bot
STORAGE_LINKS = []   # All links from file
UPLOAD_MODE = False  # Upload mode toggle

# Channel configuration
CHANNEL_CONFIG = {}  # {channel_id: {type, interval, caption, enabled, polls}}
CHANNEL_PAUSE_STATUS = {}
CHANNEL_POST_COUNT = {}

USER_DATABASE = {}
RECENT_ACTIVITY = []
UNAUTHORIZED_ATTEMPTS = []

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

# Storage
STORAGE_DIR = "/app/data"
if not os.path.exists(STORAGE_DIR):
    try:
        os.makedirs(STORAGE_DIR)
    except:
        STORAGE_DIR = "."

STORAGE_FILE = os.path.join(STORAGE_DIR, "bot_data.json")

# Verification questions
VERIFICATION_QUESTIONS = [
    {"question": "What is 7 + 5?", "answers": ["12", "twelve"]},
    {"question": "What comes after Monday?", "answers": ["tuesday", "tues"]},
    {"question": "What color is the sky?", "answers": ["blue", "sky blue"]},
    {"question": "How many days in a week?", "answers": ["7", "seven"]},
    {"question": "What is 10 - 3?", "answers": ["7", "seven"]},
    {"question": "Capital of India?", "answers": ["delhi", "new delhi"]},
    {"question": "How many fingers on one hand?", "answers": ["5", "five"]},
    {"question": "What is 4 x 3?", "answers": ["12", "twelve"]}
]


def save_data():
    """Save all data"""
    try:
        data = {
            'managed_channels': MANAGED_CHANNELS,
            'channel_config': CHANNEL_CONFIG,
            'channel_pause_status': CHANNEL_PAUSE_STATUS,
            'channel_post_count': CHANNEL_POST_COUNT,
            'storage_images': STORAGE_IMAGES,
            'storage_videos': STORAGE_VIDEOS,
            'storage_links': STORAGE_LINKS,
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
    """Load all data"""
    global MANAGED_CHANNELS, CHANNEL_CONFIG, CHANNEL_PAUSE_STATUS, CHANNEL_POST_COUNT
    global STORAGE_IMAGES, STORAGE_VIDEOS, STORAGE_LINKS
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
            BULK_APPROVAL_MODE = data.get('bulk_approval_mode', {})
            BLOCKED_USERS = set(data.get('blocked_users', []))
            USER_DATABASE = data.get('user_database', {})

            # Convert keys to int
            MANAGED_CHANNELS = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in MANAGED_CHANNELS.items()}
            CHANNEL_CONFIG = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in CHANNEL_CONFIG.items()}
            CHANNEL_PAUSE_STATUS = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in CHANNEL_PAUSE_STATUS.items()}
            CHANNEL_POST_COUNT = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in CHANNEL_POST_COUNT.items()}
            BULK_APPROVAL_MODE = {int(k) if str(k).lstrip('-').isdigit() else k: v for k, v in BULK_APPROVAL_MODE.items()}

            logger.info(f"✅ Loaded: {len(STORAGE_IMAGES)} images, {len(STORAGE_VIDEOS)} videos, {len(STORAGE_LINKS)} links")
    except Exception as e:
        logger.error(f"Load failed: {e}")


async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return bot_member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False


def is_name_suspicious(name: str) -> bool:
    """Check suspicious names"""
    if not name or len(name.strip()) == 0:
        return True

    name_lower = name.lower().strip()
    
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
            return True

    if re.search(r'(https?://|www\.|\.com|\.net|\.org|t\.me)', name_lower):
        return True

    symbols = re.findall(r'[^\w\s]', name)
    if len(symbols) > len(name) * 0.5 and len(name) > 5:
        return True

    return False


async def check_user_legitimacy(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> dict:
    """Check user legitimacy"""
    try:
        user = await context.bot.get_chat(user_id)

        if user.type == "bot":
            return {"legitimate": False, "reason": "Bot account", "score": 0}

        if not user.first_name:
            return {"legitimate": False, "reason": "No name", "score": 0}

        if is_name_suspicious(user.first_name):
            return {"legitimate": False, "reason": "Suspicious name", "score": 0}

        return {"legitimate": True, "score": 100}

    except Exception as e:
        return {"legitimate": False, "reason": "Error", "score": 0}


def track_user_activity(user_id: int, channel_id: int, action: str, user_data: dict = None):
    """Track activity"""
    if user_id not in USER_DATABASE:
        USER_DATABASE[user_id] = {
            'first_name': user_data.get('first_name', 'Unknown') if user_data else 'Unknown',
            'channels': {}
        }
    USER_DATABASE[user_id]['channels'][channel_id] = {
        'status': action,
        'date': datetime.now()
    }
    save_data()


async def owner_only_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Owner check"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        if update.message:
            await update.message.reply_text("❌ Unauthorized")
        return False
    return True


# ========== 3-QUESTION VERIFICATION ==========
async def start_verification(context: ContextTypes.DEFAULT_TYPE, user_id: int, chat_id: int, request, reason: str):
    """Start verification"""
    selected_questions = random.sample(VERIFICATION_QUESTIONS, 3)
    
    PENDING_VERIFICATIONS[user_id] = {
        'chat_id': chat_id,
        'request': request,
        'questions': selected_questions,
        'current_question': 0,
        'correct_answers': 0,
        'failed_attempts': 0,
        'timestamp': datetime.now()
    }

    try:
        first_q = selected_questions[0]['question']
        await context.bot.send_message(
            user_id,
            f"🔐 Verification Required\n\n"
            f"Answer 3 questions to join.\n\n"
            f"Question 1/3:\n{first_q}\n\n"
            f"Reply with your answer:")
        
        await context.bot.send_message(
            ADMIN_ID,
            f"🔐 Verification Started\n\n"
            f"User: {request.from_user.first_name}\n"
            f"ID: {user_id}\n"
            f"Reason: {reason}")
        
    except Exception as e:
        logger.error(f"Verification start failed: {e}")
        await request.approve()
        del PENDING_VERIFICATIONS[user_id]


async def handle_verification_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verification answers"""
    user_id = update.effective_user.id
    
    if user_id not in PENDING_VERIFICATIONS:
        return
    
    verification = PENDING_VERIFICATIONS[user_id]
    user_answer = update.message.text.strip().lower()
    
    current_q_index = verification['current_question']
    current_question = verification['questions'][current_q_index]
    correct_answers = current_question['answers']
    
    is_correct = any(ans in user_answer for ans in correct_answers)
    
    if is_correct:
        verification['correct_answers'] += 1
        verification['current_question'] += 1
        
        if verification['current_question'] >= 3:
            if verification['correct_answers'] >= 2:
                try:
                    await verification['request'].approve()
                    track_user_activity(user_id, verification['chat_id'], 'approved')
                    
                    await update.message.reply_text(
                        f"✅ Verification Passed!\n\n"
                        f"Score: {verification['correct_answers']}/3\n"
                        f"You can now join!")
                    
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"✅ Verified: {update.effective_user.first_name}\n"
                        f"Score: {verification['correct_answers']}/3")
                    
                except Exception as e:
                    logger.error(f"Approval failed: {e}")
                
                del PENDING_VERIFICATIONS[user_id]
            else:
                BLOCKED_USERS.add(user_id)
                save_data()
                
                try:
                    await verification['request'].decline()
                except:
                    pass
                
                await update.message.reply_text(
                    f"❌ Verification Failed\n\n"
                    f"Score: {verification['correct_answers']}/3\n"
                    f"Need 2/3 to pass")
                
                del PENDING_VERIFICATIONS[user_id]
        else:
            next_q = verification['questions'][verification['current_question']]['question']
            await update.message.reply_text(
                f"✅ Correct!\n\n"
                f"Question {verification['current_question'] + 1}/3:\n{next_q}")
    else:
        verification['failed_attempts'] += 1
        
        if verification['failed_attempts'] >= 5:
            BLOCKED_USERS.add(user_id)
            save_data()
            
            try:
                await verification['request'].decline()
            except:
                pass
            
            await update.message.reply_text("❌ Too many wrong attempts. Blocked.")
            del PENDING_VERIFICATIONS[user_id]
        else:
            await update.message.reply_text(
                f"❌ Incorrect. Try again.\n\n"
                f"Question {current_q_index + 1}/3:\n{current_question['question']}")


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle join requests"""
    request = update.chat_join_request
    user = request.from_user
    chat_id = request.chat.id

    if chat_id not in MANAGED_CHANNELS:
        return

    if user.id == ADMIN_ID:
        await request.approve()
        return

    if user.id in BLOCKED_USERS:
        await request.decline()
        return

    if BULK_APPROVAL_MODE.get(chat_id, False):
        await request.approve()
        track_user_activity(user.id, chat_id, 'approved')
        return

    legitimacy = await check_user_legitimacy(context, user.id)

    if not legitimacy['legitimate'] and legitimacy['score'] == 0:
        try:
            await request.decline()
            BLOCKED_USERS.add(user.id)
            save_data()
            
            await context.bot.send_message(
                ADMIN_ID,
                f"🚫 Auto-Blocked: {user.first_name}\n"
                f"Reason: {legitimacy.get('reason')}")
            return
        except Exception as e:
            logger.error(f"Block failed: {e}")

    await start_verification(context, user.id, chat_id, request, "Standard verification")


# ========== MEDIA UPLOAD (SIMPLIFIED) ==========
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start upload mode"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /start_upload TYPE\n\n"
            "Examples:\n"
            "/start_upload images\n"
            "/start_upload videos\n\n"
            "Then send images/videos to me!\n"
            "Use /done_upload when finished")
        return

    upload_type = context.args[0].lower()
    
    if upload_type not in ['images', 'videos']:
        await update.message.reply_text("Type must be: images or videos")
        return

    global UPLOAD_MODE
    UPLOAD_MODE = upload_type

    await update.message.reply_text(
        f"📤 Upload Mode: {upload_type}\n\n"
        f"Send me {upload_type} now!\n"
        f"Use /done_upload when finished\n\n"
        f"Current storage:\n"
        f"📸 Images: {len(STORAGE_IMAGES)}\n"
        f"🎥 Videos: {len(STORAGE_VIDEOS)}")


async def done_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop upload mode"""
    if not await owner_only_check(update, context):
        return

    global UPLOAD_MODE
    UPLOAD_MODE = False
    save_data()

    await update.message.reply_text(
        f"✅ Upload Complete!\n\n"
        f"📸 Total Images: {len(STORAGE_IMAGES)}\n"
        f"🎥 Total Videos: {len(STORAGE_VIDEOS)}\n"
        f"🔗 Total Links: {len(STORAGE_LINKS)}\n\n"
        f"Ready for posting!")


async def handle_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded media"""
    global UPLOAD_MODE
    
    if not UPLOAD_MODE:
        return

    message = update.message

    try:
        if UPLOAD_MODE == 'images' and message.photo:
            STORAGE_IMAGES.append({
                'file_id': message.photo[-1].file_id,
                'caption': message.caption or ''
            })
            
            if len(STORAGE_IMAGES) % 10 == 0:
                await update.message.reply_text(f"✅ {len(STORAGE_IMAGES)} images uploaded...")

        elif UPLOAD_MODE == 'videos':
            if message.video:
                STORAGE_VIDEOS.append({
                    'file_id': message.video.file_id,
                    'type': 'video',
                    'caption': message.caption or ''
                })
            elif message.photo:
                STORAGE_VIDEOS.append({
                    'file_id': message.photo[-1].file_id,
                    'type': 'image',
                    'caption': message.caption or ''
                })
            
            if len(STORAGE_VIDEOS) % 10 == 0:
                await update.message.reply_text(f"✅ {len(STORAGE_VIDEOS)} items uploaded...")

    except Exception as e:
        logger.error(f"Upload error: {e}")


async def clear_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all storage"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /clear_storage TYPE\n\n"
            "Examples:\n"
            "/clear_storage images\n"
            "/clear_storage videos\n"
            "/clear_storage links\n"
            "/clear_storage all")
        return

    clear_type = context.args[0].lower()

    if clear_type == 'images':
        count = len(STORAGE_IMAGES)
        STORAGE_IMAGES.clear()
        await update.message.reply_text(f"✅ Cleared {count} images")
    elif clear_type == 'videos':
        count = len(STORAGE_VIDEOS)
        STORAGE_VIDEOS.clear()
        await update.message.reply_text(f"✅ Cleared {count} videos")
    elif clear_type == 'links':
        count = len(STORAGE_LINKS)
        STORAGE_LINKS.clear()
        await update.message.reply_text(f"✅ Cleared {count} links")
    elif clear_type == 'all':
        img = len(STORAGE_IMAGES)
        vid = len(STORAGE_VIDEOS)
        lnk = len(STORAGE_LINKS)
        STORAGE_IMAGES.clear()
        STORAGE_VIDEOS.clear()
        STORAGE_LINKS.clear()
        await update.message.reply_text(
            f"✅ Cleared All Storage\n\n"
            f"Images: {img}\n"
            f"Videos: {vid}\n"
            f"Links: {lnk}")
    else:
        await update.message.reply_text("Invalid type. Use: images, videos, links, or all")

    save_data()


# ========== LINK FILE UPLOAD ==========
def parse_links_from_text(text: str) -> list:
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
    """Handle link file upload"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not update.message.document:
        return

    document = update.message.document
    file_name = document.file_name.lower()

    if not any(file_name.endswith(ext) for ext in ['.txt', '.xlsx', '.xls', '.pdf']):
        return

    await update.message.reply_text("⏳ Processing links...")

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
            f"✅ Links Imported!\n\n"
            f"Old: {old_count}\n"
            f"New: {len(STORAGE_LINKS)}")

        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ========== CHANNEL SETUP ==========
async def setup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Setup channel"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 5:
        await update.message.reply_text(
            "Usage: /setup_channel ID \"Name\" TYPE INTERVAL \"Caption\"\n\n"
            "Example:\n"
            "/setup_channel -1001234567890 \"Glamour\" images 30 \"💎 Premium\"\n\n"
            "Types: images, videos, links, mixed")
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
            await update.message.reply_text("Invalid type. Use: images, videos, links, mixed")
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


async def change_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change caption"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /change_caption ID \"New Caption\"\n\n"
            "Example:\n"
            "/change_caption -1001234567890 \"New caption here\"")
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
            f"✅ Caption Updated!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"New Caption: {new_caption}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def change_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Change interval"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /change_interval CHANNEL_ID MINUTES")
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

        await update.message.reply_text(f"✅ Interval updated to {interval} minutes!")

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
            await update.message.reply_text("Invalid type")
            return

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['type'] = content_type
        save_data()

        await update.message.reply_text(f"✅ Content type changed to: {content_type}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def enable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable polls"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /enable_polls CHANNEL_ID FREQUENCY\n\n"
            "Example: /enable_polls -1001234567890 5")
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
            f"Every {frequency}th post will be a poll")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_channel_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable polls"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /disable_polls CHANNEL_ID")
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in CHANNEL_CONFIG:
            await update.message.reply_text("❌ Channel not configured")
            return

        CHANNEL_CONFIG[channel_id]['polls'] = False
        save_data()

        await update.message.reply_text("✅ Polls disabled!")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def pause_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pause channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /pause CHANNEL_ID")
        return

    try:
        channel_id = int(context.args[0])
        CHANNEL_PAUSE_STATUS[channel_id] = True
        save_data()
        await update.message.reply_text(f"⏸️ Paused: {MANAGED_CHANNELS[channel_id]['name']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def resume_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Resume channel"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /resume CHANNEL_ID")
        return

    try:
        channel_id = int(context.args[0])
        CHANNEL_PAUSE_STATUS[channel_id] = False
        save_data()
        await update.message.reply_text(f"▶️ Resumed: {MANAGED_CHANNELS[channel_id]['name']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def post_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post now"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /post_now CHANNEL_ID")
        return

    try:
        channel_id = int(context.args[0])
        await update.message.reply_text("⏳ Posting now...")
        await auto_post_job(context.bot, channel_id)
        await update.message.reply_text("✅ Posted!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View channel info"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /channel_info CHANNEL_ID")
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
            f"📢 {channel_name}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"ID: {channel_id}\n"
            f"Content: {config['type']}\n"
            f"Interval: {config['interval']} min\n"
            f"Caption: {config['caption']}\n"
            f"Status: {'⏸️ Paused' if paused else '▶️ Active'}\n"
            f"Auto-post: {'✅ On' if config.get('enabled') else '❌ Off'}\n"
            f"Polls: {'✅ Every ' + str(config['poll_frequency']) + 'th' if config.get('polls') else '❌ Off'}\n"
            f"Total Posts: {post_count}\n"
            f"━━━━━━━━━━━━━━━━"
        )

        await update.message.reply_text(text)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def all_channels_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all channels"""
    if not await owner_only_check(update, context):
        return

    if not CHANNEL_CONFIG:
        await update.message.reply_text("No channels configured")
        return

    text = "📊 All Channels:\n\n"

    for channel_id, config in CHANNEL_CONFIG.items():
        channel_name = MANAGED_CHANNELS.get(channel_id, {}).get('name', 'Unknown')
        paused = CHANNEL_PAUSE_STATUS.get(channel_id, False)
        status = '⏸️' if paused else '▶️'
        
        text += (
            f"{status} {channel_name}\n"
            f"   Type: {config['type']} | {config['interval']}min\n"
            f"   Caption: {config['caption'][:30]}...\n"
            f"   Posts: {CHANNEL_POST_COUNT.get(channel_id, 0)}\n\n"
        )

    await update.message.reply_text(text)


# ========== AUTO-POSTING ==========
async def auto_post_job(bot, channel_id: int):
    """Auto-post job"""
    try:
        if CHANNEL_PAUSE_STATUS.get(channel_id, False):
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
                ("What more? 🤔", ["Images 📸", "Videos 🎥", "Links 🔗", "Mixed 🎯"]),
            ]
            question, options = random.choice(poll_questions)
            
            await bot.send_poll(
                chat_id=channel_id,
                question=question,
                options=options,
                is_anonymous=True
            )
        else:
            if content_type == 'images':
                if not STORAGE_IMAGES:
                    logger.warning(f"No images for {channel_id}")
                    return
                media = random.choice(STORAGE_IMAGES)
                await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                
            elif content_type == 'videos':
                if not STORAGE_VIDEOS:
                    logger.warning(f"No videos for {channel_id}")
                    return
                media = random.choice(STORAGE_VIDEOS)
                if media['type'] == 'video':
                    await bot.send_video(chat_id=channel_id, video=media['file_id'], caption=caption)
                else:
                    await bot.send_photo(chat_id=channel_id, photo=media['file_id'], caption=caption)
                    
            elif content_type == 'links':
                if not STORAGE_LINKS:
                    logger.warning(f"No links for {channel_id}")
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
                    logger.warning(f"No content for {channel_id}")
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

        save_data()

    except Exception as e:
        logger.error(f"Auto-post failed for {channel_id}: {e}")


async def enable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enable auto-posting"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /enable_autopost CHANNEL_ID")
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

        await update.message.reply_text(
            f"✅ Auto-post Enabled!\n\n"
            f"Channel: {MANAGED_CHANNELS[channel_id]['name']}\n"
            f"Interval: {interval} min\n"
            f"Content: {config['type']}\n"
            f"Caption: {config['caption']}\n\n"
            f"Bot will start posting! 🚀")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def disable_autopost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Disable auto-posting"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /disable_autopost CHANNEL_ID")
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

        await update.message.reply_text(f"✅ Auto-post disabled")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ========== INFO COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user

    if user.id == ADMIN_ID:
        text = (
            "👋 Welcome!\n\n"
            "🤖 Status: Online 24/7\n"
            f"📢 Channels: {len(MANAGED_CHANNELS)}\n\n"

            "━━━ UPLOAD MEDIA ━━━\n"
            "/start_upload TYPE - Start upload\n"
            "/done_upload - Finish\n"
            "Send file - Upload links\n\n"

            "━━━ CHANNEL SETUP ━━━\n"
            "/setup_channel - Full setup\n"
            "/channel_info ID - View\n"
            "/all_channels - All\n\n"

            "━━━ MODIFY ━━━\n"
            "/change_caption - Caption\n"
            "/change_interval - Timing\n"
            "/change_content_type - Type\n"
            "/enable_polls - Polls\n\n"

            "━━━ CONTROL ━━━\n"
            "/enable_autopost - Start\n"
            "/disable_autopost - Stop\n"
            "/pause - Pause\n"
            "/resume - Resume\n"
            "/post_now - Post\n\n"

            "━━━ STORAGE ━━━\n"
            "/view_storage - Check\n"
            "/clear_storage - Clear\n\n"

            "━━━ ACTIVITY ━━━\n"
            "/stats - Statistics\n"
            "/pending_users - Verify\n"
            "/recent_activity - Activity\n\n"

            "━━━ USERS ━━━\n"
            "/block_user - Block\n"
            "/unblock_user - Unblock\n"
            "/toggle_bulk - Mode"
        )
    else:
        text = "Hello! Channel management bot."

    await update.message.reply_text(text)


async def view_storage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View storage"""
    if not await owner_only_check(update, context):
        return

    text = "📦 Storage Status\n\n"
    text += f"📸 Images: {len(STORAGE_IMAGES)}\n"
    text += f"🎥 Videos: {len(STORAGE_VIDEOS)}\n"
    text += f"🔗 Links: {len(STORAGE_LINKS)}\n\n"

    if len(STORAGE_IMAGES) == 0:
        text += "⚠️ No images! Use /start_upload images\n"
    if len(STORAGE_VIDEOS) == 0:
        text += "⚠️ No videos! Use /start_upload videos\n"

    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistics"""
    if not await owner_only_check(update, context):
        return

    active = sum(1 for v in CHANNEL_CONFIG.values() if v.get('enabled'))
    total_posts = sum(CHANNEL_POST_COUNT.values())

    text = (
        f"📊 Statistics\n\n"
        f"📢 Channels: {len(MANAGED_CHANNELS)}\n"
        f"🤖 Auto-posting: {active}\n"
        f"📝 Total Posts: {total_posts}\n\n"
        f"📦 Storage:\n"
        f"   📸 Images: {len(STORAGE_IMAGES)}\n"
        f"   🎥 Videos: {len(STORAGE_VIDEOS)}\n"
        f"   🔗 Links: {len(STORAGE_LINKS)}\n\n"
        f"👥 Users:\n"
        f"   ⏳ Pending: {len(PENDING_VERIFICATIONS)}\n"
        f"   🚫 Blocked: {len(BLOCKED_USERS)}\n\n"
        f"Status: Online ✅"
    )
    await update.message.reply_text(text)


async def pending_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pending users"""
    if not await owner_only_check(update, context):
        return

    if not PENDING_VERIFICATIONS:
        await update.message.reply_text("No pending verifications")
        return

    text = "⏳ Pending:\n\n"
    for user_id, data in PENDING_VERIFICATIONS.items():
        text += f"User: {user_id}\n"
        text += f"Question: {data['current_question'] + 1}/3\n\n"

    await update.message.reply_text(text)


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block user"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /block_user USER_ID")
        return

    try:
        user_id = int(context.args[0])
        BLOCKED_USERS.add(user_id)
        save_data()
        await update.message.reply_text(f"✅ Blocked: {user_id}")
    except:
        await update.message.reply_text("❌ Invalid ID")


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unblock user"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /unblock_user USER_ID")
        return

    try:
        user_id = int(context.args[0])
        if user_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_id)
            save_data()
            await update.message.reply_text(f"✅ Unblocked: {user_id}")
        else:
            await update.message.reply_text("Not in blocked list")
    except:
        await update.message.reply_text("❌ Invalid ID")


async def toggle_bulk_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle bulk mode"""
    if not await owner_only_check(update, context):
        return

    if not context.args:
        await update.message.reply_text("Usage: /toggle_bulk CHANNEL_ID")
        return

    try:
        channel_id = int(context.args[0])

        if channel_id not in MANAGED_CHANNELS:
            await update.message.reply_text("❌ Channel not managed")
            return

        current = BULK_APPROVAL_MODE.get(channel_id, False)
        BULK_APPROVAL_MODE[channel_id] = not current
        save_data()

        mode = "🔄 Bulk (approve all)" if BULK_APPROVAL_MODE[channel_id] else "🛡️ Smart Verification"
        await update.message.reply_text(f"✅ Mode: {mode}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def recent_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent activity"""
    if not await owner_only_check(update, context):
        return

    if not RECENT_ACTIVITY:
        await update.message.reply_text("No recent activity")
        return

    text = "📊 Recent Activity\n\n"
    for activity in RECENT_ACTIVITY[-10:]:
        text += f"{activity.get('type', 'unknown')}: {activity.get('user_name', 'Unknown')}\n"

    await update.message.reply_text(text)


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add channel (simple)"""
    if not await owner_only_check(update, context):
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addchannel CHANNEL_ID Name")
        return

    try:
        channel_id = int(context.args[0])
        channel_name = ' '.join(context.args[1:])

        if not await is_bot_admin(context, channel_id):
            await update.message.reply_text("❌ Bot not admin")
            return

        MANAGED_CHANNELS[channel_id] = {'name': channel_name}
        save_data()

        await update.message.reply_text(
            f"✅ Added!\n\n"
            f"Name: {channel_name}\n"
            f"ID: {channel_id}")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List channels"""
    if not await owner_only_check(update, context):
        return

    if not MANAGED_CHANNELS:
        await update.message.reply_text("No channels")
        return

    text = "📢 Channels:\n\n"
    for channel_id, data in MANAGED_CHANNELS.items():
        text += f"{data['name']}\n"
        text += f"ID: {channel_id}\n\n"

    await update.message.reply_text(text)


async def handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all content"""
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    # Check verification first
    if update.effective_user.id in PENDING_VERIFICATIONS:
        await handle_verification_answer(update, context)
        return

    # Check upload mode
    if UPLOAD_MODE:
        await handle_media_upload(update, context)
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Error handler"""
    logger.error(f"Error: {context.error}")


def main():
    """Main"""
    logger.info("🚀 Starting Bot...")
    logger.info(f"✅ Admin: {ADMIN_ID}")

    load_data()

    app = Application.builder().token(BOT_TOKEN).build()

    # Upload
    app.add_handler(CommandHandler("start_upload", start_upload))
    app.add_handler(CommandHandler("done_upload", done_upload))
    app.add_handler(CommandHandler("clear_storage", clear_storage))
    app.add_handler(CommandHandler("view_storage", view_storage))

    # Setup
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
    
    # Info
    app.add_handler(CommandHandler("channel_info", channel_info))
    app.add_handler(CommandHandler("all_channels", all_channels_info))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("pending_users", pending_users))
    app.add_handler(CommandHandler("recent_activity", recent_activity))

    # Users
    app.add_handler(CommandHandler("block_user", block_user))
    app.add_handler(CommandHandler("unblock_user", unblock_user))
    app.add_handler(CommandHandler("toggle_bulk", toggle_bulk_approval))
    
    # Old
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("channels", list_channels))

    # Messages
    app.add_handler(MessageHandler(filters.Document.ALL, handle_link_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_content))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_content))

    # Join requests
    app.add_handler(ChatJoinRequestHandler(handle_join_request))

    # Error
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
                logger.info(f"✅ Restored: {channel_id}")
            except Exception as e:
                logger.error(f"Restore failed: {e}")

    logger.info("✅ Bot Running!")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    main()
