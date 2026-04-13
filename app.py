from flask import Flask, render_template, request, redirect, session, flash, url_for, jsonify, Response
import sqlite3
import os
import io
import imghdr
import pickle
import base64
import uuid
import numpy as np
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret123"

FACE_RECOGNITION_AVAILABLE = True
face_recognition = None
cv2 = None
try:
    import face_recognition
    import cv2
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False

known_faces = []

# ==============================
# CONFIG
# ==============================
UPLOAD_FOLDER = "static/uploads"
DB_PATH = "criminals.db"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload size

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==============================
# DATABASE
# ==============================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_case_number(case_number):
    if not case_number:
        return ""
    normalized = case_number.strip().upper()
    if normalized == "CASE":
        return "CASE-1"
    if normalized.startswith("CASE-"):
        return normalized
    if normalized.startswith("CASE"):
        suffix = normalized[4:].strip()
        suffix = suffix.lstrip("- ")
        return f"CASE-{suffix}" if suffix else "CASE-1"
    normalized = normalized.lstrip("- ")
    return f"CASE-{normalized}"


def make_case_number_unique(case_number, conn):
    base = case_number
    existing = conn.execute("SELECT 1 FROM criminals WHERE case_number = ?", (case_number,)).fetchone()
    if not existing:
        return case_number

    suffix = 1
    while True:
        candidate = f"{base}-{suffix}"
        if not conn.execute("SELECT 1 FROM criminals WHERE case_number = ?", (candidate,)).fetchone():
            return candidate
        suffix += 1


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    ''')

    cursor.execute('''
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
    ''')

    existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(criminals)").fetchall()]
    for column_def in [
        "gender TEXT",
        "address TEXT",
        "case_number TEXT",
        "arrest_date TEXT",
        "status TEXT",
        "photo BLOB",
        "encoding BLOB"
    ]:
        column_name = column_def.split()[0]
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE criminals ADD COLUMN {column_def}")

    cursor.execute(
        "INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
        ("admin", generate_password_hash("admin123"))
    )

    conn.commit()
    conn.close()

init_db()


def refresh_known_faces():
    global known_faces
    known_faces = []

    if not FACE_RECOGNITION_AVAILABLE:
        return

    conn = get_db()
    criminals = conn.execute("SELECT id, name, age, gender, address, case_number, arrest_date, status, crime, image, photo, encoding FROM criminals").fetchall()
    conn.close()

    for criminal in criminals:
        encoding_blob = criminal["encoding"]
        face_encoding = None

        if encoding_blob is not None:
            try:
                face_encoding = pickle.loads(encoding_blob)
            except Exception:
                face_encoding = None

        if face_encoding is None and criminal["photo"] is not None:
            try:
                photo_bytes = criminal["photo"]
                np_image = np.frombuffer(photo_bytes, dtype=np.uint8)
                opencv_image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)
                if opencv_image is not None:
                    rgb_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)
                    encodings = face_recognition.face_encodings(rgb_image)
                    if encodings:
                        face_encoding = encodings[0]
                        try:
                            conn = get_db()
                            conn.execute("UPDATE criminals SET encoding=? WHERE id=?", (sqlite3.Binary(pickle.dumps(face_encoding, protocol=pickle.HIGHEST_PROTOCOL)), criminal["id"]))
                            conn.commit()
                            conn.close()
                        except Exception:
                            pass
            except Exception:
                face_encoding = None

        if face_encoding is None:
            continue

        known_faces.append({
            "id": criminal["id"],
            "name": criminal["name"],
            "age": criminal["age"],
            "gender": criminal["gender"],
            "address": criminal["address"],
            "case_number": criminal["case_number"],
            "arrest_date": criminal["arrest_date"],
            "status": criminal["status"],
            "crime": criminal["crime"],
            "image": criminal["image"],
            "encoding": face_encoding,
        })

refresh_known_faces()

@app.after_request
def add_cache_control(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["Vary"] = "Cookie, Authorization"
    return response

# ==============================
# ROUTES
# ==============================

@app.route("/")
def landing():
    return render_template("landing.html")


# ==============================
# LOGIN
# ==============================
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=?",
        (username,)
    ).fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        session["user"] = user["username"]
        return redirect("/dashboard")

    flash("Invalid username or password", "danger")
    return redirect("/")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


# ==============================
# DASHBOARD
# ==============================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM criminals").fetchone()[0]
    conn.close()

    return render_template("dashboard.html", total=total)


# ==============================
# ADD CRIMINAL
# ==============================
@app.route("/add_criminal", methods=["GET", "POST"])
def add_criminal():
    if "user" not in session:
        return redirect("/")

    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        address = request.form.get("address")
        case_number = request.form.get("case_number")
        arrest_date = request.form.get("arrest_date")
        status = request.form.get("status")
        crime = request.form.get("crime")
        image = request.files.get("image")
        captured_image_data = request.form.get("captured_image_data")

        # ✅ Validation
        if not name or not age or not crime or not case_number or not arrest_date:
            flash("Please fill in all required fields", "danger")
            return redirect("/add_criminal")

        case_number = normalize_case_number(case_number)
        conn = get_db()
        case_number = make_case_number_unique(case_number, conn)
        conn.close()

        try:
            age = int(age)
        except (TypeError, ValueError):
            flash("Age must be a valid number", "danger")
            return redirect("/add_criminal")

        # ✅ Secure file upload or captured photo
        if (not image or image.filename == "") and not captured_image_data:
            flash("Please upload a photo for recognition", "danger")
            return redirect("/add_criminal")

        image_bytes = None
        filename = None

        if image and image.filename != "":
            filename = secure_filename(image.filename)
            if filename == "":
                flash("Invalid image filename", "danger")
                return redirect("/add_criminal")
            filename = f"{uuid.uuid4().hex}_{filename}"
            try:
                image_bytes = image.read()
            except Exception:
                flash("Failed to read uploaded photo", "danger")
                return redirect("/add_criminal")
        else:
            try:
                _, payload = captured_image_data.split(",", 1) if "," in captured_image_data else (None, captured_image_data)
                image_bytes = base64.b64decode(payload)
                filename = f"{uuid.uuid4().hex}_capture.png"
            except Exception:
                flash("Invalid captured image data", "danger")
                return redirect("/add_criminal")

        if image_bytes is None:
            flash("Unable to process the selected photo", "danger")
            return redirect("/add_criminal")

        upload_path = os.path.join(UPLOAD_FOLDER, filename)

        encoding_blob = None
        try:
            with open(upload_path, "wb") as f:
                f.write(image_bytes)
            photo_blob = sqlite3.Binary(image_bytes)

            if FACE_RECOGNITION_AVAILABLE:
                np_image = np.frombuffer(image_bytes, dtype=np.uint8)
                opencv_image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)
                if opencv_image is not None:
                    rgb_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)
                    encodings = face_recognition.face_encodings(rgb_image)
                    if encodings:
                        encoding_blob = sqlite3.Binary(pickle.dumps(encodings[0], protocol=pickle.HIGHEST_PROTOCOL))
        except Exception:
            flash("Failed to save uploaded photo", "danger")
            return redirect("/add_criminal")

        conn = get_db()
        conn.execute(
            "INSERT INTO criminals (name, age, gender, address, case_number, arrest_date, status, crime, image, photo, encoding) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, age, gender, address, case_number, arrest_date, status, crime, filename, photo_blob, encoding_blob)
        )
        conn.commit()
        conn.close()

        refresh_known_faces()

        flash("Criminal record added successfully", "success")
        return redirect("/dashboard")

    conn = get_db()
    names = [row["name"] for row in conn.execute("SELECT DISTINCT name FROM criminals WHERE name IS NOT NULL AND name != '' ORDER BY name").fetchall()]
    addresses = [row["address"] for row in conn.execute("SELECT DISTINCT address FROM criminals WHERE address IS NOT NULL AND address != '' ORDER BY address").fetchall()]
    case_numbers = [row["case_number"] for row in conn.execute("SELECT DISTINCT case_number FROM criminals WHERE case_number IS NOT NULL AND case_number != '' ORDER BY case_number").fetchall()]
    crimes = [row["crime"] for row in conn.execute("SELECT DISTINCT crime FROM criminals WHERE crime IS NOT NULL AND crime != '' ORDER BY crime").fetchall()]
    conn.close()

    return render_template(
        "add_criminal.html",
        names=names,
        addresses=addresses,
        case_numbers=case_numbers,
        crimes=crimes,
    )


# ==============================
# VIEW RECORDS + SEARCH
# ==============================
@app.route('/criminal_photo/<int:id>')
def criminal_photo(id):
    conn = get_db()
    criminal = conn.execute("SELECT photo FROM criminals WHERE id=?", (id,)).fetchone()
    conn.close()

    if not criminal or not criminal["photo"]:
        return Response(status=404)

    image_bytes = criminal["photo"]
    image_type = imghdr.what(None, image_bytes)
    mimetype = f"image/{image_type}" if image_type else "application/octet-stream"
    return Response(image_bytes, mimetype=mimetype)


@app.route("/records")
def records():
    if "user" not in session:
        return redirect("/")

    query = request.args.get("q")

    conn = get_db()

    if query:
        criminals = conn.execute(
            "SELECT * FROM criminals WHERE name LIKE ? OR crime LIKE ? OR case_number LIKE ? OR address LIKE ?",
            ('%' + query + '%', '%' + query + '%', '%' + query + '%', '%' + query + '%')
        ).fetchall()
    else:
        criminals = conn.execute("SELECT * FROM criminals").fetchall()

    conn.close()

    return render_template("records.html", criminals=criminals)


# ==============================
# DELETE RECORD
# ==============================
# ==============================
# SEARCH RECORDS
@app.route("/search")
def search():
    if "user" not in session:
        return redirect("/")

    query = request.args.get("q", "")
    status = request.args.get("status", "")
    gender = request.args.get("gender", "")
    crime = request.args.get("crime", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    conn = get_db()
    filters = []
    params = []

    if query:
        filters.append("(name LIKE ? OR crime LIKE ? OR case_number LIKE ? OR address LIKE ?)")
        term = f"%{query}%"
        params.extend([term, term, term, term])
    if status:
        filters.append("status = ?")
        params.append(status)
    if gender:
        filters.append("gender = ?")
        params.append(gender)
    if crime:
        filters.append("crime = ?")
        params.append(crime)
    if start_date:
        filters.append("arrest_date >= ?")
        params.append(start_date)
    if end_date:
        filters.append("arrest_date <= ?")
        params.append(end_date)

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""
    criminals = conn.execute(f"SELECT * FROM criminals {where_clause} ORDER BY arrest_date DESC", params).fetchall()

    statuses = [row["status"] for row in conn.execute("SELECT DISTINCT status FROM criminals WHERE status IS NOT NULL AND status != '' ORDER BY status").fetchall()]
    genders = [row["gender"] for row in conn.execute("SELECT DISTINCT gender FROM criminals WHERE gender IS NOT NULL AND gender != '' ORDER BY gender").fetchall()]
    crimes = [row["crime"] for row in conn.execute("SELECT DISTINCT crime FROM criminals WHERE crime IS NOT NULL AND crime != '' ORDER BY crime").fetchall()]
    conn.close()

    return render_template("search.html", criminals=criminals, statuses=statuses, genders=genders, crimes=crimes)


# ==============================
# DELETE RECORD
@app.route("/delete/<int:id>")
def delete(id):
    if "user" not in session:
        return redirect("/")

    conn = get_db()
    conn.execute("DELETE FROM criminals WHERE id=?", (id,))
    conn.commit()
    conn.close()

    flash("Record deleted", "warning")
    return redirect("/records")


# ==============================
# FACE RECOGNITION
@app.route("/recognize_image", methods=["POST"])
def recognize_image():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if not FACE_RECOGNITION_AVAILABLE:
        return jsonify({
            "error": "face_recognition library is not installed",
            "detail": "Install face_recognition and opencv-python on the server."
        }), 500

    image_file = request.files.get("image")
    if not image_file:
        return jsonify({"error": "No image provided"}), 400

    image_bytes = image_file.read()
    known_encodings = [face["encoding"] for face in known_faces]
    if not known_encodings:
        return jsonify({
            "name": "Unknown",
            "age": None,
            "gender": None,
            "address": None,
            "case_number": None,
            "arrest_date": None,
            "record_status": "No record",
            "crime": "No criminal records found",
            "confidence": "0%",
            "alert": "No criminal records found",
            "status": "No Match",
            "status_text": "No criminal records found in the database."
        })

    try:
        np_image = np.frombuffer(image_bytes, dtype=np.uint8)
        opencv_image = cv2.imdecode(np_image, cv2.IMREAD_COLOR)
        if opencv_image is None:
            raise ValueError("Unable to decode webcam image")
        rgb_image = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_image)
        face_encodings = face_recognition.face_encodings(rgb_image, face_locations)
    except Exception as e:
        return jsonify({"error": "Unable to process image", "detail": str(e)}), 500

    if not face_encodings:
        return jsonify({
            "name": "Unknown",
            "age": None,
            "gender": None,
            "address": None,
            "case_number": None,
            "arrest_date": None,
            "record_status": "No record",
            "crime": "No criminal records found",
            "confidence": "0%",
            "alert": "No face detected",
            "status": "No Face",
            "status_text": "No face detected. Please try again."
        })

    best_match = None
    best_distance = None

    for encoding in face_encodings:
        distances = face_recognition.face_distance(known_encodings, encoding)
        best_index = np.argmin(distances)
        distance = float(distances[best_index])
        if best_match is None or distance < best_distance:
            best_distance = distance
            best_match = known_faces[best_index]

    if best_match is not None and best_distance is not None and best_distance < 0.6:
        confidence = max(0, min(100, int((1 - best_distance) * 100)))
        return jsonify({
            "name": best_match["name"],
            "age": best_match["age"],
            "gender": best_match["gender"],
            "address": best_match["address"],
            "case_number": best_match["case_number"],
            "arrest_date": best_match["arrest_date"],
            "record_status": best_match["status"],
            "match_status": "Matched",
            "crime": best_match["crime"] or "Unknown offense",
            "confidence": f"{confidence}%",
            "alert": "Criminal record found",
            "status": "Matched",
            "status_text": "Criminal record found in the database.",
            "photo_url": f"/static/uploads/{best_match['image']}" if best_match.get('image') else None,
        })

    return jsonify({
        "name": "Unknown",
        "age": None,
        "gender": None,
        "address": None,
        "case_number": None,
        "arrest_date": None,
        "record_status": "No record",
        "crime": "No criminal records found",
        "confidence": "0%",
        "alert": "No criminal records found",
        "status": "No Match",
        "status_text": "No criminal records found in the database."
    })


@app.route("/recognize")
def recognize():
    if "user" not in session:
        return redirect("/")

    recognition_available = FACE_RECOGNITION_AVAILABLE
    person = {
        "name": "Unknown",
        "age": None,
        "gender": None,
        "address": None,
        "case_number": None,
        "arrest_date": None,
        "record_status": "No record",
        "crime": "No criminal records found",
        "confidence": "0%",
        "alert": "No criminal records found",
        "status": "Idle",
        "status_text": "Capture a face to compare against the database."
    }

    if not recognition_available:
        person["status_text"] = "Face recognition is unavailable. Install the required libraries on the server."

    logs = [
        {"time": "10:21 AM", "name": "John Doe", "crime": "Theft", "confidence": "92%", "status": "Matched"},
        {"time": "10:12 AM", "name": "Jane Smith", "crime": "Burglary", "confidence": "88%", "status": "Matched"},
        {"time": "09:45 AM", "name": "Unknown", "crime": "-", "confidence": "60%", "status": "No match"}
    ]

    return render_template("recognition.html", person=person, logs=logs, recognition_available=recognition_available)


# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    app.run(debug=True)