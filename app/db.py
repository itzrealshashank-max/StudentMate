import mysql.connector
from mysql.connector import Error
from app.config import Config


def get_connection():
    try:
        return mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME
        )
    except Error as error:
        print("Database connection error:", error)
        raise


def query(sql, params=None, fetchone=False, fetchall=False, commit=False):
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True, buffered=True)
        cursor.execute(sql, params or ())

        if cursor.with_rows:
            if fetchone:
                return cursor.fetchone()
            return cursor.fetchall()

        if commit:
            connection.commit()

        return cursor.rowcount

    except Exception:
        if connection is not None and commit:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None and connection.is_connected():
            connection.close()
