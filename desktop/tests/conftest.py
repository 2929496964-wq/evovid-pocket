"""Create the generic synthetic test clip locally; no external or personal media."""
from pathlib import Path

def pytest_sessionstart(session):
    from tools.make_review_fixture import make_clip
    target=Path(__file__).resolve().parents[1]/'submission-assets'/'demo-input.mp4'
    if not target.exists():
        make_clip(target, 'lowlight', seconds=8)
