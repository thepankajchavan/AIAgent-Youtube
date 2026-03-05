# Monitoring & Observability Stack

Complete monitoring solution for the YouTube Shorts Automation Engine using Prometheus, Grafana, Alertmanager, and Flower.

## 📊 Components

### 1. **Prometheus** (Metrics Collection)
- **URL**: http://localhost:9090
- **Purpose**: Collects and stores time-series metrics
- **Metrics Collected**:
  - Pipeline execution rates and durations
  - API request rates and response times
  - External API call statistics
  - Celery worker and queue status
  - System resource usage

### 2. **Grafana** (Metrics Visualization)
- **URL**: http://localhost:3000
- **Default Credentials**: `admin / admin` (change on first login)
- **Dashboards**:
  - **Pipeline Monitoring Dashboard**: Track pipeline success/failure rates, durations, and bottlenecks
  - **Celery Workers Dashboard**: Monitor worker status, queue depths, and task execution
  - **API Performance Dashboard**: HTTP request rates, error rates, response times, external API metrics

### 3. **Alertmanager** (Alert Management)
- **URL**: http://localhost:9093
- **Purpose**: Manages and routes alerts from Prometheus
- **Alert Types**:
  - **Critical**: High pipeline failure rate, no workers online, high API error rate
  - **Warning**: Slow pipelines, high queue depth, slow API responses, high resource usage

### 4. **Flower** (Celery Monitoring UI)
- **URL**: http://localhost:5555
- **Default Credentials**: `admin / admin`
- **Features**:
  - Real-time worker monitoring
  - Task history and execution details
  - Queue depth visualization
  - Worker control (restart, shutdown)

### 5. **Celery Metrics Exporter**
- **URL**: http://localhost:9090/metrics
- **Purpose**: Exports Celery-specific metrics to Prometheus
- **Metrics Exposed**:
  - `active_celery_tasks`: Currently running tasks per queue
  - `celery_queue_depth`: Tasks waiting in each queue
  - `celery_worker_online`: Online worker count

---

## 🚀 Quick Start

### Start All Services

```bash
docker-compose up -d
```

### Access Dashboards

1. **Grafana** (Main UI): http://localhost:3000
   - Login: `admin / admin`
   - Navigate to "Dashboards" → Select a dashboard

2. **Prometheus** (Metrics Explorer): http://localhost:9090
   - Click "Graph" to query metrics
   - Example: `rate(pipeline_total[5m])`

3. **Flower** (Celery Monitoring): http://localhost:5555
   - Login: `admin / admin`
   - View workers, tasks, and queues

4. **Alertmanager** (Alerts): http://localhost:9093
   - View active and silenced alerts

### Check Metrics Endpoints

```bash
# FastAPI application metrics
curl http://localhost:8000/metrics

# Celery worker metrics
curl http://localhost:9090/metrics
```

---

## 📈 Key Metrics

### Pipeline Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `pipeline_total` | Counter | Total pipelines triggered |
| `pipeline_completed` | Counter | Successfully completed pipelines |
| `pipeline_failed` | Counter | Failed pipelines (with failure step label) |
| `pipeline_duration_seconds` | Histogram | End-to-end pipeline execution time |
| `step_duration_seconds` | Histogram | Individual step execution time |

### API Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `http_requests_total` | Counter | Total HTTP requests (by status code) |
| `http_request_duration_seconds` | Histogram | HTTP response time |
| `http_requests_inprogress` | Gauge | Currently processing requests |

### External API Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `external_api_calls_total` | Counter | Total external API calls (by service) |
| `external_api_errors_total` | Counter | Failed external API calls |
| `external_api_duration_seconds` | Histogram | External API response time |

### Celery Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `active_celery_tasks` | Gauge | Running tasks per queue |
| `celery_queue_depth` | Gauge | Tasks waiting per queue |
| `celery_worker_online` | Gauge | Online worker count |

---

## 🔔 Alert Rules

### Critical Alerts (Immediate Action Required)

1. **HighPipelineFailureRate**
   - Trigger: >20% failure rate for 5 minutes
   - Impact: Pipeline system is degraded

2. **NoWorkersOnline**
   - Trigger: Zero workers online for 2 minutes
   - Impact: Pipeline processing completely stopped

