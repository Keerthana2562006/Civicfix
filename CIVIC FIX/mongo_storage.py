"""CivicFix MongoDB Photo Storage Engine.

Uses MongoDB GridFS for binary photograph storage:
- Citizen original complaint photos
- Department field completion proof photos
Retains MySQL for relational structured data (users, complaints, audit logs).
"""
import io
import mimetypes
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "civicfix_photos")

_mongo_client = None
_grid_fs = None


def get_mongo_fs():
    """Lazily initializes and returns MongoDB database and GridFS instance."""
    global _mongo_client, _grid_fs
    if _grid_fs is not None:
        try:
            # Quick ping to confirm live connection
            _mongo_client.admin.command("ping")
            return _grid_fs
        except Exception:
            _mongo_client = None
            _grid_fs = None

    try:
        from pymongo import MongoClient
        import gridfs

        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2500)
        _mongo_client.admin.command("ping")
        db = _mongo_client[MONGO_DB_NAME]
        _grid_fs = gridfs.GridFS(db)
        return _grid_fs
    except Exception as e:
        print(f"[MONGO WARNING] Could not connect to MongoDB at {MONGO_URI}: {e}")
        return None


def save_photo_to_mongo(file_obj, filename, metadata=None):
    """
    Saves an uploaded photo to MongoDB GridFS.
    file_obj: werkzeug.datastructures.FileStorage or bytes or file-like object.
    Returns: file_id (str) or None on failure.
    """
    fs = get_mongo_fs()
    if fs is None:
        return None

    try:
        # Determine content type
        content_type = getattr(file_obj, "content_type", None)
        if not content_type:
            content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            content_type = "image/jpeg"

        # Read binary content
        if hasattr(file_obj, "read"):
            file_obj.seek(0)
            data = file_obj.read()
            # Reset seek position for downstream consumers if needed
            file_obj.seek(0)
        elif isinstance(file_obj, (bytes, bytearray)):
            data = bytes(file_obj)
        else:
            raise ValueError("Unsupported file_obj type for MongoDB photo storage.")

        meta = {
            "upload_timestamp": datetime.now().isoformat(),
            "size_bytes": len(data),
        }
        if metadata and isinstance(metadata, dict):
            meta.update(metadata)

        # Remove existing file with identical filename if present
        existing = fs.find_one({"filename": filename})
        if existing:
            fs.delete(existing._id)

        file_id = fs.put(
            data,
            filename=filename,
            content_type=content_type,
            metadata=meta,
        )
        return str(file_id)

    except Exception as err:
        print(f"[MONGO ERROR] Failed to save photo '{filename}' to MongoDB: {err}")
        return None


def get_photo_from_mongo(filename):
    """
    Retrieves photo bytes and content_type from MongoDB GridFS by filename.
    Returns: (bytes_data, content_type) or None if not found.
    """
    fs = get_mongo_fs()
    if fs is None:
        return None

    try:
        grid_file = fs.find_one({"filename": filename})
        if not grid_file:
            return None
        data = grid_file.read()
        meta = getattr(grid_file, "metadata", {}) or {}
        content_type = meta.get("content_type") or getattr(grid_file, "content_type", "image/jpeg")
        return data, content_type
    except Exception as err:
        print(f"[MONGO ERROR] Failed to retrieve photo '{filename}' from MongoDB: {err}")
        return None


def get_mongo_photo_stats():
    """Returns total photo count and total storage footprint in MongoDB GridFS."""
    fs = get_mongo_fs()
    if fs is None:
        return {"status": "offline", "count": 0, "size_mb": 0.0}

    try:
        cursor = fs.find()
        count = 0
        total_bytes = 0
        for f in cursor:
            count += 1
            total_bytes += getattr(f, "length", 0)
        return {
            "status": "connected",
            "database": MONGO_DB_NAME,
            "count": count,
            "size_mb": round(total_bytes / (1024 * 1024), 2),
        }
    except Exception as err:
        return {"status": "error", "message": str(err), "count": 0, "size_mb": 0.0}
