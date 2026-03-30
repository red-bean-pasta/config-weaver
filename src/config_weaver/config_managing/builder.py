import json
import logging
from pathlib import Path

from config_weaver import manager_helper
from config_weaver.file_managers.patch_manager import PatchParam


logger = logging.getLogger(__name__)


def build(
        spec_dir: str | Path,
        param: PatchParam,
        encryption_key: str
) -> dict:
    config_manager = manager_helper.build_config_manager(spec_dir)
    patch_manager = manager_helper.build_patch_manager(spec_dir)

    logger.info(f"Decrypting config...")
    decrypted = config_manager.decrypt(encryption_key)
    logger.info(f"Parsing config...")
    parsed = json.loads(decrypted)
    logger.info(f"Patching config...")
    patched = patch_manager.patch(param, parsed)

    return patched