import { getDb, saveDatabase } from '../config/database.js';

export function initTokenUsageTable() {
  const db = getDb();
  if (!db) return;
  
  db.run(`
    CREATE TABLE IF NOT EXISTS token_usage (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      conversation_id INTEGER,
      model TEXT NOT NULL,
      prompt_tokens INTEGER NOT NULL DEFAULT 0,
      completion_tokens INTEGER NOT NULL DEFAULT 0,
      total_tokens INTEGER NOT NULL DEFAULT 0,
      confidence_score REAL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    )
  `);
  
  saveDatabase();
}

export function recordTokenUsage(data) {
  const db = getDb();
  if (!db) return null;
  
  const stmt = db.prepare(`
    INSERT INTO token_usage (session_id, conversation_id, model, prompt_tokens, completion_tokens, total_tokens, confidence_score)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);
  
  stmt.bind([
    data.sessionId,
    data.conversationId || null,
    data.model,
    data.promptTokens || 0,
    data.completionTokens || 0,
    data.totalTokens || 0,
    data.confidenceScore || null
  ]);
  
  stmt.step();
  stmt.free();
  
  saveDatabase();
  
  return { ...data };
}

export function getTotalTokenUsage() {
  const db = getDb();
  if (!db) return null;
  
  const stmt = db.prepare(`
    SELECT 
      COUNT(*) as total_requests,
      SUM(prompt_tokens) as total_prompt_tokens,
      SUM(completion_tokens) as total_completion_tokens,
      SUM(total_tokens) as total_tokens,
      AVG(confidence_score) as avg_confidence
    FROM token_usage
  `);
  
  stmt.step();
  const result = stmt.getAsObject();
  stmt.free();
  
  return result;
}

export function getTokenUsageBySession(sessionId) {
  const db = getDb();
  if (!db) return null;
  
  const stmt = db.prepare(`
    SELECT 
      session_id,
      COUNT(*) as requests,
      SUM(prompt_tokens) as prompt_tokens,
      SUM(completion_tokens) as completion_tokens,
      SUM(total_tokens) as total_tokens,
      AVG(confidence_score) as avg_confidence,
      MIN(created_at) as first_request,
      MAX(created_at) as last_request
    FROM token_usage
    WHERE session_id = ?
    GROUP BY session_id
  `);
  
  stmt.bind([sessionId]);
  stmt.step();
  const result = stmt.getAsObject();
  stmt.free();
  
  return result;
}

export function getTokenUsageByModel() {
  const db = getDb();
  if (!db) return [];
  
  const stmt = db.prepare(`
    SELECT 
      model,
      COUNT(*) as requests,
      SUM(prompt_tokens) as prompt_tokens,
      SUM(completion_tokens) as completion_tokens,
      SUM(total_tokens) as total_tokens,
      AVG(confidence_score) as avg_confidence
    FROM token_usage
    GROUP BY model
    ORDER BY total_tokens DESC
  `);
  
  const results = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  
  return results;
}

export function getRecentTokenUsage(limit = 50) {
  const db = getDb();
  if (!db) return [];
  
  const stmt = db.prepare(`
    SELECT * FROM token_usage
    ORDER BY created_at DESC
    LIMIT ?
  `);
  
  stmt.bind([limit]);
  const results = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  
  return results;
}

export function getDailyTokenUsage(days = 7) {
  const db = getDb();
  if (!db) return [];
  
  const stmt = db.prepare(`
    SELECT 
      DATE(created_at) as date,
      COUNT(*) as requests,
      SUM(prompt_tokens) as prompt_tokens,
      SUM(completion_tokens) as completion_tokens,
      SUM(total_tokens) as total_tokens
    FROM token_usage
    WHERE created_at >= DATE('now', ? || ' days')
    GROUP BY DATE(created_at)
    ORDER BY date DESC
  `);
  
  stmt.bind([`-${days}`]);
  const results = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  
  return results;
}

export function clearTokenUsage() {
  const db = getDb();
  if (!db) return;
  
  db.run('DELETE FROM token_usage');
  saveDatabase();
}

export function getSessionStats() {
  const db = getDb();
  if (!db) return [];
  
  const stmt = db.prepare(`
    SELECT 
      session_id,
      COUNT(*) as requests,
      SUM(total_tokens) as total_tokens,
      AVG(confidence_score) as avg_confidence,
      MAX(created_at) as last_active
    FROM token_usage
    GROUP BY session_id
    ORDER BY last_active DESC
    LIMIT 20
  `);
  
  const results = [];
  while (stmt.step()) {
    results.push(stmt.getAsObject());
  }
  stmt.free();
  
  return results;
}
