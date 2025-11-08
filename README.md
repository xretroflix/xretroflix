# Telegram Channel Management Bot

Smart verification bot for Telegram channels with auto-approval, captcha, and rejection features.

## 🚀 QUICK DEPLOY TO RAILWAY

### Step 1: Get Your Bot Token
1. Go to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot`
3. Follow instructions
4. Copy the bot token (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Get Your Telegram User ID
1. Go to [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send any message
3. Copy your ID (just the numbers, like: `123456789`)

### Step 3: Deploy to Railway
1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Click **"New Project"**
4. Select **"Deploy from GitHub repo"**
5. Choose this repository
6. Wait for initial build (it will fail - that's OK!)

### Step 4: Add Environment Variables
1. Click on your service
2. Go to **"Variables"** tab
3. Click **"Add Variable"**
4. Add these:

```
BOT_TOKEN=your_bot_token_here
ADMIN_ID=your_telegram_user_id_here
```

**Example:**
```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_ID=123456789
```

### Step 5: Add Volume (Storage)
1. Go to **"Settings"** tab
2. Scroll to **"Volumes"** section
3. Click **"New Volume"**
4. Set **Mount Path**: `/app/data`
5. Click **"Add"**

### Step 6: Redeploy
1. Go to **"Deployments"** tab
2. Click three dots on latest deployment
3. Click **"Redeploy"**
4. Wait 1-2 minutes

### Step 7: Test Your Bot
1. Open Telegram
2. Find your bot (search for the name you gave it)
3. Send `/start`
4. You should see the owner menu!

## ✅ Verify It's Working

Check Railway logs:
1. Go to **"Deployments"** tab
2. Click on latest deployment
3. You should see:
```
✅ Bot starting - Owner: YOUR_ID
✅ Loaded: 0 channels
```

## 📋 First-Time Setup

### 1. Add Your First Channel

**Get Channel ID:**
1. Add [@raw_data_bot](https://t.me/raw_data_bot) to your channel as admin
2. Send any message in the channel
3. Copy the channel ID (looks like: `-1001234567890`)
4. Remove the bot from your channel

**Add Bot to Your Channel:**
1. Go to your channel settings
2. Add your bot as administrator
3. Give it these permissions:
   - ✅ Post messages
   - ✅ Delete messages
   - ✅ Invite users via link
   - ✅ Manage chat (important!)

**Register Channel with Bot:**
```
/addchannel -1001234567890 My Channel Name
```

### 2. Enable Smart Verification
It's enabled by default! Your bot will now:
- ✅ Auto-approve users with real names + username + photo
- ⚠️ Send you captcha for borderline users
- ❌ Auto-reject suspicious accounts

### 3. Check Status
```
/stats
```

## 🎯 Key Commands

**Setup:**
- `/start` - Main menu
- `/addchannel` - Add channel to manage
- `/channels` - List all channels

**Activity:**
- `/stats` - View statistics
- `/recent_activity` - See who joined
- `/pending_users` - View captchas

**Approvals:**
- `/approve_user` - Approve specific user
- `/approve_all_pending` - Approve all captchas
- `/block_user` - Block user permanently

**Settings:**
- `/toggle_bulk` - Switch between Smart/Bulk mode

## 🐛 Troubleshooting

### Bot doesn't respond to /start
- Check Railway logs for errors
- Verify `BOT_TOKEN` is correct (no spaces)
- Verify `ADMIN_ID` is just numbers

### Bot crashes immediately
- Check you added both environment variables
- Check logs in Railway "Deployments" tab

### "Bot is not admin" error
Make sure bot has these permissions in your channel:
- Invite users via link
- Manage chat

### Bot doesn't approve anyone
- Check `/stats` - are there pending users?
- Check `/recent_activity` - did it auto-approve/reject?
- Try `/toggle_bulk CHANNEL_ID` for temporary bulk approval

## 💾 Data Persistence

All data is saved to `/app/data/bot_data.json` via Railway Volume.

**What's saved:**
- Managed channels
- User database
- Settings
- Uploaded images

**What's NOT saved (resets on restart):**
- Pending verifications (captchas)
- Recent activity log

## 🔒 Security Features

1. **Owner-only commands** - Only your Telegram ID can use commands
2. **Unauthorized attempt logging** - See who tried to use your bot
3. **Blocked user list** - Permanent bans
4. **Smart verification** - 3-tier auto-approval system

## 📊 How Smart Verification Works

**Tier 1: Auto-Approve (Score ≥70)**
- Real name (40 pts)
- Has username (30 pts)
- Has profile photo (30 pts)
→ User joins instantly

**Tier 2: Captcha (Score 30-69)**
- Borderline cases
- You get notified
- Simple math problem
→ You decide

**Tier 3: Auto-Reject (Score 0)**
- Bot accounts
- "User123456" names
- Suspicious profiles
→ Blocked automatically

## 📝 Notes

- Bot runs 24/7 on Railway
- Free tier gives you 500 hours/month (enough!)
- Volume storage is included in free tier
- Logs are available in Railway dashboard

## 🆘 Support

Check your Railway logs first:
1. Go to railway.app
2. Click your project
3. Click "Deployments"
4. Check the logs

Common issues are usually:
- Missing environment variables
- Bot not admin in channel
- Wrong channel ID format
