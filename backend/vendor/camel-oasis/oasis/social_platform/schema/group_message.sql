CREATE TABLE IF NOT EXISTS group_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES chat_group(group_id),
    FOREIGN KEY (sender_id) REFERENCES user(agent_id)
);
