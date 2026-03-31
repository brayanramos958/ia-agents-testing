import Groq from 'groq-sdk';
import crypto from 'crypto';
import { buildContextForLLM, addToShortTermMemory, clearShortTermMemory, getShortTermMemory } from './memoryService.js';
import { validateResponse, shouldRegenerateResponse, getConstraintPrompt } from './validationService.js';
import { recordTokenUsage } from '../models/tokenUsage.js';

import { promptKnowledgeBase } from '../config/prompts.js';

let groqClient = null;
let currentSessionId = null;

export function initGroqClient(apiKey) {
  groqClient = new Groq({ apiKey, dangerouslyAllowBrowser: true });
  currentSessionId = crypto.randomUUID();
  return groqClient;
}

export function getGroqClient() {
  return groqClient;
}

export function getCurrentSessionId() {
  return currentSessionId || 'default';
}

export function newSession() {
  currentSessionId = crypto.randomUUID();
  clearShortTermMemory();
  return currentSessionId;
}

const DEFAULT_MODEL = 'llama-3.1-8b-instant';

const MODEL_OPTIONS = {
  'llama-3.1-8b-instant': { temperature: 0.5, max_tokens: 1024 },
  'llama-3.3-70b-versatile': { temperature: 0.6, max_tokens: 2048 },
  'openai/gpt-oss-120b': { temperature: 0.5, max_tokens: 2048 },
  'openai/gpt-oss-20b': { temperature: 0.5, max_tokens: 1024 }
};

export async function sendMessageToAgent(userMessage, model = DEFAULT_MODEL, options = {}) {
  if (!groqClient) {
    throw new Error('Groq client not initialized. Please set GROQ_API_KEY in .env');
  }

  const {
    temperature = null,
    max_tokens = null,
    top_p = null,
    strictMode = false,
    conversationId = null
  } = options;

  const contextPrompt = buildContextForLLM(strictMode);
  const constraintPrompt = getConstraintPrompt(strictMode);

  const modelDefaults = MODEL_OPTIONS[model] || MODEL_OPTIONS[DEFAULT_MODEL];
  const finalTemperature = temperature !== null ? temperature : (strictMode ? 0.3 : modelDefaults.temperature);
  const finalMaxTokens = max_tokens !== null ? max_tokens : modelDefaults.max_tokens;
  const finalTopP = top_p !== null ? top_p : 0.95;

  const messages = [
    { role: 'system', content: contextPrompt + promptKnowledgeBase + '\n' + constraintPrompt },
    { role: 'user', content: userMessage }
  ];

  const chatCompletion = await groqClient.chat.completions.create({
    messages,
    model,
    temperature: finalTemperature,
    max_tokens: finalMaxTokens,
    top_p: finalTopP,
    stream: false
  });

  let agentResponse = chatCompletion.choices[0]?.message?.content || 'Lo siento, no pude generar una respuesta.';

  const usage = chatCompletion.usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };

  const validation = validateResponse(agentResponse, userMessage, { strictMode });

  if (strictMode && shouldRegenerateResponse(validation, { strictMode: true })) {
    const strictMessages = [
      { role: 'system', content: contextPrompt + '\n' + getConstraintPrompt(true) + '\nTu respuesta anterior fue de baja confianza. Responde SOLO con información verificada.' },
      { role: 'user', content: userMessage }
    ];

    const retryCompletion = await groqClient.chat.completions.create({
      messages: strictMessages,
      model,
      temperature: 0.2,
      max_tokens: finalMaxTokens,
      top_p: 0.9,
      stream: false
    });

    agentResponse = retryCompletion.choices[0]?.message?.content || agentResponse;

    if (retryCompletion.usage) {
      usage.prompt_tokens += retryCompletion.usage.prompt_tokens || 0;
      usage.completion_tokens += retryCompletion.usage.completion_tokens || 0;
      usage.total_tokens += retryCompletion.usage.total_tokens || 0;
    }
  }

  addToShortTermMemory('user', userMessage);
  addToShortTermMemory('assistant', agentResponse);

  if (usage.total_tokens > 0) {
    recordTokenUsage({
      sessionId: getCurrentSessionId(),
      conversationId,
      model,
      promptTokens: usage.prompt_tokens,
      completionTokens: usage.completion_tokens,
      totalTokens: usage.total_tokens,
      confidenceScore: validation.confidence
    });
  }

  return {
    response: agentResponse,
    model: chatCompletion.model,
    usage,
    confidence: validation.confidence,
    validation: {
      valid: validation.valid,
      contradictions: validation.contractions,
      details: validation.details
    },
    parameters: {
      temperature: finalTemperature,
      max_tokens: finalMaxTokens,
      top_p: finalTopP,
      strictMode
    }
  };
}

