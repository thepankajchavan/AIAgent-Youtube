# Telegram Bot User Guide

Complete guide to using the YouTube Shorts Automation Telegram bot.

## Getting Started

### 1. Get Your User ID

Before you can use the bot, get your Telegram user ID:

1. Open Telegram
2. Search for and message [@userinfobot](https://t.me/userinfobot)
3. Send any message
4. Copy your user ID (e.g., `123456789`)

### 2. Request Access

Ask your administrator to add you to the allowlist:

```bash
docker compose exec api python scripts/manage_telegram_users.py add YOUR_USER_ID "Your Name"
```

### 3. Start the Bot

1. Search for your bot on Telegram (`@YourBotName`)
2. Click **Start** or send `/start`
3. You should see a welcome message with available commands

---

## Commands

### /start

Display welcome message and usage instructions.

**Example:**
```
You: /start

Bot: 🎬 Welcome to YouTube Shorts Automation!

I can generate YouTube Shorts videos automatically from any topic.

Available commands:
• /video <topic> - Generate 9:16 short video
• /video_long <topic> - Generate 16:9 long video
• /status <id> - Check project status
• /list - Show your recent projects
• /cancel <id> - Cancel running project
• /retry <id> - Retry failed project
• /help - Show this message

Get started: /video 5 facts about space
```

---

### /help

Show help message with all available commands.

**Example:**
```
You: /help

Bot: [Same as /start response]
```

---

### /video <topic>

Generate a 9:16 short video (YouTube Shorts format).

**Syntax:**
```
/video <topic>
```

**Parameters:**
- `<topic>` - Video topic (3-512 characters)

**Example:**
```
You: /video 5 mind-blowing facts about black holes

Bot: ✍️ Generating script...
     [=========>          ] 30%

     Topic: 5 mind-blowing facts about black holes
     Format: Short (9:16)
     Provider: OpenAI GPT-4o

Bot: 🎙️ Creating voiceover...
     [================>   ] 60%

Bot: 🎥 Assembling video...
     [=====================>] 90%

Bot: ✅ Video published!
     🎬 https://youtube.com/shorts/dQw4w9WgXcQ

     Title: 5 Mind-Blowing Black Hole Facts
     Duration: 0:47
     Views: Processing...
```

**What Happens:**
1. **Script Generation** (30-60s) - AI writes engaging script
2. **Audio Generation** (20-40s) - Text-to-speech voiceover
3. **Visual Fetching** (30-60s) - Downloads stock footage
4. **Video Assembly** (40-90s) - FFmpeg encodes final video
5. **YouTube Upload** (30-90s) - Publishes to your channel
6. **Notification** - Sends you the YouTube URL

**Total Time:** 3-8 minutes

---

### /video_long <topic>

Generate a 16:9 long video (standard format).

**Syntax:**
```
/video_long <topic>
```

**Parameters:**
- `<topic>` - Video topic (3-512 characters)

**Example:**
```
You: /video_long The complete history of artificial intelligence

Bot: ✍️ Generating script...

     Topic: The complete history of artificial intelligence
     Format: Long (16:9)
     Provider: OpenAI GPT-4o
     Expected duration: 5-10 minutes

[... processing ...]

Bot: ✅ Video published!
     🎬 https://youtube.com/watch?v=dQw4w9WgXcQ

     Title: The Complete History of Artificial Intelligence
     Duration: 7:32
     Views: Processing...
```

---

### /status [project_id]

Check the status of a video project.

**Syntax:**
```
/status [project_id]
```

**Parameters:**
- `[project_id]` - Optional. If omitted, shows your latest project

**Example:**
```
You: /status

Bot: 📊 Project Status

     ID: 550e8400-e29b-41d4-a716-446655440000
     Topic: 5 facts about black holes
     Status: 🎥 Assembling video (80%)
     Started: 2026-03-03 10:30:00
     Elapsed: 3m 42s
```

**With Project ID:**
```
You: /status 550e8400-e29b-41d4-a716-446655440000

Bot: [Status details]
```

**Status Indicators:**
- ⏳ PENDING - Waiting for worker
- ✍️ SCRIPT_GENERATING - AI writing script
- 🎙️ AUDIO_GENERATING - Creating voiceover
- 🎥 VIDEO_GENERATING - Downloading footage
- 🔧 ASSEMBLING - Encoding video
- 📤 UPLOADING - Publishing to YouTube
- ✅ COMPLETED - Video published
- ❌ FAILED - Pipeline failed

---

### /list

Show your recent video projects.

**Syntax:**
```
/list
```

**Example:**
```
You: /list

Bot: 📋 Your Recent Projects

     1. ✅ 5 facts about black holes
        ID: 550e8400...440000
        YouTube: https://youtube.com/shorts/abc123
        Created: 2 hours ago

     2. ✍️ History of AI
        ID: 660f9511...551111
        Status: Generating script (40%)
        Created: 5 minutes ago

     3. ❌ Facts about Mars
        ID: 770g0622...662222
        Status: FAILED - OpenAI API rate limit
        Created: 1 day ago

     Showing 3 of 12 total projects
     Use /status <id> for details
```

---

### /cancel <project_id>

Cancel a running video project.

**Syntax:**
```
/cancel <project_id>
```

**Parameters:**
- `<project_id>` - Project ID to cancel

**Example:**
```
You: /cancel 550e8400-e29b-41d4-a716-446655440000

Bot: ⏹️ Project Cancelled

     ID: 550e8400-e29b-41d4-a716-446655440000
     Topic: 5 facts about black holes
     Status: Cancelled during video assembly

     Celery task terminated.
```

**Note:** Cancellation may take a few seconds. The project status will update to FAILED.

---

### /retry <project_id>

Retry a failed video project.

**Syntax:**
```
/retry <project_id>
```

**Parameters:**
- `<project_id>` - Project ID to retry

**Example:**
```
You: /retry 550e8400-e29b-41d4-a716-446655440000

Bot: 🔄 Retrying Project

     ID: 550e8400-e29b-41d4-a716-446655440000
     Topic: 5 facts about black holes
     Resuming from: Assembly step

     New task ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890

Bot: 🔧 Assembling video...
     [Continues from where it failed]
```

**Smart Resume:**
- If script exists → Skip script generation
- If audio exists → Skip audio generation
- If clips downloaded → Skip visual fetching
- Continues from failure point

---

## Rate Limiting

**Default Limits:**
- **5 videos per hour** per user
- **10 concurrent projects** maximum

**Rate Limit Exceeded:**
```
You: /video Another topic

Bot: ⚠️ Rate Limit Exceeded

     You've reached your limit of 5 videos per hour.
     Next video available in: 23 minutes

     Current usage: 5/5 videos
     Resets at: 11:30 AM
```

---

## Error Handling

### Common Errors

#### 1. Unauthorized User
```
You: /start

Bot: ❌ Unauthorized

     Your user ID (123456789) is not in the allowlist.
     Please contact the administrator.
```

**Solution:** Ask admin to add you with `manage_telegram_users.py add 123456789`

#### 2. Topic Too Short
```
You: /video AI

Bot: ❌ Validation Error

     Topic must be at least 3 characters long.

     Example: /video 5 facts about AI
```

#### 3. Topic Too Long
```
You: /video [very long topic 600+ characters]

Bot: ❌ Validation Error

     Topic must be less than 512 characters.
     Current length: 623 characters

     Please shorten your topic.
```

#### 4. Pipeline Failed
```
Bot: ❌ Pipeline Failed

     ID: 550e8400-e29b-41d4-a716-446655440000
     Topic: 5 facts about black holes
     Failed at: Audio generation

     Error: ElevenLabs API rate limit exceeded

     You can retry with: /retry 550e8400...440000
```

---

## Tips & Best Practices

### Writing Good Topics

**✅ Good Topics:**
- "5 surprising facts about the ocean"
- "How photosynthesis actually works"
- "The rise and fall of the Roman Empire"
- "3 easy cooking hacks for beginners"

**❌ Bad Topics:**
- "facts" (too vague)
- "Tell me everything about quantum physics in extreme detail with formulas" (too long/complex)
- "Make a video" (not descriptive)

### Topic Guidelines

1. **Be Specific**: "5 facts about Mars" > "Space facts"
2. **Use Numbers**: "7 tips..." > "Tips for..."
3. **Target Audience**: "...for beginners" works well
4. **Avoid Questions**: "Facts about..." > "What are facts about...?"
5. **Length**: 10-60 characters is optimal

### Video Format Selection

**Use Short Format (9:16) When:**
- Topic can be covered in 30-60 seconds
- Target audience is mobile users
- Publishing to YouTube Shorts, TikTok, Instagram Reels
- Quick facts, tips, or listicles

**Use Long Format (16:9) When:**
- Topic requires 5+ minutes to explain
- Detailed tutorials or educational content
- Traditional YouTube video format
- Desktop viewing expected

---

## Troubleshooting

### Bot Not Responding

**Check:**
1. Is the bot online? (Check with admin)
2. Are you in the allowlist? (Send `/start` to verify)
3. Is Telegram down? (Check https://downdetector.com/status/telegram/)

**Solution:**
```bash
# Admin checks bot status
docker compose ps telegram-bot

# Admin restarts bot
docker compose restart telegram-bot
```

### Video Stuck in Processing

**If video is stuck for >15 minutes:**

1. Check status: `/status <project_id>`
2. Cancel and retry: `/cancel <project_id>` then `/retry <project_id>`
3. Contact admin if issue persists

**Admin Debug:**
```bash
# Check worker logs
docker compose logs -f celery-media

# Check task status
curl http://localhost:8000/api/v1/system/tasks/<task_id>
```

### Notification Not Updating

**If progress bar stops updating:**
- The video is still processing
- Notifications update every 10-30 seconds
- Check `/status` for current progress
- Final notification sent when complete

---

## Advanced Features

### Custom Voice Selection (Coming Soon)

Future feature to select different ElevenLabs voices:

```
/voice list                    # List available voices
/voice set <voice_id>          # Set your default voice
/video <topic> --voice=<id>    # Use specific voice
```

### Scheduled Videos (Coming Soon)

Schedule videos for future generation:

```
/schedule "5 facts about space" at 3pm tomorrow
/schedule "Daily news recap" daily at 9am
/schedule list                 # View scheduled videos
```

---

## FAQ

**Q: How long does video generation take?**
A: Typically 3-8 minutes. Short videos are faster than long videos.

**Q: Can I edit the script before video generation?**
A: Not currently. Script is auto-generated. You can retry with a different topic.

**Q: Can I upload to multiple YouTube channels?**
A: Currently supports one channel per bot instance. Contact admin for multi-channel setup.

**Q: What if my video gets copyright striked?**
A: All stock footage is from Pexels (free commercial license). Strikes are rare. Contact YouTube support if it occurs.

**Q: Can I download the video before upload?**
A: Use `skip_upload: true` in API mode. Telegram bot always uploads.

**Q: How do I delete a video from YouTube?**
A: Go to YouTube Studio and delete manually. Bot doesn't support deletion.

**Q: Can I use my own voice?**
A: Currently uses ElevenLabs default voice. Voice cloning support coming soon.

---

## Getting Help

- **Check Logs**: Ask admin for recent logs
- **Project Status**: Use `/status <id>` for details
- **Retry Failed**: Use `/retry <id>` if pipeline failed
- **Contact Admin**: If issue persists

**Admin Contact:**
- Telegram: @YourAdminUsername
- Email: admin@yourdomain.com

---

**Last Updated:** 2026-03-03
**Bot Version:** 1.0.0
