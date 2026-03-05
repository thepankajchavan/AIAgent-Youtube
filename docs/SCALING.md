# Worker Scaling Guide

## Overview

The YouTube Shorts Automation Engine is designed to handle 100+ concurrent pipelines efficiently through optimized worker scaling and resource allocation.

## Current Worker Configuration

### Worker Types and Concurrency

| Worker Type | Queue | Concurrency | Workload Type | Resource Usage |
|-------------|-------|-------------|---------------|----------------|
| **celery-default** | `default` | 1 | Orchestration | Low CPU, Low I/O |
| **celery-scripts** | `scripts` | 4 | LLM API calls | Low CPU, High I/O |
| **celery-media** | `media` | 2 | FFmpeg processing | **High CPU**, Low I/O |
| **celery-upload** | `upload` | 2 | YouTube uploads | Low CPU, High I/O |

### Concurrency Rationale

**Scripts Queue (4 concurrent):**
- I/O-bound: Waiting for OpenAI/Anthropic responses
- Network latency is the bottleneck, not CPU
- Higher concurrency = better throughput
- Recommended: 4-8 concurrent based on API rate limits

**Media Queue (2 concurrent):**
- **CPU-bound**: FFmpeg video encoding is computationally expensive
- Each task can max out a CPU core
- Concurrency = number of CPU cores available
- Recommended: 2 on dual-core, 4 on quad-core

**Upload Queue (2 concurrent):**
- I/O-bound: Large file uploads to YouTube
- Limited by network bandwidth
- 2 concurrent provides good balance
- Recommended: 2-4 concurrent

## Performance Optimizations

### Prefetch Multiplier

```python
worker_prefetch_multiplier = 1  # Fair scheduling
```

- **Value: 1** = Each worker prefetches only 1 task at a time
- Ensures fair distribution across workers
- Prevents long-running tasks from blocking the queue

### Task Limits

```python
worker_max_tasks_per_child = 100  # Restart worker after 100 tasks
task_time_limit = 3600            # Hard limit: 1 hour
task_soft_time_limit = 3300       # Soft limit: 55 minutes
```

- **max_tasks_per_child**: Prevents memory leaks from accumulating
- **time_limit**: Kills runaway tasks to prevent resource exhaustion
- **soft_time_limit**: Allows graceful shutdown before hard kill

### Compression

```python
task_compression = 'gzip'    # Compress task payloads
result_compression = 'gzip'  # Compress results
```

- Reduces Redis memory usage
- Reduces network bandwidth
- Small CPU overhead, significant memory savings

## Horizontal Scaling Strategies

### Docker Compose Scaling

Scale specific worker types based on load:

```bash
# Scale scripts workers (LLM bottleneck)
docker-compose up -d --scale celery-scripts=3

# Scale media workers (encoding bottleneck)
docker-compose up -d --scale celery-media=4

# Scale upload workers (upload bottleneck)
docker-compose up -d --scale celery-upload=2
```

### Kubernetes Horizontal Pod Autoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: celery-scripts-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: celery-scripts
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: External
      external:
        metric:
          name: celery_queue_depth
          selector:
            matchLabels:
              queue: scripts
        target:
          type: Value
          value: "20"  # Scale up if queue depth > 20
```

### Manual Scaling Decision Matrix

| Queue Depth | CPU Usage | Action |
|-------------|-----------|--------|
| < 10 tasks | < 50% | No action needed |
| 10-30 tasks | 50-80% | Monitor closely |
| 30-50 tasks | > 80% | Scale up by 1-2 workers |
| > 50 tasks | Any | **Immediate scale-up** (backpressure threshold) |

## Monitoring for Scaling Decisions

### Key Metrics to Watch

**Queue Depth (Prometheus):**
```promql
celery_queue_depth{queue="scripts"}
celery_queue_depth{queue="media"}
celery_queue_depth{queue="upload"}
```

**Worker Utilization:**
```promql
active_celery_tasks{queue="scripts"} / (celery_worker_online{queue="scripts"} * 4)
```

**Task Wait Time:**
```promql
histogram_quantile(0.95, rate(step_duration_seconds_bucket[5m]))
```

### Grafana Alerts

Configure alerts for scaling triggers:

```yaml
- alert: HighQueueDepth
  expr: celery_queue_depth{queue="scripts"} > 30
  for: 5m
  annotations:
    summary: "Scripts queue is backed up ({{ $value }} tasks)"
    action: "Consider scaling celery-scripts workers"