export async function sendMessageWithHistory(userMessage, history, model = DEFAULT_MODEL, options = {}) {
  if (!groqClient) {
    throw new Error('Groq client not initialized. Please set GROQ_API_KEY in .env');
  }

  clearShortTermMemory();

  history.forEach(msg => {
    addToShortTermMemory(msg.role, msg.content);
  });

  const {
    temperature = null,
    max_tokens = null,
    top_p = null,
    strictMode = false,
    conversationId = null
  } = options;

  const contextPrompt = buildContextForLLM(strictMode);
  const constraintPrompt = getConstraintPrompt(strictMode);

  const memory = getShortTermMemory();
  const messages = [
    { role: 'system', content: contextPrompt + '\n' + constraintPrompt },
    ...memory.map(msg => ({
      role: msg.role,
      content: msg.content
    })),
    { role: 'user', content: userMessage }
  ];

  const modelDefaults = MODEL_OPTIONS[model] || MODEL_OPTIONS[DEFAULT_MODEL];
  const finalTemperature = temperature !== null ? temperature : (strictMode ? 0.3 : modelDefaults.temperature);
  const finalMaxTokens = max_tokens !== null ? max_tokens : modelDefaults.max_tokens;
  const finalTopP = top_p !== null ? top_p : 0.95;

  const chatCompletion = await groqClient.chat.completions.create({
    messages,
    model,
    temperature: finalTemperature,
    max_tokens: finalMaxTokens,
    top_p: finalTopP,
    stream: false
  });

  const agentResponse = chatCompletion.choices[0]?.message?.content || 'Lo siento, no pude generar una respuesta.';

  addToShortTermMemory('user', userMessage);
  addToShortTermMemory('assistant', agentResponse);

  const usage = chatCompletion.usage || { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 };
  const validation = validateResponse(agentResponse, userMessage, { strictMode });

  if (usage.total_tokens > 0) {
    recordTokenUsage({
      sessionId: getCurrentSessionId(),
      conversationId,
      model,
      promptTokens: usage.prompt_tokens,
      completionTokens: usage.completion_tokens,
      totalTokens: usage.total_tokens,
      confidenceScore: validation.confidence
    });
  }

  return {
    response: agentResponse,
    model: chatCompletion.model,
    usage,
    confidence: validation.confidence,
    validation: {
      valid: validation.valid,
      contradictions: validation.contradictions,
      details: validation.details
    },
    parameters: {
      temperature: finalTemperature,
      max_tokens: finalMaxTokens,
      top_p: finalTopP,
      strictMode
    }
  };
}

export function getAvailableModels() {
  return [
    { id: 'llama-3.1-8b-instant', name: 'Llama 3.1 8B Instant', description: 'Modelo rápido y eficiente', defaultTemp: 0.5, defaultMaxTokens: 1024 },
    { id: 'llama-3.3-70b-versatile', name: 'Llama 3.3 70B Versatile', description: 'Modelo potente de Meta', defaultTemp: 0.6, defaultMaxTokens: 2048 },
    { id: 'openai/gpt-oss-120b', name: 'GPT OSS 120B', description: 'Modelo abierto de OpenAI', defaultTemp: 0.5, defaultMaxTokens: 2048 },
    { id: 'openai/gpt-oss-20b', name: 'GPT OSS 20B', description: 'Versión más pequeña de GPT OSS', defaultTemp: 0.5, defaultMaxTokens: 1024 }
  ];
}
