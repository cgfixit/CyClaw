"""Scheduled sync entry point: read only the rclone credential at execution time."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from utils.child_environment import child_environment, configured_path_names
from utils.errors import SyncConfigError
from utils.secret_policy import POLICY_PATH, load_secret_policy


def _service() -> str:
    """Read the service from the shared policy, refusing a missing mapping."""
    load_secret_policy(POLICY_PATH)
    for line in POLICY_PATH.read_text(encoding="ascii").splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[:2] == ["exact", "RCLONE_CONFIG_PASS"] and fields[2]:
            return fields[2]
    raise OSError("missing rclone secret mapping")


def _windows_password(service: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("BlobSize", wintypes.DWORD),
                    ("Blob", ctypes.c_void_p), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    pointer = ctypes.POINTER(Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(type(pointer))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    if not api.CredReadW(service, 1, 0, ctypes.byref(pointer)):
        code = ctypes.get_last_error()
        if code in (2, 1168):
            return None
        raise OSError("Credential Manager read failed")
    try:
        item = pointer.contents
        return ctypes.string_at(item.Blob, item.BlobSize).decode("utf-16-le") if item.Blob else ""
    finally:
        api.CredFree(pointer)


def _password() -> str | None:
    """Missing is optional for plaintext config; failed/empty reads are errors."""
    service = _service()
    if sys.platform == "win32":
        return _windows_password(service)
    if sys.platform == "darwin":
        import pwd

        result = subprocess.run(  # noqa: S603 -- fixed OS binary and policy service, never a shell
            ["/usr/bin/security", "find-generic-password", "-a", pwd.getpwuid(os.getuid()).pw_name,
             "-s", service, "-w"], env=child_environment("filesystem"),
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 44:
            return None
        if result.returncode:
            raise OSError("Keychain read failed")
        return result.stdout.removesuffix("\n")
    # Linux has no supported automatic keystore backend. An operator-managed
    # service may inject RCLONE_CONFIG_PASS; absent it, encrypted config fails
    # noninteractively in rclone instead of prompting or falling back to .env.
    return None


def prepare_environment(path_names: tuple[str, ...] = ()) -> dict[str, str]:
    """Discard unrelated credentials and retrieve only the sync capability."""
    env = child_environment("sync", secret_names=path_names)
    if not env.get("RCLONE_CONFIG_PASS"):
        password = _password()
        if password is not None:
            if not password or "\x00" in password:
                raise OSError("rclone credential is empty or invalid")
            env["RCLONE_CONFIG_PASS"] = password
    return env


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        path_names = ()
        if args != ["--check-credentials"]:
            from sync.cli import build_parser
            from sync.config import load_sync_config
            from utils.logger import _get_config

            parsed = build_parser().parse_args(args)
            load_sync_config(parsed.config)  # normalize malformed/config errors before environment changes
            config = _get_config(parsed.config) or {}
            path_names = configured_path_names(config.get("sync"))
        env = prepare_environment(path_names)
        if args == ["--check-credentials"]:
            binary = shutil.which("rclone")
            if binary is None:
                raise OSError("rclone is unavailable")
            result = subprocess.run(  # noqa: S603 -- resolved rclone; local config read only
                [binary, "listremotes"], env=env, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=15, check=False,
            )
            if result.returncode:
                raise OSError("rclone cannot read its configuration")
            print("rclone configuration is readable (no transfer performed)")
            return 0
        os.environ.clear()
        os.environ.update(env)
    except (OSError, ValueError, SyncConfigError, subprocess.TimeoutExpired):
        # Never echo OS-tool stderr or credential bytes, even on failure.
        print("Scheduled sync credential setup failed; check the OS keystore and rclone configuration.", file=sys.stderr)
        return 3
    # Outside the setup handler: a failure in the sync run itself keeps the
    # sync CLI's own exit codes and tracebacks instead of a keystore message.
    from sync.cli import main as sync_main

    return sync_main(args)


if __name__ == "__main__":
    sys.exit(main())
