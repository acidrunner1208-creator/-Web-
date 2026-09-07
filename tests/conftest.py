import os
import tempfile

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("SCRAPING_ENABLED", "false")
os.environ.setdefault("N_SIMS", "2000")
os.environ.setdefault("CACHE_DIR", tempfile.mkdtemp(prefix="keiba-cache-"))
os.environ.setdefault("OUT_DIR", tempfile.mkdtemp(prefix="keiba-out-"))
