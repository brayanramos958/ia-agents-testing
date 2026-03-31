import { getDb, saveDatabase } from '../config/database.js';

export function createConversation(userMessage, agentResponse) {
  const db = getDb();
  const stmt = db.prepare('INSERT INTO conversations (user_message, agent_response) VALUES (?, ?)');
  stmt.run([userMessage, agentResponse]);
  stmt.free();
  
  const result = db.exec('SELECT last_insert_rowid() as id');
  const id = result[0].values[0][0];
  
  saveDatabase();
  return { id, userMessage, agentResponse };
}

export function getConversation(id) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM conversations WHERE id = ?');
  stmt.bind([id]);
  
  if (stmt.step()) {
    const row = stmt.getAsObject();
    stmt.free();
    return row;
  }
  stmt.free();
  return null;
}

export function getRecentConversations(limit = 10) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM conversations ORDER BY timestamp DESC LIMIT ?');
  stmt.bind([limit]);
  
  const conversations = [];
  while (stmt.step()) {
    conversations.push(stmt.getAsObject());
  }
  stmt.free();
  return conversations;
}

export function getAllConversations() {
  const db = getDb();
  const result = db.exec('SELECT * FROM conversations ORDER BY timestamp DESC');
  
  if (result.length === 0) return [];
  
  const columns = result[0].columns;
  return result[0].values.map(row => {
    const obj = {};
    columns.forEach((col, i) => obj[col] = row[i]);
    return obj;
  });
}

export function deleteConversation(id) {
  const db = getDb();
  db.run('DELETE FROM conversations WHERE id = ?', [id]);
  saveDatabase();
}

export function clearAllConversations() {
  const db = getDb();
  db.run('DELETE FROM conversations');
  saveDatabase();
}
