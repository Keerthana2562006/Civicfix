#!/usr/bin/env python3
"""
Safe database migration script for CivicFix.
Preserves existing records, adds missing columns and tables if necessary.
"""
import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

def run_migration():
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", 3306))
    user = os.getenv("MYSQL_USER", "civicfix_app")
    password = os.getenv("MYSQL_PASSWORD", "CivicFix@2026")
    database = os.getenv("MYSQL_DATABASE", "civicfix_friendcopy")

    print(f"Connecting to MySQL ({host}:{port}, database: {database})...")
    conn = mysql.connector.connect(
        host=host, port=port, user=user, password=password, database=database
    )
    cursor = conn.cursor(dictionary=True)

    # 1. Verify users table
    cursor.execute("DESCRIBE users")
    user_cols = {col["Field"]: col["Type"] for col in cursor.fetchall()}
    print(f"Users table verified: {len(user_cols)} columns present.")

    # 2. Check complaints table
    cursor.execute("DESCRIBE complaints")
    comp_cols = {col["Field"]: col["Type"] for col in cursor.fetchall()}
    print(f"Complaints table verified: {len(comp_cols)} columns present.")

    # Add resolution_notes to complaints if missing
    if "resolution_notes" not in comp_cols:
        print("Adding 'resolution_notes' column to complaints table...")
        cursor.execute("ALTER TABLE complaints ADD COLUMN resolution_notes TEXT NULL AFTER resolution_proof;")
        conn.commit()
        print("Column 'resolution_notes' added.")
    else:
        print("'resolution_notes' column already exists.")

    # 3. Create complaint_history table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS complaint_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            complaint_id VARCHAR(30) NOT NULL,
            from_status VARCHAR(50) NULL,
            to_status VARCHAR(50) NOT NULL,
            actor_id INT NULL,
            actor_role VARCHAR(50) NOT NULL,
            action_note TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_complaint_id (complaint_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)
    conn.commit()
    print("Complaint history table verified / created.")

    # 4. Summary of current counts
    cursor.execute("SELECT COUNT(*) AS cnt FROM users")
    u_count = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM complaints")
    c_count = cursor.fetchone()["cnt"]
    cursor.execute("SELECT COUNT(*) AS cnt FROM complaint_history")
    h_count = cursor.fetchone()["cnt"]

    print(f"\nMigration Status: Success! Database '{database}' is ready.")
    print(f"Current Stats -> Users: {u_count}, Complaints: {c_count}, History Records: {h_count}")

    cursor.close()
    conn.close()

if __name__ == "__main__":
    run_migration()
