import { getDb, saveDatabase } from '../config/database.js';

export function createCorrection(conversationId, userMessage, agentResponse, userCorrection) {
  const db = getDb();
  const stmt = db.prepare(
    'INSERT INTO corrections (conversation_id, user_message, agent_response, user_correction) VALUES (?, ?, ?, ?)'
  );
  stmt.run([conversationId, userMessage, agentResponse, userCorrection]);
  stmt.free();
  
  const result = db.exec('SELECT last_insert_rowid() as id');
  const id = result[0].values[0][0];
  
  saveDatabase();
  return { id, conversationId, userMessage, agentResponse, userCorrection };
}

export function getCorrectionsByConversation(conversationId) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM corrections WHERE conversation_id = ? ORDER BY timestamp DESC');
  stmt.bind([conversationId]);
  
  const corrections = [];
  while (stmt.step()) {
    corrections.push(stmt.getAsObject());
  }
  stmt.free();
  return corrections;
}

export function getAllCorrections() {
  const db = getDb();
  const result = db.exec('SELECT * FROM corrections ORDER BY timestamp DESC');
  
  if (result.length === 0) return [];
  
  const columns = result[0].columns;
  return result[0].values.map(row => {
    const obj = {};
    columns.forEach((col, i) => obj[col] = row[i]);
    return obj;
  });
}

export function getRecentCorrections(limit = 20) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM corrections ORDER BY timestamp DESC LIMIT ?');
  stmt.bind([limit]);
  
  const corrections = [];
  while (stmt.step()) {
    corrections.push(stmt.getAsObject());
  }
  stmt.free();
  return corrections;
}

export function deleteCorrection(id) {
  const db = getDb();
  db.run('DELETE FROM corrections WHERE id = ?', [id]);
  saveDatabase();
}

export function clearAllCorrections() {
  const db = getDb();
  db.run('DELETE FROM corrections');
  saveDatabase();
}
