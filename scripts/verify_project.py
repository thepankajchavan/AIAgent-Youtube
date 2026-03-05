#!/usr/bin/env python3
"""
Project Verification Script
Performs comprehensive checks on the YouTube Shorts Automation Engine
"""

import sys
import subprocess
from pathlib import Path
import importlib.util

# ANSI colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_header(text):
    """Print a section header"""
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}{text:^70}{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}\n")

def print_check(description, passed, details=""):
    """Print a check result"""
    status = f"{GREEN}[PASS]{RESET}" if passed else f"{RED}[FAIL]{RESET}"
    print(f"{status} {description}")
    if details and not passed:
        print(f"        {YELLOW}{details}{RESET}")

def check_python_version():
    """Check Python version is 3.12+"""
    version = sys.version_info
    passed = version.major == 3 and version.minor >= 12
    print_check(
        f"Python version (current: {version.major}.{version.minor}.{version.micro})",
        passed,
        "Python 3.12+ required"
    )
    return passed

def check_file_exists(filepath):
    """Check if a file exists"""
    path = Path(filepath)
    return path.exists()

def check_python_file_syntax(filepath):
    """Check if a Python file compiles"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            compile(f.read(), filepath, 'exec')
        return True
    except SyntaxError as e:
        return False, str(e)

def check_dependencies():
    """Check if key dependencies are importable"""
    dependencies = [
        'fastapi',
        'celery',
        'sqlalchemy',
        'redis',
        'openai',
        'anthropic',
        'elevenlabs',
        'telegram',
        'loguru',
        'pydantic',
    ]

    failed = []
    for dep in dependencies:
        try:
            __import__(dep)
        except ImportError:
            failed.append(dep)

    return len(failed) == 0, failed

def run_command(cmd, description):
    """Run a shell command and return success status"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0, result.stderr
    except Exception as e:
        return False, str(e)

def main():
    """Run all verification checks"""
    print_header("YouTube Shorts Automation Engine - Project Verification")

    all_passed = True

    # ═══════════════════════════════════════════════════════════
    # Section 1: Environment Checks
    # ═══════════════════════════════════════════════════════════
    print_header("1. Environment Checks")

    passed = check_python_version()
    all_passed = all_passed and passed

    # Check FFmpeg
    passed, error = run_command("ffmpeg -version", "FFmpeg installation")
    print_check("FFmpeg installation", passed, error if not passed else "")
    all_passed = all_passed and passed

    # Check Docker
    passed, error = run_command("docker --version", "Docker installation")
    print_check("Docker installation", passed, error if not passed else "")
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # Section 2: File Structure
    # ═══════════════════════════════════════════════════════════
    print_header("2. File Structure")

    critical_files = [
        "app/main.py",
        "app/core/config.py",
        "app/core/celery_app.py",
        "requirements.txt",
        "requirements-dev.txt",
        "Dockerfile",
        "docker-compose.yml",
        "alembic.ini",
        ".env.docker",
    ]

    for filepath in critical_files:
        passed = check_file_exists(filepath)
        print_check(f"File exists: {filepath}", passed)
        all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # Section 3: Python Code Syntax
    # ═══════════════════════════════════════════════════════════
    print_header("3. Python Code Syntax")

    # Compile all Python files in app/
    try:
        result = subprocess.run(
            ["python", "-m", "compileall", "app/", "-q"],
            capture_output=True,
            text=True,
            timeout=30
        )
        passed = result.returncode == 0
        print_check("All Python files compile successfully", passed, result.stderr)
        all_passed = all_passed and passed
    except Exception as e:
        print_check("All Python files compile successfully", False, str(e))
        all_passed = False

    # ═══════════════════════════════════════════════════════════
    # Section 4: Dependencies
    # ═══════════════════════════════════════════════════════════
    print_header("4. Python Dependencies")

    passed, failed_deps = check_dependencies()
    if passed:
        print_check("All required dependencies importable", True)
    else:
        print_check("All required dependencies importable", False,
                   f"Missing: {', '.join(failed_deps)}")
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # Section 5: Docker Configuration
    # ═══════════════════════════════════════════════════════════
    print_header("5. Docker Configuration")

    passed, error = run_command("docker compose config --quiet", "docker-compose.yml validation")
    print_check("docker-compose.yml syntax", passed, error if not passed else "")
    all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # Section 6: Database Migrations
    # ═══════════════════════════════════════════════════════════
    print_header("6. Database Migrations")

    # Count migration files
    migrations_dir = Path("alembic/versions")
    if migrations_dir.exists():
        migration_files = list(migrations_dir.glob("*.py"))
        migration_count = len([f for f in migration_files if f.name != "__init__.py"])
        print_check(f"Migration files found: {migration_count}", migration_count > 0)

        # Verify migrations compile
        try:
            result = subprocess.run(
                ["python", "-m", "compileall", "alembic/versions/", "-q"],
                capture_output=True,
                text=True,
                timeout=10
            )
            passed = result.returncode == 0
            print_check("All migration files compile", passed, result.stderr)
            all_passed = all_passed and passed
        except Exception as e:
            print_check("All migration files compile", False, str(e))
            all_passed = False
    else:
        print_check("Migrations directory exists", False, "alembic/versions/ not found")
        all_passed = False

    # ═══════════════════════════════════════════════════════════
    # Section 7: Documentation
    # ═══════════════════════════════════════════════════════════
    print_header("7. Documentation")

    doc_files = [
        "README.md",
        "CONTRIBUTING.md",
        "docs/API.md",
        "docs/TELEGRAM_GUIDE.md",
        "docs/PRODUCTION_CHECKLIST.md",
        "PROJECT_STATUS.md",
    ]

    for filepath in doc_files:
        passed = check_file_exists(filepath)
        print_check(f"Documentation: {filepath}", passed)
        all_passed = all_passed and passed

    # ═══════════════════════════════════════════════════════════
    # Final Summary
    # ═══════════════════════════════════════════════════════════
    print_header("Verification Summary")

    if all_passed:
        print(f"{GREEN}{BOLD}[SUCCESS] ALL CHECKS PASSED{RESET}")
        print(f"\n{GREEN}Project is ready for local testing and deployment!{RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}[ERROR] SOME CHECKS FAILED{RESET}")
        print(f"\n{RED}Please fix the issues above before deployment.{RESET}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