3. **HighAPIErrorRate**
   - Trigger: >10% external API error rate for 5 minutes
   - Impact: External service integrations failing

### Warning Alerts (Investigation Needed)

1. **SlowPipelineExecution**
   - Trigger: p95 duration >10 minutes for 10 minutes
   - Impact: Pipelines are slower than expected

2. **HighQueueDepth**
   - Trigger: >50 tasks waiting for 5 minutes
   - Impact: Workers may be overloaded

3. **SlowAPIResponse**
   - Trigger: p95 response time >5 seconds for 5 minutes
   - Impact: API performance degradation

4. **HighMemoryUsage**
   - Trigger: >80% memory usage for 5 minutes
   - Impact: System may run out of memory

5. **HighDiskUsage**
   - Trigger: >80GB media storage for 10 minutes
   - Impact: Disk space running low

---

## ⚙️ Configuration

### Alertmanager Email Notifications

Edit `monitoring/alertmanager.yml`:

```yaml
global:
  smtp_from: 'alerts@yourdomain.com'
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_auth_username: 'your-email@gmail.com'
  smtp_auth_password: 'your-app-password'  # Use App Password for Gmail

receivers:
  - name: 'critical-alerts'
    email_configs:
      - to: 'admin@yourdomain.com,oncall@yourdomain.com'
```

### Alertmanager Slack Notifications (Optional)

```yaml
receivers:
  - name: 'critical-alerts'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts-critical'
        send_resolved: true
```

### Grafana Admin Password

Set via environment variable in `.env`:

```bash
GRAFANA_USER=admin
GRAFANA_PASSWORD=your-secure-password
```

### Flower Authentication

Set via environment variable in `.env`:

```bash
FLOWER_BASIC_AUTH=admin:your-secure-password
```

---

## 🔍 Querying Metrics

### Prometheus Query Examples

```promql
# Pipeline failure rate (last 5 minutes)
rate(pipeline_failed[5m]) / rate(pipeline_total[5m])

# Average pipeline duration (last 15 minutes)
rate(pipeline_duration_seconds_sum[15m]) / rate(pipeline_duration_seconds_count[15m])

# Queue depth by queue
sum by(queue) (celery_queue_depth)

# API error rate by status code
sum by(status) (rate(http_requests_total{status=~"5.."}[5m]))

# External API call rate by service
sum by(service) (rate(external_api_calls_total[5m]))
```

### View Metrics in Grafana

1. Go to http://localhost:3000
2. Navigate to **Dashboards** → **Browse**
3. Select a dashboard:
   - Pipeline Monitoring Dashboard
   - Celery Workers Dashboard
   - API Performance Dashboard

---

## 🛠️ Troubleshooting

### Prometheus Not Scraping Metrics

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Check if metrics endpoint is accessible
curl http://localhost:8000/metrics
```

### Grafana Not Showing Data

1. Check Prometheus datasource: **Configuration** → **Data Sources** → **Prometheus**
2. Test connection (should show "Data source is working")
3. Verify time range in dashboard (default: last 1 hour)

### Alertmanager Not Sending Alerts

```bash
# Check Alertmanager status
curl http://localhost:9093/api/v1/status

# Check alert rules in Prometheus
curl http://localhost:9090/api/v1/rules
```

### Flower Not Showing Workers

```bash
# Check Celery broker connection
docker logs content-engine-flower

# Verify Redis is accessible
docker exec -it content-engine-redis redis-cli ping
```

---

## 📚 Additional Resources

- **Prometheus Documentation**: https://prometheus.io/docs/
- **Grafana Tutorials**: https://grafana.com/tutorials/
- **Alertmanager Guide**: https://prometheus.io/docs/alerting/latest/alertmanager/
- **Flower Documentation**: https://flower.readthedocs.io/

---

## 🔒 Security Notes

1. **Change default passwords** for Grafana and Flower in production
2. **Configure SMTP credentials** in `alertmanager.yml` for email alerts
3. **Restrict access** to monitoring dashboards using firewall rules or reverse proxy
4. **Enable HTTPS** for all monitoring services in production

---

**Last Updated**: 2025-01-XX
**Maintainer**: YouTube Shorts Automation Team
