# Production Launch Checklist

Complete pre-launch, launch, and post-launch checklist for YouTube Shorts Automation Engine.

---

## ✅ Pre-Launch Checklist

### 1. API Keys & Credentials

- [ ] **OpenAI API Key** - Production key with sufficient credits
- [ ] **Anthropic API Key** - Backup LLM provider configured
- [ ] **ElevenLabs API Key** - Production key with sufficient quota
- [ ] **Pexels API Key** - Production key (unlimited free)
- [ ] **Telegram Bot Token** - Production bot created via @BotFather
- [ ] **YouTube OAuth Credentials** - `client_secrets.json` configured
- [ ] **YouTube OAuth Token** - `youtube_token.json` generated and encrypted
- [ ] **Database Password** - Strong password set (minimum 32 characters)
- [ ] **Redis Password** - Strong password set (optional but recommended)
- [ ] **SMTP Credentials** - For alerting emails configured

**Verification:**
```bash
# Run configuration validation
docker compose exec api python -m app.core.validation

# Should output: ✅ All checks passed
```

---

### 2. Infrastructure Setup

- [ ] **Domain Configured** - DNS A record points to server IP
- [ ] **SSL Certificate** - Let's Encrypt or commercial SSL installed
- [ ] **Nginx Configured** - Reverse proxy with rate limiting active
- [ ] **Firewall Rules** - Only ports 80, 443, 22 exposed
- [ ] **Server Resources** - Minimum 4 CPU, 8GB RAM, 100GB SSD
- [ ] **Docker Installed** - Version 24.0+ with Compose V2
- [ ] **Backup Storage** - External backup location configured

**Verification:**
```bash
# Check domain resolution
nslookup your-domain.com

# Check SSL
curl -I https://your-domain.com

# Check Docker
docker --version
docker compose version

# Check resources
htop  # or top
df -h
```

---

### 3. Database & Redis

- [ ] **PostgreSQL 16** - Running with health checks passing
- [ ] **Database Backups** - Daily automated backups configured
- [ ] **Connection Pool** - Sized appropriately (pool_size=20, max_overflow=40)
- [ ] **Indexes Created** - All migrations applied (5 composite indexes)
- [ ] **Redis Persistence** - AOF enabled for durability
- [ ] **Redis Maxmemory** - Set with eviction policy (allkeys-lru)
- [ ] **Redis Backups** - RDB snapshots enabled (save 900 1)

**Verification:**
```bash
# Check PostgreSQL
docker compose exec postgres pg_isready
docker compose exec postgres psql -U postgres -d content_engine -c "\dt"

# Check migrations
docker compose exec api alembic current
docker compose exec api alembic check

# Check Redis
docker compose exec redis redis-cli ping
docker compose exec redis redis-cli CONFIG GET save
docker compose exec redis redis-cli CONFIG GET appendonly
```

---

### 4. Security Hardening

- [ ] **API Authentication** - API keys required for all endpoints
- [ ] **Rate Limiting** - Per-endpoint limits configured
- [ ] **CORS Restrictions** - Specific origins only (no *)
- [ ] **Input Sanitization** - 13 injection patterns blocked
- [ ] **Secret Encryption** - OAuth tokens encrypted at rest
- [ ] **Security Headers** - X-Frame-Options, CSP, HSTS configured
- [ ] **SSH Key Auth** - Password auth disabled
- [ ] **Fail2Ban** - Installed and monitoring SSH/Nginx logs
- [ ] **Secret Scanning** - No credentials in Git history
- [ ] **Dependency Scanning** - Trivy scan passing

**Verification:**
```bash
# Check API auth
curl http://localhost:8000/api/v1/projects  # Should return 401

# Check rate limiting
for i in {1..20}; do curl -X POST http://localhost:8000/api/v1/pipeline -H "X-API-Key: test"; done
# Should get 429 after threshold

# Check security headers
curl -I https://your-domain.com

# Run Trivy scan
docker compose exec api trivy fs /app --severity HIGH,CRITICAL
```

---

### 5. Monitoring & Alerting

- [ ] **Prometheus** - Running and scraping metrics
- [ ] **Grafana** - Dashboards accessible (admin password changed)
- [ ] **Alertmanager** - Configured with email/Slack webhooks
- [ ] **Test Alert** - Sent and received successfully
- [ ] **Celery Flower** - Task monitoring accessible
- [ ] **Log Aggregation** - Logs centralized (optional: ELK stack)
- [ ] **Uptime Monitoring** - External monitoring (UptimeRobot, Pingdom)
- [ ] **Error Tracking** - Sentry or similar configured (optional)

