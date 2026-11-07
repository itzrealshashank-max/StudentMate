from pathlib import Path

ROOT = Path(__file__).resolve().parent

FILES = {}

FILES["app/config.py"] = r'''
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-development-key")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "student_academic_portal")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
'''

FILES["app/db.py"] = r'''
import mysql.connector
from flask import current_app

def get_db():
    config = current_app.config
    return mysql.connector.connect(
        host=config["DB_HOST"],
        port=config["DB_PORT"],
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
        database=config["DB_NAME"]
    )

def query(sql, params=(), fetchone=False, commit=False):
    connection = get_db()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        result = None
        if cursor.with_rows:
            result = cursor.fetchone() if fetchone else cursor.fetchall()
        if commit:
            connection.commit()
        return result
    finally:
        cursor.close()
        connection.close()
'''

FILES["app/__init__.py"] = r'''
import os
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from app.config import Config
from app.db import query

ALLOWED_EXTENSIONS = {"pdf", "txt", "doc", "docx", "png", "jpg", "jpeg"}

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    upload_dir = Path(app.root_path).parent / "uploads"
    upload_dir.mkdir(exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    def current_user():
        return query(
            "SELECT id, name, email FROM users WHERE id=%s",
            (session["user_id"],),
            fetchone=True
        )

    @app.context_processor
    def inject_user():
        return {"logged_in": "user_id" in session}

    @app.route("/")
    def home():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not name or not email or len(password) < 8:
                flash("Enter your name and email. Password must be at least 8 characters.", "danger")
                return render_template("register.html")

            existing = query(
                "SELECT id FROM users WHERE email=%s",
                (email,),
                fetchone=True
            )
            if existing:
                flash("This email is already registered. Please log in.", "warning")
                return redirect(url_for("login"))

            query(
                "INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s)",
                (name, email, generate_password_hash(password)),
                commit=True
            )
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            user = query(
                "SELECT id, name, email, password_hash FROM users WHERE email=%s",
                (email,),
                fetchone=True
            )
            if not user or not check_password_hash(user["password_hash"], password):
                flash("Invalid email or password.", "danger")
                return render_template("login.html")

            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        uid = session["user_id"]

        attendance = query(
            """SELECT COUNT(*) AS total,
            COALESCE(SUM(status='Present'),0) AS present
            FROM attendance WHERE user_id=%s""",
            (uid,), fetchone=True
        )
        assignments = query(
            """SELECT COUNT(*) AS total,
            COALESCE(SUM(status='Completed'),0) AS completed
            FROM assignments WHERE user_id=%s""",
            (uid,), fetchone=True
        )
        marks = query(
            """SELECT COALESCE(AVG(marks/total_marks*100),0) AS average
            FROM tests WHERE user_id=%s AND total_marks > 0""",
            (uid,), fetchone=True
        )
        recent_tests = query(
            """SELECT subject, test_name, marks, total_marks, test_date
            FROM tests WHERE user_id=%s
            ORDER BY test_date DESC, id DESC LIMIT 5""",
            (uid,)
        )
        return render_template(
            "dashboard.html",
            attendance=attendance,
            assignments=assignments,
            marks=marks,
            recent_tests=recent_tests
        )

    @app.route("/attendance", methods=["GET", "POST"])
    @login_required
    def attendance():
        uid = session["user_id"]
        if request.method == "POST":
            subject = request.form.get("subject", "").strip()
            date = request.form.get("date", "")
            status = request.form.get("status", "")

            if subject and date and status in ("Present", "Absent"):
                query(
                    """INSERT INTO attendance (user_id, subject, class_date, status)
                    VALUES (%s,%s,%s,%s)""",
                    (uid, subject, date, status), commit=True
                )
                flash("Attendance saved.", "success")
            else:
                flash("Please complete all fields correctly.", "danger")
            return redirect(url_for("attendance"))

        records = query(
            """SELECT id, subject, class_date, status
            FROM attendance WHERE user_id=%s
            ORDER BY class_date DESC, id DESC""",
            (uid,)
        )
        summary = query(
            """SELECT subject, COUNT(*) AS total,
            SUM(status='Present') AS present,
            ROUND(100*SUM(status='Present')/COUNT(*),1) AS percentage
            FROM attendance WHERE user_id=%s
            GROUP BY subject ORDER BY subject""",
            (uid,)
        )
        return render_template("attendance.html", records=records, summary=summary)

    @app.route("/attendance/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_attendance(item_id):
        query(
            "DELETE FROM attendance WHERE id=%s AND user_id=%s",
            (item_id, session["user_id"]), commit=True
        )
        flash("Attendance record deleted.", "success")
        return redirect(url_for("attendance"))

    @app.route("/assignments", methods=["GET", "POST"])
    @login_required
    def assignments():
        uid = session["user_id"]
        if request.method == "POST":
            subject = request.form.get("subject", "").strip()
            title = request.form.get("title", "").strip()
            due_date = request.form.get("due_date") or None

            if subject and title:
                query(
                    """INSERT INTO assignments
                    (user_id, subject, title, due_date)
                    VALUES (%s,%s,%s,%s)""",
                    (uid, subject, title, due_date), commit=True
                )
                flash("Assignment added.", "success")
            else:
                flash("Subject and title are required.", "danger")
            return redirect(url_for("assignments"))

        items = query(
            """SELECT id, subject, title, due_date, status
            FROM assignments WHERE user_id=%s
            ORDER BY due_date IS NULL, due_date""",
            (uid,)
        )
        return render_template("assignments.html", items=items)

    @app.route("/assignments/toggle/<int:item_id>", methods=["POST"])
    @login_required
    def toggle_assignment(item_id):
        query(
            """UPDATE assignments
            SET status=IF(status='Completed','Pending','Completed')
            WHERE id=%s AND user_id=%s""",
            (item_id, session["user_id"]), commit=True
        )
        return redirect(url_for("assignments"))

    @app.route("/assignments/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_assignment(item_id):
        query(
            "DELETE FROM assignments WHERE id=%s AND user_id=%s",
            (item_id, session["user_id"]), commit=True
        )
        flash("Assignment deleted.", "success")
        return redirect(url_for("assignments"))

    @app.route("/notes", methods=["GET", "POST"])
    @login_required
    def notes():
        uid = session["user_id"]
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            uploaded = request.files.get("file")

            if not title or not uploaded or not uploaded.filename:
                flash("Enter a title and choose a file.", "danger")
                return redirect(url_for("notes"))

            original = secure_filename(uploaded.filename)
            if not original or "." not in original:
                flash("Invalid filename.", "danger")
                return redirect(url_for("notes"))

            extension = original.rsplit(".", 1)[1].lower()
            if extension not in ALLOWED_EXTENSIONS:
                flash("File type not allowed.", "danger")
                return redirect(url_for("notes"))

            import uuid
            stored = uuid.uuid4().hex + "." + extension
            folder = Path(app.config["UPLOAD_FOLDER"]) / str(uid)
            folder.mkdir(parents=True, exist_ok=True)
            uploaded.save(folder / stored)

            try:
                query(
                    """INSERT INTO notes (user_id, title, original_name, stored_name)
                    VALUES (%s,%s,%s,%s)""",
                    (uid, title, original, stored), commit=True
                )
            except Exception:
                (folder / stored).unlink(missing_ok=True)
                raise

            flash("Note uploaded successfully.", "success")
            return redirect(url_for("notes"))

        items = query(
            """SELECT id, title, original_name, created_at
            FROM notes WHERE user_id=%s ORDER BY created_at DESC""",
            (uid,)
        )
        return render_template("notes.html", items=items)

    @app.route("/notes/download/<int:item_id>")
    @login_required
    def download_note(item_id):
        from flask import send_from_directory, abort
        item = query(
            "SELECT stored_name, original_name FROM notes WHERE id=%s AND user_id=%s",
            (item_id, session["user_id"]), fetchone=True
        )
        if not item:
            abort(404)
        return send_from_directory(
            str(Path(app.config["UPLOAD_FOLDER"]) / str(session["user_id"])),
            item["stored_name"],
            as_attachment=True,
            download_name=item["original_name"]
        )

    @app.route("/notes/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_note(item_id):
        item = query(
            "SELECT stored_name FROM notes WHERE id=%s AND user_id=%s",
            (item_id, session["user_id"]), fetchone=True
        )
        if item:
            query(
                "DELETE FROM notes WHERE id=%s AND user_id=%s",
                (item_id, session["user_id"]), commit=True
            )
            path = Path(app.config["UPLOAD_FOLDER"]) / str(session["user_id"]) / item["stored_name"]
            path.unlink(missing_ok=True)
            flash("Note deleted.", "success")
        return redirect(url_for("notes"))

    @app.route("/tests", methods=["GET", "POST"])
    @login_required
    def tests():
        uid = session["user_id"]
        if request.method == "POST":
            subject = request.form.get("subject", "").strip()
            name = request.form.get("test_name", "").strip()
            date = request.form.get("test_date", "")
            try:
                marks = float(request.form.get("marks", ""))
                total = float(request.form.get("total_marks", ""))
                if not (0 <= marks <= total and total > 0):
                    raise ValueError
            except ValueError:
                flash("Enter valid marks. Marks must be between zero and total marks.", "danger")
                return redirect(url_for("tests"))

            if not subject or not name or not date:
                flash("Complete all fields.", "danger")
                return redirect(url_for("tests"))

            query(
                """INSERT INTO tests
                (user_id, subject, test_name, test_date, marks, total_marks)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (uid, subject, name, date, marks, total), commit=True
            )
            flash("Test marks saved.", "success")
            return redirect(url_for("tests"))

        items = query(
            """SELECT id, subject, test_name, test_date, marks, total_marks,
            ROUND(marks*100/total_marks,1) AS percentage
            FROM tests WHERE user_id=%s
            ORDER BY test_date DESC, id DESC""",
            (uid,)
        )
        return render_template("tests.html", items=items)

    @app.route("/tests/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_test(item_id):
        query(
            "DELETE FROM tests WHERE id=%s AND user_id=%s",
            (item_id, session["user_id"]), commit=True
        )
        flash("Test record deleted.", "success")
        return redirect(url_for("tests"))

    @app.errorhandler(413)
    def too_large(error):
        flash("File is too large. Maximum allowed size is 10 MB.", "danger")
        return redirect(url_for("notes"))

    return app
'''

