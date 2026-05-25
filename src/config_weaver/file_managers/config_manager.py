from config_weaver.encrypt import encryptor
from config_weaver.file_managers.file_data import FileData


class ConfigManager(FileData):
    def decrypt(self, encryption_key: str) -> bytes | None:
        encrypted = self.get_content()

        if not encrypted:
            raise FileNotFoundError(f"Base config not found: {self.path}")

        return encryptor.decrypt_file(
            encryption_key,
            encrypted
        )