-- This is the schema definition for the report table
CREATE TABLE report (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    report_reason TEXT,
    created_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES user(user_id),
    FOREIGN KEY(post_id) REFERENCES post(post_id)
);
