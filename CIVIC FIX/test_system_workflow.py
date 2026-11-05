#!/usr/bin/env python3
"""
CivicFix End-to-End System Workflow Integration Test.
Tests all roles, authentication, workflow states, and MySQL persistence.
"""
import io
import os
import unittest
from app import app, get_db_connection

class CivicFixWorkflowTests(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

    def test_01_database_connectivity(self):
        """Test MySQL connection and table schemas."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT DATABASE() as db;")
        db_name = cursor.fetchone()["db"]
        self.assertIn("civicfix_friendcopy", db_name)

        cursor.execute("SHOW TABLES;")
        tables = [list(r.values())[0] for r in cursor.fetchall()]
        self.assertIn("users", tables)
        self.assertIn("complaints", tables)
        self.assertIn("complaint_history", tables)
        cursor.close()
        conn.close()
        print("✓ Test 1 Passed: Connected to civicfix_friendcopy with all required tables.")

    def test_02_authentication_checks(self):
        """Test Admin, Department, and Citizen login authentication."""
        from werkzeug.security import generate_password_hash
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor(dictionary=True)
        test_admin_email = "test_admin_auth@civicfix.com"
        test_admin_pwd = "TestAdmin@2026"
        cur.execute("DELETE FROM users WHERE email = %s", (test_admin_email,))
        cur.execute(
            "INSERT INTO users (full_name, email, phone, password_hash, role, is_verified) "
            "VALUES (%s, %s, %s, %s, 'admin', 1)",
            ("Test Admin", test_admin_email, "9999900001", generate_password_hash(test_admin_pwd))
        )
        cur.close()
        conn.close()

        try:
            # 1. Admin Login (Valid)
            res = self.client.post("/admin-login", data={
                "email": test_admin_email,
                "password": test_admin_pwd
            }, follow_redirects=False)
            self.assertEqual(res.status_code, 302)
            self.assertIn("/admin-dashboard", res.location)

            # 2. Invalid Admin Password
            res_bad = self.client.post("/admin-login", data={
                "email": test_admin_email,
                "password": "WrongPassword123"
            })
            self.assertIn(b"Invalid admin email or password", res_bad.data)

            # 3. Department Login
            res_dept = self.client.post("/department-login", data={
                "email": "roads@civicfix.com",
                "password": "Roads@CivicFix2026"
            }, follow_redirects=False)
            self.assertEqual(res_dept.status_code, 302)
            self.assertIn("/department-dashboard", res_dept.location)

            # 4. Citizen Login
            res_cit = self.client.post("/citizen-login", data={
                "email": "sharvanireddy678@gmail.com",
                "password": "Admin@123"
            }, follow_redirects=False)
            self.assertEqual(res_cit.status_code, 302)
            self.assertIn("/citizen-dashboard", res_cit.location)

            print("✓ Test 2 Passed: Admin, Department, and Citizen authentication verified.")
        finally:
            c = get_db_connection()
            c.autocommit = True
            cr = c.cursor()
            cr.execute("DELETE FROM users WHERE email = %s", (test_admin_email,))
            cr.close()
            c.close()

    def test_03_complete_complaint_lifecycle(self):
        """
        Complete end-to-end workflow:
        Citizen submits -> AI recommends -> Pending Admin approval ->
        Admin approves & assigns -> Department starts work ->
        Department uploads completion proof -> Admin verifies -> Citizen tracks.
        """
        # Step 1: Citizen logs in
        with self.client.session_transaction() as sess:
            sess["citizen_id"] = 1
            sess["citizen_name"] = "Sharvani"
            sess["citizen_email"] = "sharvanireddy678@gmail.com"
            sess["role"] = "citizen"

        # Step 2: Citizen submits complaint with image
        test_img = (io.BytesIO(b"fake image bytes for pothole testing"), "test_pothole.jpg")
        res_submit = self.client.post("/submit-complaint", data={
            "category": "Roads & Potholes",
            "description": "Dangerous deep pothole near junction causing bike accidents.",
            "location": "12.9716, 77.5946 - MG Road junction",
            "image": test_img
        }, content_type="multipart/form-data", follow_redirects=False)

        self.assertEqual(res_submit.status_code, 302)

        # Verify complaint stored in DB with department assigned by AI based on category
        conn = get_db_connection()
        conn.autocommit = True
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT complaint_id, status, department, ai_department, ai_priority, image_path, assignment_source
            FROM complaints
            WHERE citizen_id = 1
            ORDER BY created_at DESC
            LIMIT 1
        """)
        complaint = cursor.fetchone()
        self.assertIsNotNone(complaint)
        c_id = complaint["complaint_id"]

        self.assertEqual(complaint["status"], "Assigned")
        self.assertEqual(complaint["department"], "BBMP Roads")
        self.assertEqual(complaint["ai_department"], "BBMP Roads")
        self.assertEqual(complaint["assignment_source"], "AI")
        self.assertTrue(os.path.exists(complaint["image_path"]))
        print(f"✓ Step 1 & 2 Passed: Complaint {c_id} automatically assigned to BBMP Roads by AI based on category.")

        # Step 3: Check Department queue isolation (Assigned dept sees it; other dept does NOT)
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["department_id"] = 4
            sess["department_name"] = "Solid Waste Management Department"
            sess["department_email"] = "waste@civicfix.com"
            sess["role"] = "department"

        res_other_dept = self.client.get("/department-dashboard")
        self.assertNotIn(c_id.encode(), res_other_dept.data)
        print("✓ Step 3 Passed: Isolated from other departments (Waste dept cannot see Roads complaint).")

        # Step 4: Admin reviews AI assignment on Admin Dashboard
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["admin_id"] = 2
            sess["admin_name"] = "CivicFix Admin"
            sess["admin_email"] = "admin@civicfix.com"
            sess["role"] = "admin"

        res_admin_view = self.client.get("/admin-dashboard")
        self.assertIn(c_id.encode(), res_admin_view.data)
        self.assertIn(b"BBMP Roads", res_admin_view.data)

        # Admin can reassign or confirm assignment
        res_assign = self.client.post("/admin-assign", data={
            "complaint_id": c_id,
            "department": "BBMP Roads"
        }, follow_redirects=False)
        self.assertEqual(res_assign.status_code, 302)

        cursor.execute("SELECT status, department FROM complaints WHERE complaint_id = %s", (c_id,))
        updated_c = cursor.fetchone()
        self.assertEqual(updated_c["status"], "Assigned")
        self.assertEqual(updated_c["department"], "BBMP Roads")
        print("✓ Step 4 Passed: Admin reviewed and confirmed assignment to BBMP Roads.")

        # Step 5: Assigned department sees complaint and starts work
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["department_id"] = 3
            sess["department_name"] = "BBMP Roads Department"
            sess["department_email"] = "roads@civicfix.com"
            sess["role"] = "department"

        res_dept_view2 = self.client.get("/department-dashboard")
        self.assertIn(c_id.encode(), res_dept_view2.data)

        # Department starts work
        res_start = self.client.post("/department-update-status", data={
            "complaint_id": c_id,
            "status": "In Progress"
        }, follow_redirects=False)
        self.assertEqual(res_start.status_code, 302)

        cursor.execute("SELECT status FROM complaints WHERE complaint_id = %s", (c_id,))
        self.assertEqual(cursor.fetchone()["status"], "In Progress")
        print("✓ Step 5 Passed: Department transitioned complaint to 'In Progress'.")

        # Step 6: Department uploads resolution proof
        proof_img = (io.BytesIO(b"fake resolution proof image after fixing"), "proof_fixed.jpg")
        res_proof = self.client.post("/department-upload-proof", data={
            "complaint_id": c_id,
            "proof_file": proof_img,
            "resolution_notes": "Filled pothole with cold asphalt mix and roller compacted."
        }, content_type="multipart/form-data", follow_redirects=False)
        self.assertEqual(res_proof.status_code, 302)

        cursor.execute("SELECT status, proof_status, resolution_proof, resolution_notes FROM complaints WHERE complaint_id = %s", (c_id,))
        comp_proof = cursor.fetchone()
        self.assertEqual(comp_proof["status"], "Resolved")
        self.assertEqual(comp_proof["proof_status"], "Pending")
        self.assertIsNotNone(comp_proof["resolution_proof"])
        print("✓ Step 6 Passed: Department uploaded proof, status is 'Resolved', proof is 'Pending'.")

        # Step 7: Admin verifies proof
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["admin_id"] = 2
            sess["admin_name"] = "CivicFix Admin"
            sess["admin_email"] = "admin@civicfix.com"
            sess["role"] = "admin"

        res_verify = self.client.post("/admin-verify-proof", data={
            "complaint_id": c_id
        }, follow_redirects=False)
        self.assertEqual(res_verify.status_code, 302)

        cursor.execute("SELECT status, proof_status FROM complaints WHERE complaint_id = %s", (c_id,))
        comp_verified = cursor.fetchone()
        self.assertEqual(comp_verified["status"], "Resolved")
        self.assertEqual(comp_verified["proof_status"], "Verified")
        print("✓ Step 7 Passed: Admin verified proof.")

        # Step 8: Citizen tracks verified complaint
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["citizen_id"] = 1
            sess["citizen_name"] = "Sharvani"
            sess["citizen_email"] = "sharvanireddy678@gmail.com"
            sess["role"] = "citizen"

        res_cit_view = self.client.get("/citizen-dashboard")
        self.assertIn(c_id.encode(), res_cit_view.data)
        self.assertIn(b"Verified by Admin", res_cit_view.data)
        print("✓ Step 8 Passed: Citizen sees complaint verified and resolved.")

        # Verify audit history table records
        cursor.execute("SELECT to_status, actor_role FROM complaint_history WHERE complaint_id = %s ORDER BY id", (c_id,))
        history = cursor.fetchall()
        self.assertTrue(len(history) >= 4)
        print(f"✓ Step 9 Passed: Audit history recorded {len(history)} state transitions.")

        cursor.close()
        conn.close()

if __name__ == "__main__":
    unittest.main()
