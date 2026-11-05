import io
import os
import re
import secrets
from datetime import datetime, timedelta
from email.message import EmailMessage
import smtplib

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from ai_engine import analyze_complaint
from mongo_storage import (
    get_mongo_photo_stats,
    get_photo_from_mongo,
    save_photo_to_mongo,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "civicfix-production-secret-key-2026-secure")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB max upload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CIVICFIX_EMAIL = os.getenv("CIVICFIX_EMAIL")
CIVICFIX_APP_PASSWORD = os.getenv("CIVICFIX_APP_PASSWORD")

# Scope Configuration
ALLOWED_CATEGORIES = {
    "Roads & Potholes",
    "Waterlogging & Drainage",
    "Garbage & Waste",
    "Streetlights",
    "Water Supply",
    "Sewerage",
}

# The 3 primary departments in scope
PRIMARY_DEPARTMENTS = {
    "BBMP Roads": "Roadside Engineering Department",
    "BBMP Storm Water": "Stormwater and Drain Department",
    "BBMP Solid Waste": "Solid Waste Management Department",
}

DEPARTMENT_MAP = {
    "roads@civicfix.com": ("BBMP Roads", "Roadside Engineering Department"),
    "stormwater@civicfix.com": ("BBMP Storm Water", "Stormwater and Drain Department"),
    "waste@civicfix.com": ("BBMP Solid Waste", "Solid Waste Management Department"),
    # Legacy compatibility mappings
    "electrical@civicfix.com": ("BBMP Electrical", "Electrical Department"),
    "water@civicfix.com": ("BWSSB Water", "Water Supply Department"),
    "sewerage@civicfix.com": ("BWSSB Sewerage", "Sewerage Department"),
}


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "civicfix_app"),
        password=os.getenv("MYSQL_PASSWORD", "CivicFix@2026"),
        database=os.getenv("MYSQL_DATABASE", "civicfix_friendcopy"),
        autocommit=False,
    )


