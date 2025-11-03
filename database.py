import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from settings import settings


tls_kwargs = {}
try:
    tls_kwargs["tlsCAFile"] = certifi.where()
except Exception:
    pass

_client = AsyncIOMotorClient(settings.mongodb_uri, **tls_kwargs)
db = _client[settings.mongodb_db_name]


def get_collection(name: str):
    return db[name]
