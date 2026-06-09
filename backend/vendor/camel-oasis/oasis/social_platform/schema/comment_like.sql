-- This is the schema definition for the comment_like table
CREATE TABLE comment_like (
    comment_like_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    comment_id INTEGER,
    created_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES user(user_id),
    FOREIGN KEY(comment_id) REFERENCES comment(comment_id)
);