FILES["run.py"] = r'''
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
'''

FILES["database/schema.sql"] = r'''
CREATE DATABASE IF NOT EXISTS student_academic_portal
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE student_academic_portal;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(190) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject VARCHAR(100) NOT NULL,
    class_date DATE NOT NULL,
    status ENUM('Present','Absent') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject VARCHAR(100) NOT NULL,
    title VARCHAR(200) NOT NULL,
    due_date DATE NULL,
    status ENUM('Pending','Completed') NOT NULL DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    subject VARCHAR(100) NOT NULL,
    test_name VARCHAR(150) NOT NULL,
    test_date DATE NOT NULL,
    marks DECIMAL(7,2) NOT NULL,
    total_marks DECIMAL(7,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
'''

FILES["app/templates/base.html"] = r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}StudentMate{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary">
 <div class="container">
  <a class="navbar-brand fw-bold" href="{{ url_for('dashboard') if logged_in else url_for('login') }}">StudentMate</a>
  {% if logged_in %}
  <div class="d-flex flex-wrap gap-3">
   <a class="nav-link text-white" href="{{ url_for('dashboard') }}">Dashboard</a>
   <a class="nav-link text-white" href="{{ url_for('attendance') }}">Attendance</a>
   <a class="nav-link text-white" href="{{ url_for('assignments') }}">Assignments</a>
   <a class="nav-link text-white" href="{{ url_for('notes') }}">Notes</a>
   <a class="nav-link text-white" href="{{ url_for('tests') }}">Tests & Marks</a>
   <a class="nav-link text-white" href="{{ url_for('logout') }}">Logout</a>
  </div>
  {% endif %}
 </div>
</nav>
<main class="container py-4">
 {% with messages = get_flashed_messages(with_categories=true) %}
 {% for category, message in messages %}
 <div class="alert alert-{{ category }} alert-dismissible fade show">{{ message }}
 <button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>
 {% endfor %}
 {% endwith %}
 {% block content %}{% endblock %}
</main>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="{{ url_for('static', filename='js/main.js') }}"></script>
</body>
</html>
'''

FILES["app/templates/login.html"] = r'''
{% extends "base.html" %}
{% block title %}Login | StudentMate{% endblock %}
{% block content %}
<div class="auth-card card shadow-sm mx-auto p-4">
 <h2 class="mb-1">Welcome back!</h2><p class="text-muted">Log in to manage your academics.</p>
 <form method="post">
  <label class="form-label">Email</label><input class="form-control mb-3" type="email" name="email" required>
  <label class="form-label">Password</label><input class="form-control mb-3" type="password" name="password" required>
  <button class="btn btn-primary w-100">Login</button>
 </form>
 <p class="mt-3 mb-0">New student? <a href="{{ url_for('register') }}">Create an account</a></p>
</div>
{% endblock %}
'''

FILES["app/templates/register.html"] = r'''
{% extends "base.html" %}
{% block title %}Register | StudentMate{% endblock %}
{% block content %}
<div class="auth-card card shadow-sm mx-auto p-4">
 <h2>Create your account</h2><p class="text-muted">Keep all your academic records in one place.</p>
 <form method="post">
  <label class="form-label">Full name</label><input class="form-control mb-3" name="name" maxlength="100" required>
  <label class="form-label">Email</label><input class="form-control mb-3" type="email" name="email" required>
  <label class="form-label">Password (at least 8 characters)</label><input class="form-control mb-3" type="password" name="password" minlength="8" required>
  <button class="btn btn-primary w-100">Register</button>
 </form>
 <p class="mt-3 mb-0">Already registered? <a href="{{ url_for('login') }}">Login</a></p>
</div>
{% endblock %}
'''

FILES["app/templates/dashboard.html"] = r'''
{% extends "base.html" %}
{% block title %}Dashboard | StudentMate{% endblock %}
{% block content %}
<h2 class="mb-1">Hello, {{ session.get('user_name', 'Student') }}! 👋</h2>
<p class="text-muted mb-4">Your academic progress at a glance.</p>
<div class="row g-3 mb-4">
 <div class="col-md-4"><div class="stat-card"><p>Attendance</p><h3>{{ attendance.present or 0 }} / {{ attendance.total or 0 }}</h3><small>Present classes</small></div></div>
 <div class="col-md-4"><div class="stat-card"><p>Assignments</p><h3>{{ assignments.completed or 0 }} / {{ assignments.total or 0 }}</h3><small>Completed</small></div></div>
 <div class="col-md-4"><div class="stat-card"><p>Average Marks</p><h3>{{ "%.1f"|format(marks.average or 0) }}%</h3><small>Across recorded tests</small></div></div>
</div>
<div class="card p-4 shadow-sm">
 <h5>Recent test performance</h5>
 {% if recent_tests %}
 <canvas id="marksChart" height="100"></canvas>
 <script>
 const labels = {{ recent_tests|map(attribute='test_name')|list|reverse|tojson }};
 const values = {{ recent_tests|map(attribute='marks')|list|reverse|tojson }};
 const totals = {{ recent_tests|map(attribute='total_marks')|list|reverse|tojson }};
 new Chart(document.getElementById('marksChart'), {
  type:'bar',
  data:{labels:labels,datasets:[
   {label:'Marks obtained',data:values},
   {label:'Total marks',data:totals}
  ]},
  options:{responsive:true,scales:{y:{beginAtZero:true}}}
 });
 </script>
 {% else %}
 <p class="text-muted mb-0">No test results yet. Add your first test in Tests & Marks.</p>
 {% endif %}
</div>
<div class="row g-3 mt-2">
 <div class="col-md-6"><a class="quick-link" href="{{ url_for('attendance') }}">＋ Record attendance</a></div>
 <div class="col-md-6"><a class="quick-link" href="{{ url_for('assignments') }}">＋ Add an assignment</a></div>
 <div class="col-md-6"><a class="quick-link" href="{{ url_for('notes') }}">＋ Upload notes</a></div>
 <div class="col-md-6"><a class="quick-link" href="{{ url_for('tests') }}">＋ Enter test marks</a></div>
</div>
{% endblock %}
'''

FILES["app/templates/attendance.html"] = r'''
{% extends "base.html" %}
{% block title %}Attendance | StudentMate{% endblock %}
{% block content %}
<h2>Attendance Management</h2><p class="text-muted">Record each class and track attendance by subject.</p>
<div class="card p-4 mb-4 shadow-sm">
 <form method="post" class="row g-3">
  <div class="col-md-4"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div>
  <div class="col-md-3"><label class="form-label">Class date</label><input class="form-control" type="date" name="date" required></div>
  <div class="col-md-3"><label class="form-label">Status</label><select class="form-select" name="status"><option>Present</option><option>Absent</option></select></div>
  <div class="col-md-2 d-flex align-items-end"><button class="btn btn-primary w-100">Save</button></div>
 </form>
</div>
<h5>Subject summary</h5>
<div class="table-responsive"><table class="table table-striped bg-white"><thead><tr><th>Subject</th><th>Classes</th><th>Present</th><th>Attendance %</th></tr></thead><tbody>
{% for s in summary %}<tr><td>{{ s.subject }}</td><td>{{ s.total }}</td><td>{{ s.present }}</td><td>{{ s.percentage }}%</td></tr>{% else %}<tr><td colspan="4">No attendance records yet.</td></tr>{% endfor %}
</tbody></table></div>
<h5 class="mt-4">All records</h5>
<div class="table-responsive"><table class="table table-hover"><thead><tr><th>Date</th><th>Subject</th><th>Status</th><th></th></tr></thead><tbody>
{% for r in records %}<tr><td>{{ r.class_date }}</td><td>{{ r.subject }}</td><td>{{ r.status }}</td><td><form method="post" action="{{ url_for('delete_attendance',item_id=r.id) }}"><button class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete this record?')">Delete</button></form></td></tr>{% else %}<tr><td colspan="4">No records yet.</td></tr>{% endfor %}
</tbody></table></div>
{% endblock %}
'''

FILES["app/templates/assignments.html"] = r'''
{% extends "base.html" %}
{% block title %}Assignments | StudentMate{% endblock %}
{% block content %}
<h2>Assignments</h2><p class="text-muted">Organise your coursework and deadlines.</p>
<div class="card p-4 mb-4 shadow-sm"><form method="post" class="row g-3">
 <div class="col-md-4"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div>
 <div class="col-md-4"><label class="form-label">Assignment title</label><input class="form-control" name="title" required></div>
 <div class="col-md-2"><label class="form-label">Due date</label><input class="form-control" type="date" name="due_date"></div>
 <div class="col-md-2 d-flex align-items-end"><button class="btn btn-primary w-100">Add</button></div>
</form></div>
<div class="card shadow-sm"><div class="table-responsive"><table class="table align-middle mb-0">
<thead><tr><th>Subject</th><th>Assignment</th><th>Due date</th><th>Status</th><th>Actions</th></tr></thead><tbody>
{% for item in items %}<tr><td>{{ item.subject }}</td><td>{{ item.title }}</td><td>{{ item.due_date or 'Not set' }}</td><td><span class="badge {{ 'bg-success' if item.status=='Completed' else 'bg-warning text-dark' }}">{{ item.status }}</span></td><td class="d-flex gap-2">
<form method="post" action="{{ url_for('toggle_assignment',item_id=item.id) }}"><button class="btn btn-sm btn-outline-primary">Toggle</button></form>
<form method="post" action="{{ url_for('delete_assignment',item_id=item.id) }}"><button class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete assignment?')">Delete</button></form>
</td></tr>{% else %}<tr><td colspan="5" class="text-center p-4">No assignments added yet.</td></tr>{% endfor %}
</tbody></table></div></div>
{% endblock %}
'''

FILES["app/templates/notes.html"] = r'''
{% extends "base.html" %}
{% block title %}Notes | StudentMate{% endblock %}
{% block content %}
<h2>Study Notes</h2><p class="text-muted">Upload and download your study material.</p>
<div class="card p-4 mb-4 shadow-sm">
 <form method="post" enctype="multipart/form-data" class="row g-3">
  <div class="col-md-5"><label class="form-label">Note title</label><input class="form-control" name="title" required></div>
  <div class="col-md-5"><label class="form-label">Choose file (max 10 MB)</label><input class="form-control" type="file" name="file" required></div>
  <div class="col-md-2 d-flex align-items-end"><button class="btn btn-primary w-100">Upload</button></div>
 </form>
 <small class="text-muted mt-2">Allowed formats: PDF, TXT, DOC, DOCX, PNG, JPG.</small>
</div>
<div class="card shadow-sm"><div class="table-responsive"><table class="table mb-0">
<thead><tr><th>Title</th><th>File</th><th>Uploaded</th><th>Actions</th></tr></thead><tbody>
{% for item in items %}<tr><td>{{ item.title }}</td><td>{{ item.original_name }}</td><td>{{ item.created_at }}</td><td class="d-flex gap-2">
<a class="btn btn-sm btn-outline-primary" href="{{ url_for('download_note',item_id=item.id) }}">Download</a>
<form method="post" action="{{ url_for('delete_note',item_id=item.id) }}"><button class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete note?')">Delete</button></form>
</td></tr>{% else %}<tr><td colspan="4" class="text-center p-4">No notes uploaded yet.</td></tr>{% endfor %}
</tbody></table></div></div>
{% endblock %}
'''

FILES["app/templates/tests.html"] = r'''
{% extends "base.html" %}
{% block title %}Tests & Marks | StudentMate{% endblock %}
{% block content %}
<h2>Tests & Marks</h2><p class="text-muted">Record test results and monitor performance.</p>
<div class="card p-4 mb-4 shadow-sm"><form method="post" class="row g-3">
 <div class="col-md-3"><label class="form-label">Subject</label><input class="form-control" name="subject" required></div>
 <div class="col-md-3"><label class="form-label">Test name</label><input class="form-control" name="test_name" required></div>
 <div class="col-md-2"><label class="form-label">Test date</label><input class="form-control" type="date" name="test_date" required></div>
 <div class="col-md-2"><label class="form-label">Marks obtained</label><input class="form-control" type="number" name="marks" min="0" step="0.01" required></div>
 <div class="col-md-2"><label class="form-label">Total marks</label><input class="form-control" type="number" name="total_marks" min="0.01" step="0.01" required></div>
 <div class="col-12"><button class="btn btn-primary">Save test result</button></div>
</form></div>
<div class="card shadow-sm"><div class="table-responsive"><table class="table mb-0">
<thead><tr><th>Date</th><th>Subject</th><th>Test</th><th>Marks</th><th>Percentage</th><th></th></tr></thead><tbody>
{% for item in items %}<tr><td>{{ item.test_date }}</td><td>{{ item.subject }}</td><td>{{ item.test_name }}</td><td>{{ item.marks }} / {{ item.total_marks }}</td><td>{{ item.percentage }}%</td><td><form method="post" action="{{ url_for('delete_test',item_id=item.id) }}"><button class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete this result?')">Delete</button></form></td></tr>{% else %}<tr><td colspan="6" class="text-center p-4">No test results yet.</td></tr>{% endfor %}
</tbody></table></div></div>
{% endblock %}
'''

FILES["app/static/css/style.css"] = r'''
body {
    background: #f4f7fb;
    color: #202a44;
    min-height: 100vh;
}
.navbar { box-shadow: 0 2px 10px #00000012; }
.nav-link { font-size: .94rem; }
.auth-card { max-width: 470px; margin-top: 3rem; border: 0; border-radius: 16px; }
.card { border: 0; border-radius: 14px; }
.stat-card {
    height: 100%;
    background: white;
    border-radius: 14px;
    padding: 24px;
    box-shadow: 0 3px 14px #24365b0c;
    border-top: 4px solid #0d6efd;
}
.stat-card p { color: #6c757d; margin-bottom: 8px; }
.stat-card h3 { font-weight: 750; }
.quick-link {
    display: block; background: white; padding: 18px;
    border-radius: 12px; color: #0d6efd; text-decoration: none;
    box-shadow: 0 2px 12px #24365b0c;
}
.quick-link:hover { background: #eaf2ff; }
.table { vertical-align: middle; }
'''

FILES["app/static/js/main.js"] = r'''
console.log("StudentMate Academic Management Portal loaded.");
'''

FILES[".env.example"] = r'''
SECRET_KEY=replace-with-a-long-random-secret
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=student_academic_portal
'''

FILES[".gitignore"] = r'''
.env
.venv/
venv/
__pycache__/
*.py[cod]
uploads/*
!uploads/.gitkeep
'''

FILES["requirements.txt"] = r'''
Flask>=3.1,<4
mysql-connector-python>=9.0
python-dotenv>=1.0
'''

FILES["docs/README.md"] = r'''
# Student Academic Management Portal

A college mini project built with Python, Flask, MySQL, HTML, CSS,
Bootstrap, Jinja2 and Chart.js.

## Features
- Student registration and login
- Personal dashboard
- Attendance records and subject-wise percentage
- Assignment tracking
- Notes upload and download
- Test marks and performance chart

## Setup
1. Install the packages: `python -m pip install -r requirements.txt`
2. Create the MySQL database by running `database/schema.sql` in MySQL Workbench.
3. Configure your local `.env` file.
4. Start the app with `python run.py`.
5. Open `http://127.0.0.1:5000` in your browser.

This is a learning project. Review and strengthen security before any public deployment.


# Write the files without replacing the user's .env or database credentials.
for relative_path, content in FILES.items():
    destination = ROOT / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    if relative_path == ".env" and destination.exists():
        print("Keeping existing .env file.")
        continue

    destination.write_text(content.lstrip(), encoding="utf-8")
    print("Created/updated:", relative_path)

print("\nProject files are ready.")
print("Next: configure .env, run database/schema.sql in MySQL Workbench,")
print("then start the app with: python run.py")
'''

# Write the files without replacing the user's .env or database credentials.
for relative_path, content in FILES.items():
    destination = ROOT / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)

    if relative_path == ".env" and destination.exists():
        print("Keeping existing .env file.")
        continue

    destination.write_text(content.lstrip(), encoding="utf-8")
    print("Created/updated:", relative_path)

print("\nProject files are ready.")
print("Next: configure .env, run database/schema.sql in MySQL Workbench,")
print("then start the app with: python run.py")