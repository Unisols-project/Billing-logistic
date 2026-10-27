"""
client_license.py

Offline licensing client for Windows desktop applications.
Provides LicenseManager class with activation, validation, and storage.
Uses Ed25519 signatures, AES-GCM encryption, and Windows Registry storage.
"""

import base64
import datetime
import json
import os
import secrets
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import winreg
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ----------------------------- Configuration ---------------------------------
COMPANY = "MyCompany"
PRODUCT = "MyProduct"
REGISTRY_PATH = f"Software\\{COMPANY}\\{PRODUCT}"
APP_DATA_PATH = os.path.join(os.environ.get("APPDATA", ""), COMPANY, PRODUCT)
USAGE_LOG_FILE = "usage_log.enc"

# Embedded Ed25519 public key (raw 32 bytes) - generated once and hardcoded.
# This key corresponds to the private key in server_license.py.
# To generate: from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
# key = Ed25519PrivateKey.generate(); pub = key.public_key().public_bytes_raw()
PUBLIC_KEY_BYTES = bytes.fromhex(
    "af2b954117216342a8281c2169ac6c63bbb12c883432b05a4e1bd06bb3a83de7"
)

# Fixed salt for key derivation (should be unique per product)
KEY_SALT = b"2e262f5c340206fc01377b5fb4d44a1640b16fdda7b0f845299c22bb739aafef"

# License version - increment on format changes
LICENSE_VERSION = 1
SUPPORT_EMAIL = "barcode@unisols.in"
SUPPORT_PHONE = "+91 9970899918 / +91 7020254530 "

# Rollback detection action: if True, invalidates license on rollback; else warns.
ROLLBACK_INVALIDATES = True

# ----------------------------- Helper Functions -----------------------------


def _get_machine_guid() -> str:
    """Retrieve Windows Machine GUID for machine binding."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Cryptography")
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return guid
    except Exception:
        # Fallback: use a deterministic but less secure value
        return "FALLBACK_MACHINE_GUID"


def _derive_key(salt: bytes, length: int = 32) -> bytes:
    """Derive an encryption key from MachineGuid and fixed salt."""
    guid = _get_machine_guid()
    password = guid.encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(password)


def _encrypt_data(data: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-GCM. Returns nonce + ciphertext + tag."""
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def _decrypt_data(encrypted: bytes, key: bytes) -> bytes:
    """Decrypt AES-GCM data. Expects nonce + ciphertext + tag."""
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ----------------------------- License Data Models --------------------------


@dataclass
class LicenseData:
    """Stored license information (plaintext before encryption)."""
    challenge: str
    requested_days: int
    issue_timestamp: float  # Unix timestamp
    license_version: int
    nonce: str  # random hex
    expiry_timestamp: float
    rollback_detected: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "LicenseData":
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class StoredLicense:
    """Encrypted license blob plus metadata stored in registry."""
    encrypted_blob: bytes
    salt: bytes
    installation_timestamp: float
    last_successful_run: float
    version: int


# ----------------------------- Registry Helper ------------------------------


class RegistryHelper:
    """Low-level Windows Registry operations under HKCU."""

    @staticmethod
    def _ensure_key():
        """Create registry key if not exists."""
        try:
            winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH)
        except Exception:
            pass

    @staticmethod
    def write_value(name: str, value: Any, value_type: int = winreg.REG_SZ):
        RegistryHelper._ensure_key()
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0,
                             winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, name, 0, value_type, value)
        finally:
            winreg.CloseKey(key)

    @staticmethod
    def read_value(name: str, default: Any = None) -> Any:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0,
                                 winreg.KEY_QUERY_VALUE)
            try:
                value, _ = winreg.QueryValueEx(key, name)
                return value
            finally:
                winreg.CloseKey(key)
        except FileNotFoundError:
            return default
        except Exception:
            return default

    @staticmethod
    def delete_value(name: str):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0,
                                 winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, name)
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass


# ----------------------------- Usage Logger --------------------------------


