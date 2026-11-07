import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException


class KeyStore:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        master = directory / "master.key"
        try:
            descriptor = os.open(master, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as output:
                output.write(Fernet.generate_key())
        self.cipher = Fernet(master.read_bytes())
        self.database = directory / "keys.sqlite3"
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS auth_keys (scope TEXT, scope_id INTEGER, name TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(scope,scope_id))")
        self.database.chmod(0o600)

    def get(self, scope: str, scope_id: int):
        with sqlite3.connect(self.database) as db:
            row = db.execute("SELECT name,data FROM auth_keys WHERE scope=? AND scope_id=?", (scope, scope_id)).fetchone()
        return (row[0], self.cipher.decrypt(row[1]).decode()) if row else None

    def metadata(self, scope: str, scope_id: int):
        value = self.get(scope, scope_id)
        return {"configured": value is not None, "key_name": value[0] if value else "CMNC"}

    def save(self, scope: str, scope_id: int, name: str, pem: str):
        try:
            key = serialization.load_pem_private_key(pem.encode(), password=None)
            if not isinstance(key, rsa.RSAPrivateKey):
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "Нужен незашифрованный приватный RSA-ключ Veyon в формате PEM") from exc
        with sqlite3.connect(self.database) as db:
            db.execute("INSERT INTO auth_keys VALUES (?,?,?,?) ON CONFLICT(scope,scope_id) DO UPDATE SET name=excluded.name,data=excluded.data", (scope, scope_id, name, self.cipher.encrypt(pem.encode())))

    def delete(self, scope: str, scope_id: int):
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM auth_keys WHERE scope=? AND scope_id=?", (scope, scope_id))

    def resolve(self, router_id: int, classroom_id: int):
        # A configured router key is authoritative, even if authentication fails.
        value = self.get("router", router_id) or self.get("classroom", classroom_id)
        if value is None:
            raise HTTPException(409, "Ключ Veyon не настроен для MikroTik или аудитории")
        return value
