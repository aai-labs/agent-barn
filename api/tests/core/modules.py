import os
from typing import TypeVar

from injector import Injector
from starlette.testclient import TestClient

from api.api_app import create_app
from api.core.config import get_config
from api.core.utils import create_modules
from api.ingest_app import create_ingest_app


def prepare_injector(modules=None):
    def step(context):
        default_modules = create_modules()
        modules_final = default_modules + (modules or [])
        context.injector = Injector(modules=modules_final)

    return step


def prepare_api_server():
    def step(context):
        context.app = create_app(injector=context.injector)

    return step


def create_test_client():
    def step(context):
        context.client = TestClient(context.app)

    return step


def prepare_ingest_server():
    def step(context):
        context.ingest_app = create_ingest_app(injector=context.injector)
        context.ingest_client = TestClient(context.ingest_app)

    return step


def set_env_variable(vars_dict: dict[str, str]):
    def step(context):
        get_config.cache_clear()
        for key, value in vars_dict.items():
            os.environ[key] = value

    return step


C = TypeVar("C")
