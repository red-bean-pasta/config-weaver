import argparse
import getpass
import sys
from pathlib import Path

from config_weaver.config_managing import secret_generator
from config_weaver.config_managing import encryptor, editor, hasher, builder
from config_weaver.file_managers.patch_manager import PatchParam
from config_weaver.network import service_starter
from config_weaver.utils import json_helper, file_operator


def serve(
        args: argparse.Namespace,
        passthrough: list[str] | None = None
) -> None:
    service_starter.start(args, passthrough)


def build(args: argparse.Namespace) -> None:
    param = PatchParam(
        args.user,
        args.agent,
        args.version
    )

    try:
        key = getpass.getpass("Enter decryption key: ")
    except (KeyboardInterrupt, EOFError):
        print()
        return

    result = builder.build(args.spec_dir, param, key)

    if not result:
        return

    dump = json_helper.dump_readable(result)
    if args.output_path:
        file_operator.save(dump.encode("utf-8"), Path(args.output_path))
    else:
        print(dump)


def encrypt(args: argparse.Namespace) -> None:
    key = encryptor.encrypt(args.input_path, args.output_path)
    print(f"Encryption key: {key}")


def edit(args: argparse.Namespace) -> None:
    try:
        key = getpass.getpass("Enter decryption key: ")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)
    editor.edit(args.path, key, args.editor_command)


def hash(args: argparse.Namespace) -> None:
    for c in args.credentials:
        print(f"{c}: {hasher.hash(c)}")


def generate_secret(args: argparse.Namespace) -> None:
    print(secret_generator.generate(args.length))
