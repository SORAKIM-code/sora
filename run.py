"""서버 실행 진입점: python run.py  (어느 폴더에서 실행해도 된다)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.server import main  # noqa: E402

if __name__ == "__main__":
    main()
