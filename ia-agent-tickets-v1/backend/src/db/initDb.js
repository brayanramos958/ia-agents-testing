import Database from 'better-sqlite3';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const db = new Database(join(__dirname, 'database.sqlite'));

// Enable foreign keys
db.pragma('foreign_keys = ON');

// Create tables
db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    cargo TEXT NOT NULL,
    area TEXT NOT NULL,
    correo TEXT NOT NULL UNIQUE,
    rol TEXT NOT NULL CHECK(rol IN ('creador', 'resueltor', 'supervisor'))
  );

  CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_requerimiento TEXT NOT NULL,
    categoria TEXT NOT NULL,
    descripcion TEXT DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'abierto' CHECK(estado IN ('abierto', 'asignado', 'resuelto', 'cerrado')),
    asignado_a INTEGER,
    urgencia TEXT NOT NULL CHECK(urgencia IN ('baja', 'media', 'alta', 'critica')),
    impacto TEXT NOT NULL CHECK(impacto IN ('bajo', 'medio', 'alto')),
    prioridad TEXT NOT NULL CHECK(prioridad IN ('baja', 'media', 'alta', 'urgente')),
    resolucion TEXT DEFAULT '',
    created_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (asignado_a) REFERENCES users(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS ticket_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL,
    accion TEXT NOT NULL CHECK(accion IN ('creado', 'asignado', 'resuelto', 'reabierto', 'actualizado')),
    detalle TEXT,
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
  );
`);

// Seed data
const existingUsers = db.prepare('SELECT COUNT(*) as count FROM users').get();
if (existingUsers.count === 0) {
  console.log('Inserting seed data...');

  const insertUser = db.prepare(`
    INSERT INTO users (nombre, cargo, area, correo, rol)
    VALUES (?, ?, ?, ?, ?)
  `);

  const users = [
    ['Ana García', 'Soporte TI', 'Tecnología', 'creadorti@empresa.com', 'creador'],
    ['Carlos López', 'Técnico TI', 'Tecnología', 'tecnicoti@empresa.com', 'resueltor'],
    ['María Rodríguez', 'Supervisor TI', 'Tecnología', 'supervisorti@empresa.com', 'supervisor']
  ];

  users.forEach(u => insertUser.run(...u));

  const insertTicket = db.prepare(`
    INSERT INTO tickets (tipo_requerimiento, categoria, descripcion, estado, asignado_a, urgencia, impacto, prioridad, created_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const insertHistory = db.prepare(`
    INSERT INTO ticket_history (ticket_id, accion, detalle, user_id, fecha)
    VALUES (?, ?, ?, ?, ?)
  `);

  const now = new Date().toISOString();
  const tickets = [
    ['Incidente', 'Hardware', 'La computadora no enciende desde ayer', 'abierto', null, 'alta', 'alto', 'urgente', 1, now],
    ['Solicitud', 'Software', 'Necesito instalar Microsoft Office en mi equipo', 'abierto', null, 'baja', 'medio', 'baja', 1, now],
    ['Incidente', 'Red', 'No tengo acceso a internet desde esta mañana', 'asignado', 2, 'media', 'medio', 'media', 1, now]
  ];

  tickets.forEach(t => {
    const result = insertTicket.run(...t);
    const ticketId = result.lastInsertRowid;
    insertHistory.run(ticketId, 'creado', `Ticket creado`, 1, now);
  });

  console.log('Seed data inserted successfully');
}

export default db;
