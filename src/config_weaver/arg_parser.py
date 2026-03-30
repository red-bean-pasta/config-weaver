import argparse
import os
from pathlib import Path
from typing import Callable

from config_weaver import meta
from config_weaver import arg_funcs


_SPEC_DIR_ENV = "SPEC_DIR"
_env_spec_dir = os.getenv(_SPEC_DIR_ENV)

_STATE_DIR_ENV = "STATE_DIR"
_env_state_dir = os.getenv(_STATE_DIR_ENV)


def parse_args() -> tuple[argparse.Namespace, list[str] | None]:
    parser = _setup_parser()
    parsed = parser.parse_known_args()
    _validate_args(parsed, parser.error)
    return parsed


def _validate_args(
        parse_result: tuple[argparse.Namespace, list[str] | None],
        error_raiser: Callable[[str], None],
) -> None:
    args, passthrough = parse_result
    if args.command != "serve" and passthrough:
        error_raiser(f"{args.command}: Unrecognized arguments: {' '.join(passthrough)}")
    if args.command == "serve" and any(not d for d in (args.spec_dir, args.state_dir)):
        error_raiser(f"{args.command}: Parameters --spec-dir and --state-dir are required")


def _setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=meta.MODULE_NAME,
        epilog="Use '%(prog)s <command> --help' for more information on a specific command")
    subparsers = parser.add_subparsers(
        title="Available commands",
        dest="command",
        required=True)

    _setup_secret_generate_parser(subparsers)
    _setup_hash_parser(subparsers)
    _setup_encrypt_parsers(subparsers)
    _setup_build_parser(subparsers)
    _setup_serve_parser(subparsers)

    return parser


def _setup_serve_parser(subparsers):
    parser = subparsers.add_parser(
        "serve",
        help="Start the config patching service over HTTP or HTTPS",
        epilog="""Anything behind a standalone '--' will be passed to uvicorn
Example: 
  %(prog)s -d /path/to/spec/dir -s /path/to/state/dir --port 8000 -- --worker 4 --log-level trace""",
        formatter_class=argparse.RawTextHelpFormatter)

    config = parser.add_argument_group("Configuration")
    config.add_argument(
        "-d", "--spec-dir",
        metavar="PATH",
        default=_env_spec_dir,
        help=f"""Path to the spec directory
This directory must contain:
  - base.json.enc
  - auth_rules.json
It may also contain:
  - user_rules.json
  - agent_rules.json
  - version_rules.json
Defaults to ${_SPEC_DIR_ENV}""")
    config.add_argument(
        "-s", "--state-dir",
        metavar="PATH",
        default=_env_state_dir,
        help=f"""Directory for files created and managed by the service
This currently only includes the revoked-credentials record
Defaults to ${_STATE_DIR_ENV}""")

    network = parser.add_argument_group("Network")
    network.add_argument(
        "--host",
        default=os.getenv("HOST") or "127.0.0.1",
        help="Interface to bind to. Defaults to $HOST else 127.0.0.1")
    network.add_argument(
        "--port",
        type=_port_type,
        default=_port_type(os.getenv("PORT") or 9443),
        help="Port to listen on. Defaults to $PORT else 9443")
    network.add_argument(
        "--forwarded-allow-ips",
        metavar="IP",
        default=os.getenv("FORWARDED_ALLOW_IPS") or "127.0.0.1",
        help="""Comma-separated list of proxy IPs whose forwarded headers are trusted
Warning: Should only be used when running behind reverse proxies, such as Nginx or Caddy
Defaults to FORWARDED_ALLOW_IPS else 127.0.0.1""")
    network.add_argument(
        "--unsafe-mode",
        action='store_true', default=False,
        help="""Allow plaintext HTTP request and disable exposed credentials revoking
Warning: Enable this only in trusted development environments""")

    _add_log_arg(parser)

    parser.set_defaults(func=arg_funcs.serve)


def _setup_build_parser(subparsers):
    parser = subparsers.add_parser(
        "build",
        help="Generate config from your spec directory. It reads and decrypts the encrypted base config and applies optional rules based on user, agent, and version settings.")
    parser.add_argument(
        "-d", "--spec-dir",
        default=_env_spec_dir,
        help=f"Path to the spec directory. Required files: [base.json.enc]. Optional files: [user_rules.json, agent_rules.json, version_rules.json]. Defaults to ${_SPEC_DIR_ENV}"
    )
    parser.add_argument(
        "-o", "--output-path",
        default=None,
        help="Path to save patched config. Omit to print to stdout")
    parser.add_argument(
        "-u", "--user",
        default=None,
        help="Name of the user to build for")
    parser.add_argument(
        "-a", "--agent",
        default=None,
        help="Client agent to build for")
    parser.add_argument(
        "-v", "--version",
        default=None,
        help="Client version to build for")
    parser.add_argument(
        "-k", "--key",
        help="Key used decrypt base.json.enc")
    _add_log_arg(parser)
    parser.set_defaults(func=arg_funcs.build)


def _setup_encrypt_parsers(subparsers):
    enc = subparsers.add_parser(
        "encrypt",
        help="Encrypt config file for secure storage")
    enc.add_argument(
        "input_path",
        type=Path,
        metavar="INPUT",
        help="Path to the file to encrypt")
    enc.add_argument(
        "output_path",
        type=Path,
        nargs="?",
        metavar="OUTPUT",
        help="Destination path. Defaults to INPUT + '.enc'")
    enc.set_defaults(func=arg_funcs.encrypt)

    edit = subparsers.add_parser(
        "edit",
        help="Decrypt and edit encrypted config file then re-encrypt")
    edit.add_argument(
        "path",
        type=Path,
        metavar="PATH",
        help="Path to the encrypted file")
    edit.add_argument(
        "key",
        metavar="KEY",
        help="Decryption key")
    edit.add_argument(
        "-e", "--editor-command",
        metavar="COMMAND",
        default="nano",
        help="Editor command to run, such as 'vim' or 'code --wait'. Defaults to 'nano'")
    edit.set_defaults(func=arg_funcs.edit)


def _setup_hash_parser(subparsers):
    parser = subparsers.add_parser(
        "hash",
        help="Hash authentication credentials for secure storage")
    parser.add_argument(
        "credentials",
        nargs="+",
        metavar="CREDENTIAL",
        help="One or more credentials to hash")
    parser.set_defaults(func=arg_funcs.hash)


def _setup_secret_generate_parser(subparsers):
    parser = subparsers.add_parser(
        "generate",
        help="Generate random URL-safe secret")
    parser.add_argument(
        "length",
        nargs="?", type=int, default=24,
        help="Number of random bytes to generate. Every 4 bytes output 6 characters. Default to 24")
    parser.set_defaults(func=arg_funcs.generate_secret)


def _add_log_arg(parser):
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default=os.getenv("LOG_LEVEL") or "info",
        help="Defaults to $LOG_LEVEL else 'info'")


def _port_type(value: str) -> int:
    port = int(value)
    if 1 <= port <= 65535: return port
    raise ValueError(f"Port overflow: {value} not within 1 and 65535")
