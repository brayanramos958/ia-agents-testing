import express from 'express';
import { sendMessageToAgent, initGroqClient, getGroqClient, getCurrentSessionId, newSession, getAvailableModels } from '../services/agentService.js';
import { createConversation, getAllConversations, clearAllConversations } from '../models/conversation.js';
import { createCorrection, getAllCorrections, clearAllCorrections } from '../models/correction.js';
import { getLearnedFacts, clearAllLearnedFacts, addOrUpdateLearnedFact } from '../models/learnedFacts.js';
import { extractFactsFromCorrection, clearShortTermMemory } from '../services/memoryService.js';
import { 
  getTotalTokenUsage, 
  getTokenUsageBySession, 
  getTokenUsageByModel, 
  getRecentTokenUsage, 
  getDailyTokenUsage, 
  clearTokenUsage, 
  getSessionStats 
} from '../models/tokenUsage.js';
import 'dotenv/config';

const router = express.Router();

router.post('/chat', async (req, res) => {
  try {
    const { 
      message, 
      model, 
      temperature, 
      max_tokens, 
      top_p, 
      strictMode,
      conversationId 
    } = req.body;
    
    if (!message || message.trim() === '') {
      return res.status(400).json({ error: 'Message is required' });
    }
    
    const groqClient = getGroqClient();
    if (!groqClient) {
      return res.status(500).json({ error: 'Groq client not initialized' });
    }
    
    const result = await sendMessageToAgent(message, model, {
      temperature: temperature !== undefined ? parseFloat(temperature) : null,
      max_tokens: max_tokens !== undefined ? parseInt(max_tokens) : null,
      top_p: top_p !== undefined ? parseFloat(top_p) : null,
      strictMode: strictMode === true || strictMode === 'true',
      conversationId
    });
    
    const conversation = createConversation(message, result.response);
    
    res.json({
      response: result.response,
      conversationId: conversation.id,
      model: result.model,
      usage: result.usage,
      confidence: result.confidence,
      validation: result.validation,
      parameters: result.parameters,
      sessionId: getCurrentSessionId()
    });
  } catch (error) {
    console.error('Error in /chat:', error);
    res.status(500).json({ error: error.message });
  }
});

router.post('/correct', async (req, res) => {
  try {
    const { conversationId, userCorrection, userMessage, agentResponse } = req.body;
    
    if (!conversationId || !userCorrection) {
      return res.status(400).json({ error: 'conversationId and userCorrection are required' });
    }
    
    const correction = createCorrection(
      conversationId,
      userMessage || '',
      agentResponse || '',
      userCorrection
    );
    
    const facts = extractFactsFromCorrection(userMessage, agentResponse, userCorrection);
    facts.forEach(fact => {
      addOrUpdateLearnedFact(fact.fact, fact.category);
    });
    
    res.json({
      success: true,
      correction,
      factsExtracted: facts.length
    });
  } catch (error) {
    console.error('Error in /correct:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/conversations', (req, res) => {
  try {
    const conversations = getAllConversations();
    res.json({ conversations });
  } catch (error) {
    console.error('Error in /conversations:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/corrections', (req, res) => {
  try {
    const corrections = getAllCorrections();
    res.json({ corrections });
  } catch (error) {
    console.error('Error in /corrections:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/learnings', (req, res) => {
  try {
    const corrections = getAllCorrections();
    const facts = getLearnedFacts();
    res.json({ corrections, facts });
  } catch (error) {
    console.error('Error in /learnings:', error);
    res.status(500).json({ error: error.message });
  }
});

router.delete('/reset', (req, res) => {
  try {
    clearAllConversations();
    clearAllCorrections();
    clearAllLearnedFacts();
    clearShortTermMemory();
    
    res.json({ success: true, message: 'All memory has been reset' });
  } catch (error) {
    console.error('Error in /reset:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/health', (req, res) => {
  const groqClient = getGroqClient();
  res.json({
    status: 'ok',
    groqInitialized: !!groqClient,
    sessionId: getCurrentSessionId(),
    timestamp: new Date().toISOString()
  });
});

// Token usage endpoints
router.get('/tokens', (req, res) => {
  try {
    const total = getTotalTokenUsage();
    const byModel = getTokenUsageByModel();
    const recent = getRecentTokenUsage(10);
    
    res.json({
      total,
      byModel,
      recent
    });
  } catch (error) {
    console.error('Error in /tokens:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/tokens/session/:sessionId', (req, res) => {
  try {
    const { sessionId } = req.params;
    const usage = getTokenUsageBySession(sessionId);
    res.json({ session: usage });
  } catch (error) {
    console.error('Error in /tokens/session:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/tokens/session', (req, res) => {
  try {
    const currentId = getCurrentSessionId();
    const usage = getTokenUsageBySession(currentId);
    res.json({ session: usage, sessionId: currentId });
  } catch (error) {
    console.error('Error in /tokens/session:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/tokens/models', (req, res) => {
  try {
    const byModel = getTokenUsageByModel();
    res.json({ models: byModel });
  } catch (error) {
    console.error('Error in /tokens/models:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/tokens/daily', (req, res) => {
  try {
    const days = parseInt(req.query.days) || 7;
    const daily = getDailyTokenUsage(days);
    res.json({ daily });
  } catch (error) {
    console.error('Error in /tokens/daily:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/tokens/sessions', (req, res) => {
  try {
    const sessions = getSessionStats();
    res.json({ sessions });
  } catch (error) {
    console.error('Error in /tokens/sessions:', error);
    res.status(500).json({ error: error.message });
  }
});

router.post('/tokens/reset', (req, res) => {
  try {
    clearTokenUsage();
    res.json({ success: true, message: 'Token usage data has been cleared' });
  } catch (error) {
    console.error('Error in /tokens/reset:', error);
    res.status(500).json({ error: error.message });
  }
});

router.post('/session/new', (req, res) => {
  try {
    const newSessionId = newSession();
    res.json({ success: true, sessionId: newSessionId });
  } catch (error) {
    console.error('Error in /session/new:', error);
    res.status(500).json({ error: error.message });
  }
});

router.get('/models', (req, res) => {
  try {
    const models = getAvailableModels();
    res.json({ models });
  } catch (error) {
    console.error('Error in /models:', error);
    res.status(500).json({ error: error.message });
  }
});

export default router;
