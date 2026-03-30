import copy
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import TypeVar, Self, Generic

import portalocker

from sailor_tailor import file_operator
from sailor_tailor.json_helper import get_readable_dump


logger = logging.getLogger(__name__)


T = TypeVar("T")
@dataclass # 'slots=True' causes weird super() resolution bug as it needs to swap to slotted class
class Config(Generic[T]):
    path: Path
    content: T
    modified_time_ns: int
    _reload_callbacks: list[Callable[[Self], None]]

    @classmethod
    def load(cls, path: Path | str) -> Self:
        path = Path(path)
        data = cls._read_bytes(path)
        mtime = Config._read_mtime_ns(path) or -1
        content = cls._parse_bytes(data if data is not None else cls._handle_file_not_found())
        base_kwargs = {
            "path": path,
            "content": content,
            "modified_time_ns": mtime,
            "_reload_callbacks": cls._get_default_reload_callbacks()
        }
        extra_kwargs = cls._extra_kwargs(base_kwargs)
        kwargs = base_kwargs | extra_kwargs
        return cls(**kwargs)

    # Future-prone:
    # Comparing mtime on every request will have a hard time scaling
    def reload_if_changed(self) -> bool:
        new_mtime = Config._read_mtime_ns(self.path)
        if new_mtime is None or new_mtime == self.modified_time_ns:
            return False

        logger.info(f"{self.path}: Change detected. Reloading...")
        new = self.load(self.path)
        self.content = new.content
        self.modified_time_ns = new.modified_time_ns
        for callback in self._reload_callbacks:
            callback(self)
        return True

    def _apply_reload_from(self, new: Self) -> None:
        excluded = self._get_excluded_reload_fields()
        for f in fields(self):
            if f not in excluded:
                setattr(self, f.name, getattr(new, f.name))

    @staticmethod
    def _read_mtime_ns(path: Path) -> int | None:
        try:
            return path.stat().st_mtime_ns
        except FileNotFoundError:
            return -1
        except Exception as e:
            logger.warning(f"{str(path)}: Could not read the modified time: {e}")
            return None

    @staticmethod
    def _read_bytes(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            logger.warning(f"{str(path)} not found. Default to empty")
            return None
        except OSError as e:
            logger.warning(f"{str(path)} could not be read. Default to empty: {e}.")
            return None

    @classmethod
    def _handle_file_not_found(cls) -> bytes:
        raise NotImplementedError

    @classmethod
    def _parse_bytes(cls, data: bytes) -> T:
        raise NotImplementedError

    @classmethod
    def _extra_kwargs(cls, base_kwargs: dict) -> dict:
        return {}

    @staticmethod
    def _get_excluded_reload_fields() -> set:
        return {"_reload_callbacks"}

    @classmethod
    def _get_default_reload_callbacks(cls) -> list[Callable[[Self], None]]:
        return []


@dataclass
class BytesConfig(Config[bytes]):
    @classmethod
    def _handle_file_not_found(cls) -> bytes:
        return b""

    @classmethod
    def _parse_bytes(cls, data: bytes) -> bytes:
        return data


@dataclass
class JsonConfig(Config[dict]):
    @classmethod
    def _handle_file_not_found(cls) -> bytes:
        return b"{}"

    @classmethod
    def _parse_bytes(cls, data: bytes) -> dict:
        return json.loads(data.decode().strip() or "{}")


@dataclass
class MetaAttrJsonConfig(JsonConfig):
    @classmethod
    def _parse_bytes(cls, data: bytes) -> dict:
        parsed = super()._parse_bytes(data)
        parsed.pop("$meta", None)
        return parsed


class Method(StrEnum):
    SECRET = "secret"
    BASIC = "basic"
    BEARER = "bearer"


class Policy(StrEnum):
    BREACHED = "breached"
    REJECT = "reject"
    DISABLED = "disabled"
    OPTIONAL = "optional"
    REQUIRED = "required"
    SUFFICIENT = "sufficient"


@dataclass
class AuthRules(MetaAttrJsonConfig):
    raw: dict[str, dict[str, dict[str, dict[str, str]]]]
    required_chain: dict[str, list[Method]]
    revoked: set[str] | None

    @property
    def has_revoke(self):
        return self.revoked is not None

    @classmethod
    def _extra_kwargs(cls, base_kwargs: dict) -> dict:
        normalized : dict[str, dict[Method, dict[str, tuple[Policy, str]]]] = {}
        required_chain : dict[str, list[Method]] = {}

        content = base_kwargs["content"]
        clone = copy.deepcopy(base_kwargs["content"])
        for group, methods in clone.items():
            required_chain[group] = []
            normalized[group] = {}
            for method, policies in methods.items():
                m = Method(method.lower())
                normalized[group][m] = {}
                for policy, pairs in policies.items():
                    p = Policy(policy.lower())
                    if p == Policy.REQUIRED:
                        required_chain[group].append(m)
                    for key, value in pairs.items():
                        k = key if m != Method.SECRET else value
                        v = value if k == key else key
                        normalized[group][m][k] = p, v
        return {
            "raw": content,
            "content": normalized,
            "required_chain": required_chain,
            "revoked": None
        }

    @staticmethod
    def _get_excluded_reload_fields() -> set:
        return super()._get_excluded_reload_fields().union({"revoked"})

    @classmethod
    def _get_default_reload_callbacks(cls) -> list[Callable[[Self], None]]:
        def _revoke_after_reload(a: AuthRules) -> None:
            reloaded = a.content
            revoked = a.revoked
            a._apply_revoke_to_rules(reloaded, revoked)
        return super()._get_default_reload_callbacks() + [_revoke_after_reload]

    def revoke_rule(self, group: str, method: Method, policy: Policy, subject: str) -> None:
        credential = self.raw[group][method.value][policy.value][subject]
        self.revoke_credentials(credential)

    def revoke_credentials(self, credentials: str | set[str]) -> None:
        """
        Revoking doesn't distinguish group, method or user
        :param credentials:
        :return:
        """
        if self.revoked is None:
            self.revoked = set()
        self.revoked.update({credentials} if not isinstance(credentials, set) else credentials)
        self._apply_revoke(credentials)

    def _apply_revoke(self, new_revoked_rules: set[str] | str) -> None:
        self._apply_revoke_to_rules(self.content, {new_revoked_rules} if not isinstance(new_revoked_rules, set) else new_revoked_rules)

    @staticmethod
    def _apply_revoke_to_rules(
            current_rules: dict[str, dict[Method, dict[str, tuple[Policy, str]]]],
            revoked_rules: set[str]
    ) -> None:
        for group, methods in current_rules.items():
            for method, kpvs in methods.items():
                for key, (policy, value) in kpvs.items():
                    if policy == Policy.BREACHED:
                        continue
                    if method == Method.SECRET:
                        if key in revoked_rules:
                            kpvs[key] = Policy.BREACHED, value
                    elif value in revoked_rules:
                        kpvs[key] = Policy.BREACHED, value


@dataclass
class PlatformRules(MetaAttrJsonConfig):
    agent_platform_map: dict[str, str] | None

    @classmethod
    def _extra_kwargs(cls, base_kwargs: dict) -> dict:
        content = base_kwargs["content"]
        assert isinstance(content, dict)
        agent_map = content.pop("$map", None)
        return {
            "content": content,
            "agent_platform_map": agent_map
        }


@dataclass
class ConfigManager:
    _auth_rules_path: Path
    _base_path: Path
    _user_rules_path: Path | None
    _platform_rules_path: Path | None
    _version_rules_path: Path | None

    _revoked_auth_rules_path: Path

    _auth_rules: AuthRules | None = None
    _base: BytesConfig | None = None
    _user_rules: MetaAttrJsonConfig | None = None
    _platform_rules: MetaAttrJsonConfig | None = None
    _version_rules: MetaAttrJsonConfig | None = None

    def _get_auth_rules_obj(self) -> AuthRules:
        a = self._get_config("_auth_rules", self._auth_rules_path, AuthRules)
        if not a.has_revoke:
            r = self._read_saved_revoked_auth_rules()[1]
            a.revoke_credentials(r)
        return a

    def _get_platform_rules_obj(self) -> PlatformRules | None:
        if not self._platform_rules_path:
            return None
        return self._get_config("_platform_rules", self._platform_rules_path, PlatformRules)

    def get_auth_rules(self) -> tuple[dict, dict]:
        """

        :return: (auth rules, required chain (method path if via required))
        """
        rules = self._get_auth_rules_obj()
        return rules.content, rules.required_chain

    def get_encrypted_base(self) -> bytes:
        return self._get_config("_base", self._base_path, BytesConfig).content

    def get_user_rules(self) -> dict | None:
        if not self._user_rules_path:
            return None
        return self._get_config("_user_rules", self._user_rules_path, MetaAttrJsonConfig).content

    def get_platform_rules(self) -> dict | None:
        pro = self._get_platform_rules_obj()
        return None if pro is None else pro.content

    def get_agent_platform_map(self) -> dict | None:
        pro = self._get_platform_rules_obj()
        return None if pro is None else pro.agent_platform_map

    def get_version_rules(self) -> dict | None:
        if not self._version_rules_path:
            return None
        return self._get_config("_version_rules", self._version_rules_path, MetaAttrJsonConfig).content

    def get_revoked_auth_rules(self) -> set[str]:
        if self._auth_rules is None:
            self._get_auth_rules_obj()
        assert self._auth_rules.has_revoke
        return self._auth_rules.revoked

    def _read_saved_revoked_auth_rules(self) -> tuple[dict[str, list[str]], set[str]]:
        all_saved = JsonConfig.load(self._revoked_auth_rules_path).content
        current_saved = all_saved.get(str(self._auth_rules_path.absolute()), [])
        return all_saved, set(list(current_saved))

    T = TypeVar("T", bound="Config")
    def _get_config(
            self,
            field_name: str,
            file_path: str | Path,
            class_type: type[T]
    ) -> T:
        current = getattr(self, field_name)
        if current is not None:
            return current
        logger.debug(f"Loading {file_path}...")
        new = class_type.load(file_path)
        setattr(self, field_name, new)
        return new

    def revoke_auth_rule(self, group: str, method: Method, policy: Policy, subject: str) -> None:
        self._get_auth_rules_obj().revoke_rule(group, method, policy, subject)

    def save_revoked_rules(self) -> None:
        record = self._read_saved_revoked_auth_rules()[0]
        path = str(self._auth_rules_path.absolute())
        record[path] = list(self.get_revoked_auth_rules())

        try:
            file_operator.save(get_readable_dump(record).encode(), self._revoked_auth_rules_path)
        except portalocker.exceptions.LockException as e:
            logger.warning(f"Lock timeout. Could there be a hanging process? Skipping for now: {e}")
        # propagate errors like PermissionError or OSError