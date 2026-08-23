import os
import sys

# Ensure root workspace directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Must be set before `main` is imported: it gates the cookie/logging bootstrap in the
# lifespan, which shells out to yt-dlp and would make tests slow and network-dependent.
os.environ.setdefault("TESTING", "1")
