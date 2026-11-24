# CivicFix — Civic Complaint Management System

CivicFix is a full-stack civic complaint management web application connecting citizens, municipal administrators, and municipal department staff through a centralized MySQL database and hybrid AI routing engine.

---

## 1. Project Workflow & User Roles

The system strictly enforces the complete civic complaint lifecycle:

```text
Citizen Submits Complaint (Photo + Location + Description)
            │
            ▼
AI Engine Analyzes Complaint (Category, Suggested Dept, Priority, Reasoning)
            │
            ▼
Status: "Submitted" (Pending Admin Approval)
[Complaint is completely INVISIBLE to department queues until approved]
            │
            ▼
Admin Reviews, Approves & Assigns Complaint to Department
            │
            ▼
Status: "Assigned"
[Complaint becomes visible ONLY to the assigned department]
            │
            ▼
Department Staff Accepts & Starts Work (Status: "In Progress")
            │
            ▼
Department Completes Work & Uploads Completion Photo Proof + Summary
(Status: "Resolved", Proof Status: "Pending")
            │
            ▼
Admin Verifies Resolution Proof Photo
   ├── If Approved: Proof Status -> "Verified" (Case closed)
   └── If Rejected: Proof Status -> "Rejected", returns to "In Progress" with feedback
            │
            ▼
Citizen Tracks Real-Time Progress, Department Assignment & Proof Photos
```

---

## 2. Supported Municipal Departments (In Scope)

CivicFix focuses on three core municipal departments:

| Department Code | Department Name | Responsibility | Default Account Email |
| :--- | :--- | :--- | :--- |
| `BBMP Roads` | **Roadside Engineering Department** | Potholes, broken roads, damaged footpaths & pavements | `roads@civicfix.com` |
| `BBMP Storm Water` | **Stormwater and Drain Department** | Blocked drains, clogged drainage channels, waterlogging | `stormwater@civicfix.com` |
| `BBMP Solid Waste` | **Solid Waste Management Department** | Garbage accumulation, overflowing bins, public waste | `waste@civicfix.com` |

**Admin Portal Account:**
- Email: `admin@civicfix.com`

*Note: Legacy categories (e.g. Streetlights, Water Supply, Sewerage) present in the database are safely preserved. Any submitted complaints under these categories are flagged with `review_required=True` for manual Admin assignment.*

---

## 3. Technology Stack

- **Backend:** Python 3.14 / 3.15, Flask 3.x
- **Database:** MySQL Server (Database: `civicfix_friendcopy`)
- **Connector:** `mysql-connector-python`
- **Authentication:** Flask Sessions & Werkzeug `scrypt` password hashing
- **AI / NLP Routing:** Hybrid rule-based signal extractor, risk/priority scoring, and ML classifier fallback
- **File Uploads:** Local secure storage in `uploads/` with UUID-based unique filenames, separate tracking of original issue photographs and completion proof photographs

---

## 4. Windows Setup & Installation

### Step 1: Open Terminal in Project Directory
Open PowerShell or Command Prompt:
```powershell
cd "C:\Users\HP\Documents\CIVIC FIX"
```

### Step 2: Install Python Dependencies
```powershell
python -m pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env` (or verify existing `.env`):
```ini
# Database Configuration
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=civicfix_app
MYSQL_PASSWORD=CivicFix@2026
MYSQL_DATABASE=civicfix_friendcopy

# Flask Configuration
FLASK_SECRET_KEY=civicfix-production-secret-key-2026-secure
FLASK_DEBUG=False

# Optional: SMTP Email for Citizen Registration OTP
CIVICFIX_EMAIL=your_email@gmail.com
CIVICFIX_APP_PASSWORD=your_app_password
```

### Step 4: Run Database Migration
Ensures all required tables (`users`, `complaints`, `complaint_history`) and columns (`resolution_notes`) are present without modifying existing data:
```powershell
python migrate_db.py
```

### Step 5: (Optional) Set or Reset Account Passwords
To securely set or reset a password for any account using masked input:
```powershell
python reset_password.py admin@civicfix.com
```

---

## 5. Running the Application

Start the Flask server:
```powershell
python app.py
```
Open your web browser and navigate to:
**`http://127.0.0.1:5000`**

### Pre-configured Demo Accounts:
- **Admin Portal (`/admin-login`):**
  - Email: `admin@civicfix.com`
  - Password: `Admin@CivicFix2026`
- **Roadside Engineering Department (`/department-login`):**
  - Email: `roads@civicfix.com`
  - Password: `Roads@CivicFix2026`
- **Stormwater & Drain Department (`/department-login`):**
  - Email: `stormwater@civicfix.com`
  - Password: `Storm@CivicFix2026`
- **Solid Waste Management Department (`/department-login`):**
  - Email: `waste@civicfix.com`
  - Password: `Waste@CivicFix2026`
- **Citizen Account (`/citizen-login`):**
  - Email: `sharvanireddy678@gmail.com`
  - Password: `Admin@123`
  - *(Or click "Register" on the homepage to register a new citizen account)*

---

## 6. Running Automated Tests

### 1. End-to-End System Workflow Tests:
Tests all roles, complaint submission, queue isolation, status progression, proof upload, and MySQL persistence:
```powershell
python test_system_workflow.py
```

### 2. AI Recommendation & Priority Engine Tests:
Verifies offline AI routing rules, priority scoring, and review flags:
```powershell
python test_ai_engine.py
```

---

## 7. Troubleshooting & Common Issues

1. **Department Login Fails:**
   - Confirm MySQL service is running (`net start MySQL80` or via Services).
   - Ensure `MYSQL_DATABASE=civicfix_friendcopy` in `.env`.
   - Run `python reset_password.py <email>` to set a known password.
2. **Missing Uploads or 404 on Images:**
   - Images are served via Flask route `/uploads/<filename>`.
   - Confirm the `uploads/` directory exists in the project root.
3. **Database Connection Refused:**
   - Verify MySQL user credentials in `.env`. Test with:
     ```powershell
     python -c "from app import test_db; print(test_db())"
     ```
