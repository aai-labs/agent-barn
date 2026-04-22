from injector import Injector

from api.infrastructure.app import AppModule


def create_injector():
    return Injector(modules=create_modules())


def create_modules():
    modules = [
        AppModule(),
    ]
    return modules