**Verification:**
```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health:.health}'

# Check Grafana
curl http://localhost:3000/api/health

# Send test alert
curl -X POST http://localhost:9093/api/v1/alerts -d '[{
  "labels": {"alertname":"TestAlert","severity":"warning"},
  "annotations": {"summary":"Test alert"}
}]'

# Check Flower
curl http://localhost:5555
```

---

### 6. CI/CD Pipeline

- [ ] **GitHub Repository** - Code pushed to main branch
- [ ] **GitHub Actions** - CI pipeline passing (6 jobs)
- [ ] **Branch Protection** - Main branch protected, requires PR
- [ ] **Required Checks** - Test, lint, build, security passing
- [ ] **Dependabot** - Enabled and monitoring dependencies
- [ ] **Staging Environment** - Deployed and tested
- [ ] **Production Environment** - Manual approval configured
- [ ] **Rollback Tested** - Rollback procedure verified

**Verification:**
```bash
# Check latest CI run
gh run list --limit 1

# Check branch protection
gh api repos/OWNER/REPO/branches/main/protection

# Verify staging deployment
curl https://staging.your-domain.com/health
```

---

### 7. Testing & Validation

- [ ] **Unit Tests** - 183+ tests passing
- [ ] **Integration Tests** - All API endpoints tested
- [ ] **E2E Test** - Full pipeline tested end-to-end
- [ ] **Load Test** - 50 concurrent pipelines tested
- [ ] **Chaos Test** - Services recover from failures
- [ ] **Coverage** - 80%+ code coverage achieved
- [ ] **Manual QA** - All features tested manually

**Verification:**
```bash
# Run all tests
docker compose exec api pytest -v --cov=app --cov-report=term

# Load test (requires k6 or similar)
k6 run load-test.js

# E2E test
docker compose exec api pytest tests/e2e/ -v
```

---

### 8. Documentation

- [ ] **README.md** - Comprehensive overview complete
- [ ] **CONTRIBUTING.md** - Contribution guidelines ready
- [ ] **API.md** - All endpoints documented
- [ ] **DEPLOYMENT.md** - Deployment guide ready
- [ ] **TELEGRAM_GUIDE.md** - User guide complete
- [ ] **PRODUCTION_CHECKLIST.md** - This checklist (you are here!)
- [ ] **Runbooks** - Incident response procedures documented
- [ ] **Architecture Diagrams** - Up-to-date and accurate

**Verification:**
```bash
# Check docs exist
ls docs/*.md

# Check completeness
grep -r "TODO" docs/
grep -r "FIXME" docs/
```

---

### 9. Media Cleanup & Storage

- [ ] **Media Directories** - Correct permissions (appuser:1000)
- [ ] **Cleanup Tasks** - Celery Beat scheduled tasks active
- [ ] **Retention Policies** - 7 days for completed, 24h for failed
- [ ] **Disk Monitoring** - Alerts at 80% capacity
- [ ] **Backup Exclusions** - Media not backed up (regenerable)
- [ ] **S3/Object Storage** - Configured for media archival (optional)

**Verification:**
```bash
# Check Celery Beat schedule
docker compose exec celery-beat celery -A app.core.celery_app inspect scheduled

# Check disk usage
docker compose exec api df -h /app/media

# Manually trigger cleanup
docker compose exec api python -m app.workers.cleanup_tasks
```

---

### 10. Performance Optimization

- [ ] **Worker Scaling** - Appropriate concurrency per queue
- [ ] **Database Indexes** - 5 composite indexes created
- [ ] **Connection Pooling** - Pool sized for load
- [ ] **Redis Caching** - Query caching enabled
- [ ] **GPU Acceleration** - NVENC/VA-API detected (if available)
- [ ] **FFmpeg Optimized** - Hardware encoding enabled
- [ ] **Queue Backpressure** - Threshold set (50 tasks)

**Verification:**
```bash
# Check worker concurrency
docker compose ps | grep celery

# Check GPU detection
docker compose exec api python -c "from app.services.media_optimization import GPUAcceleration; print(GPUAcceleration.detect_nvenc())"

# Check cache stats
curl http://localhost:8000/api/v1/system/cache/stats
```

---

## 🚀 Launch Checklist

### Launch Day Tasks

1. **[ ] Final Staging Test**
   - Deploy latest main to staging
   - Run full E2E test
   - Verify all monitoring dashboards

2. **[ ] Create Release Tag**
   ```bash
   git tag -a v1.0.0 -m "Production launch v1.0.0"
   git push origin v1.0.0
   ```

3. **[ ] Deploy to Production**
   - GitHub Actions workflow triggers
   - Manual approval required
   - Verify deployment success

