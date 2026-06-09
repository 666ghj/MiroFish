-- This is the schema definition for the rec table
CREATE TABLE rec (
    user_id INTEGER,
    post_id INTEGER,
    PRIMARY KEY(user_id, post_id),
    FOREIGN KEY(user_id) REFERENCES user(user_id)
    FOREIGN KEY(post_id) REFERENCES tweet(post_id)
);
