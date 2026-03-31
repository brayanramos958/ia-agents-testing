const initSqlJs = require('./backend/node_modules/sql.js/dist/sql-wasm.js');
const fs = require('fs');
const path = require('path');

async function debugSql() {
  try {
    const SQL = await initSqlJs();
    const db = new SQL.Database();
    
    console.log('Testing SQL statement...');
    const sql = `
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
    `;
    
    console.log('SQL to execute:');
    console.log(sql.replace(/\s+/g, ' ').trim());
    
    try {
      db.run(sql);
      console.log('CREATE TABLE executed without error');
    } catch (runError) {
      console.log('Error during CREATE TABLE:', runError.message);
      console.log('Error stack:', runError.stack);
    }
    
    // Check what tables we have
    const tables = db.exec("SELECT name FROM sqlite_master WHERE type='table'");
    console.log('\nTables in database:');
    tables[0].values.forEach(row => {
      console.log('  -', row[0]);
    });
    
    // Check specifically for token_usage
    const tokenCheck = db.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='token_usage'");
    console.log('\nToken usage table check:', tokenCheck.length > 0 && tokenCheck[0].values.length > 0 ? 'EXISTS' : 'NOT FOUND');
    
    if (tokenCheck.length > 0 && tokenCheck[0].values.length > 0) {
      const schema = db.exec('PRAGMA table_info(token_usage)');
      console.log('\nToken usage schema:');
      schema[0].values.forEach(row => {
        console.log('  ' + row[1] + ' ' + row[2] + (row[3] ? ' NOT NULL' : ' NULL'));
      });
    }
    
  } catch (error) {
    console.error('Error in debugSql:', error);
    console.error('Error stack:', error.stack);
  }
}

debugSql();