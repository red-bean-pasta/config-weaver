import logging
import re
from dataclasses import dataclass, fields

from fastapi import APIRouter, Response, Request
from fastapi.security import HTTPBearer, HTTPBasic
from starlette.middleware.base import BaseHTTPMiddleware

from sailor_tailor import authenticator, encryptor
from sailor_tailor.config_manager import ConfigManager, Policy, Method
from sailor_tailor.json_helper import get_readable_dump
from sailor_tailor.profile_generator import build_profile


logger = logging.getLogger(__name__)

router = APIRouter()

basic_security = HTTPBasic(auto_error=False)
bearer_security = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class ParsedPath:
    root: str
    agent: str | None = None
    version: str | None = None
    secret: str | None = None
    key: str | None = None
    rest: list[str] | None = None


@dataclass(slots=True)
class VerifyResult:
    authenticate: bool
    decryptable: bool
    subject: str
    user_agent: str
    version: str
    encrypt_key: str
    summary: tuple[str, dict[Policy, dict[Method, str]]]


class HttpAuthRevokeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.scheme == "https" or _check_if_unsafe_mode(request):
            return await call_next(request)

        # No constant timing here. No need
        config_manager = _get_config_manger(request)
        v = await _auth_request(request, config_manager)

        group, content = v.summary
        leaked = False
        for policy, methods in content.items():
            if policy == Policy.BREACHED or policy == Policy.REJECT:
                continue
            leaked = True
            for method, subject in methods.items():
                logger.warning(f"{method} credential of user '{subject}' is exposed over plaintext HTTP request. Revoking it...")
                config_manager.revoke_auth_rule(group, method, policy, subject)
        if leaked:
            logger.info("Updating revoked rules to disk...")
            config_manager.save_revoked_rules()

        if v.decryptable:
            logger.warning("Encryption key LEAKED in plaintext HTTP request. PLEASE ROTATE IT SOON")

        return _get_uniform_reject()


@router.get("/{full_path:path}")
async def _get_profile(request: Request):
    return await _auth_request_and_build(request)


async def _auth_request_and_build(request: Request):
    logger.info("Received build request")
    try:
        config_manager = request.app.state.config_manager

        v = await _auth_request(request, config_manager)
        _log_request_auth_result(v.authenticate, v.decryptable)

        if not v.authenticate or not v.decryptable:
            return _get_uniform_reject()
        result = build_profile(config_manager, v.encrypt_key, v.subject, v.user_agent, v.version)
        return get_readable_dump(result)

    except Exception as e: # Catch all to avoid 500 or timeout after crash
        logger.error(f"Unexpected error occurred: {e}", exc_info=True)
        return _get_uniform_reject()


def _parse_path(full_path: str) -> ParsedPath:
    full_path = full_path.strip().strip("/")
    split = full_path.split('/')

    count = len(fields(ParsedPath))
    expected = count - 1
    args = split[:expected]
    if len(split) > expected:
        args.append(split[expected:])
    return ParsedPath(*args)


async def _auth_request(
        request: Request,
        config_manager: ConfigManager
) -> VerifyResult:
    full_path = request.url.path
    parsed_path = _parse_path(full_path)

    logger.debug("Authenticating credentials...")
    auth_rules = config_manager.get_auth_rules()
    basic_creds = await basic_security(request)
    bearer_creds = await bearer_security(request)
    authenticate, subject, summary = await authenticator.verify(auth_rules, parsed_path.root, bearer_creds, basic_creds, parsed_path.secret)
    authenticate &= parsed_path.rest is None or len(parsed_path.rest) == 0

    logger.debug("Authenticating encryption key...")
    encrypt_key = request.headers.get("x-request-id") or parsed_path.key or "\0"
    decryptable = encryptor.decrypt_file(encrypt_key, config_manager.get_encrypted_base()) is not None
    logger.debug(f"{'Valid' if decryptable else 'Invalid'} encryption key")

    user_agent_header = request.headers.get("user-agent")
    user_agent = user_agent_header or parsed_path.agent or None
    version = _get_user_agent_version(user_agent_header) or parsed_path.version or None
    return VerifyResult(
        authenticate, decryptable,
        subject, version, user_agent, encrypt_key,
        summary
    )


def _log_request_auth_result(is_authed: bool, is_decrypted: bool):
    level = 20 if is_authed == is_decrypted else 30

    if is_authed:
        if is_decrypted: note = "Things are good to go"
        else: note = "USER CREDENTIALS MAY BE LEAKED"
    else:
        if is_decrypted: note = "ENCRYPTION KEY MAY BE LEAKED"
        else: note =  "Everything is protected"

    logger.log(level, f"Verification result: Credential - {is_authed}; Encryption key - {is_decrypted}: {note}")


def _get_uniform_reject() -> Response:
    return Response(status_code=404)


def _get_config_manger(request: Request) -> ConfigManager:
    return request.app.state.config_manager


def _check_if_unsafe_mode(request: Request) -> bool:
    return request.app.state.unsafe_mode


def _get_user_agent_version(user_agent: str) -> str | None:
    """
    Example: Mozilla/5.0-beta (comment) product/version (comment) ... => 5.0-beta
    :param user_agent:
    :return:
    """
    return re.search(r'[^/]+/([\d.]+\S)*', user_agent)