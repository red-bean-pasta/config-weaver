from config_weaver.hash.hasher import hash_secret


def hash(credential: str) -> str:
    return hash_secret(credential)