class UsageLogger:
    """Encrypted append-only usage log stored in %APPDATA%\Company\Product."""

    def __init__(self):
        self.log_dir = Path(APP_DATA_PATH)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / USAGE_LOG_FILE
        self.key = _derive_key(b"usage_log_salt", 32)

    def log_event(self, app_version: str, license_id: str, session_number: int):
        """Append an encrypted log entry."""
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "app_version": app_version,
            "license_id": license_id,
            "session_number": session_number,
        }
        entry_json = json.dumps(entry, sort_keys=True).encode("utf-8") + b"\n"

        # Read existing encrypted log, decrypt, append, re-encrypt
        existing = b""
        if self.log_path.exists():
            try:
                with open(self.log_path, "rb") as f:
                    encrypted = f.read()
                if encrypted:
                    existing = _decrypt_data(encrypted, self.key)
            except Exception:
                # If decryption fails, start fresh (corrupt log)
                existing = b""

        new_log = existing + entry_json
        encrypted_log = _encrypt_data(new_log, self.key)
        with open(self.log_path, "wb") as f:
            f.write(encrypted_log)


# ----------------------------- License Manager -----------------------------


class LicenseManager:
    """Main client license management class."""

    def __init__(self, app_version: str = "1.0.0"):
        self.app_version = app_version
        self.registry = RegistryHelper()
        self.logger = UsageLogger()
        self._license_data: Optional[LicenseData] = None
        self._pending_challenge = None
        
        # Load pending challenge from registry if exists
        self._pending_challenge = self.registry.read_value("PendingChallenge")
        
        self._load_license()

    def _load_license(self):
        """Load and decrypt license data from registry."""
        encrypted_blob = self.registry.read_value("LicenseBlob")
        salt = self.registry.read_value("LicenseSalt")
        if not encrypted_blob or not salt:
            self._license_data = None
            return

        # Convert from base64 if stored as string
        if isinstance(encrypted_blob, str):
            encrypted_blob = base64.b64decode(encrypted_blob)
        if isinstance(salt, str):
            salt = base64.b64decode(salt)

        # Derive key from stored salt
        key = _derive_key(salt, 32)

        try:
            plaintext = _decrypt_data(encrypted_blob, key)
            data_json = plaintext.decode("utf-8")
            self._license_data = LicenseData.from_json(data_json)
        except Exception:
            # Corrupted or tampered license
            self._license_data = None
            # Optionally clear invalid license
            self.remove_license()

        # Rollback detection: check last successful run
        last_run = self.registry.read_value("LastSuccessfulRun")
        print("=" * 60)
        print("Stored:", last_run)
        print("Stored UTC:", datetime.datetime.utcfromtimestamp(float(last_run)) if last_run else None)
        print("Current:", datetime.datetime.utcnow().timestamp())
        print("Current UTC:", datetime.datetime.utcnow())
        print("=" * 60)
        if last_run is not None:
            try:
                last_run_ts = float(last_run)
                now = datetime.datetime.utcnow().timestamp()
                if now < last_run_ts - 5:  # allow small clock drift
                    # Rollback detected
                    if ROLLBACK_INVALIDATES and self._license_data:
                        self._license_data.rollback_detected = True
                        self._save_license(self._license_data)
                    # Log rollback
                    self.logger.log_event(
                        self.app_version,
                        self._license_data.challenge if self._license_data else "unknown",
                        0
                    )
            except Exception:
                pass

        # Update last successful run
        self.registry.write_value("LastSuccessfulRun",
                                  str(datetime.datetime.utcnow().timestamp()),
                                  winreg.REG_SZ)

        # Log session
        if self._license_data:
            # Get session number from registry or generate
            session = self.registry.read_value("SessionNumber")
            if session is None:
                session = 1
            else:
                session = int(session) + 1
            self.registry.write_value("SessionNumber", str(session), winreg.REG_SZ)
            self.logger.log_event(
                self.app_version,
                self._license_data.challenge,
                session
            )

    def _save_license(self, license_data: LicenseData):
        """Encrypt and save license data to registry."""
        salt = secrets.token_bytes(16)
        key = _derive_key(salt, 32)
        plaintext = license_data.to_json().encode("utf-8")
        encrypted = _encrypt_data(plaintext, key)
        self.registry.write_value("LicenseBlob",
                                  base64.b64encode(encrypted).decode("ascii"),
                                  winreg.REG_SZ)
        self.registry.write_value("LicenseSalt",
                                  base64.b64encode(salt).decode("ascii"),
                                  winreg.REG_SZ)
        self.registry.write_value("InstallationTimestamp",
                                  str(datetime.datetime.utcnow().timestamp()),
                                  winreg.REG_SZ)
        self.registry.write_value("Version", self.app_version, winreg.REG_SZ)
        self._license_data = license_data

    def generate_challenge(self) -> str:
        """
        Generate a random 16-character challenge (uppercase letters and digits).
        The challenge is used to bind the license to this activation request.
        The client does NOT specify the duration - the server decides.
        """
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        challenge = ''.join(secrets.choice(alphabet) for _ in range(16))
        
        # Store challenge in registry for persistence
        self.registry.write_value("PendingChallenge", challenge, winreg.REG_SZ)
        
        # Store in memory for immediate use
        self._pending_challenge = challenge
        return challenge

    def activate(self, activation_code: str) -> bool:
        """
        Activate the license using the provided activation code.
        Returns True on success.
        The server decides the license duration.
        """
        try:
            # Decode activation code: base64(payload) + '|' + base64(signature)
            parts = activation_code.split('|')
            if len(parts) != 2:
                return False
            payload_b64, sig_b64 = parts
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            signature = base64.b64decode(sig_b64)

            # Verify signature
            public_key = Ed25519PublicKey.from_public_bytes(PUBLIC_KEY_BYTES)
            try:
                public_key.verify(signature, payload_json.encode('utf-8'))
            except Exception:
                return False

            # Parse payload
            data = json.loads(payload_json)
            required_fields = ['challenge', 'days', 'issue_timestamp',
                               'license_version', 'nonce']
            if not all(f in data for f in required_fields):
                return False

            # Get pending challenge from registry if not in memory
            if not self._pending_challenge:
                self._pending_challenge = self.registry.read_value("PendingChallenge")

            # Verify challenge matches pending
            if not self._pending_challenge or data['challenge'] != self._pending_challenge:
                return False

            # Verify license version
            if data['license_version'] != LICENSE_VERSION:
                return False

            # Build LicenseData - days come from server, not from client
            issue_ts = data['issue_timestamp']
            days = data['days']  # Server decides the duration
            expiry_ts = issue_ts + days * 86400
            license_data = LicenseData(
                challenge=data['challenge'],
                requested_days=days,  # Store what the server granted
                issue_timestamp=issue_ts,
                license_version=data['license_version'],
                nonce=data['nonce'],
                expiry_timestamp=expiry_ts,
                rollback_detected=False
            )

            # Save
            self._save_license(license_data)
            self.registry.write_value("LastSuccessfulRun",
                                      str(datetime.datetime.utcnow().timestamp()),
                                      winreg.REG_SZ)
            
            # Clean up pending challenge after successful activation
            self.registry.delete_value("PendingChallenge")
            self._pending_challenge = None
            
            return True

        except Exception:
            return False

    def is_activated(self) -> bool:
        """Return True if a license is present (even if expired)."""
        return self._license_data is not None

    def check_license(self) -> bool:
        """
        Verify license validity: activated, not expired, no rollback, etc.
        Returns True if license is fully valid.
        """
        if not self._license_data:
            return False

        if self._license_data.rollback_detected and ROLLBACK_INVALIDATES:
            return False

        # Check expiry
        now = datetime.datetime.utcnow().timestamp()
        if now > self._license_data.expiry_timestamp:
            return False

        return True

    def days_remaining(self) -> int:
        """Return number of full days remaining, or 0 if expired or no license."""
        if not self._license_data:
            return 0
        remaining = self._license_data.expiry_timestamp - datetime.datetime.utcnow().timestamp()
        if remaining < 0:
            return 0
        return int(remaining // 86400)

    def license_info(self) -> Dict[str, Any]:
        """Return a dictionary containing license information."""
        if not self._license_data:
            return {}
        return {
            "challenge": self._license_data.challenge,
            "granted_days": self._license_data.requested_days,
            "issue_timestamp": self._license_data.issue_timestamp,
            "expiry_timestamp": self._license_data.expiry_timestamp,
            "version": self._license_data.license_version,
            "rollback_detected": self._license_data.rollback_detected,
            "is_valid": self.check_license(),
            "days_remaining": self.days_remaining()
        }

    def remove_license(self):
        """Delete all license-related registry entries."""
        self.registry.delete_value("LicenseBlob")
        self.registry.delete_value("LicenseSalt")
        self.registry.delete_value("InstallationTimestamp")
        self.registry.delete_value("LastSuccessfulRun")
        self.registry.delete_value("Version")
        self.registry.delete_value("SessionNumber")
        self.registry.delete_value("PendingChallenge")
        self._license_data = None
        self._pending_challenge = None

    def renew_license(self, new_activation_code: str) -> bool:
        """
        Renew an existing license by providing a new activation code.
        The server decides the new duration.
        """
        if not self._license_data:
            return False
        # Set pending from current license
        self._pending_challenge = self._license_data.challenge
        self.registry.write_value("PendingChallenge", self._pending_challenge, winreg.REG_SZ)
        return self.activate(new_activation_code)


# ----------------------------- CLI -----------------------------------------
class ActivationGUI:

    def __init__(self):

        self.lm = LicenseManager()

        self.root = tk.Tk()
        self.root.title("Universal Solutions Inventory Management Software Activation")
        self.root.geometry("650x350")
        self.root.resizable(False, False)

        self.build()

        if self.lm.check_license():

            days = self.lm.days_remaining()

            messagebox.showinfo(
                "License Verified",
                f"""License Verified

Remaining Days : {days}

Contact Support

Email : {SUPPORT_EMAIL}

Phone : {SUPPORT_PHONE}
"""
            )

            self.root.destroy()
            return

        self.root.mainloop()

    def build(self):

        frm = ttk.Frame(self.root, padding=20)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="Universal Solutions Software Activation",
            font=("Segoe UI", 18, "bold")
        ).pack(pady=10)

        ttk.Label(frm, text="Request Code").pack(anchor="w")

        self.challenge = tk.StringVar()

        if self.lm._pending_challenge:
            self.challenge.set(self.lm._pending_challenge)
        else:
            self.challenge.set(self.lm.generate_challenge())

        e = ttk.Entry(
            frm,
            textvariable=self.challenge,
            width=60,
            state="readonly"
        )

        e.pack()

        ttk.Button(
            frm,
            text="Copy Request Code",
            command=self.copy_request
        ).pack(pady=5)

        ttk.Label(frm, text="Activation Code").pack(anchor="w", pady=(10,0))

        self.activation = tk.Text(
            frm,
            height=5,
            width=70
        )

        self.activation.pack()

        ttk.Button(
            frm,
            text="Activate",
            command=self.activate
        ).pack(pady=15)

    def copy_request(self):

        self.root.clipboard_clear()
        self.root.clipboard_append(self.challenge.get())

    def activate(self):

        code = self.activation.get("1.0", tk.END).strip()

        if not code:
            messagebox.showerror(
                "Error",
                "Please enter activation code."
            )
            return

        ok = self.lm.activate(code)

        if ok:

            days = self.lm.days_remaining()

            messagebox.showinfo(
                "License Activated",
                f"""License Activated Successfully

Remaining Days : {days}

Email : {SUPPORT_EMAIL}

Phone : {SUPPORT_PHONE}
"""
            )

            self.root.destroy()

        else:

            messagebox.showerror(
                "License Invalid",
                "License Invalid."
            )

if __name__ == "__main__":
    ActivationGUI()