def allowed_file(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def log_complaint_history(cursor, complaint_id, from_status, to_status, actor_role, actor_id=None, action_note=None):
    try:
        cursor.execute(
            """
            INSERT INTO complaint_history (complaint_id, from_status, to_status, actor_id, actor_role, action_note)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (complaint_id, from_status, to_status, actor_id, actor_role, action_note),
        )
    except Exception as history_error:
        print(f"Audit log warning: {history_error}")


def send_otp_email(to_email, otp):
    print(f"[OTP GENERATED for {to_email}]: {otp}")
    if not CIVICFIX_EMAIL or not CIVICFIX_APP_PASSWORD:
        print(f"[DEV MODE] Email credentials not fully set. Generated OTP for {to_email} is: {otp}")
        return True

    msg = EmailMessage()
    msg["Subject"] = f"CivicFix Verification Code: {otp}"
    msg["From"] = f"CivicFix Bengaluru <{CIVICFIX_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(
        f"Hello,\n\nYour CivicFix verification code is: {otp}\n\n"
        f"This code will expire in 5 minutes.\n"
        f"If you did not request this code, please ignore this email.\n\n"
        f"Best regards,\nCivicFix Bengaluru Civic Portal"
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
            smtp.login(CIVICFIX_EMAIL, CIVICFIX_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"SMTP SEND ERROR: {e}")
        # Return False or re-raise so callers can report status if needed
        return False


# ---------------------------------------------------------
# Static File / Photo Serving (MongoDB GridFS primary, disk fallback)
# ---------------------------------------------------------
@app.route("/uploads/<path:filename>")
@app.route("/photo/<path:filename>")
def serve_upload(filename):
    safe_filename = os.path.basename(filename)

    # 1. Stream photo directly from MongoDB GridFS
    mongo_photo = get_photo_from_mongo(safe_filename)
    if mongo_photo:
        data, content_type = mongo_photo
        return send_file(
            io.BytesIO(data),
            mimetype=content_type,
            as_attachment=False,
            download_name=safe_filename,
        )

    # 2. Graceful fallback to local uploads/ directory
    return send_from_directory(UPLOAD_FOLDER, safe_filename)


# ---------------------------------------------------------
# Public Routes
# ---------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/test-db")
def test_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT DATABASE(), COUNT(*) FROM users;")
        db_name, user_count = cur.fetchone()
        cur.close()
        conn.close()

        mongo_stats = get_mongo_photo_stats()

        return {
            "status": "connected",
            "mysql_database": db_name,
            "mysql_user_count": user_count,
            "mongodb_photo_storage": mongo_stats,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


# ---------------------------------------------------------
# Citizen Authentication & Registration
# ---------------------------------------------------------
@app.route("/citizen-login", methods=["GET", "POST"])
def citizen_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, email, password_hash, role, is_verified
                FROM users
                WHERE email = %s AND role = 'citizen'
                LIMIT 1
                """,
                (email,),
            )
            user = cursor.fetchone()
            cursor.close()
            db.close()

            if user is None or not check_password_hash(user["password_hash"], password):
                return render_template("citizen_login.html", error="Invalid email or password.")

            if not user["is_verified"]:
                return render_template(
                    "citizen_login.html",
                    error="Your account is not verified yet. Please register or complete verification.",
                )

            session.clear()
            session["citizen_id"] = user["id"]
            session["citizen_name"] = user["full_name"]
            session["citizen_email"] = user["email"]
            session["role"] = "citizen"
            return redirect("/citizen-dashboard")

        except Exception as e:
            print("CITIZEN LOGIN ERROR:", e)
            return render_template("citizen_login.html", error="Database connection error. Please try again.")

    message = request.args.get("message")
    error = request.args.get("error")
    return render_template("citizen_login.html", message=message, error=error)


@app.route("/citizen-register", methods=["GET", "POST"])
def citizen_register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not email or not phone:
            return render_template("citizen_register.html", error="All fields are required.")

        if password != confirm_password:
            return render_template("citizen_register.html", error="Passwords do not match.")

        if len(password) < 6:
            return render_template("citizen_register.html", error="Password must be at least 6 characters.")

        password_hash = generate_password_hash(password)

        db = None
        cursor = None
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)

            cursor.execute("SELECT id FROM users WHERE email = %s OR phone = %s LIMIT 1", (email, phone))
            if cursor.fetchone():
                cursor.close()
                db.close()
                return render_template("citizen_register.html", error="Email or phone number is already registered.")

            cursor.execute("DELETE FROM pending_registrations WHERE email = %s OR phone = %s", (email, phone))

            otp = str(secrets.randbelow(900000) + 100000)
            expires_at = datetime.now() + timedelta(minutes=5)

            cursor.execute(
                """
                INSERT INTO pending_registrations (full_name, email, phone, password_hash, otp_code, expires_at, attempts)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
                """,
                (full_name, email, phone, password_hash, otp, expires_at),
            )
            db.commit()
            cursor.close()
            db.close()

            email_sent = False
            try:
                email_sent = send_otp_email(email, otp)
            except Exception as email_err:
                print("EMAIL SEND WARNING:", email_err)

            status_msg = "A 6-digit OTP has been sent to your email address." if email_sent else "Registration started. Check your email or console for your 6-digit OTP code."
            return render_template("verify_otp.html", email=email, message=status_msg)

        except Exception as e:
            print("REGISTRATION ERROR:", e)
            if db:
                db.rollback()
                db.close()
            return render_template("citizen_register.html", error="Something went wrong during registration.")

    return render_template("citizen_register.html")


