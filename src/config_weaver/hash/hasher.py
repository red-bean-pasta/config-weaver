import anyio
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


ARGON_HASHER = Argon2Hasher(
    memory_cost=65536,
    time_cost=3,
    parallelism=3
)
HASH_MANAGER = PasswordHash((ARGON_HASHER,))

DUMMY_HASH = HASH_MANAGER.hash("this-is-a-dummy-password")


def hash_secret(secret: str) -> str:
    return HASH_MANAGER.hash(secret)

async def verify_hash(secret: str, secret_hash: str) -> bool:
    return await anyio.to_thread.run_sync(HASH_MANAGER.verify, secret, secret_hash)

async def dummy_verify() -> None:
    await verify_hash("", DUMMY_HASH)