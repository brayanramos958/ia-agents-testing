import express from 'express';
import cors from 'cors';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

// Initialize database (creates tables and seed data)
import './db/initDb.js';

import usersRouter from './routes/users.js';
import ticketsRouter from './routes/tickets.js';
import historyRouter from './routes/history.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Routes
app.use('/api/users', usersRouter);
app.use('/api/tickets', ticketsRouter);
app.use('/api/tickets', historyRouter);

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.listen(PORT, () => {
  console.log(`🚀 Backend running on http://localhost:${PORT}`);
  console.log(`   Health: http://localhost:${PORT}/api/health`);
});