@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "GET":
        email = request.args.get("email", "").strip().lower()
        if not email:
            return redirect("/citizen-register")
        return render_template("verify_otp.html", email=email)

    email = request.form.get("email", "").strip().lower()
    entered_otp = request.form.get("otp", "").strip()

    if not email:
        return redirect("/citizen-register")

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, full_name, email, phone, password_hash, otp_code, expires_at, attempts
            FROM pending_registrations
            WHERE email = %s
            LIMIT 1
            """,
            (email,),
        )
        pending = cursor.fetchone()

        if not pending:
            cursor.close()
            db.close()
            return render_template("citizen_register.html", error="Registration session not found or already verified. Please register or login.")

        if pending["attempts"] >= 5:
            cursor.execute("DELETE FROM pending_registrations WHERE id = %s", (pending["id"],))
            db.commit()
            cursor.close()
            db.close()
            return render_template("citizen_register.html", error="Too many incorrect OTP attempts. Please register again.")

        if datetime.now() > pending["expires_at"]:
            cursor.execute("DELETE FROM pending_registrations WHERE id = %s", (pending["id"],))
            db.commit()
            cursor.close()
            db.close()
            return render_template("citizen_register.html", error="OTP has expired. Please register again.")

        if entered_otp != str(pending["otp_code"]).strip():
            new_attempts = pending["attempts"] + 1
            cursor.execute("UPDATE pending_registrations SET attempts = attempts + 1 WHERE id = %s", (pending["id"],))
            db.commit()
            cursor.close()
            db.close()
            remaining = 5 - new_attempts
            return render_template("verify_otp.html", email=email, error=f"Incorrect OTP code. {remaining} attempt(s) remaining.")

        # Valid OTP: Create user
        cursor.execute(
            """
            INSERT INTO users (full_name, email, phone, password_hash, role, is_verified)
            VALUES (%s, %s, %s, %s, 'citizen', 1)
            """,
            (pending["full_name"], pending["email"], pending["phone"], pending["password_hash"]),
        )
        cursor.execute("DELETE FROM pending_registrations WHERE id = %s", (pending["id"],))
        db.commit()
        cursor.close()
        db.close()

        return redirect("/citizen-login?message=Email+verified+successfully!+You+can+now+log+in.")

    except Exception as e:
        print("VERIFY OTP ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return render_template("verify_otp.html", email=email, error="Verification failed. Please try again.")


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    email = request.form.get("email", "").strip().lower()
    if not email:
        return redirect("/citizen-register")

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, email FROM pending_registrations WHERE email = %s LIMIT 1
            """,
            (email,),
        )
        pending = cursor.fetchone()

        if not pending:
            cursor.close()
            db.close()
            return render_template("citizen_register.html", error="Registration session expired. Please register again.")

        new_otp = str(secrets.randbelow(900000) + 100000)
        new_expires = datetime.now() + timedelta(minutes=5)

        cursor.execute(
            """
            UPDATE pending_registrations
            SET otp_code = %s, expires_at = %s, attempts = 0
            WHERE id = %s
            """,
            (new_otp, new_expires, pending["id"]),
        )
        db.commit()
        cursor.close()
        db.close()

        try:
            send_otp_email(email, new_otp)
        except Exception as email_err:
            print("RESEND EMAIL WARNING:", email_err)

        return render_template("verify_otp.html", email=email, message="A fresh OTP code has been sent to your email!")

    except Exception as e:
        print("RESEND OTP ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return render_template("verify_otp.html", email=email, error="Failed to resend OTP. Please try again.")


# ---------------------------------------------------------
# Citizen Dashboard & Complaint Submission
# ---------------------------------------------------------
@app.route("/citizen-dashboard")
def citizen_dashboard():
    if "citizen_id" not in session or session.get("role") != "citizen":
        return redirect("/citizen-login")

    citizen_id = session["citizen_id"]
    db = None
    cursor = None
    complaints = []
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, complaint_id, category, description, location, image_path,
                   status, department, resolution_proof, resolution_notes, proof_status,
                   admin_feedback, created_at, updated_at
            FROM complaints
            WHERE citizen_id = %s
            ORDER BY created_at DESC
            """,
            (citizen_id,),
        )
        complaints = cursor.fetchall()
        cursor.close()
        db.close()
    except Exception as e:
        print("CITIZEN DASHBOARD FETCH ERROR:", e)
        if db:
            db.close()

    message = request.args.get("message")
    if request.args.get("submitted"):
        message = "Your complaint has been submitted successfully and automatically assigned to the responsible department by AI!"

    return render_template("citizen_dashboard.html", complaints=complaints, message=message)


@app.route("/submit-complaint", methods=["POST"])
def submit_complaint():
    if "citizen_id" not in session or session.get("role") != "citizen":
        return redirect("/citizen-login")

    category = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    location = request.form.get("location", "").strip()
    image = request.files.get("image")

    if not category or category not in ALLOWED_CATEGORIES:
        flash("Please select a valid complaint category.")
        return redirect("/citizen-dashboard")

    if not description or len(description) < 5:
        flash("Please provide a meaningful complaint description.")
        return redirect("/citizen-dashboard")

    if not location:
        flash("Please provide the location of the problem.")
        return redirect("/citizen-dashboard")

    if not image or image.filename == "" or not allowed_file(image.filename):
        flash("Please upload a valid image file (PNG, JPG, JPEG, WEBP).")
        return redirect("/citizen-dashboard")

    # Save original image securely in MongoDB GridFS (with disk cache backup)
    ext = image.filename.rsplit(".", 1)[1].lower()
    complaint_id = f"CF{datetime.now().strftime('%Y%m%d')}{secrets.randbelow(9000) + 1000}"
    img_filename = f"{complaint_id}_{secrets.token_hex(6)}.{ext}"
    img_rel_path = f"uploads/{img_filename}"
    img_abs_path = os.path.join(UPLOAD_FOLDER, img_filename)

    try:
        # Save to local disk cache
        image.save(img_abs_path)
        # Store in MongoDB GridFS
        save_photo_to_mongo(
            image,
            img_filename,
            metadata={
                "complaint_id": complaint_id,
                "type": "original_complaint",
                "citizen_id": session.get("citizen_id"),
                "category": category,
            },
        )
    except Exception as file_err:
        print("IMAGE SAVE ERROR:", file_err)
        flash("Failed to save uploaded image. Please try again.")
        return redirect("/citizen-dashboard")

    # Run AI Analysis
    try:
        ai_res = analyze_complaint(category, description, location)
    except Exception as ai_err:
        print("AI ENGINE WARNING:", ai_err)
        ai_res = {
            "department": "BBMP Roads",
            "confidence": 0.0,
            "priority": "Medium",
            "priority_score": 50,
            "reason": "AI model unavailable; flagged for manual admin review.",
            "suggested_solution": "Inspect site and determine corrective actions.",
            "assignment_source": "Fallback",
        }

    # AI Department Assignment based on Category
    ai_dept = ai_res.get("department")
    if ai_dept in PRIMARY_DEPARTMENTS:
        assigned_department = ai_dept
        complaint_status = "Assigned"
        assignment_source = "AI"
        history_note = f"Complaint registered and automatically assigned to {assigned_department} by AI based on category '{category}'."
    else:
        # If category is outside the 3 primary departments, hold for Admin review
        assigned_department = None
        complaint_status = "Submitted"
        assignment_source = "Pending Review"
        history_note = f"Complaint registered with category '{category}' and held for manual Admin assignment."

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor()

        cursor.execute(
            """
            INSERT INTO complaints (
                complaint_id, citizen_id, category, description, image_path, location,
                status, department, ai_department, ai_department_confidence,
                ai_priority, ai_priority_score, ai_reason, ai_suggested_solution,
                assignment_source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                complaint_id,
                session["citizen_id"],
                category,
                description,
                img_rel_path,
                location,
                complaint_status,
                assigned_department,
                ai_res.get("department"),
                ai_res.get("confidence", 95.0),
                ai_res.get("priority", "Medium"),
                ai_res.get("priority_score", 50),
                ai_res.get("reason"),
                ai_res.get("suggested_solution"),
                assignment_source,
            ),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            None,
            complaint_status,
            "AI",
            None,
            history_note,
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/citizen-dashboard?submitted=1")

    except Exception as e:
        print("COMPLAINT INSERT ERROR:", e)
        if db:
            db.rollback()
            db.close()
        # Clean up uploaded image if DB insert failed
        if os.path.exists(img_abs_path):
            try:
                os.remove(img_abs_path)
            except OSError:
                pass
        flash("Database error while submitting complaint. Please try again.")
        return redirect("/citizen-dashboard")


# ---------------------------------------------------------
# Admin Authentication & Dashboard
# ---------------------------------------------------------
@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, email, password_hash, role, is_verified
                FROM users
                WHERE email = %s AND role = 'admin'
                LIMIT 1
                """,
                (email,),
            )
            admin = cursor.fetchone()
            cursor.close()
            db.close()

            if admin is None or not check_password_hash(admin["password_hash"], password):
                return render_template("admin_login.html", error="Invalid admin email or password.")

            session.clear()
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["full_name"]
            session["admin_email"] = admin["email"]
            session["role"] = "admin"
            return redirect("/admin-dashboard")

        except Exception as e:
            print("ADMIN LOGIN ERROR:", e)
            return render_template("admin_login.html", error="Database error during admin login.")

    message = request.args.get("message")
    error = request.args.get("error")
    return render_template("admin_login.html", message=message, error=error)


@app.route("/admin-dashboard")
def admin_dashboard():
    if "admin_id" not in session or session.get("role") != "admin":
        return redirect("/admin-login")

    status_filter = request.args.get("status")

    db = None
    cursor = None
    complaints = []
    stats = {
        "total": 0,
        "submitted": 0,
        "assigned": 0,
        "in_progress": 0,
        "awaiting_verification": 0,
        "completed": 0,
        "rejected": 0,
    }

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Get KPI Stats
        cursor.execute("SELECT status, proof_status, resolution_proof FROM complaints")
        all_comps = cursor.fetchall()
        stats["total"] = len(all_comps)
        for c in all_comps:
            st = c["status"]
            if st == "Submitted":
                stats["submitted"] += 1
            elif st == "Assigned":
                stats["assigned"] += 1
            elif st == "In Progress":
                stats["in_progress"] += 1
            elif st == "Rejected":
                stats["rejected"] += 1

            if c["proof_status"] == "Pending" and c["resolution_proof"]:
                stats["awaiting_verification"] += 1
            elif c["proof_status"] == "Verified":
                stats["completed"] += 1

        # Fetch complaints according to filter
        query = """
            SELECT c.id, c.complaint_id, c.category, c.description, c.image_path, c.location,
                   c.status, c.department, c.resolution_proof, c.resolution_notes, c.proof_status,
                   c.created_at, c.ai_department, c.ai_department_confidence, c.ai_priority,
                   c.ai_priority_score, c.ai_reason, c.ai_suggested_solution, c.assignment_source,
                   c.admin_feedback,
                   u.full_name AS citizen_name, u.email AS citizen_email, u.phone AS citizen_phone
            FROM complaints c
            JOIN users u ON c.citizen_id = u.id
        """
        params = []
        if status_filter == "Verification":
            query += " WHERE c.proof_status = 'Pending' AND c.resolution_proof IS NOT NULL AND c.resolution_proof <> ''"
        elif status_filter:
            query += " WHERE c.status = %s"
            params.append(status_filter)

        query += " ORDER BY c.created_at DESC"
        cursor.execute(query, tuple(params))
        complaints = cursor.fetchall()

        cursor.close()
        db.close()

    except Exception as e:
        print("ADMIN DASHBOARD ERROR:", e)
        if db:
            db.close()

    msg = request.args.get("msg")
    err = request.args.get("err")
    return render_template(
        "admin_dashboard.html",
        complaints=complaints,
        stats=stats,
        current_filter=status_filter,
        message=msg,
        error=err,
    )


@app.route("/admin-assign", methods=["POST"])
def admin_assign():
    if "admin_id" not in session or session.get("role") != "admin":
        return redirect("/admin-login")

    complaint_id = request.form.get("complaint_id", "").strip()
    department = request.form.get("department", "").strip()

    # In-scope department validation
    if not complaint_id or department not in PRIMARY_DEPARTMENTS:
        return redirect("/admin-dashboard?err=Invalid+department+or+complaint+ID")

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT status, department FROM complaints WHERE complaint_id = %s", (complaint_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            db.close()
            return redirect("/admin-dashboard?err=Complaint+not+found")

        prev_status = row["status"]
        new_status = "Assigned"

        cursor.execute(
            """
            UPDATE complaints
            SET department = %s,
                status = %s,
                assignment_source = 'Admin',
                admin_feedback = NULL
            WHERE complaint_id = %s
            """,
            (department, new_status, complaint_id),
        )

        dept_display = PRIMARY_DEPARTMENTS.get(department, department)
        log_complaint_history(
            cursor,
            complaint_id,
            prev_status,
            new_status,
            "admin",
            session["admin_id"],
            f"Approved and assigned to {dept_display} by Admin.",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/admin-dashboard?msg=Complaint+approved+and+assigned+successfully")

    except Exception as e:
        print("ADMIN ASSIGN ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/admin-dashboard?err=Error+assigning+complaint")


@app.route("/admin-reject-complaint", methods=["POST"])
def admin_reject_complaint():
    if "admin_id" not in session or session.get("role") != "admin":
        return redirect("/admin-login")

    complaint_id = request.form.get("complaint_id", "").strip()
    reason = request.form.get("reason", "").strip() or "Rejected by administrator after review."

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute("SELECT status FROM complaints WHERE complaint_id = %s", (complaint_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            db.close()
            return redirect("/admin-dashboard?err=Complaint+not+found")

        prev_status = row["status"]
        cursor.execute(
            """
            UPDATE complaints
            SET status = 'Rejected',
                admin_feedback = %s
            WHERE complaint_id = %s
            """,
            (reason, complaint_id),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            prev_status,
            "Rejected",
            "admin",
            session["admin_id"],
            f"Rejected by Admin: {reason}",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/admin-dashboard?msg=Complaint+rejected")

    except Exception as e:
        print("ADMIN REJECT COMPLAINT ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/admin-dashboard?err=Error+rejecting+complaint")


@app.route("/admin-verify-proof", methods=["POST"])
def admin_verify_proof():
    if "admin_id" not in session or session.get("role") != "admin":
        return redirect("/admin-login")

    complaint_id = request.form.get("complaint_id", "").strip()

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            UPDATE complaints
            SET proof_status = 'Verified',
                status = 'Resolved'
            WHERE complaint_id = %s
              AND resolution_proof IS NOT NULL
            """,
            (complaint_id,),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            "Resolved",
            "Resolved",
            "admin",
            session["admin_id"],
            "Admin verified completion proof and approved case closure.",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/admin-dashboard?msg=Proof+verified+and+complaint+completed")

    except Exception as e:
        print("ADMIN VERIFY PROOF ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/admin-dashboard?err=Error+verifying+proof")


@app.route("/admin-reject-proof", methods=["POST"])
def admin_reject_proof():
    if "admin_id" not in session or session.get("role") != "admin":
        return redirect("/admin-login")

    complaint_id = request.form.get("complaint_id", "").strip()
    feedback = request.form.get("feedback", "").strip() or "Completion proof unsatisfactory. Please rework."

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # Return status to 'In Progress' so department can rework
        cursor.execute(
            """
            UPDATE complaints
            SET proof_status = 'Rejected',
                status = 'In Progress',
                admin_feedback = %s
            WHERE complaint_id = %s
            """,
            (feedback, complaint_id),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            "Resolved",
            "In Progress",
            "admin",
            session["admin_id"],
            f"Admin rejected proof: {feedback}",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/admin-dashboard?msg=Proof+rejected+and+complaint+returned+to+In+Progress")

    except Exception as e:
        print("ADMIN REJECT PROOF ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/admin-dashboard?err=Error+rejecting+proof")


# ---------------------------------------------------------
# Department Authentication & Dashboard
# ---------------------------------------------------------
@app.route("/department-login", methods=["GET", "POST"])
def department_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id, full_name, email, password_hash, role, is_verified
                FROM users
                WHERE email = %s AND role = 'department'
                LIMIT 1
                """,
                (email,),
            )
            dept_user = cursor.fetchone()
            cursor.close()
            db.close()

            if dept_user is None or not check_password_hash(dept_user["password_hash"], password):
                return render_template("department_login.html", error="Invalid email or password.")

            if not dept_user["is_verified"]:
                return render_template("department_login.html", error="This department account is not verified.")

            session.clear()
            session["department_id"] = dept_user["id"]
            session["department_name"] = dept_user["full_name"]
            session["department_email"] = dept_user["email"]
            session["role"] = "department"
            return redirect("/department-dashboard")

        except Exception as e:
            print("DEPARTMENT LOGIN ERROR:", e)
            return render_template("department_login.html", error="Database error during department login.")

    message = request.args.get("message")
    error = request.args.get("error")
    return render_template("department_login.html", message=message, error=error)


@app.route("/department-dashboard")
def department_dashboard():
    if "department_id" not in session or session.get("role") != "department":
        return redirect("/department-login")

    dept_email = session.get("department_email", "")
    mapping = DEPARTMENT_MAP.get(dept_email)

    if not mapping:
        return render_template("department_login.html", error="Department configuration not recognized.")

    department_code, department_name = mapping

    db = None
    cursor = None
    complaints = []
    stats = {
        "total": 0,
        "in_progress": 0,
        "awaiting_verification": 0,
        "completed": 0,
    }

    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        # STRICT ACCESS CONTROL:
        # Department can ONLY view complaints assigned to its department code
        # AND where status is 'Assigned', 'In Progress', or 'Resolved'.
        # Unapproved complaints ('Submitted') are strictly hidden.
        cursor.execute(
            """
            SELECT id, complaint_id, category, description, image_path, location,
                   status, resolution_proof, resolution_notes, proof_status,
                   ai_priority, ai_suggested_solution, admin_feedback, created_at, updated_at
            FROM complaints
            WHERE department = %s
              AND status IN ('Assigned', 'In Progress', 'Resolved')
            ORDER BY created_at DESC
            """,
            (department_code,),
        )
        complaints = cursor.fetchall()

        stats["total"] = len(complaints)
        for c in complaints:
            if c["status"] == "In Progress":
                stats["in_progress"] += 1
            if c["proof_status"] == "Pending" and c["resolution_proof"]:
                stats["awaiting_verification"] += 1
            elif c["proof_status"] == "Verified":
                stats["completed"] += 1

        cursor.close()
        db.close()

    except Exception as e:
        print("DEPARTMENT DASHBOARD ERROR:", e)
        if db:
            db.close()

    msg = request.args.get("msg")
    err = request.args.get("err")
    return render_template(
        "department_dashboard.html",
        complaints=complaints,
        department_name=department_name,
        department_code=department_code,
        stats=stats,
        message=msg,
        error=err,
    )


@app.route("/department-update-status", methods=["POST"])
def department_update_status():
    if "department_id" not in session or session.get("role") != "department":
        return redirect("/department-login")

    complaint_id = request.form.get("complaint_id", "").strip()
    new_status = request.form.get("status", "").strip()

    dept_email = session.get("department_email", "")
    mapping = DEPARTMENT_MAP.get(dept_email)
    if not mapping or not complaint_id or new_status != "In Progress":
        return redirect("/department-dashboard?err=Invalid+transition")

    department_code, _ = mapping

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT status
            FROM complaints
            WHERE complaint_id = %s AND department = %s
            LIMIT 1
            """,
            (complaint_id, department_code),
        )
        complaint = cursor.fetchone()

        if not complaint or complaint["status"] != "Assigned":
            cursor.close()
            db.close()
            return redirect("/department-dashboard?err=Complaint+not+in+Assigned+state")

        cursor.execute(
            """
            UPDATE complaints
            SET status = 'In Progress'
            WHERE complaint_id = %s AND department = %s
            """,
            (complaint_id, department_code),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            "Assigned",
            "In Progress",
            "department",
            session["department_id"],
            "Department initiated work on complaint.",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/department-dashboard?msg=Work+started+successfully")

    except Exception as e:
        print("DEPARTMENT UPDATE ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/department-dashboard?err=Failed+to+update+status")


@app.route("/department-upload-proof", methods=["POST"])
def department_upload_proof():
    if "department_id" not in session or session.get("role") != "department":
        return redirect("/department-login")

    complaint_id = request.form.get("complaint_id", "").strip()
    proof_file = request.files.get("proof_file")
    notes = request.form.get("resolution_notes", "").strip()

    dept_email = session.get("department_email", "")
    mapping = DEPARTMENT_MAP.get(dept_email)
    if not mapping or not complaint_id:
        return redirect("/department-dashboard?err=Invalid+request")

    department_code, _ = mapping

    if not proof_file or proof_file.filename == "" or not allowed_file(proof_file.filename):
        return redirect("/department-dashboard?err=Please+upload+a+valid+proof+image")

    # Save resolution proof image safely in MongoDB GridFS (with disk cache backup)
    ext = proof_file.filename.rsplit(".", 1)[1].lower()
    proof_filename = f"proof_{complaint_id}_{secrets.token_hex(6)}.{ext}"
    proof_abs_path = os.path.join(UPLOAD_FOLDER, proof_filename)

    try:
        # Save to local disk cache
        proof_file.save(proof_abs_path)
        # Store in MongoDB GridFS
        save_photo_to_mongo(
            proof_file,
            proof_filename,
            metadata={
                "complaint_id": complaint_id,
                "type": "resolution_proof",
                "department_code": department_code,
                "department_id": session.get("department_id"),
            },
        )
    except Exception as file_err:
        print("PROOF FILE SAVE ERROR:", file_err)
        return redirect("/department-dashboard?err=Failed+to+save+proof+image")

    db = None
    cursor = None
    try:
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT status, proof_status
            FROM complaints
            WHERE complaint_id = %s AND department = %s
            LIMIT 1
            """,
            (complaint_id, department_code),
        )
        complaint = cursor.fetchone()

        if not complaint or complaint["status"] not in ["In Progress", "Resolved"]:
            cursor.close()
            db.close()
            return redirect("/department-dashboard?err=Complaint+not+eligible+for+proof+upload")

        prev_status = complaint["status"]

        cursor.execute(
            """
            UPDATE complaints
            SET resolution_proof = %s,
                resolution_notes = %s,
                status = 'Resolved',
                proof_status = 'Pending'
            WHERE complaint_id = %s AND department = %s
            """,
            (proof_filename, notes, complaint_id, department_code),
        )

        log_complaint_history(
            cursor,
            complaint_id,
            prev_status,
            "Resolved",
            "department",
            session["department_id"],
            f"Uploaded completion proof. Notes: {notes}",
        )

        db.commit()
        cursor.close()
        db.close()

        return redirect("/department-dashboard?msg=Proof+uploaded+successfully.+Awaiting+Admin+verification.")

    except Exception as e:
        print("DEPARTMENT PROOF ERROR:", e)
        if db:
            db.rollback()
            db.close()
        return redirect("/department-dashboard?err=Database+error+saving+proof")


# ---------------------------------------------------------
# Shared Logout
# ---------------------------------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1")
    print(f"Starting CivicFix on http://127.0.0.1:5000 (debug={debug_mode})")
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)