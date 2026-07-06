from .handlers import register_mirror_handlers

def register(application):
    register_mirror_handlers(application)
