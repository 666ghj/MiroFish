-- This is the schema definition for the trace table
CREATE TABLE trace (
    user_id INTEGER,
    created_at DATETIME,
    action TEXT,
    info TEXT,
    PRIMARY KEY(user_id, created_at, action, info),
    FOREIGN KEY(user_id) REFERENCES user(user_id)
);
