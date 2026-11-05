from app import app, get_db_connection
import secrets

client = app.test_client()
app.config['TESTING'] = True

test_email = f"testuser_{secrets.token_hex(4)}@example.com"
print(f"Testing registration and OTP for {test_email}...")

# 1. Register
res_reg = client.post('/citizen-register', data={
    'full_name': 'Test Citizen',
    'email': test_email,
    'phone': '98' + str(secrets.randbelow(90000000) + 10000000),
    'password': 'Password@123',
    'confirm_password': 'Password@123'
})
assert res_reg.status_code == 200
assert b'Verify Your Email' in res_reg.data
print("1. Registration form submitted successfully, rendered verify_otp.html")

# 2. Check pending registration in DB
conn = get_db_connection()
conn.autocommit = True
cur = conn.cursor(dictionary=True)
cur.execute("SELECT id, otp_code, attempts FROM pending_registrations WHERE email = %s", (test_email,))
pending = cur.fetchone()
assert pending is not None
otp = pending["otp_code"]
print(f"2. Pending registration verified in DB: OTP = {otp}")

# 3. Test wrong OTP
res_wrong = client.post('/verify-otp', data={'email': test_email, 'otp': '000000'})
assert b'Incorrect OTP code' in res_wrong.data
print("3. Wrong OTP correctly rejected and error displayed")

# 4. Test Resend OTP
res_resend = client.post('/resend-otp', data={'email': test_email})
assert res_resend.status_code == 200
assert b'fresh OTP' in res_resend.data or b'sent' in res_resend.data
cur.execute("SELECT otp_code, attempts FROM pending_registrations WHERE email = %s", (test_email,))
pending_new = cur.fetchone()
new_otp = pending_new["otp_code"]
assert pending_new["attempts"] == 0
print(f"4. Resend OTP succeeded. New OTP: {new_otp}")

# 5. Verify with correct OTP
res_verify = client.post('/verify-otp', data={'email': test_email, 'otp': new_otp}, follow_redirects=True)
assert res_verify.status_code == 200
assert b'verified successfully' in res_verify.data or b'Login' in res_verify.data

# 6. Check user in DB
cur.execute("SELECT id, full_name, email, is_verified FROM users WHERE email = %s", (test_email,))
new_user = cur.fetchone()
assert new_user is not None
assert new_user["is_verified"] == 1
print(f"5. User activated and verified in DB: ID = {new_user['id']}")

# Clean up test user
cur.execute("DELETE FROM users WHERE id = %s", (new_user["id"],))
cur.close()
conn.close()
print("ALL OTP & VERIFICATION TESTS PASSED SUCCESSFULLY!")
