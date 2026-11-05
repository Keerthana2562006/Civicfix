#!/usr/bin/env python3
"""
Secure CLI Utility to set or reset a CivicFix account password.
Uses Werkzeug password hashing. Never logs or prints plaintext passwords.
"""
import os
import sys
import getpass
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash

load_dotenv()

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "civicfix_app"),
        password=os.getenv("MYSQL_PASSWORD", "CivicFix@2026"),
        database=os.getenv("MYSQL_DATABASE", "civicfix_friendcopy"),
    )

def reset_password(email=None, new_password=None):
    if not email:
        email = input("Enter account email to reset: ").strip().lower()
    else:
        email = email.strip().lower()

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT id, full_name, email, role, is_verified FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()

    if not user:
        print(f"Error: Account with email '{email}' does not exist.")
        cursor.close()
        conn.close()
        return False

    if not new_password:
        pw1 = getpass.getpass(f"Enter new password for {user['full_name']} ({user['role']}): ")
        pw2 = getpass.getpass("Confirm new password: ")
        if pw1 != pw2:
            print("Error: Passwords do not match.")
            cursor.close()
            conn.close()
            return False
        if len(pw1) < 6:
            print("Error: Password must be at least 6 characters.")
            cursor.close()
            conn.close()
            return False
        new_password = pw1

    new_hash = generate_password_hash(new_password)
    cursor.execute(
        "UPDATE users SET password_hash = %s, is_verified = 1 WHERE id = %s",
        (new_hash, user["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()

    print(f"Success: Password for {user['email']} has been updated and account verified.")
    return True

if __name__ == "__main__":
    target_email = sys.argv[1] if len(sys.argv) > 1 else None
    reset_password(target_email)
