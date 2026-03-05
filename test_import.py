"""Test if the FastAPI app can be imported without errors."""
from app.main import app

print("[OK] FastAPI app imported successfully")
print(f"[OK] App title: {app.title}")
print(f"[OK] Routes: {len(app.routes)}")
