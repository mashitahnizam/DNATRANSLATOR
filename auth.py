import hashlib
import os
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("MONGO_DATABASE", "dna_translation_db")


def get_db_client():
    try:
        return MongoClient(MONGO_URI)
    except Exception as e:
        print(f"Database Connection Error: {e}")
        return None


def make_hashes(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def add_user(username, email, password, role="user"):
    client = get_db_client()

    if client is None:
        return False, "Database connection failed."

    db = client[DATABASE_NAME]
    users_col = db["users"]

    if users_col.find_one({"username": username}):
        client.close()
        return False, "Username already taken."

    if users_col.find_one({"email": email}):
        client.close()
        return False, "Email already registered."

    user_document = {
        "username": username,
        "email": email,
        "password": make_hashes(password),
        "role": role,
        "history": []
    }

    try:
        users_col.insert_one(user_document)
        client.close()
        return True, "Success"

    except Exception as e:
        client.close()
        return False, str(e)


def login_user(username, password):
    client = get_db_client()

    if client is None:
        return False

    db = client[DATABASE_NAME]
    users_col = db["users"]

    user = users_col.find_one({"username": username})

    if not user:
        client.close()
        return False

    entered_hash = make_hashes(password)
    stored_password = user.get("password", "")

    if stored_password == entered_hash:
        client.close()
        return True

    double_hash = make_hashes(entered_hash)

    if stored_password == double_hash:
        users_col.update_one(
            {"username": username},
            {"$set": {"password": entered_hash}}
        )

        client.close()
        return True

    client.close()
    return False


def get_user_role(username):
    client = get_db_client()

    if client is None:
        return "user"

    db = client[DATABASE_NAME]
    users_col = db["users"]

    user = users_col.find_one({"username": username}, {"role": 1})

    client.close()

    if not user:
        return "user"

    return user.get("role", "user")


def verify_email_exists(email):
    client = get_db_client()

    if client is None:
        return None

    db = client[DATABASE_NAME]
    user = db["users"].find_one({"email": email})

    client.close()

    return user if user else None


def update_password(email, new_password):
    client = get_db_client()

    if client is None:
        return False

    db = client[DATABASE_NAME]
    hashed_password = make_hashes(new_password)

    result = db["users"].update_one(
        {"email": email},
        {"$set": {"password": hashed_password}}
    )

    client.close()

    return result.modified_count > 0
