import logging

from api.memory_app import create_memory_app

logging.basicConfig(level=logging.INFO)

app = create_memory_app()
