import { getDb, saveDatabase } from '../config/database.js';

export function addOrUpdateLearnedFact(fact, category = null) {
  const db = getDb();
  
  const existingStmt = db.prepare('SELECT * FROM learned_facts WHERE fact = ?');
  existingStmt.bind([fact]);
  
  if (existingStmt.step()) {
    const existing = existingStmt.getAsObject();
    existingStmt.free();
    
    const updateStmt = db.prepare(`
      UPDATE learned_facts 
      SET times_confirmed = times_confirmed + 1, 
          confidence_score = MIN(1.0, confidence_score + 0.1),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `);
    updateStmt.run([existing.id]);
    updateStmt.free();
    
    saveDatabase();
    return { ...existing, times_confirmed: existing.times_confirmed + 1 };
  }
  existingStmt.free();
  
  const insertStmt = db.prepare(
    'INSERT INTO learned_facts (fact, category, confidence_score, times_confirmed) VALUES (?, ?, 0.6, 1)'
  );
  insertStmt.run([fact, category]);
  insertStmt.free();
  
  const result = db.exec('SELECT last_insert_rowid() as id');
  const id = result[0].values[0][0];
  
  saveDatabase();
  return { id, fact, category, confidence_score: 0.6, times_confirmed: 1 };
}

export function getLearnedFacts(limit = 50) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM learned_facts ORDER BY confidence_score DESC, times_confirmed DESC LIMIT ?');
  stmt.bind([limit]);
  
  const facts = [];
  while (stmt.step()) {
    facts.push(stmt.getAsObject());
  }
  stmt.free();
  return facts;
}

export function getLearnedFactsByCategory(category) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM learned_facts WHERE category = ? ORDER BY confidence_score DESC');
  stmt.bind([category]);
  
  const facts = [];
  while (stmt.step()) {
    facts.push(stmt.getAsObject());
  }
  stmt.free();
  return facts;
}

export function getHighConfidenceFacts(minConfidence = 0.7) {
  const db = getDb();
  const stmt = db.prepare('SELECT * FROM learned_facts WHERE confidence_score >= ? ORDER BY confidence_score DESC');
  stmt.bind([minConfidence]);
  
  const facts = [];
  while (stmt.step()) {
    facts.push(stmt.getAsObject());
  }
  stmt.free();
  return facts;
}

export function updateFactConfidence(id, confidenceScore) {
  const db = getDb();
  const stmt = db.prepare('UPDATE learned_facts SET confidence_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?');
  stmt.run([confidenceScore, id]);
  stmt.free();
  saveDatabase();
}

export function deleteLearnedFact(id) {
  const db = getDb();
  db.run('DELETE FROM learned_facts WHERE id = ?', [id]);
  saveDatabase();
}

export function clearAllLearnedFacts() {
  const db = getDb();
  db.run('DELETE FROM learned_facts');
  saveDatabase();
}
