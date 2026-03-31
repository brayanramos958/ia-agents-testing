import { Router } from 'express';
import db from '../db/initDb.js';
import { requireRole } from '../middleware/roleAuth.js';

const router = Router();

// Helper para registrar historial
const logHistory = (ticketId, accion, detalle, userId) => {
  db.prepare(`
    INSERT INTO ticket_history (ticket_id, accion, detalle, user_id, fecha)
    VALUES (?, ?, ?, ?, ?)
  `).run(ticketId, accion, detalle, userId, new Date().toISOString());
};

// GET /api/tickets - Listar tickets (con filtros opcionales)
router.get('/', (req, res) => {
  try {
    const { estado, urgencia, prioridad, asignado_a, categoria } = req.query;
    
    let query = `
      SELECT t.*, u.nombre as asignado_nombre, u.cargo as asignado_cargo
      FROM tickets t
      LEFT JOIN users u ON t.asignado_a = u.id
      WHERE 1=1
    `;
    const params = [];
    
    if (estado) {
      query += ' AND t.estado = ?';
      params.push(estado);
    }
    if (urgencia) {
      query += ' AND t.urgencia = ?';
      params.push(urgencia);
    }
    if (prioridad) {
      query += ' AND t.prioridad = ?';
      params.push(prioridad);
    }
    if (asignado_a) {
      query += ' AND t.asignado_a = ?';
      params.push(asignado_a);
    }
    if (categoria) {
      query += ' AND t.categoria = ?';
      params.push(categoria);
    }
    
    query += ' ORDER BY t.created_at DESC';
    
    const tickets = db.prepare(query).all(...params);
    res.json(tickets);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// GET /api/tickets/:id - Obtener un ticket
router.get('/:id', (req, res) => {
  try {
    const ticket = db.prepare(`
      SELECT t.*, u.nombre as asignado_nombre, u.cargo as asignado_cargo,
             c.nombre as creador_nombre
      FROM tickets t
      LEFT JOIN users u ON t.asignado_a = u.id
      LEFT JOIN users c ON t.created_by = c.id
      WHERE t.id = ?
    `).get(req.params.id);
    
    if (!ticket) {
      return res.status(404).json({ error: 'Ticket no encontrado' });
    }
    
    res.json(ticket);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// POST /api/tickets - Crear ticket (solo creadores)
router.post('/', requireRole('creador'), (req, res) => {
  try {
    const { 
      tipo_requerimiento, categoria, descripcion, urgencia, impacto, prioridad, asignado_a 
    } = req.body;
    
    if (!tipo_requerimiento || !categoria || !urgencia || !impacto || !prioridad) {
      return res.status(400).json({ error: 'Faltan campos requeridos' });
    }
    
    const result = db.prepare(`
      INSERT INTO tickets (tipo_requerimiento, categoria, descripcion, urgencia, impacto, prioridad, asignado_a, estado, created_by)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      tipo_requerimiento,
      categoria,
      descripcion || '',
      urgencia,
      impacto,
      prioridad,
      asignado_a || null,
      asignado_a ? 'asignado' : 'abierto',
      req.user.id
    );
    
    logHistory(result.lastInsertRowid, 'creado', `Ticket creado por ${req.user.id}`, req.user.id);
    
    const ticket = db.prepare('SELECT * FROM tickets WHERE id = ?').get(result.lastInsertRowid);
    res.status(201).json(ticket);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// PUT /api/tickets/:id - Actualizar ticket
router.put('/:id', requireRole('creador', 'supervisor'), (req, res) => {
  try {
    const { tipo_requerimiento, categoria, urgencia, impacto, prioridad } = req.body;
    
    const ticket = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    if (!ticket) {
      return res.status(404).json({ error: 'Ticket no encontrado' });
    }
    
    db.prepare(`
      UPDATE tickets 
      SET tipo_requerimiento = COALESCE(?, tipo_requerimiento),
          categoria = COALESCE(?, categoria),
          urgencia = COALESCE(?, urgencia),
          impacto = COALESCE(?, impacto),
          prioridad = COALESCE(?, prioridad),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(
      tipo_requerimiento,
      categoria,
      urgencia,
      impacto,
      prioridad,
      req.params.id
    );
    
    logHistory(req.params.id, 'actualizado', `Ticket actualizado por ${req.user.id}`, req.user.id);
    
    const updated = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    res.json(updated);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// PUT /api/tickets/:id/assign - Asignar ticket (solo supervisor)
router.put('/:id/assign', requireRole('supervisor'), (req, res) => {
  try {
    const { asignado_a } = req.body;
    const userToAssign = db.prepare('SELECT * FROM users WHERE id = ? AND rol = ?')
      .get(asignado_a, 'resueltor');
    
    if (!userToAssign) {
      return res.status(400).json({ error: 'Debe asignar a un resolutor válido' });
    }
    
    db.prepare(`
      UPDATE tickets 
      SET asignado_a = ?, estado = 'asignado', updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(asignado_a, req.params.id);
    
    logHistory(req.params.id, 'asignado', `Asignado a ${userToAssign.nombre}`, req.user.id);
    
    const updated = db.prepare(`
      SELECT t.*, u.nombre as asignado_nombre 
      FROM tickets t 
      LEFT JOIN users u ON t.asignado_a = u.id 
      WHERE t.id = ?
    `).get(req.params.id);
    
    res.json(updated);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// PUT /api/tickets/:id/resolve - Resolver ticket (solo resolutor)
router.put('/:id/resolve', requireRole('resueltor'), (req, res) => {
  try {
    const { resolucion } = req.body;
    
    const ticket = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    if (!ticket) {
      return res.status(404).json({ error: 'Ticket no encontrado' });
    }
    
    if (ticket.estado === 'cerrado') {
      return res.status(400).json({ error: 'No se puede resolver un ticket cerrado' });
    }
    
    db.prepare(`
      UPDATE tickets 
      SET estado = 'resuelto', 
          resolucion = COALESCE(?, ''),
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(resolucion || '', req.params.id);
    
    logHistory(req.params.id, 'resuelto', `Resuelto por ${req.user.id}`, req.user.id);
    
    const updated = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    res.json(updated);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// PUT /api/tickets/:id/reopen - Reabrir ticket (solo supervisor)
router.put('/:id/reopen', requireRole('supervisor'), (req, res) => {
  try {
    const { motivo } = req.body;
    
    const ticket = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    if (!ticket) {
      return res.status(404).json({ error: 'Ticket no encontrado' });
    }
    
    db.prepare(`
      UPDATE tickets 
      SET estado = 'abierto', 
          resolucion = '',
          updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(req.params.id);
    
    logHistory(req.params.id, 'reabierto', `Reabierto por ${req.user.id}. Motivo: ${motivo || 'Sin motivo'}`, req.user.id);
    
    const updated = db.prepare('SELECT * FROM tickets WHERE id = ?').get(req.params.id);
    res.json(updated);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
