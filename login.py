import base64
import json
import os
import tkinter as tk
from tkinter import messagebox

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# -------------------------------------------------
# Configuration
# -------------------------------------------------

PASSWORD_FILE = ".password"

# POC ONLY - Move to KeyVault in production
AES_KEY = bytes.fromhex(
    "3d7d21c9b784d7334ef94f58f0f99d80"
    "d69e4a1ef2b53b51fd44f4e51a5bc2b8"
)

# -------------------------------------------------
# Crypto
# -------------------------------------------------


def encrypt_password(password: str):
    iv = os.urandom(16)

    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(
        pad(password.encode(), AES.block_size)
    )

    with open(PASSWORD_FILE, "w") as f:
        json.dump(
            {
                "iv": base64.b64encode(iv).decode(),
                "password": base64.b64encode(ciphertext).decode(),
            },
            f,
            indent=4,
        )


def verify_password(password: str) -> bool:

    if not os.path.exists(PASSWORD_FILE):
        return False

    with open(PASSWORD_FILE) as f:
        data = json.load(f)

    iv = base64.b64decode(data["iv"])
    ciphertext = base64.b64decode(data["password"])

    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)

    try:
        plain = unpad(
            cipher.decrypt(ciphertext),
            AES.block_size
        ).decode()

        return plain == password

    except Exception:
        return False


# -------------------------------------------------
# Login Window
# -------------------------------------------------

def show_login():

    login_success = False

    first_run = not os.path.exists(PASSWORD_FILE)

    root = tk.Tk()
    root.title("Inventory Login")
    root.geometry("430x270")
    root.configure(bg="#1b2038")
    root.resizable(False, False)

    title = "CREATE PASSWORD" if first_run else "LOGIN"

    tk.Label(
        root,
        text=title,
        bg="#1b2038",
        fg="#00D8FF",
        font=("Consolas", 18, "bold"),
    ).pack(pady=15)

    frame = tk.Frame(root, bg="#1b2038")
    frame.pack()

    tk.Label(
        frame,
        text="Username",
        bg="#1b2038",
        fg="white",
    ).grid(row=0, column=0, padx=10, pady=8, sticky="w")

    username = tk.Entry(frame, width=28)
    username.grid(row=0, column=1)
    username.insert(0, "admin")
    username.config(state="readonly")

    tk.Label(
        frame,
        text="Password",
        bg="#1b2038",
        fg="white",
    ).grid(row=1, column=0, padx=10, pady=8, sticky="w")

    password_entry = tk.Entry(frame, width=28, show="*")
    password_entry.grid(row=1, column=1)

    confirm_entry = None

    if first_run:

        tk.Label(
            frame,
            text="Confirm",
            bg="#1b2038",
            fg="white",
        ).grid(row=2, column=0, padx=10, pady=8, sticky="w")

        confirm_entry = tk.Entry(frame, width=28, show="*")
        confirm_entry.grid(row=2, column=1)

    def do_login():
        nonlocal login_success

        password = password_entry.get()

        if first_run:

            if not password:
                messagebox.showerror(
                    "Error",
                    "Password cannot be empty."
                )
                return

            if password != confirm_entry.get():
                messagebox.showerror(
                    "Error",
                    "Passwords do not match."
                )
                return

            encrypt_password(password)

            messagebox.showinfo(
                "Success",
                "Password created."
            )

            login_success = True
            root.destroy()
            return

        if verify_password(password):

            login_success = True
            root.destroy()

        else:

            messagebox.showerror(
                "Error",
                "Invalid password."
            )

    tk.Button(
        root,
        text="Create" if first_run else "Login",
        width=12,
        bg="#00B140",
        fg="white",
        command=do_login,
    ).pack(pady=20)

    root.protocol("WM_DELETE_WINDOW", root.destroy)

    root.mainloop()

    return login_success