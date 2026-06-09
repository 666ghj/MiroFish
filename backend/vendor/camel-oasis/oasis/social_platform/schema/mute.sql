-- This is the schema definition for the mute table
CREATE TABLE mute (
    mute_id INTEGER PRIMARY KEY AUTOINCREMENT,
    muter_id INTEGER,
    mutee_id INTEGER,
    created_at DATETIME,
    FOREIGN KEY(muter_id) REFERENCES user(user_id),
    FOREIGN KEY(mutee_id) REFERENCES user(user_id)
);