4. **[ ] Post-Deployment Verification**
   ```bash
   # Health checks
   curl https://your-domain.com/health
   curl https://your-domain.com/api/v1/system/health

   # Test pipeline
   curl -X POST https://your-domain.com/api/v1/pipeline \
     -H "X-API-Key: your-key" \
     -d '{"topic":"test deployment","video_format":"short"}'
   ```

5. **[ ] Monitor for 1 Hour**
   - Watch Grafana dashboards
   - Monitor error logs
   - Check alert silence (no alerts should fire)

6. **[ ] Enable Telegram Bot**
   ```bash
   # Add first production users
   docker compose exec api python scripts/manage_telegram_users.py add USER_ID "Name"

   # Test bot
   # Send /start to bot on Telegram
   ```

7. **[ ] Announce Launch**
   - Notify users via Telegram/Email
   - Update status page
   - Post on social media (if applicable)

---

## 📋 Post-Launch Checklist

### First 24 Hours

- [ ] **Monitor Dashboards** - Check every 2 hours
- [ ] **Review Logs** - Check for unexpected errors
- [ ] **Check Alerts** - Ensure alerting is working
- [ ] **Test Features** - Generate 5-10 test videos
- [ ] **User Feedback** - Collect feedback from early users
- [ ] **Performance Metrics** - Review pipeline duration, success rate

### First Week

- [ ] **Daily Health Checks** - Review metrics daily
- [ ] **Backup Verification** - Verify backups are running
- [ ] **Security Scan** - Run full security audit
- [ ] **Resource Usage** - Monitor CPU, RAM, disk trends
- [ ] **Cost Analysis** - Review API costs (OpenAI, ElevenLabs)
- [ ] **User Onboarding** - Add remaining users to allowlist

### First Month

- [ ] **Performance Review** - Analyze metrics trends
- [ ] **Cost Optimization** - Optimize API usage
- [ ] **Feature Requests** - Collect and prioritize
- [ ] **Incident Review** - Document any incidents
- [ ] **Dependency Updates** - Review Dependabot PRs
- [ ] **Capacity Planning** - Plan for scaling if needed

---

## 🔧 Runbook - Common Scenarios

### Scenario 1: High Failure Rate (>20%)

**Diagnosis:**
```bash
# Check circuit breaker status
curl http://localhost:8000/api/v1/system/circuit-breakers

# Check DLQ
curl http://localhost:8000/api/v1/admin/dlq/tasks
```

**Resolution:**
- If OpenAI circuit open → Check API key quota
- If ElevenLabs circuit open → Check TTS quota
- Review failed tasks in DLQ for patterns

### Scenario 2: Slow Pipeline (>15 minutes)

**Diagnosis:**
```bash
# Check queue depth
curl http://localhost:8000/api/v1/system/queue-depth

# Check worker CPU
docker stats
```

**Resolution:**
- If queue depth >50 → Scale workers
- If CPU >90% → Add more worker containers
- Check for FFmpeg bottlenecks

### Scenario 3: Database Connection Errors

**Diagnosis:**
```bash
# Check PostgreSQL health
docker compose exec postgres pg_isready

# Check connection pool
docker compose logs api | grep "connection pool"
```

**Resolution:**
- Restart PostgreSQL if unhealthy
- Increase connection pool if exhausted
- Check for connection leaks

### Scenario 4: Out of Disk Space

**Diagnosis:**
```bash
# Check disk usage
df -h

# Check media directory
du -sh /var/lib/docker/volumes/*media*
```

**Resolution:**
- Manually run cleanup task
- Reduce retention periods
- Archive old media to S3

---

## 📞 Emergency Contacts

**On-Call Engineer:**
- Primary: your-name@company.com
- Secondary: backup@company.com

**Service Providers:**
- OpenAI Support: https://platform.openai.com/support
- ElevenLabs Support: support@elevenlabs.io
- Anthropic Support: support@anthropic.com

**Infrastructure:**
- VPS Provider: [Your provider support]
- Domain Registrar: [Your registrar support]

---

## 🎯 Success Criteria

**Launch is successful when:**

- ✅ Zero critical errors in first 24 hours
- ✅ 95%+ pipeline success rate
- ✅ Average pipeline duration <8 minutes
- ✅ All monitoring dashboards green
- ✅ No security incidents
- ✅ Positive user feedback
- ✅ Cost per video <$1.00

**If any criteria not met:**
- Document issues
- Create action items
- Prioritize fixes
- Consider rollback if critical

---

**Last Updated:** 2026-03-03
**Version:** 1.0.0
**Maintained By:** YouTube Shorts Automation Team
