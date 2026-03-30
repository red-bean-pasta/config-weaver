from config_weaver.encrypt import encryptor
from config_weaver.file_managers.file_data import FileData


class ConfigManager(FileData):
    def decrypt(self, encryption_key: str) -> bytes | None:
        return encryptor.decrypt_file(
            encryption_key,
            self.get_content()
        )