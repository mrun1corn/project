from .handlers import register_help_handlers

def register(application):
    register_help_handlers(application)
