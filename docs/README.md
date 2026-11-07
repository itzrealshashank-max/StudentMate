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
