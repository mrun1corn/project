from .handlers import register_note_handlers

def register(application):
    register_note_handlers(application)
