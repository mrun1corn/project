import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from src.core.config import settings


tls_kwargs = {}
try:
    tls_kwargs["tlsCAFile"] = certifi.where()
except Exception:
    pass

_client = AsyncIOMotorClient(
    settings.mongodb_uri,
    serverSelectionTimeoutMS=2000,
    connectTimeoutMS=2000,
    socketTimeoutMS=3000,
    **tls_kwargs
)
db = _client[settings.mongodb_db_name]


def get_collection(name: str):
    return db[name]
