import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.security import HTTPBasicCredentials, HTTPAuthorizationCredentials, HTTPBasic, HTTPBearer
from packaging.version import Version, InvalidVersion


BASIC = HTTPBasic(auto_error=False)
BEARER = HTTPBearer(auto_error=False)


@dataclass(slots=True, frozen=True)
class ParsedRequest:
    encryption_key: str | None
    agent: str | None
    version: str | None
    basic_creds: HTTPBasicCredentials
    bearer_creds: HTTPAuthorizationCredentials


async def parse(request: Request) -> ParsedRequest:
    agent_header = request.headers.get("User-Agent")
    agent, version = _normalize_agent_header(agent_header)

    version = _normalize_version(version)

    key = request.query_params.get("key") or request.headers.get("Encryption-Key")
    agent = request.query_params.get("agent") or agent
    version = request.query_params.get("version") or version

    basic_creds = await BASIC(request)
    bearer_creds = await BEARER(request)

    return ParsedRequest(
        encryption_key=key,
        agent=agent,
        version=version,
        basic_creds=basic_creds,
        bearer_creds=bearer_creds,
    )


def _normalize_agent_header(header: str) -> tuple[str, str]:
    agent = header.strip().partition('/')[0]
    version = header.split()[0].split('/')[1]
    return agent, version


def _normalize_version(value: str) -> str:
    try:
        return str(Version(value))
    except InvalidVersion:
        extracted = re.search(r'\d+(?:\.\d+)*', value)
        if extracted:
            return str(Version(extracted[0]))
        raise