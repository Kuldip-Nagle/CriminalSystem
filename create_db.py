import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = "criminals.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS criminals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    age INTEGER,
    gender TEXT,
    address TEXT,
    case_number TEXT,
    arrest_date TEXT,
    status TEXT,
    crime TEXT,
    image TEXT,
    photo BLOB,
    encoding BLOB
)
""")

password = generate_password_hash("admin123")
cursor.execute("INSERT OR IGNORE INTO users (username,password) VALUES (?,?)", ("admin", password))

sample_criminals = [
    {
        "name": "Ramesh Kumar",
        "age": 34,
        "gender": "Male",
        "address": "Sector 12, Mumbai",
        "case_number": "CASE-2026-001",
        "arrest_date": "2026-03-22",
        "status": "Arrested",
        "crime": "Theft",
    },
    {
        "name": "Anjali Singh",
        "age": 28,
        "gender": "Female",
        "address": "MG Road, Bengaluru",
        "case_number": "CASE-2026-002",
        "arrest_date": "2026-02-11",
        "status": "At Large",
        "crime": "Burglary",
    },
    {
        "name": "Vikram Patel",
        "age": 41,
        "gender": "Male",
        "address": "Kalbadevi, Mumbai",
        "case_number": "CASE-2026-003",
        "arrest_date": "2025-12-30",
        "status": "Released",
        "crime": "Fraud",
    },
    {
        "name": "Sahana Reddy",
        "age": 36,
        "gender": "Female",
        "address": "Banjara Hills, Hyderabad",
        "case_number": "CASE-2026-004",
        "arrest_date": "2026-01-15",
        "status": "Arrested",
        "crime": "Assault",
    },
]

for criminal in sample_criminals:
    cursor.execute("SELECT 1 FROM criminals WHERE case_number = ?", (criminal["case_number"],))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO criminals (name, age, gender, address, case_number, arrest_date, status, crime, image, photo, encoding) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                criminal["name"],
                criminal["age"],
                criminal["gender"],
                criminal["address"],
                criminal["case_number"],
                criminal["arrest_date"],
                criminal["status"],
                criminal["crime"],
                None,
                None,
                None,
            ),
        )

conn.commit()
conn.close()
print("Database ready with demo criminal records")