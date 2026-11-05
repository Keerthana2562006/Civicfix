import os
import mysql.connector

conn = mysql.connector.connect(
    host="127.0.0.1",
    port=3306,
    user="civicfix_app",
    password="CivicFix@2026",
    database="civicfix_friendcopy"
)
cursor = conn.cursor()

cursor.execute("SHOW TABLES")
tables = [row[0] for row in cursor.fetchall()]

output_file = "civicfix_cloud_backup.sql"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("-- CivicFix Cloud Database Export\n")
    f.write("-- Generated for 24/7 Cloud Deployment (Railway / Render / Aiven / TiDB)\n\n")
    f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

    for table in tables:
        # Get CREATE TABLE statement
        cursor.execute(f"SHOW CREATE TABLE `{table}`")
        create_stmt = cursor.fetchone()[1]
        f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
        f.write(f"{create_stmt};\n\n")

        # Get rows
        cursor.execute(f"SELECT * FROM `{table}`")
        rows = cursor.fetchall()
        if rows:
            cursor.execute(f"DESCRIBE `{table}`")
            columns = [f"`{col[0]}`" for col in cursor.fetchall()]
            cols_str = ", ".join(columns)

            f.write(f"-- Dumping data for table `{table}`\n")
            for row in rows:
                values = []
                for val in row:
                    if val is None:
                        values.append("NULL")
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    elif isinstance(val, (bytes, bytearray)):
                        hex_str = val.hex()
                        values.append(f"X'{hex_str}'")
                    else:
                        val_str = str(val).replace("\\", "\\\\").replace("'", "''").replace("\n", "\\n").replace("\r", "\\r")
                        values.append(f"'{val_str}'")
                vals_str = ", ".join(values)
                f.write(f"INSERT INTO `{table}` ({cols_str}) VALUES ({vals_str});\n")
            f.write("\n")

    f.write("SET FOREIGN_KEY_CHECKS = 1;\n")

print(f"Successfully exported {len(tables)} tables to {output_file}")
cursor.close()
conn.close()
