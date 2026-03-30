import json
import logging
import secrets
from dataclasses import dataclass
from enum import StrEnum

import anyio
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from fastapi.security import HTTPBasicCredentials, HTTPAuthorizationCredentials

from sailor_tailor.config_manager import Method, Policy


# TODO:
#   Async logging system
#   Warn inconsistent subject along the required chain


class Scope(StrEnum):
    GET = "get"

@dataclass
class AuthSuccess:
    method: Method
    subject: str
    scopes: Scope | list[Scope]

@dataclass
class AuthFail:
    method: Method
    logs: str

AuthResult = AuthSuccess | AuthFail


# Explicitly commented out to avoid I/O operations and inconsistent timing
# logger = logging.getLogger(__name__)

argon_hasher = Argon2Hasher(
    memory_cost=65536,
    time_cost=3,
    parallelism=3
)
hash_manager = PasswordHash((argon_hasher,))


DUMMY_HASH = hash_manager.hash("this-is-a-dummy-password")


def hash_password(password: str) -> str:
    return hash_manager.hash(password)


def generate_base64url(length: int) -> str:
    return secrets.token_urlsafe(length)


async def verify(
        parsed_auth_rules: tuple[dict, dict],
        group: str,
        bearer_creds: HTTPAuthorizationCredentials | None,
        basic_creds: HTTPAuthorizationCredentials | None,
        secret: str | None
) -> tuple[bool, str | None, tuple[str | None, dict[Policy, dict[Method, str]]]]:
    """

    :param parsed_auth_rules:
    :param group:
    :param bearer_creds:
    :param basic_creds:
    :param secret:
    :return: (if_authenticate, user)
    """
    grouped_rules, grouped_required_chain = parsed_auth_rules
    method_keys_dict = grouped_rules.get(group, {})
    required_chain = grouped_required_chain.get(group, {})

    bearer_result = await _validate_bearer(method_keys_dict.get(Method.BEARER, {}), bearer_creds)
    basic_result = await _validate_basic(method_keys_dict.get(Method.BASIC, {}), basic_creds)
    secret_result = _validate_url_secret(method_keys_dict.get(Method.SECRET, {}), secret)

    # No heavy synchronous processing here to avoid noticeable timing
    grouped = _group_results(bearer_result, basic_result, secret_result)
    breached = grouped[Policy.BREACHED]
    rejected = grouped[Policy.REJECT]
    sufficient = grouped[Policy.SUFFICIENT]
    required = grouped[Policy.REQUIRED]

    summary = _get_auth_summary(grouped)
    def _log(success: bool):
        logging.getLogger(__name__).info(f"Authentication {('succeeded' if success else 'failed')}: {json.dumps({group: summary}) if len(method_keys_dict) > 0 else f'Unknown group: "{group}"'}")
    if len(breached) > 0 or len(rejected) > 0:
        _log(False)
        return False, None, (group, summary)
    if len(sufficient) > 0:
        _log(True)
        return True, sufficient[0].subject, (group, summary)
    if 0< len(required) == len(required_chain):
        _log(True)
        return True, required[0].subject, (group, summary)
    _log(False)
    return False, None, (group, summary)


async def _validate_bearer(records: dict[str, tuple[Policy, str]], creds: HTTPAuthorizationCredentials | None) -> AuthResult | None:
    if creds is None:
        await _dummy_verify() # In case the request is authenticated via `required` path
        return None

    method = Method.BEARER
    subject, token = r if (r := _parse_bearer(creds.credentials)) is not None else (None, None)
    policy, stored_hash = r if subject is not None and (r := records.get(subject)) is not None else (None, None)

    if stored_hash is None:
        await _dummy_verify()
        return _create_auth_fail(method, "Invalid Authentication Bearer token")

    ok = await _verify_password(token, stored_hash)
    if ok:
        return _apply_policy_auth_success(_create_auth_success(method, subject, Scope.GET), policy)
    else:
        return _create_auth_fail(method, f"Wrong bearer from user '{subject}'")


async def _validate_basic(records: dict, creds: HTTPBasicCredentials | None) -> AuthResult | None:
    if creds is None:
        await _dummy_verify()
        return None

    method = Method.BASIC
    username = creds.username
    password = creds.password
    ph = records.get(username)
    if ph is None:
        await _dummy_verify()
        return _create_auth_fail(method, f"Invalid user '{username}'")

    policy, stored_hash = ph
    ok = await _verify_password(password, stored_hash)
    if ok:
        return _apply_policy_auth_success(_create_auth_success(method, username, Scope.GET), policy)
    else:
        return _create_auth_fail(method, f"Wrong password from user '{username}'")


def _validate_url_secret(records: dict, secret: str | None) -> AuthResult | None:
    if not secret:
        return None

    method = Method.SECRET
    pa = records.get(secret)
    if pa is None:
        return _create_auth_fail(method, "Invalid URL secret")

    policy, applicant = pa
    return _apply_policy_auth_success(_create_auth_success(method, applicant, Scope.GET), policy)


def _group_results(*args: AuthResult | None) -> dict[Policy, list[AuthResult]]:
    result = {}
    for p in Policy:
        result[p] = []
    for a in args:
       if a is None:
           continue
       if isinstance(a, AuthSuccess):
           result[a.policy].append(a)
       else:
           result[Policy.REJECT].append(a)
    return result


async def _verify_password(credential: str, credential_hash: str) -> bool:
    return await anyio.to_thread.run_sync(hash_manager.verify, credential, credential_hash)


async def _dummy_verify() -> None:
    await _verify_password("", DUMMY_HASH) # Dummy verification for timing attack


def _create_auth_success(method: Method, subject: str, scopes: list[Scope] | Scope) -> AuthSuccess:
    if isinstance(scopes, str): scopes = [scopes]
    return AuthSuccess(method, subject, scopes)


def _create_auth_fail(method: Method, log: str | None) -> AuthFail:
    return AuthFail(method, log)


def _apply_policy_auth_success(result: AuthSuccess, policy: Policy) -> AuthResult | None:
    if policy == Policy.REJECT:
        return _create_auth_fail(result.method, f"User '{result.subject}' used rejected method {result.method}")
    else:
        result.policy = policy
        return result


def _get_auth_summary(grouped_results: dict[Policy, list[AuthResult]]) -> dict[Policy, dict[Method, str]]:
    summary = {}
    for policy, results in grouped_results.items():
        for result in results:
            if policy not in summary: summary[policy] = {}
            summary[policy][result.method] = getattr(result, "subject", "UNKNOWN")
    return summary


def _parse_bearer(content: str) -> tuple[str, str] | None:
    split = content.rsplit('~', 1)
    if len(split) < 2:
        return None
    return tuple(split)