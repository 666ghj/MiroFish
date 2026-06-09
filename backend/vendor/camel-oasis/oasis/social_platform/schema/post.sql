-- This is the schema definition for the post table
-- Add Images, location etc.?
CREATE TABLE post (
    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    original_post_id INTEGER,  -- NULL if this is an original post
    content TEXT DEFAULT '',  -- DEFAULT '' for initial posts
    quote_content TEXT,  -- NULL if this is an original post or a repost
    created_at DATETIME,
    num_likes INTEGER DEFAULT 0,
    num_dislikes INTEGER DEFAULT 0,
    num_shares INTEGER DEFAULT 0,  -- num_shares = num_reposts + num_quotes
    num_reports INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES user(user_id),
    FOREIGN KEY(original_post_id) REFERENCES post(post_id)
);
