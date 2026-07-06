from .handlers import register_shell_handlers

def register(application):
    register_shell_handlers(application)
