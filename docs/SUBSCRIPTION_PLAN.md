# Subscription Plan & Budget — 2 Shorts/Day

## Active Subscriptions

| Service | Plan | Cost | Allocation |
|---------|------|------|------------|
| **ElevenLabs** | Creator | ~$23/mo (INR 1,936) | 100,000 characters/month |
| **Runway** | Standard | $12/month | 625 credits/month + Gen-4.5 access, 4K upscaling, no watermarks |

## Production Target

- **2 YouTube Shorts per day** (60/month)
- Strategy: `ai_only` with `gen3a_turbo`
- Each short: 30-60 seconds, 4-6 AI-generated scenes

## Monthly Cost Breakdown

| Resource | Calculation | Monthly Usage | Monthly Cost |
|----------|-------------|---------------|--------------|
| **Runway API** | 60 shorts x 6 scenes x 5s x 5 credits/s | ~9,000 credits | ~$90 |
| **Runway Subscription** | Included 625 credits | -625 credits | -$6.25 |
| **ElevenLabs** | 60 shorts x ~450 chars | ~27,000 / 100,000 chars (27%) | Included |
| **OpenAI (GPT-4o)** | 60 scripts + 60 scene splits | ~120 API calls | ~$3 |
| **Pexels** | Fallback only | Minimal | Free |

### Per-Short Cost

| Component | Cost |
|-----------|------|
| Runway (6 scenes x 5s) | ~$1.50 |
| OpenAI (script + scene split) | ~$0.05 |
| ElevenLabs (TTS) | ~$0.00 (included in plan) |
| **Total per short** | **~$1.55** |

### Monthly Total

| Item | Cost |
|------|------|
| Runway API credits (net of subscription) | ~$84 |
| Runway Standard subscription | $12 |
| ElevenLabs Creator subscription | ~$23 |
| OpenAI API | ~$3 |
| **Monthly total** | **~$122** |

## Configuration Reference

### `.env` Settings

```env
# Strategy
AI_VIDEO_ENABLED=true
AI_VIDEO_STRATEGY=ai_only
AI_VIDEO_PRIMARY_PROVIDER=runway
RUNWAY_MODEL=gen3a_turbo

# Budget guards
AI_VIDEO_MAX_COST_PER_VIDEO=2.00    # single short cap ($1.50 + buffer)
AI_VIDEO_MAX_DAILY_SPEND=3.50       # 2 shorts/day cap ($3.00 + buffer)
```

### `config.py` Defaults

| Setting | Default | Description |
|---------|---------|-------------|
| `runway_model` | `gen3a_turbo` | Faster/cheaper Runway model |
| `ai_video_max_cost_per_video` | `2.0` | Per-video spend cap (USD) |
| `ai_video_max_daily_spend` | `3.50` | Daily spend cap (USD) |
| `elevenlabs_monthly_char_limit` | `100,000` | ElevenLabs Creator plan limit |

## Scaling Notes

- **To 3 shorts/day:** raise `AI_VIDEO_MAX_DAILY_SPEND` to ~$5.50, monthly Runway ~$135
- **To reduce cost:** switch to `hybrid` strategy (LLM picks AI vs stock per scene)
- **To improve quality:** switch `RUNWAY_MODEL` to `gen3a_alpha` (~2x cost, better coherence)
- **ElevenLabs headroom:** 27% usage at 2/day, can scale to ~7/day before hitting 100k limit
