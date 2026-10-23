import os
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "bluewave-change-this-secret-key"
DATABASE = "bluewave.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "jfif"}
ALLOWED_COLORS = {
    "#168cff", "#22c55e", "#a855f7", "#ef4444",
    "#f97316", "#eab308", "#ec4899", "#14b8a6"
}
ALLOWED_REACTIONS = {"❤️", "😂", "😮", "👍", "😢", "🔥"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def allowed_file(filename):
    if "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


def initialize_database():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        user_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(users)").fetchall()
        }

        if "profile_image" not in user_columns:
            db.execute("""
                ALTER TABLE users
                ADD COLUMN profile_image TEXT
            """)

        if "username_changed_at" not in user_columns:
            db.execute("""
                ALTER TABLE users
                ADD COLUMN username_changed_at TEXT
            """)

        message_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(messages)").fetchall()
        }

        if "receiver_id" not in message_columns:
            db.execute("""
                ALTER TABLE messages
                ADD COLUMN receiver_id INTEGER
            """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                other_user_id INTEGER NOT NULL,
                background_image TEXT,
                message_color TEXT DEFAULT '#168cff',
                UNIQUE(user_id, other_user_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (other_user_id) REFERENCES users(id)
            )
        """)

        chat_columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(chat_settings)").fetchall()
        }

        if "message_color" not in chat_columns:
            db.execute("""
                ALTER TABLE chat_settings
                ADD COLUMN message_color TEXT DEFAULT '#168cff'
            """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS message_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                UNIQUE(message_id, user_id),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)


initialize_database()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return function(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/users")
    return render_template("register.html", error="")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if len(username) < 3 or len(password) < 8:
            error = (
                "اسم المستخدم 3 حروف على الأقل "
                "وكلمة المرور 8 حروف."
            )
        else:
            try:
                with get_db() as db:
                    db.execute(
                        """
                        INSERT INTO users (username, password)
                        VALUES (?, ?)
                        """,
                        (
                            username,
                            generate_password_hash(password)
                        ),
                    )
                return redirect("/login")
            except sqlite3.IntegrityError:
                error = "اسم المستخدم مستخدم بالفعل."

    return render_template(
        "register.html",
        error=error
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as db:
            user = db.execute(
                """
                SELECT *
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()

        if user and check_password_hash(
            user["password"],
            password
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect("/users")

        error = (
            "اسم المستخدم أو كلمة المرور "
            "غير صحيحة."
        )

    return render_template(
        "login.html",
        error=error
    )


@app.route("/users")
@login_required
def users():
    search = request.args.get(
        "search",
        ""
    ).strip()

    people = []
    conversations = []

    with get_db() as db:
        conversations = db.execute(
            """
            SELECT
                u.id,
                u.username,
                u.profile_image,
                COUNT(m.id) AS message_count,
                MAX(m.id) AS last_message_id,
                (
                    SELECT lm.message
                    FROM messages AS lm
                    WHERE
                        (
                            lm.user_id = ? AND lm.receiver_id = u.id
                        )
                        OR
                        (
                            lm.user_id = u.id AND lm.receiver_id = ?
                        )
                    ORDER BY lm.id DESC
                    LIMIT 1
                ) AS last_message
            FROM users AS u
            JOIN messages AS m
                ON (
                    (m.user_id = ? AND m.receiver_id = u.id)
                    OR
                    (m.user_id = u.id AND m.receiver_id = ?)
                )
            WHERE u.id != ?
            GROUP BY u.id
            ORDER BY last_message_id DESC
            """,
            (
                session["user_id"],
                session["user_id"],
                session["user_id"],
                session["user_id"],
                session["user_id"],
            ),
        ).fetchall()

        if search:
            people = db.execute(
                """
                SELECT
                    id,
                    username,
                    profile_image
                FROM users
                WHERE id != ?
                AND username LIKE ?
                ORDER BY username
                """,
                (
                    session["user_id"],
                    f"%{search}%"
                ),
            ).fetchall()

    return render_template(
        "users.html",
        people=people,
        conversations=conversations,
        username=session["username"],
        search=search,
    )


@app.route(
    "/chat/<int:other_user_id>",
    methods=["GET", "POST"]
)
@login_required
def chat(other_user_id):
    current_user_id = session["user_id"]

    if other_user_id == current_user_id:
        return redirect("/users")

    with get_db() as db:
        other_user = db.execute(
            """
            SELECT
                id,
                username,
                profile_image
            FROM users
            WHERE id = ?
            """,
            (other_user_id,),
        ).fetchone()

        if other_user is None:
            return "المستخدم غير موجود.", 404

        error = ""

        action = request.form.get(
            "action",
            ""
        )

        if request.method == "POST" and action == "react":
            try:
                message_id = int(
                    request.form.get(
                        "message_id",
                        "0"
                    )
                )
            except (TypeError, ValueError):
                return redirect(
                    f"/chat/{other_user_id}"
                )

            emoji = request.form.get(
                "emoji",
                ""
            )

            if emoji not in ALLOWED_REACTIONS:
                return redirect(
                    f"/chat/{other_user_id}"
                )

            target_message = db.execute(
                """
                SELECT id
                FROM messages
                WHERE id = ?
                AND (
                    (user_id = ? AND receiver_id = ?)
                    OR
                    (user_id = ? AND receiver_id = ?)
                )
                """,
                (
                    message_id,
                    current_user_id,
                    other_user_id,
                    other_user_id,
                    current_user_id
                ),
            ).fetchone()

            if target_message:
                existing = db.execute(
                    """
                    SELECT emoji
                    FROM message_reactions
                    WHERE message_id = ?
                    AND user_id = ?
                    """,
                    (
                        message_id,
                        current_user_id
                    ),
                ).fetchone()

                if existing and existing["emoji"] == emoji:
                    db.execute(
                        """
                        DELETE FROM message_reactions
                        WHERE message_id = ?
                        AND user_id = ?
                        """,
                        (
                            message_id,
                            current_user_id
                        ),
                    )
                else:
                    db.execute(
                        """
                        INSERT INTO message_reactions
                            (message_id, user_id, emoji)
                        VALUES (?, ?, ?)
                        ON CONFLICT(message_id, user_id)
                        DO UPDATE SET emoji = excluded.emoji
                        """,
                        (
                            message_id,
                            current_user_id,
                            emoji
                        ),
                    )

            return redirect(
                f"/chat/{other_user_id}"
            )

        if (
            request.method == "POST"
            and action == "change_color"
        ):
            message_color = request.form.get(
                "message_color",
                "#168cff"
            )

            if message_color not in ALLOWED_COLORS:
                message_color = "#168cff"

            old_setting = db.execute(
                """
                SELECT background_image
                FROM chat_settings
                WHERE user_id = ?
                AND other_user_id = ?
                """,
                (
                    current_user_id,
                    other_user_id
                ),
            ).fetchone()

            current_background = None

            if old_setting:
                current_background = (
                    old_setting["background_image"]
                )

            db.execute(
                """
                INSERT INTO chat_settings
                    (
                        user_id,
                        other_user_id,
                        background_image,
                        message_color
                    )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, other_user_id)
                DO UPDATE SET
                    message_color =
                    excluded.message_color
                """,
                (
                    current_user_id,
                    other_user_id,
                    current_background,
                    message_color
                ),
            )

            return redirect(
                f"/chat/{other_user_id}"
            )

        background_image = request.files.get(
            "chat_background"
        )

        if background_image is not None:
            if background_image.filename == "":
                error = "اختار صورة للخلفية الأول."

            elif not allowed_file(
                background_image.filename
            ):
                error = (
                    "نوع الصورة غير مسموح. "
                    "استخدم PNG أو JPG أو JPEG "
                    "أو GIF أو WEBP أو JFIF."
                )

            else:
                original_name = secure_filename(
                    background_image.filename
                )

                extension = original_name.rsplit(
                    ".",
                    1
                )[1].lower()

                filename = (
                    f"chat_"
                    f"{current_user_id}_"
                    f"{other_user_id}."
                    f"{extension}"
                )

                image_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )

                background_image.save(
                    image_path
                )

                old_setting = db.execute(
                    """
                    SELECT message_color
                    FROM chat_settings
                    WHERE user_id = ?
                    AND other_user_id = ?
                    """,
                    (
                        current_user_id,
                        other_user_id
                    ),
                ).fetchone()

                current_color = "#168cff"

                if old_setting:
                    if old_setting["message_color"]:
                        current_color = (
                            old_setting["message_color"]
                        )

                db.execute(
                    """
                    INSERT INTO chat_settings
                        (
                            user_id,
                            other_user_id,
                            background_image,
                            message_color
                        )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, other_user_id)
                    DO UPDATE SET
                        background_image =
                        excluded.background_image
                    """,
                    (
                        current_user_id,
                        other_user_id,
                        filename,
                        current_color
                    ),
                )

                return redirect(
                    f"/chat/{other_user_id}"
                )

        if (
            request.method == "POST"
            and background_image is None
            and action not in {
                "change_color",
                "react"
            }
        ):
            message = request.form.get(
                "message",
                ""
            ).strip()

            if not message:
                error = "اكتب رسالة الأول."

            elif len(message) > 2000:
                error = "الرسالة طويلة جدًا."

            else:
                db.execute(
                    """
                    INSERT INTO messages
                        (
                            user_id,
                            receiver_id,
                            message
                        )
                    VALUES (?, ?, ?)
                    """,
                    (
                        current_user_id,
                        other_user_id,
                        message
                    ),
                )

                return redirect(
                    f"/chat/{other_user_id}"
                )

        chat_setting = db.execute(
            """
            SELECT
                background_image,
                message_color
            FROM chat_settings
            WHERE user_id = ?
            AND other_user_id = ?
            """,
            (
                current_user_id,
                other_user_id
            ),
        ).fetchone()

        chat_background = None
        message_color = "#168cff"

        if chat_setting:
            if chat_setting["background_image"]:
                chat_background = (
                    chat_setting["background_image"]
                )

            if chat_setting["message_color"]:
                message_color = (
                    chat_setting["message_color"]
                )

        messages = db.execute(
            """
            SELECT
                messages.id,
                messages.user_id,
                messages.receiver_id,
                messages.message,
                messages.created_at,
                users.username
            FROM messages
            JOIN users
                ON users.id = messages.user_id
            WHERE
                (
                    messages.user_id = ?
                    AND messages.receiver_id = ?
                )
                OR
                (
                    messages.user_id = ?
                    AND messages.receiver_id = ?
                )
            ORDER BY messages.id ASC
            """,
            (
                current_user_id,
                other_user_id,
                other_user_id,
                current_user_id,
            ),
        ).fetchall()

        messages_with_reactions = []

        for row in messages:
            message_data = dict(row)

            reaction_rows = db.execute(
                """
                SELECT
                    emoji,
                    COUNT(*) AS count,
                    MAX(
                        CASE
                            WHEN user_id = ?
                            THEN 1
                            ELSE 0
                        END
                    ) AS mine
                FROM message_reactions
                WHERE message_id = ?
                GROUP BY emoji
                ORDER BY emoji
                """,
                (
                    current_user_id,
                    row["id"]
                ),
            ).fetchall()

            message_data["reactions"] = [
                dict(reaction)
                for reaction in reaction_rows
            ]

            message_data["reaction_counts"] = {
                reaction["emoji"]: reaction["count"]
                for reaction in reaction_rows
            }

            message_data["my_reaction"] = next(
                (
                    reaction["emoji"]
                    for reaction in reaction_rows
                    if reaction["mine"]
                ),
                None,
            )

            messages_with_reactions.append(
                message_data
            )

    return render_template(
        "chat.html",
        messages=messages_with_reactions,
        allowed_reactions=sorted(
            ALLOWED_REACTIONS
        ),
        username=session["username"],
        other_username=other_user["username"],
        other_user_id=other_user_id,
        error=error,
        user_reactions={},
        other_profile_image=other_user["profile_image"],
        chat_background=chat_background,
        message_color=message_color,
        reaction_counts={
            msg["id"]: msg["reaction_counts"]
            for msg in messages_with_reactions
        },
    )


@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():
    user_id = session["user_id"]
    error = ""
    success = ""

    if request.method == "POST":
        action = request.form.get(
            "action",
            "change_picture"
        )

        if action == "change_username":
            new_username = request.form.get(
                "new_username",
                ""
            ).strip()

            if len(new_username) < 3:
                error = (
                    "اسم المستخدم لازم يكون 3 حروف على الأقل."
                )

            elif len(new_username) > 30:
                error = (
                    "اسم المستخدم مينفعش يزيد عن 30 حرف."
                )

            else:
                try:
                    with get_db() as db:
                        user_row = db.execute(
                            """
                            SELECT
                                username,
                                username_changed_at
                            FROM users
                            WHERE id = ?
                            """,
                            (user_id,),
                        ).fetchone()

                        if user_row is None:
                            session.clear()
                            return redirect("/login")

                        if new_username == user_row["username"]:
                            error = (
                                "ده اسم المستخدم الحالي بالفعل."
                            )

                        else:
                            changed_at = (
                                user_row[
                                    "username_changed_at"
                                ]
                            )

                            if changed_at:
                                elapsed_row = db.execute(
                                    """
                                    SELECT
                                        (
                                            julianday('now')
                                            - julianday(?)
                                        ) * 24
                                        AS hours_elapsed
                                    """,
                                    (changed_at,),
                                ).fetchone()

                                elapsed = elapsed_row[
                                    "hours_elapsed"
                                ]

                                if (
                                    elapsed is not None
                                    and elapsed < 48
                                ):
                                    hours_left = max(
                                        1,
                                        int(
                                            48
                                            - elapsed
                                            + 0.999
                                        )
                                    )

                                    error = (
                                        "مينفعش تغيّر اسمك دلوقتي. "
                                        f"جرّب بعد حوالي "
                                        f"{hours_left} ساعة."
                                    )

                            if not error:
                                db.execute(
                                    """
                                    UPDATE users
                                    SET
                                        username = ?,
                                        username_changed_at =
                                            CURRENT_TIMESTAMP
                                    WHERE id = ?
                                    """,
                                    (
                                        new_username,
                                        user_id
                                    ),
                                )

                                session["username"] = (
                                    new_username
                                )

                                success = (
                                    "تم تغيير اسم المستخدم بنجاح."
                                )

                except sqlite3.IntegrityError:
                    error = (
                        "اسم المستخدم مستخدم بالفعل."
                    )

        elif action == "change_picture":
            image = request.files.get(
                "profile_image"
            )

            if image is None or image.filename == "":
                error = "اختار صورة الأول."

            elif not allowed_file(
                image.filename
            ):
                error = (
                    "نوع الصورة غير مسموح. "
                    "استخدم PNG أو JPG أو JPEG أو GIF أو WEBP أو JFIF."
                )

            else:
                original_name = secure_filename(
                    image.filename
                )

                extension = original_name.rsplit(
                    ".",
                    1
                )[1].lower()

                filename = (
                    f"user_{user_id}.{extension}"
                )

                image_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )

                image.save(
                    image_path
                )

                with get_db() as db:
                    db.execute(
                        """
                        UPDATE users
                        SET profile_image = ?
                        WHERE id = ?
                        """,
                        (
                            filename,
                            user_id
                        ),
                    )

                return redirect(
                    "/profile"
                )

        else:
            error = "الطلب غير صحيح."

    with get_db() as db:
        user = db.execute(
            """
            SELECT
                id,
                username,
                profile_image,
                username_changed_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        can_change_username = True
        hours_left = 0

        if user and user["username_changed_at"]:
            elapsed_row = db.execute(
                """
                SELECT
                    (
                        julianday('now')
                        - julianday(?)
                    ) * 24
                    AS hours_elapsed
                """,
                (
                    user["username_changed_at"],
                ),
            ).fetchone()

            elapsed = elapsed_row[
                "hours_elapsed"
            ]

            if (
                elapsed is not None
                and elapsed < 48
            ):
                can_change_username = False

                hours_left = max(
                    1,
                    int(
                        48
                        - elapsed
                        + 0.999
                    )
                )

    if user is None:
        session.clear()
        return redirect("/login")

    return render_template(
        "profile.html",
        user=user,
        error=error,
        success=success,
        can_change_username=can_change_username,
        hours_left=hours_left,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.errorhandler(404)
def page_not_found(error):
    return "الصفحة غير موجودة (404)", 404

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
