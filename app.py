
def ensure_admin(db, force_new=False):
    """Create an admin if none exists, or update the configured admin
    credentials when explicitly requested."""
    username = os.environ.get(
        "CLEANCONNECT_ADMIN_USER",
        "admin@cleanconnect.local"
    )
    env_pw = os.environ.get("CLEANCONNECT_ADMIN_PASSWORD")

    existing_admin = db.execute(
        "SELECT id FROM admins WHERE username = ?",
        (username,)
    ).fetchone()

    # Update only the selected admin when a password is explicitly configured.
    if existing_admin and env_pw and force_new:
        db.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (generate_password_hash(env_pw), username)
        )
        db.commit()
        print(f"[CleanConnect] Updated password for admin '{username}'.")
        return

    # Preserve existing admin accounts during normal startup.
    if db.execute("SELECT 1 FROM admins").fetchone():
        return

    password = env_pw if env_pw else secrets.token_urlsafe(18)

    db.execute(
        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
        (username, generate_password_hash(password))
    )
    db.commit()

    if not env_pw:
        credentials_path = os.path.join(
            INSTANCE_DIR, "admin_credentials.txt"
        )
        with open(credentials_path, "w", encoding="utf-8") as fh:
            fh.write(f"username: {username}\npassword: {password}\n")
        try:
            os.chmod(credentials_path, 0o600)
        except OSError:
            pass
