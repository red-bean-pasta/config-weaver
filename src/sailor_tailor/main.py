import argparse
import json
import logging
import os
import shlex
import sys
from pathlib import Path

from .app_helper import MODULE_NAME, initialize_logging, exit_on_error
from .json_helper import get_readable_dump

# Expect usage: systemd service with DynamicUser set to yes
CONFIG_DIR_ENV = "CONFIG_DIR"
CONFIG_DIR = os.getenv(CONFIG_DIR_ENV)
STATE_DIR_ENV = "STATE_DIR"
STATE_DIR = os.getenv(STATE_DIR_ENV)

logger = logging.getLogger(__name__)


def main():
    args, unknown = _parse_args()
    initialize_logging(getattr(args, "log_level", "debug"))
    if unknown:
        args.func(args, unknown)
    else:
        args.func(args)


def _serve(my_args, uvicorn_args = None):
    from . import http_api
    os.environ[http_api.CONFIG_DIR_ENV] = my_args.config_dir or exit_on_error("Config directory empty")
    os.environ[http_api.STATE_DIR_ENV] = my_args.state_dir or exit_on_error("State directory empty")
    os.environ[http_api.UNSAFE_MODE_ENV] = "1" if my_args.unsafe_mode else "0"
    os.environ[http_api.LOG_LEVEL_ENV] = my_args.log_level

    uvicorn_env = os.getenv("UVICORN_ARGS")
    uvicorn_env_args = [] if not uvicorn_env else shlex.split(uvicorn_env)
    uvicorn_env_args.extend(uvicorn_args or [])
    argv = [
        sys.executable,
        "-m", "uvicorn",
        f"{MODULE_NAME}.http_api:create_http_api",
        "--factory",
        "--host", my_args.host,
        "--port", str(my_args.port),
        "--proxy-headers",
        "--no-server-header",
        "--forwarded-allow-ips", my_args.forwarded_allow_ips,
        *uvicorn_env_args
    ]
    logger.info(f"Starting uvicorn process: {argv}")
    os.execvp(argv[0], argv)


def _build(args):
    from .config_manager_factory import StaticConfigFilename, StateConfigFilename, FileImportance, construct_config_manager
    config_overrides = {
        StaticConfigFilename.AUTH : FileImportance.SKIPPED,
        StateConfigFilename.REVOKED : FileImportance.SKIPPED
    }
    try:
        manager = construct_config_manager(args.config_dir, None, config_overrides)
    except Exception as e:
        exit_on_error(e)

    from . import profile_generator
    result = profile_generator.build_profile(manager, args.key, args.username, args.platform)

    if args.output_path is None:
        print(get_readable_dump(result))
    else:
        with Path(args.output_path).open("w") as f:
            json.dump(result, f, indent=4, ensure_ascii=False)


def _generate_base64url(args):
    from . import authenticator
    print(authenticator.generate_base64url(args.length))


def _hash(args):
    from . import authenticator
    for c in args.credentials:
        h = authenticator.hash_password(c)
        print(h)


def _encrypt(args):
    from . import encryptor
    i = args.input_path
    o = args.output_path or i.with_name(i.name + ".enc")
    encryptor.generate_key_encrypt_file(i, o)


