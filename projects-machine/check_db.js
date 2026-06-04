import initSqlJs from 'sql.js';
import fs from 'fs';
import path from 'path';

const DB_PATH = path.join(process.cwd(), 'backend', 'data', 'agente.db');

async function checkDatabase() {
  try {
    const SQL = await initSqlJs();
    const buffer = fs.readFileSync(DB_PATH);
    const db = new SQL.Database(buffer);
    
    // Get list of tables
    const tables = db.exec("SELECT name FROM sqlite_master WHERE type='table'");
    console.log('Tables in database:');
    tables[0].values.forEach(row => {
      console.log(`  - ${row[0]}`);
    });
    
    // Check if token_usage table exists
    const tokenUsageExists = db.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='token_usage'");
    if (tokenUsageExists.length > 0 && tokenUsageExists[0].values.length > 0) {
      console.log('\nToken usage table EXISTS');
      
      // Check schema
      const schema = db.exec("PRAGMA table_info(token_usage)");
      console.log('\nToken usage table schema:');
      schema[0].values.forEach(row => {
        console.log(`  ${row[1]} ${row[2]} ${row[3] ? 'NOT NULL' : 'NULL'} ${row[4] || ''} ${row[5]}`);
      });
    } else {
      console.log('\nToken usage table DOES NOT EXIST');
    }
    
    db.close();
  } catch (error) {
    console.error('Error checking database:', error);
  }
}

checkDatabase();