-- This is the schema definition for the follow table
CREATE TABLE follow (
    follow_id INTEGER PRIMARY KEY AUTOINCREMENT,
    follower_id INTEGER,
    followee_id INTEGER,
    created_at DATETIME,
    FOREIGN KEY(follower_id) REFERENCES user(user_id),
    FOREIGN KEY(followee_id) REFERENCES user(user_id)
);
