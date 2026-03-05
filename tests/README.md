# Testing Documentation

This directory contains the complete test suite for the YouTube Shorts Automation Engine.

## Test Structure

```
tests/
├── conftest.py                 # Shared fixtures and configuration
├── fixtures/                   # Test data and sample media files
│   ├── sample_script.json
│   ├── sample_audio.mp3
│   └── sample_video.mp4
├── unit/                       # Unit tests (mocked dependencies)
│   ├── test_llm_service.py
│   ├── test_tts_service.py
│   ├── test_visual_service.py
│   ├── test_media_service.py
│   ├── test_youtube_service.py
│   ├── test_sanitizers.py
│   ├── test_encryption.py
│   └── test_models.py
├── integration/                # Integration tests (real DB, mocked APIs)
│   ├── test_pipeline_route.py
│   ├── test_projects_route.py
│   ├── test_admin_route.py
│   └── test_system_route.py
├── tasks/                      # Celery task tests
│   └── test_celery_pipeline.py
└── e2e/                        # End-to-end tests
    └── test_full_pipeline.py
```

## Running Tests

### Quick Start

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest -v

# Run with coverage
pytest --cov=app --cov-report=html --cov-report=term-missing
```

### Using Makefile

```bash
# Run all tests
make test

# Run specific test types
make test-unit
make test-integration
make test-e2e

# Run linting
make lint

# Format code
make format
```

### Test Categories

**Unit Tests** (tests/unit/)
```bash
pytest tests/unit/ -v
```
- Test individual components in isolation
- All external dependencies mocked
- Fast execution (~10-20s)
- Target: 90%+ coverage

**Integration Tests** (tests/integration/)
```bash
pytest tests/integration/ -v
```
- Test API endpoints with real database
- External services (OpenAI, Pexels, etc.) mocked
- Medium execution (~30-60s)
- Target: 85%+ coverage

**Task Tests** (tests/tasks/)
```bash
pytest tests/tasks/ -v
```
- Test Celery pipeline orchestration
- Tests run in eager mode (synchronous)
- Target: 80%+ coverage

**E2E Tests** (tests/e2e/)
```bash
pytest tests/e2e/ -v -m e2e
```
- Test complete pipeline flows
- All external services mocked
- Slower execution (~2-5min)
- Target: 70%+ coverage

## Test Database

Tests use a separate PostgreSQL database:

```
Database: content_engine_test
URL: postgresql+asyncpg://postgres:postgres@localhost:5432/content_engine_test
```

The test database is automatically created and cleaned up via fixtures in `conftest.py`.

## Coverage Requirements

| Test Type | Target Coverage | Priority |
|-----------|----------------|----------|
| Unit Tests (Services) | 90%+ | CRITICAL |
| Unit Tests (Security) | 95%+ | CRITICAL |
| Integration Tests (API) | 85%+ | HIGH |
| Celery Task Tests | 80%+ | HIGH |
| E2E Tests | 70%+ | MEDIUM |
| **Overall Target** | **80%+** | **REQUIRED** |

## Writing Tests

### Unit Test Example

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

class TestMyService:
    @pytest.mark.asyncio
    async def test_my_function(self, mocker):
        """Test description."""
        # Mock external dependency
        mock_api = AsyncMock()
        mock_api.call.return_value = {"data": "value"}
        mocker.patch("app.services.my_service.api_client", mock_api)
        
        # Execute
        result = await my_function()
        
        # Assert
        assert result["data"] == "value"
        mock_api.call.assert_called_once()
```

### Integration Test Example

```python
class TestMyEndpoint:
    @pytest.mark.asyncio
    async def test_create_resource(self, client, db_session):
        """Test API endpoint."""
        # Make request
        response = await client.post(
            "/api/v1/resource",
            json={"name": "Test"}
        )
        
        # Verify response
        assert response.status_code == 201
        
        # Verify database
        from sqlalchemy import select
        result = await db_session.execute(select(MyModel))
        assert result.scalar_one().name == "Test"
```

## Fixtures

### Shared Fixtures (conftest.py)

- `test_settings`: Override app settings for testing
- `test_engine`: Test database engine (session-scoped)
- `db_session`: Fresh database session per test (auto-rollback)
- `client`: Async HTTP client for API testing
- `fixtures_dir`: Path to test fixtures
- `sample_script`: Mock LLM response
- `sample_audio_path`: Path to test audio file
- `sample_video_path`: Path to test video file

### Using Fixtures

```python
@pytest.mark.asyncio
async def test_with_fixtures(client, db_session, sample_script):
    # Use fixtures directly as parameters
    assert sample_script["title"] is not None
```

## Generating Test Fixtures

Generate sample media files (requires FFmpeg in Docker):

```bash
docker compose exec api python tests/generate_fixtures.py
```

Or manually with FFmpeg:

```bash
# Silent audio
ffmpeg -f lavfi -i anullsrc=duration=1.0 -c:a libmp3lame tests/fixtures/sample_audio.mp3

# Black video (9:16 Shorts format)
ffmpeg -f lavfi -i color=black:s=1080x1920:d=1.0 -c:v libx264 tests/fixtures/sample_video.mp4
```

## Mocking Patterns

### Async Functions

```python
mock_func = AsyncMock(return_value={"result": "value"})
mocker.patch("app.module.async_function", mock_func)
```

### HTTP Streaming

```python
async def mock_aiter_bytes(chunk_size):
    yield b"chunk1"
    yield b"chunk2"

mock_response = AsyncMock()
mock_response.aiter_bytes = mock_aiter_bytes
```

### Subprocess (FFmpeg)

```python
mock_result = MagicMock()
mock_result.returncode = 0
mock_result.stdout = '{"duration": "10.5"}'
mocker.patch("subprocess.run", return_value=mock_result)
```

## CI/CD Integration

### GitHub Actions

Tests run automatically on:
- Push to `main` or `develop`
- Pull requests

See `.github/workflows/tests.yml` for configuration.

### Pre-commit Hooks

Install pre-commit hooks to run tests before commits:

```bash
pip install pre-commit
pre-commit install
```

Configured in `.pre-commit-config.yaml`.

## Troubleshooting

### Database Connection Errors

Ensure PostgreSQL is running:
```bash
docker compose up -d postgres
```

### Redis Connection Errors

Ensure Redis is running:
```bash
docker compose up -d redis
```

### FFmpeg Not Found

Install FFmpeg:
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt-get install ffmpeg`
- Windows: Download from https://ffmpeg.org/

Or run tests inside Docker:
```bash
docker compose exec api pytest
```

### Coverage Too Low

Run coverage report to identify untested code:
```bash
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

## Best Practices

1. **One Concept Per Test**: Each test should verify one specific behavior
2. **Descriptive Names**: Use descriptive test names that explain what is being tested
3. **AAA Pattern**: Arrange, Act, Assert
4. **Mock External Dependencies**: Never call real APIs in tests
5. **Clean Up**: Use fixtures with automatic cleanup
6. **Fast Tests**: Keep unit tests under 100ms each
7. **Deterministic**: Tests should always produce the same result

## Coverage Reports

After running tests with coverage:

```bash
pytest --cov=app --cov-report=html
```

Open the HTML report:
- macOS/Linux: `open htmlcov/index.html`
- Windows: `start htmlcov/index.html`

## Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.slow
```

Run specific markers:
```bash
pytest -m "unit"
pytest -m "not slow"
```

## Support

For questions or issues with tests:
1. Check this README
2. Review test examples in each directory
3. See pytest documentation: https://docs.pytest.org/
4. Check conftest.py for available fixtures
