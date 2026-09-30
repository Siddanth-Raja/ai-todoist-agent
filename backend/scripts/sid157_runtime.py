#!/usr/bin/env python3
"""Explicit synthetic bootstrap/run/backup/restore CLI. No infrastructure setup."""
from __future__ import annotations
import argparse
import json
import logging
import os
from pathlib import Path
import sys

# Before any app import: no local dotenv or personal service configuration.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["PCOS_SYNTHETIC_RUNTIME"] = "1"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.runtime_store import RuntimeConfig, RuntimeStore, RuntimeRefusal, bootstrap
from app.runtime_auth import password_hasher


def private_file(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_mode & 0o077:
        raise RuntimeRefusal("private_secret_file_required")
    return p.read_text().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=["bootstrap","empty-recovery","run","backup","sync","restore"])
    parser.add_argument("--config",required=True,help="New synthetic environment config JSON; never a .env")
    parser.add_argument("--password-file",help="Synthetic local password, mode 0600, outside backup tree")
    parser.add_argument("--vault")
    parser.add_argument("--signing-key-file",help="32-byte hex signing key, mode 0600, outside vault")
    parser.add_argument("--recipient-file",help="Public age recipient; runtime does not possess recovery identity")
    parser.add_argument("--identity-file",help="Synthetic age identity for isolated local test restore only")
    parser.add_argument("--backup-id")
    parser.add_argument("--recovery-config")
    args = parser.parse_args()
    config = RuntimeConfig(**{**json.loads(Path(args.config).read_text()),"root":Path(json.loads(Path(args.config).read_text())["root"])})
    for secret in (args.password_file, args.signing_key_file, args.identity_file):
        if secret is not None:
            path = Path(secret).resolve()
            if path.is_relative_to(config.root.resolve()) or (args.vault and path.is_relative_to(Path(args.vault).resolve())):
                raise RuntimeRefusal("recovery_secret_must_be_outside_data_and_vault")
    if args.operation in {"bootstrap","empty-recovery"}:
        bootstrap(config,password_hasher().hash(private_file(args.password_file)),recovery=args.operation=="empty-recovery")
        print(json.dumps({"status":"created_synthetic_store","capture_disabled":args.operation=="empty-recovery"}))
        return
    if args.operation == "run":
        from app.runtime_api import create_runtime_app
        import uvicorn
        # Uvicorn default access/error logs can include query/body validation text.
        # Only our allowlisted application event logger is enabled.
        logging.basicConfig(level=logging.INFO,format="%(message)s")
        for name in ("uvicorn","uvicorn.access","uvicorn.error"):
            logging.getLogger(name).disabled = True
        backup = None
        if args.vault:
            from app.runtime_backup import LocalVault
            backup = (LocalVault(args.vault,config.environment_id,bytes.fromhex(private_file(args.signing_key_file))),
                      Path(args.recipient_file).read_text().strip())
        uvicorn.run(create_runtime_app(config,backup=backup),host="127.0.0.1",port=8017,workers=1,
                    access_log=False,log_config=None,timeout_graceful_shutdown=15,proxy_headers=False)
        return
    from app.runtime_backup import LocalVault
    vault = LocalVault(args.vault,config.environment_id,bytes.fromhex(private_file(args.signing_key_file)))
    store = RuntimeStore(config)
    store.start()
    try:
        if args.operation == "sync":
            result = {"generation":vault.sync(store)}
        elif args.operation == "backup":
            result = {"backup_id":vault.backup(store,Path(args.recipient_file).read_text().strip())}
        else:
            raw = json.loads(Path(args.recovery_config).read_text())
            target = RuntimeConfig(**{**raw,"root":Path(raw["root"])})
            result = {"recovery_root":str(vault.restore(args.backup_id,private_file(args.identity_file),target,
                     password_hasher().hash(private_file(args.password_file)),authority=store))}
        print(json.dumps(result))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Deliberately do not print exception text, secrets or paths.
        print(json.dumps({"status":"refused","code":"synthetic_operation_failed"}),file=sys.stderr)
        raise SystemExit(1)