- alert: SlowPipelineDuration
  expr: histogram_quantile(0.95, rate(pipeline_duration_seconds_bucket[10m])) > 600
  for: 10m
  annotations:
    summary: "Pipeline p95 duration > 10 minutes"
    action: "Check worker CPU usage and scale if needed"
```

## Resource Requirements

### Per-Worker Resource Allocation

**Scripts Worker:**
- CPU: 0.5 cores
- Memory: 512 MB
- Network: High bandwidth (API calls)

**Media Worker:**
- CPU: **2 cores** (FFmpeg is CPU-intensive)
- Memory: 1-2 GB (video processing)
- Disk: 5-10 GB temp space

**Upload Worker:**
- CPU: 0.5 cores
- Memory: 512 MB
- Network: High bandwidth (large file uploads)

### Total System Requirements (100 Concurrent Pipelines)

Assuming average pipeline: 5 scripts, 3 media, 2 upload tasks

**Minimum Configuration:**
- **Scripts Workers**: 4 workers × 4 concurrency = 16 concurrent
- **Media Workers**: 8 workers × 2 concurrency = 16 concurrent
- **Upload Workers**: 4 workers × 2 concurrency = 8 concurrent

**Resource Total:**
- CPU: ~30 cores (4×0.5 + 8×2 + 4×0.5)
- Memory: ~20 GB (4×0.5 + 8×2 + 4×0.5)
- Storage: 100 GB (media files + temp)
- Network: 1 Gbps

## Auto-Scaling Implementation

### KEDA (Kubernetes Event-Driven Autoscaling)

Install KEDA and configure Redis scaler:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: celery-scripts-scaler
spec:
  scaleTargetRef:
    name: celery-scripts
  minReplicaCount: 2
  maxReplicaCount: 20
  triggers:
    - type: redis
      metadata:
        address: redis:6379
        listName: scripts
        listLength: "10"  # Target 10 tasks per worker
```

### AWS ECS Auto Scaling

```json
{
  "serviceName": "celery-scripts",
  "scalingPolicies": [
    {
      "policyName": "scale-on-queue-depth",
      "targetTrackingScaling": {
        "targetValue": 20.0,
        "customizedMetricSpecification": {
          "metricName": "celery_queue_depth",
          "namespace": "YouTube-Automation",
          "dimensions": [{"name": "queue", "value": "scripts"}],
          "statistic": "Average"
        }
      }
    }
  ]
}
```

## Best Practices

### Do's ✅

- Monitor queue depth continuously
- Scale based on sustained load (> 5 minutes), not spikes
- Set reasonable min/max replica counts
- Use prefetch_multiplier=1 for fair scheduling
- Restart workers periodically (max_tasks_per_child)
- Set task time limits to prevent runaway tasks

### Don'ts ❌

- Don't over-provision workers (wastes resources)
- Don't set concurrency too high for CPU-bound tasks
- Don't ignore memory limits (causes OOM kills)
- Don't scale without monitoring metrics first
- Don't forget to scale down during low load

## Troubleshooting

### High Queue Depth Despite Scaling

**Possible Causes:**
1. Workers are crashing (check logs)
2. Tasks are timing out (increase limits)
3. External API rate limits (OpenAI, YouTube)
4. Database connection pool exhaustion

**Solutions:**
- Check worker health: `docker-compose ps`
- View worker logs: `docker-compose logs -f celery-scripts`
- Monitor external API errors in Grafana
- Increase database pool size

### Memory Issues

**Symptoms:**
- Workers being killed (OOM)
- Slow task execution
- High swap usage

**Solutions:**
- Reduce worker concurrency
- Decrease max_tasks_per_child
- Add more RAM or scale horizontally
- Enable result compression

### CPU Bottleneck

**Symptoms:**
- Media workers at 100% CPU
- Long pipeline durations
- Queue depth increasing

**Solutions:**
- Scale media workers horizontally
- Use GPU-accelerated encoding (NVENC)
- Reduce video resolution/bitrate
- Process clips in parallel

---

**Last Updated:** 2026-03-03
**Maintained By:** YouTube Shorts Automation Team
