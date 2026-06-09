-- This is the schema definition for the dislike table
CREATE TABLE dislike (
    dislike_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    created_at DATETIME,
    FOREIGN KEY(user_id) REFERENCES user(user_id),
    FOREIGN KEY(post_id) REFERENCES tweet(post_id)
);
