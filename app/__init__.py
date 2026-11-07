import os
import uuid
from functools import wraps
from pathlib import Path
from datetime import date

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    send_from_directory,
    abort
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)
from werkzeug.utils import secure_filename

from app.config import Config
from app.db import query


ALLOWED_EXTENSIONS = {
    "pdf", "txt", "doc", "docx", "png", "jpg", "jpeg"
}


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    upload_dir = Path(app.root_path).parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    app.config["UPLOAD_FOLDER"] = str(upload_dir)

    # ---------------- LOGIN PROTECTION ----------------

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login"))

            return view(*args, **kwargs)

        return wrapped

    # ---------------- CURRENT USER ----------------

    def current_user():
        if "user_id" not in session:
            return None

        return query(
            "SELECT id, name, email FROM users WHERE id=%s",
            (session["user_id"],),
            fetchone=True
        )

    @app.context_processor
    def inject_user():
        return {
            "logged_in": "user_id" in session,
            "current_user": current_user
        }

    # ---------------- HOME ----------------

    @app.route("/")
    def home():
        if "user_id" in session:
            return redirect(url_for("dashboard"))

        return redirect(url_for("login"))

    # ---------------- REGISTER ----------------

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            if not name or not email or len(password) < 8:
                flash(
                    "Enter your name and email. Password must be at least 8 characters.",
                    "danger"
                )
                return render_template("register.html")

            existing = query(
                "SELECT id FROM users WHERE email=%s",
                (email,),
                fetchone=True
            )

            if existing:
                flash(
                    "This email is already registered. Please log in.",
                    "warning"
                )
                return redirect(url_for("login"))

            query(
                """
                INSERT INTO users (name, email, password_hash)
                VALUES (%s, %s, %s)
                """,
                (name, email, generate_password_hash(password)),
                commit=True
            )

            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    # ---------------- LOGIN ----------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")

            user = query(
                """
                SELECT id, name, email, password_hash
                FROM users
                WHERE email=%s
                """,
                (email,),
                fetchone=True
            )

            if not user or not check_password_hash(
                user["password_hash"], password
            ):
                flash("Invalid email or password.", "danger")
                return render_template("login.html")

            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            return redirect(url_for("dashboard"))

        return render_template("login.html")

    # ---------------- LOGOUT ----------------

    @app.route("/logout")
    def logout():
        session.clear()
        flash("You have been logged out.", "success")

        return redirect(url_for("login"))

    # ---------------- DASHBOARD ----------------

    @app.route("/dashboard")
    @login_required
    def dashboard():
        uid = session["user_id"]

        attendance = query(
            """
            SELECT
                COALESCE(SUM(total_classes), 0) AS total,
                COALESCE(SUM(attended_classes), 0) AS present
            FROM attendance
            WHERE user_id=%s
            """,
            (uid,),
            fetchone=True
        )

        assignments = query(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(status='Completed'), 0) AS completed
            FROM assignments
            WHERE user_id=%s
            """,
            (uid,),
            fetchone=True
        )

        marks = query(
            """
            SELECT COALESCE(AVG(marks * 100.0 / total_marks), 0) AS average
            FROM test_subject_marks tm
            JOIN tests t ON t.id = tm.test_id
            WHERE t.user_id=%s AND tm.total_marks > 0
            """,
            (uid,),
            fetchone=True
        )

        recent_tests = query(
            """
            SELECT
                t.test_name,
                t.test_date,
                SUM(tm.marks) AS marks,
                SUM(tm.total_marks) AS total_marks
            FROM tests t
            JOIN test_subject_marks tm ON tm.test_id = t.id
            WHERE t.user_id=%s
            GROUP BY t.id, t.test_name, t.test_date
            ORDER BY t.test_date DESC, t.id DESC
            LIMIT 5
            """,
            (uid,)
        )

        return render_template(
            "dashboard.html",
            attendance=attendance,
            assignments=assignments,
            marks=marks,
            recent_tests=recent_tests
        )

    # ---------------- ATTENDANCE ----------------

    @app.route("/attendance", methods=["GET", "POST"])
    @login_required
    def attendance():
        uid = session["user_id"]

        if request.method == "POST":
            date_value = request.form.get("date", "").strip()

            try:
                total_classes = int(
                    request.form.get("total_classes", "")
                )

                attended_classes = int(
                    request.form.get("attended_classes", "")
                )

                if not date_value:
                    raise ValueError

                # Validate the date format.
                date.fromisoformat(date_value)

                if total_classes < 1:
                    flash(
                        "Total classes must be at least 1.",
                        "danger"
                    )
                    return redirect(url_for("attendance"))

                if not 0 <= attended_classes <= total_classes:
                    flash(
                        "Attended classes must be between 0 and total classes.",
                        "danger"
                    )
                    return redirect(url_for("attendance"))

            except (ValueError, TypeError):
                flash(
                    "Enter a valid date and valid class counts.",
                    "danger"
                )
                return redirect(url_for("attendance"))

            existing = query(
                """
                SELECT id
                FROM attendance
                WHERE user_id=%s AND class_date=%s
                """,
                (uid, date_value),
                fetchone=True
            )

            if existing:
                query(
                    """
                    UPDATE attendance
                    SET total_classes=%s,
                        attended_classes=%s
                    WHERE user_id=%s AND class_date=%s
                    """,
                    (
                        total_classes,
                        attended_classes,
                        uid,
                        date_value
                    ),
                    commit=True
                )

                flash(
                    "Attendance for this date has been updated.",
                    "success"
                )

            else:
                query(
                    """
                    INSERT INTO attendance
                    (
                        user_id,
                        class_date,
                        total_classes,
                        attended_classes
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        uid,
                        date_value,
                        total_classes,
                        attended_classes
                    ),
                    commit=True
                )

                flash("Attendance saved successfully.", "success")

            return redirect(url_for("attendance"))

        # Optional date filtering.
        filter_date = request.args.get("date", "").strip()

        if filter_date:
            records = query(
                """
                SELECT
                    id,
                    class_date,
                    total_classes,
                    attended_classes,
                    total_classes - attended_classes AS missed_classes,
                    ROUND(
                        attended_classes * 100.0 / total_classes, 1
                    ) AS percentage
                FROM attendance
                WHERE user_id=%s AND class_date=%s
                ORDER BY class_date DESC
                """,
                (uid, filter_date)
            )
        else:
            records = query(
                """
                SELECT
                    id,
                    class_date,
                    total_classes,
                    attended_classes,
                    total_classes - attended_classes AS missed_classes,
                    ROUND(
                        attended_classes * 100.0 / total_classes, 1
                    ) AS percentage
                FROM attendance
                WHERE user_id=%s
                ORDER BY class_date DESC
                """,
                (uid,)
            )

        # Overall summary remains based on ALL records,
        # even when a date filter is selected.
        summary = query(
            """
            SELECT
                COALESCE(SUM(total_classes), 0) AS total,
                COALESCE(SUM(attended_classes), 0) AS attended,
                COALESCE(
                    SUM(total_classes - attended_classes), 0
                ) AS missed,
                CASE
                    WHEN COALESCE(SUM(total_classes), 0) > 0
                    THEN ROUND(
                        SUM(attended_classes) * 100.0
                        / SUM(total_classes),
                        1
                    )
                    ELSE 0
                END AS percentage
            FROM attendance
            WHERE user_id=%s
            """,
            (uid,),
            fetchone=True
        )

        return render_template(
            "attendance.html",
            records=records,
            summary=summary,
            filter_date=filter_date
        )

    # ---------------- EDIT ATTENDANCE ----------------

    @app.route(
        "/attendance/edit/<int:item_id>",
        methods=["GET", "POST"]
    )
    @login_required
    def edit_attendance(item_id):
        uid = session["user_id"]

        item = query(
            """
            SELECT id, class_date, total_classes, attended_classes
            FROM attendance
            WHERE id=%s AND user_id=%s
            """,
            (item_id, uid),
            fetchone=True
        )

        if not item:
            flash("Attendance record not found.", "danger")
            return redirect(url_for("attendance"))

        if request.method == "POST":
            date_value = request.form.get("date", "").strip()

            try:
                total_classes = int(
                    request.form.get("total_classes", "")
                )

                attended_classes = int(
                    request.form.get("attended_classes", "")
                )

                if not date_value:
                    raise ValueError

                date.fromisoformat(date_value)

                if total_classes < 1:
                    raise ValueError

                if not 0 <= attended_classes <= total_classes:
                    raise ValueError

            except (ValueError, TypeError):
                flash(
                    "Enter a valid date and class counts.",
                    "danger"
                )
                return redirect(
                    url_for("edit_attendance", item_id=item_id)
                )

            duplicate = query(
                """
                SELECT id
                FROM attendance
                WHERE user_id=%s AND class_date=%s AND id<>%s
                """,
                (uid, date_value, item_id),
                fetchone=True
            )

            if duplicate:
                flash(
                    "Another attendance record already exists for that date.",
                    "warning"
                )
                return redirect(
                    url_for("edit_attendance", item_id=item_id)
                )

            query(
                """
                UPDATE attendance
                SET class_date=%s,
                    total_classes=%s,
                    attended_classes=%s
                WHERE id=%s AND user_id=%s
                """,
                (
                    date_value,
                    total_classes,
                    attended_classes,
                    item_id,
                    uid
                ),
                commit=True
            )

            flash("Attendance record updated.", "success")
            return redirect(url_for("attendance"))

        return render_template("edit_attendance.html", item=item)

    # ---------------- DELETE ATTENDANCE ----------------

    @app.route("/attendance/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_attendance(item_id):
        query(
            """
            DELETE FROM attendance
            WHERE id=%s AND user_id=%s
            """,
            (item_id, session["user_id"]),
            commit=True
        )

        flash("Attendance record deleted.", "success")
        return redirect(url_for("attendance"))

    # ---------------- ASSIGNMENTS ----------------

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
                    """
                    INSERT INTO assignments
                    (user_id, subject, title, due_date)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (uid, subject, title, due_date),
                    commit=True
                )

                flash("Assignment added.", "success")
            else:
                flash(
                    "Subject and title are required.",
                    "danger"
                )

            return redirect(url_for("assignments"))

        items = query(
            """
            SELECT id, subject, title, due_date, status
            FROM assignments
            WHERE user_id=%s
            ORDER BY due_date IS NULL, due_date
            """,
            (uid,)
        )

        return render_template("assignments.html", items=items)

    @app.route("/assignments/toggle/<int:item_id>", methods=["POST"])
    @login_required
    def toggle_assignment(item_id):
        query(
            """
            UPDATE assignments
            SET status=IF(status='Completed', 'Pending', 'Completed')
            WHERE id=%s AND user_id=%s
            """,
            (item_id, session["user_id"]),
            commit=True
        )

        return redirect(url_for("assignments"))

    @app.route("/assignments/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_assignment(item_id):
        query(
            """
            DELETE FROM assignments
            WHERE id=%s AND user_id=%s
            """,
            (item_id, session["user_id"]),
            commit=True
        )

        flash("Assignment deleted.", "success")
        return redirect(url_for("assignments"))

    # ---------------- NOTES ----------------

    @app.route("/notes", methods=["GET", "POST"])
    @login_required
    def notes():
        uid = session["user_id"]

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            uploaded = request.files.get("file")

            if not title or not uploaded or not uploaded.filename:
                flash(
                    "Enter a title and choose a file.",
                    "danger"
                )
                return redirect(url_for("notes"))

            original = secure_filename(uploaded.filename)

            if not original or "." not in original:
                flash("Invalid filename.", "danger")
                return redirect(url_for("notes"))

            extension = original.rsplit(".", 1)[1].lower()

            if extension not in ALLOWED_EXTENSIONS:
                flash("File type not allowed.", "danger")
                return redirect(url_for("notes"))

            stored = uuid.uuid4().hex + "." + extension

            folder = (
                Path(app.config["UPLOAD_FOLDER"]) / str(uid)
            )
            folder.mkdir(parents=True, exist_ok=True)

            uploaded.save(folder / stored)

            try:
                query(
                    """
                    INSERT INTO notes
                    (user_id, title, original_name, stored_name)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (uid, title, original, stored),
                    commit=True
                )
            except Exception:
                (folder / stored).unlink(missing_ok=True)
                raise

            flash("Note uploaded successfully.", "success")
            return redirect(url_for("notes"))

        items = query(
            """
            SELECT id, title, original_name, created_at
            FROM notes
            WHERE user_id=%s
            ORDER BY created_at DESC
            """,
            (uid,)
        )

        return render_template("notes.html", items=items)

    @app.route("/notes/download/<int:item_id>")
    @login_required
    def download_note(item_id):
        item = query(
            """
            SELECT stored_name, original_name
            FROM notes
            WHERE id=%s AND user_id=%s
            """,
            (item_id, session["user_id"]),
            fetchone=True
        )

        if not item:
            abort(404)

        return send_from_directory(
            str(
                Path(app.config["UPLOAD_FOLDER"])
                / str(session["user_id"])
            ),
            item["stored_name"],
            as_attachment=True,
            download_name=item["original_name"]
        )

    @app.route("/notes/delete/<int:item_id>", methods=["POST"])
    @login_required
    def delete_note(item_id):
        uid = session["user_id"]

        item = query(
            """
            SELECT stored_name
            FROM notes
            WHERE id=%s AND user_id=%s
            """,
            (item_id, uid),
            fetchone=True
        )

        if item:
            query(
                """
                DELETE FROM notes
                WHERE id=%s AND user_id=%s
                """,
                (item_id, uid),
                commit=True
            )

            path = (
                Path(app.config["UPLOAD_FOLDER"])
                / str(uid)
                / item["stored_name"]
            )
            path.unlink(missing_ok=True)

            flash("Note deleted.", "success")

        return redirect(url_for("notes"))

    # ---------------- TESTS AND MARKS ----------------

    @app.route("/tests", methods=["GET", "POST"])
    @login_required
    def tests():
        uid = session["user_id"]

        if request.method == "POST":
            semester = request.form.get("semester", "").strip()
            name = request.form.get("test_name", "").strip()
            test_date = request.form.get("test_date", "").strip()
            subjects = request.form.getlist("subject[]")
            marks_values = request.form.getlist("marks[]")
            totals_values = request.form.getlist("total_marks[]")

            if not semester or not name or not test_date:
                flash("Enter the semester, test name, and test date.", "danger")
                return redirect(url_for("tests"))

            try:
                date.fromisoformat(test_date)
            except ValueError:
                flash("Enter a valid test date.", "danger")
                return redirect(url_for("tests"))

            if not subjects or not (len(subjects) == len(marks_values) == len(totals_values)):
                flash("Add at least one subject with marks.", "danger")
                return redirect(url_for("tests"))

            cleaned = []
            seen_subjects = set()
            try:
                for subject, mark_text, total_text in zip(subjects, marks_values, totals_values):
                    subject = subject.strip()
                    marks = float(mark_text)
                    total = float(total_text)
                    subject_key = subject.casefold()

                    if not subject:
                        raise ValueError("Every subject needs a name.")
                    if subject_key in seen_subjects:
                        raise ValueError("A subject can only be added once per test.")
                    if total <= 0 or marks < 0 or marks > total:
                        raise ValueError("Marks must be between zero and total marks.")

                    seen_subjects.add(subject_key)
                    cleaned.append((subject, marks, total))
            except (ValueError, TypeError) as exc:
                message = str(exc) or "Enter valid marks for every subject."
                flash(message, "danger")
                return redirect(url_for("tests"))

            duplicate = query(
                """
                SELECT id FROM tests
                WHERE user_id=%s AND semester=%s AND test_name=%s
                """,
                (uid, semester, name),
                fetchone=True
            )
            if duplicate:
                flash("A test with this name already exists in this semester.", "warning")
                return redirect(url_for("tests"))

            query(
                """
                INSERT INTO tests (user_id, semester, test_name, test_date)
                VALUES (%s, %s, %s, %s)
                """,
                (uid, semester, name, test_date),
                commit=True
            )

            # Find the test just created so its subject marks can be attached.
            created_test = query(
                """
                SELECT id FROM tests
                WHERE user_id=%s AND semester=%s AND test_name=%s
                ORDER BY id DESC LIMIT 1
                """,
                (uid, semester, name),
                fetchone=True
            )

            try:
                for subject, marks, total in cleaned:
                    query(
                        """
                        INSERT INTO test_subject_marks
                            (test_id, subject, marks, total_marks)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (created_test["id"], subject, marks, total),
                        commit=True
                    )
            except Exception:
                # Avoid leaving a partially saved test if an insert fails.
                query(
                    "DELETE FROM tests WHERE id=%s AND user_id=%s",
                    (created_test["id"], uid),
                    commit=True
                )
                raise

            flash("Test and all subject marks saved successfully.", "success")
            return redirect(url_for("tests"))

        test_items = query(
            """
            SELECT
                t.id,
                t.semester,
                t.test_name,
                t.test_date,
                COUNT(tm.id) AS subject_count,
                COALESCE(SUM(tm.marks), 0) AS marks,
                COALESCE(SUM(tm.total_marks), 0) AS total_marks,
                CASE WHEN COALESCE(SUM(tm.total_marks), 0) > 0
                     THEN ROUND(SUM(tm.marks) * 100.0 / SUM(tm.total_marks), 1)
                     ELSE 0 END AS percentage
            FROM tests t
            LEFT JOIN test_subject_marks tm ON tm.test_id = t.id
            WHERE t.user_id=%s
            GROUP BY t.id, t.semester, t.test_name, t.test_date
            ORDER BY t.test_date DESC, t.id DESC
            """,
            (uid,)
        )

        # Subject-wise data for comparing each subject across tests.
        comparison_rows = query(
            """
            SELECT
                tm.subject,
                t.id AS test_id,
                t.semester,
                t.test_name,
                t.test_date,
                tm.marks,
                tm.total_marks,
                ROUND(tm.marks * 100.0 / tm.total_marks, 1) AS percentage
            FROM tests t
            JOIN test_subject_marks tm ON tm.test_id = t.id
            WHERE t.user_id=%s AND tm.total_marks > 0
            ORDER BY tm.subject, t.test_date, t.id
            """,
            (uid,)
        )

        comparison = {}
        for row in comparison_rows:
            subject = row["subject"]
            comparison.setdefault(subject, []).append(row)

        subject_summaries = []
        for subject, rows in comparison.items():
            first = rows[0]
            last = rows[-1]
            subject_summaries.append({
                "subject": subject,
                "test_count": len(rows),
                "latest_percentage": last["percentage"],
                "change": round(float(last["percentage"]) - float(first["percentage"]), 1),
                "first_test": first["test_name"],
                "latest_test": last["test_name"],
            })

        # Keep chart data JSON-safe and in chronological order.
        chart_data = []
        for test in reversed(test_items):
            chart_data.append({
                "label": f'{test["test_name"]} ({test["semester"]})',
                "percentage": float(test["percentage"] or 0)
            })

        return render_template(
            "tests.html",
            items=test_items,
            comparison=comparison,
            subject_summaries=subject_summaries,
            chart_data=chart_data
        )

    @app.route("/tests/<int:test_id>")
    @login_required
    def view_test(test_id):
        uid = session["user_id"]
        test = query(
            """
            SELECT id, semester, test_name, test_date
            FROM tests
            WHERE id=%s AND user_id=%s
            """,
            (test_id, uid),
            fetchone=True
        )
        if not test:
            abort(404)

        subjects = query(
            """
            SELECT id, subject, marks, total_marks,
                   ROUND(marks * 100.0 / total_marks, 1) AS percentage
            FROM test_subject_marks
            WHERE test_id=%s
            ORDER BY subject
            """,
            (test_id,)
        )
        return render_template("view_test.html", test=test, subjects=subjects)

    @app.route("/tests/delete/<int:test_id>", methods=["POST"])
    @login_required
    def delete_test(test_id):
        query(
            "DELETE FROM tests WHERE id=%s AND user_id=%s",
            (test_id, session["user_id"]),
            commit=True
        )
        flash("Test deleted successfully.", "success")
        return redirect(url_for("tests"))

    # ---------------- FILE SIZE ERROR ----------------

    @app.errorhandler(413)
    def too_large(error):
        flash(
            "File is too large. Maximum allowed size is 10 MB.",
            "danger"
        )
        return redirect(url_for("notes"))

    return app