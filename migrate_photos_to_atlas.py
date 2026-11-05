"""CivicFix MongoDB Atlas Migration Script.

Transfers all photographs and completion proofs stored in local MongoDB GridFS
(civicfix_photos) directly to a remote MongoDB Atlas cluster for 24/7 cloud hosting.

Usage:
    python migrate_photos_to_atlas.py "<YOUR_MONGODB_ATLAS_CONNECTION_STRING>"
"""
import sys
import gridfs
from pymongo import MongoClient

LOCAL_URI = "mongodb://127.0.0.1:27017/"
DB_NAME = "civicfix_photos"


def migrate_to_atlas(atlas_uri):
    print(f"Connecting to Local MongoDB: {LOCAL_URI}...")
    local_client = MongoClient(LOCAL_URI, serverSelectionTimeoutMS=3000)
    local_db = local_client[DB_NAME]
    local_fs = gridfs.GridFS(local_db)

    print("Connecting to MongoDB Atlas...")
    atlas_client = MongoClient(atlas_uri, serverSelectionTimeoutMS=10000)
    atlas_client.admin.command("ping")
    atlas_db = atlas_client[DB_NAME]
    atlas_fs = gridfs.GridFS(atlas_db)
    print("Successfully connected to MongoDB Atlas!")

    # Count local files
    files = list(local_fs.find())
    total = len(files)
    print(f"Found {total} photos in local MongoDB GridFS.")

    migrated = 0
    skipped = 0

    for idx, f in enumerate(files, 1):
        filename = f.filename
        content_type = getattr(f, "content_type", None) or (f.metadata.get("content_type") if f.metadata else "image/jpeg")
        metadata = f.metadata or {}

        # Check if already exists in Atlas
        existing = atlas_fs.find_one({"filename": filename})
        if existing:
            print(f"[{idx}/{total}] Already exists in Atlas: {filename}")
            skipped += 1
            continue

        file_bytes = f.read()
        atlas_fs.put(
            file_bytes,
            filename=filename,
            content_type=content_type,
            metadata=metadata
        )
        print(f"[{idx}/{total}] Migrated: {filename} ({len(file_bytes)} bytes)")
        migrated += 1

    print("\n--- Migration Complete ---")
    print(f"Total: {total} | Migrated: {migrated} | Skipped/Existing: {skipped}")
    print(f"Atlas database '{DB_NAME}' now has all photos.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Error: Missing MongoDB Atlas URI.")
        print("Usage: python migrate_photos_to_atlas.py \"mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/\"")
        sys.exit(1)

    target_uri = sys.argv[1].strip()
    migrate_to_atlas(target_uri)
