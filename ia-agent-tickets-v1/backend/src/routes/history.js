import { Router } from 'express';
import db from '../db/initDb.js';

const router = Router();

// GET /api/tickets/:id/history - Historial de un ticket
router.get('/:id/history', (req, res) => {
  try {
    const ticket = db.prepare('SELECT id FROM tickets WHERE id = ?').get(req.params.id);
    if (!ticket) {
      return res.status(404).json({ error: 'Ticket no encontrado' });
    }
    
    const history = db.prepare(`
      SELECT h.*, u.nombre as usuario_nombre, u.cargo as usuario_cargo, u.rol as usuario_rol
      FROM ticket_history h
      LEFT JOIN users u ON h.user_id = u.id
      WHERE h.ticket_id = ?
      ORDER BY h.fecha DESC
    `).all(req.params.id);
    
    res.json(history);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