def _edit(args):
    target = Path(args.path)
    target_dir = target.parent

    from .config_manager import BytesConfig
    print(f"Loading {target}...")
    loaded = BytesConfig.load(target)
    if loaded.modified_time_ns <= 0:
        print("Failed to load file: Maybe file doesn't exist?")
        sys.exit(1)
    payload = BytesConfig.load(target).content

    from . import encryptor
    print(f"Decrypting {target}...")
    decrypted = encryptor.decrypt_file(args.key, payload)
    if decrypted is None:
        print("Failed to decrypt: Maybe an invalid key?")
        sys.exit(1)

    from . import file_operator
    try:
        tmp = file_operator.save_to_temp_file(target_dir, decrypted)
    except PermissionError as e:
        print(f"Failed to save decrypted result temporarily: {e}")
        sys.exit(1)

    print(f"Editing with {args.editor}...")
    try:
        file_operator.confident_edit(args.editor, tmp)

        enc_tmp = tmp.with_name(tmp.name + ".enc")
        encryptor.encrypt_file(args.key, tmp, enc_tmp)

        file_operator.replace(enc_tmp, target)
        print(f"Edit saved and encrypted")
    except (RuntimeError, FileNotFoundError) as e:
        print(f"{type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        file_operator.clean_up(tmp)


def _parse_args() -> tuple[argparse.Namespace, list[str] | None]:
    parser = argparse.ArgumentParser(
        epilog="Use '%(prog)s <command> --help' for more information on a specific command")
    subparsers = parser.add_subparsers(
        title="Available commands",
        dest="command",
        required=True)

    _setup_base64_parser(subparsers)
    _setup_hash_parser(subparsers)
    _setup_crypto_parsers(subparsers)
    _setup_build_parser(subparsers)
    _setup_serve_parser(subparsers)

    known, unknown = parser.parse_known_args()
    if known.command != "serve" and unknown:
        parser.error(f"Unrecognized arguments for command `{known.command}`: {' '.join(unknown)}")
    return known, unknown


def _setup_serve_parser(subparsers):
    parser = subparsers.add_parser(
        "serve",
        help="Launch and serve for HTTPS requests",
        epilog="Example: -d /path/to/config/dir -s /path/to/state/dir --port 8000 -- --worker 4 --log-level trace. Anything behind standalone '--' should be uvicorn-specific arguments.")

    config = parser.add_argument_group("Configuration")
    config.add_argument(
        "-d", "--config-dir",
        default=CONFIG_DIR,
        help=f"Directory containing config files. Default to ${CONFIG_DIR_ENV} environment variable. Required config: [auth_rules.json]; Optional: [base.enc, user_rules.json, platform_rules.json, agent_platform_dict.json]")
    config.add_argument(
        "-s", "--state-dir",
        default=STATE_DIR,
        help=f"Directory to store state files. Default to ${STATE_DIR_ENV}")

    network = parser.add_argument_group("Network Settings")
    network.add_argument(
        "--host",
        default=os.getenv("HOST") or "127.0.0.1",
        help="Interface to bind to. Default to $HOST else '127.0.0.1'")
    network.add_argument(
        "--port",
        type=_port_type,
        default=_port_type(os.getenv("PORT") or 9443),
        help="Port to listen on. Default to $PORT else 9443")
    network.add_argument(
        "--forwarded-allow-ips",
        default=os.getenv("FORWARDED_ALLOW_IPS") or "127.0.0.1",
        help="Comma separated list of addresses with proxy headers trust. Useful when serving behind reverse proxy like Nginx or Caddy. Default to $FORWARDED_ALLOW_IPS else 127.0.0.1")
    network.add_argument(
        "--unsafe-mode",
        action='store_true', default=False,
        help="Disable TLS enforcement and skip revoking credentials leaked in plaintext request. Disabled by default")

    _add_log_arg(parser)

    parser.set_defaults(func=_serve)


def _setup_build_parser(subparsers):
    parser = subparsers.add_parser(
        "build",
        help="Build and output directly")
    parser.add_argument(
        "-d", "--config-dir",
        default=CONFIG_DIR,
        help=f"Directory containing config files. Default to ${CONFIG_DIR_ENV}. Required config: [None]; Optional: [base.enc, user_rules.json, platform_rules.json, agent_platform_dict.json]"
    )
    parser.add_argument(
        "-o", "--output-path",
        help="Where to save output. Omit to print to stdout")
    parser.add_argument(
        "username",
        help="user to build for")
    parser.add_argument(
        "platform",
        help="Platform or user agent")
    parser.add_argument(
        "key",
        help="Key to decrypt base.enc if applicable")
    _add_log_arg(parser)
    parser.set_defaults(func=_build)


def _setup_crypto_parsers(subparsers):
    enc = subparsers.add_parser(
        "encrypt",
        help="Lock a file with AES-128 encryption")
    enc.add_argument(
        "input_path", metavar="INPUT",
        type=Path,
        help="File to encrypt")
    enc.add_argument(
        "output_path", metavar="OUTPUT",
        nargs="?", type=Path,
        help="Where to save. Default to INPUT + '.enc'")
    enc.set_defaults(func=_encrypt)

    edit = subparsers.add_parser(
        "edit",
        help="Decrypt, view, edit, and automatically re-lock a file")
    edit.add_argument(
        "path",
        type=Path,
        help="Path to the encrypted file")
    edit.add_argument(
        "key",
        help="The decryption key")
    edit.add_argument(
        "-e", "--editor",
        default="nano",
        help="Command to call the editor like `vim` or `code --wait`. Default to `nano`")
    edit.set_defaults(func=_edit)


def _setup_hash_parser(subparsers):
    parser = subparsers.add_parser(
        "hash",
        help="Hash credentials for safe storage")
    parser.add_argument(
        "credentials",
        nargs="+",
        help="One or more credentials to hash")
    parser.set_defaults(func=_hash)


def _setup_base64_parser(subparsers):
    parser = subparsers.add_parser(
        "token", aliases=["base64url"],
        help="Generate random URL-safe security token")
    parser.add_argument(
        "length",
        nargs="?", type=int, default=24,
        help="Number of random bytes to generate. Every 4 bytes output 6 characters. Default to 24")
    parser.set_defaults(func=_generate_base64url)


def _add_log_arg(parser):
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default=os.getenv("LOG_LEVEL") or "info",
        help="Default to $LOG_LEVEL else 'info'")


def _port_type(value: str) -> int:
    port = int(value)
    if 1 <= port <= 65535: return port
    raise ValueError(f"Port overflow: {value} not within 1 and 65535")


if __name__ == "__main__":
    main()