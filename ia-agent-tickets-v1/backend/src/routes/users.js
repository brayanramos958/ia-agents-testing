import { Router } from 'express';
import db from '../db/initDb.js';

const router = Router();

// GET /api/users - Listar todos los usuarios
router.get('/', (req, res) => {
  try {
    const { rol } = req.query;
    
    let query = 'SELECT id, nombre, cargo, area, correo, rol FROM users';
    const params = [];
    
    if (rol) {
      query += ' WHERE rol = ?';
      params.push(rol);
    }
    
    query += ' ORDER BY nombre';
    const users = db.prepare(query).all(...params);
    
    res.json(users);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// GET /api/users/:id - Obtener un usuario
router.get('/:id', (req, res) => {
  try {
    const user = db.prepare(
      'SELECT id, nombre, cargo, area, correo, rol FROM users WHERE id = ?'
    ).get(req.params.id);
    
    if (!user) {
      return res.status(404).json({ error: 'Usuario no encontrado' });
    }
    
    res.json(user);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

export default router;
