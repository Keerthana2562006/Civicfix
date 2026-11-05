"""Integration test for MongoDB GridFS Photo Storage in CivicFix."""
import io
import os
import unittest
from app import app, get_db_connection
from mongo_storage import get_mongo_fs, get_photo_from_mongo, get_mongo_photo_stats

class MongoPhotoStorageTests(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_mongodb_connection_and_stats(self):
        fs = get_mongo_fs()
        self.assertIsNotNone(fs, "MongoDB GridFS must be connected")
        stats = get_mongo_photo_stats()
        self.assertEqual(stats["status"], "connected")
        self.assertEqual(stats["database"], "civicfix_photos")
        self.assertGreater(stats["count"], 0)
        print("✓ Test 1: MongoDB GridFS connection and stats verified:", stats)

    def test_complaint_photo_stored_in_mongo(self):
        # 1. Citizen submits complaint with dummy image
        with self.client.session_transaction() as sess:
            sess["citizen_id"] = 1
            sess["citizen_name"] = "Sharvani"
            sess["citizen_email"] = "sharvanireddy678@gmail.com"
            sess["role"] = "citizen"

        raw_test_bytes = b"CIVICFIX_TEST_POTHOLE_PHOTO_BYTES_PNG_123456789"
        test_img = (io.BytesIO(raw_test_bytes), "mongo_test_pothole.png")

        res_submit = self.client.post("/submit-complaint", data={
            "category": "Roads & Potholes",
            "description": "MongoDB photo integration test complaint.",
            "location": "12.9716, 77.5946 - Indiranagar",
            "image": test_img,
        }, content_type="multipart/form-data", follow_redirects=False)

        self.assertEqual(res_submit.status_code, 302)

        # 2. Query MySQL for the latest complaint
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT complaint_id, image_path, status, department FROM complaints WHERE citizen_id = 1 ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        conn.close()

        self.assertIsNotNone(row)
        c_id = row["complaint_id"]
        img_filename = os.path.basename(row["image_path"])

        # 3. Verify photo is stored in MongoDB GridFS
        mongo_res = get_photo_from_mongo(img_filename)
        self.assertIsNotNone(mongo_res, f"Photo {img_filename} must exist in MongoDB GridFS")
        data, content_type = mongo_res
        self.assertEqual(data, raw_test_bytes)
        print(f"✓ Test 2: Original complaint photo '{img_filename}' verified in MongoDB GridFS ({len(data)} bytes).")

        # 4. Verify photo streaming via HTTP /uploads/ route
        res_http = self.client.get(f"/uploads/{img_filename}")
        self.assertEqual(res_http.status_code, 200)
        self.assertEqual(res_http.data, raw_test_bytes)
        print(f"✓ Test 3: HTTP route /uploads/{img_filename} streamed identical bytes directly from MongoDB.")

        # 5. Department uploads resolution proof
        with self.client.session_transaction() as sess:
            sess.clear()
            sess["department_id"] = 3
            sess["department_name"] = "Roadside Engineering Department"
            sess["department_email"] = "roads@civicfix.com"
            sess["role"] = "department"

        # Mark in progress first
        self.client.post("/department-update-status", data={
            "complaint_id": c_id,
            "status": "In Progress"
        })

        # Upload completion proof
        proof_raw_bytes = b"CIVICFIX_PROOF_COMPLETION_PHOTO_BYTES_PNG_987654321"
        proof_img = (io.BytesIO(proof_raw_bytes), "mongo_proof.png")

        res_proof = self.client.post("/department-upload-proof", data={
            "complaint_id": c_id,
            "proof_file": proof_img,
            "resolution_notes": "Road surface repaired with cold mix asphalt."
        }, content_type="multipart/form-data", follow_redirects=False)

        self.assertEqual(res_proof.status_code, 302)

        # 6. Query DB for resolution proof filename
        conn = get_db_connection()
        conn.autocommit = True
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT resolution_proof FROM complaints WHERE complaint_id = %s", (c_id,))
        proof_row = cur.fetchone()
        cur.close()
        conn.close()

        proof_fname = proof_row["resolution_proof"]
        self.assertIsNotNone(proof_fname)

        # 7. Verify resolution proof in MongoDB GridFS
        mongo_proof_res = get_photo_from_mongo(proof_fname)
        self.assertIsNotNone(mongo_proof_res, f"Proof photo {proof_fname} must exist in MongoDB GridFS")
        proof_data, proof_mime = mongo_proof_res
        self.assertEqual(proof_data, proof_raw_bytes)
        print(f"✓ Test 4: Completion proof photo '{proof_fname}' verified in MongoDB GridFS ({len(proof_data)} bytes).")

        # 8. Verify proof streaming via HTTP /uploads/
        res_proof_http = self.client.get(f"/uploads/{proof_fname}")
        self.assertEqual(res_proof_http.status_code, 200)
        self.assertEqual(res_proof_http.data, proof_raw_bytes)
        print(f"✓ Test 5: HTTP route /uploads/{proof_fname} streamed proof photo directly from MongoDB.")


if __name__ == "__main__":
    unittest.main()
