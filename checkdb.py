import sqlite3

conn = sqlite3.connect("criminals.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS criminals(
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT,
age INTEGER,
crime TEXT,
image TEXT
)
""")

conn.commit()
conn.close()