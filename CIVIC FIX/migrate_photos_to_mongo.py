"""Migrates existing image files in uploads/ into MongoDB GridFS."""
import os
from mongo_storage import save_photo_to_mongo, get_mongo_photo_stats

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")

def migrate_all():
    if not os.path.exists(UPLOAD_FOLDER):
        print("Uploads folder not found.")
        return

    files = [f for f in os.listdir(UPLOAD_FOLDER) if os.path.isfile(os.path.join(UPLOAD_FOLDER, f))]
    print(f"Found {len(files)} files in {UPLOAD_FOLDER} to migrate to MongoDB GridFS...")

    migrated = 0
    for fname in files:
        fpath = os.path.join(UPLOAD_FOLDER, fname)
        try:
            with open(fpath, "rb") as fp:
                data = fp.read()
            photo_type = "proof" if fname.startswith("proof_") else "original_complaint"
            fid = save_photo_to_mongo(data, fname, {"type": photo_type, "migrated_from_disk": True})
            if fid:
                migrated += 1
                print(f"  ✓ Migrated {fname} -> Mongo ID {fid}")
            else:
                print(f"  ✗ Failed to migrate {fname}")
        except Exception as e:
            print(f"  ✗ Error migrating {fname}: {e}")

    print(f"\nMigration complete: {migrated}/{len(files)} photos stored in MongoDB GridFS.")
    print("Storage stats:", get_mongo_photo_stats())

if __name__ == "__main__":
    migrate_all()
