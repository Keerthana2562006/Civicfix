
from dotenv import load_dotenv
from ai_engine import analyze_complaint
from app import get_db_connection

load_dotenv()

db = get_db_connection()
cursor = db.cursor(dictionary=True)

try:
    cursor.execute("""
        SELECT id, complaint_id, category, description
        FROM complaints
        WHERE ai_department IS NULL
           OR ai_department_confidence IS NULL
           OR ai_priority IS NULL
           OR ai_priority_score IS NULL
           OR ai_reason IS NULL
    """)

    complaints = cursor.fetchall()
    print(f"Found {len(complaints)} complaints needing AI results.")

    for complaint in complaints:
        result = analyze_complaint(
            complaint["category"],
            complaint["description"]
        )

        cursor.execute("""
            UPDATE complaints
            SET ai_department = %s,
                ai_department_confidence = %s,
                ai_priority = %s,
                ai_priority_score = %s,
                ai_reason = %s
            WHERE id = %s
        """, (
            result["department"],
            result["confidence"],
            result["priority"],
            result["priority_score"],
            result["reason"],
            complaint["id"]
        ))

        print(
            complaint["complaint_id"],
            "->", result["department"],
            "|", result["priority"]
        )

    db.commit()
    print("AI backfill completed successfully.")

except Exception as error:
    db.rollback()
    print("AI backfill failed:", error)

finally:
    cursor.close()
    db.close()
