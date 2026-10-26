"""Dedicated browser-test server; uses a temporary DB and explicit model stub."""
from pathlib import Path
import tempfile

import uvicorn

from app.config import Settings
from app.main import create_app
from tests.test_api import LocalModelStub

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='campusflow-ui-') as folder:
        root = Path(folder)
        app = create_app(Settings(), db_path=root/'db.sqlite',config_path=root/'config.json',llm=LocalModelStub())
        uvicorn.run(app,host='127.0.0.1',port=8765)
