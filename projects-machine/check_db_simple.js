const initSqlJs = require('sql.js');
const fs = require('fs');
const path = require('path');

const DB_PATH = path.join(__dirname, 'backend', 'data', 'agente.db');

async function checkDatabase() {
  try {
    const SQL = await initSqlJs();
    let db;
    if (fs.existsSync(DB_PATH)) {
      const buffer = fs.readFileSync(DB_PATH);
      db = new SQL.Database(buffer);
    } else {
      db = new SQL.Database();
    }
    
    // Get list of tables
    const tables = db.exec("SELECT name FROM sqlite_master WHERE type='table'");
    console.log('Tables in database:');
    tables[0].values.forEach(row => {
      console.log('  -', row[0]);
    });
    
    // Check if token_usage table exists
    const tokenUsageExists = db.exec("SELECT name FROM sqlite_master WHERE type='table' AND name='token_usage'");
    if (tokenUsageExists.length > 0 && tokenUsageExists[0].values.length > 0) {
      console.log('\nToken usage table EXISTS');
      
      // Check schema
      const schema = db.exec("PRAGMA table_info(token_usage)");
      console.log('\nToken usage table schema:');
      schema[0].values.forEach(row => {
        console.log('  ' + row[1] + ' ' + row[2] + (row[3] ? ' NOT NULL' : ' NULL') + (row[4] ? ' DEFAULT ' + row[4] : '') + (row[5] ? ' PK' : ''));
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