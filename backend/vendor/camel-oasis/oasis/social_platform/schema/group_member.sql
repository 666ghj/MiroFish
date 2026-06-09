CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, agent_id),
    FOREIGN KEY (group_id) REFERENCES chat_group(group_id)
);
