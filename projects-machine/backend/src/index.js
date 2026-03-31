import express from 'express';
import cors from 'cors';
import { initDatabase, closeDatabase } from './config/database.js';
import { initGroqClient } from './services/agentService.js';
import apiRoutes from './routes/api.js';
import 'dotenv/config';

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

app.use('/api', apiRoutes);

app.get('/', (req, res) => {
  res.json({
    name: 'Agente de Aprendizaje API',
    version: '1.0.0',
    endpoints: {
      chat: 'POST /api/chat',
      correct: 'POST /api/correct',
      conversations: 'GET /api/conversations',
      corrections: 'GET /api/corrections',
      learnings: 'GET /api/learnings',
      reset: 'DELETE /api/reset',
      health: 'GET /api/health'
    }
  });
});

async function startServer() {
  try {
    console.log('Initializing database...');
    await initDatabase();
    console.log('Database initialized successfully');
    
    const apiKey = process.env.GROQ_API_KEY;
    if (!apiKey || apiKey === 'tu_clave_api_aqui') {
      console.warn('WARNING: GROQ_API_KEY not configured in .env file');
      console.warn('Please add your Groq API key to backend/.env');
    } else {
      console.log('Initializing Groq client...');
      initGroqClient(apiKey);
      console.log('Groq client initialized successfully');
    }
    
    app.listen(PORT, () => {
      console.log(`Server running on http://localhost:${PORT}`);
      console.log(`API Documentation: http://localhost:${PORT}/`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

process.on('SIGINT', () => {
  console.log('\nShutting down gracefully...');
  closeDatabase();
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\nShutting down gracefully...');
  closeDatabase();
  process.exit(0);
});

startServer();
