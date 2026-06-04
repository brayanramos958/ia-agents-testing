import { getRecentConversations, getAllConversations } from '../models/conversation.js';
import { getRecentCorrections, getAllCorrections } from '../models/correction.js';
import { getLearnedFacts, getHighConfidenceFacts } from '../models/learnedFacts.js';

let shortTermMemory = [];

export function addToShortTermMemory(role, content) {
  shortTermMemory.push({ role, content });
  
  const MAX_MEMORY_SIZE = 20;
  if (shortTermMemory.length > MAX_MEMORY_SIZE) {
    shortTermMemory = shortTermMemory.slice(-MAX_MEMORY_SIZE);
  }
}

export function getShortTermMemory() {
  return [...shortTermMemory];
}

export function clearShortTermMemory() {
  shortTermMemory = [];
}

export function getShortTermMemoryAsContext() {
  if (shortTermMemory.length === 0) {
    return '';
  }
  
  return shortTermMemory.map(msg => 
    `${msg.role === 'user' ? 'Usuario' : 'Asistente'}: ${msg.content}`
  ).join('\n');
}

export function getLongTermMemory() {
  const corrections = getRecentCorrections(20);
  const facts = getLearnedFacts(20);
  const highConfidenceFacts = getHighConfidenceFacts(0.7);
  
  return {
    corrections,
    facts,
    highConfidenceFacts
  };
}

export function getLongTermMemoryAsContext() {
  const { corrections, facts, highConfidenceFacts } = getLongTermMemory();
  
  let context = '';
  
  if (highConfidenceFacts.length > 0) {
    context += '\n=== HECHOS APRENDIDOS DE ALTA CONFIANZA ===\n';
    highConfidenceFacts.forEach(fact => {
      context += `- ${fact.fact} (confianza: ${(fact.confidence_score * 100).toFixed(0)}%)\n`;
    });
  }
  
  if (corrections.length > 0) {
    context += '\n=== CORRECCIONES RECIENTES ===\n';
    corrections.slice(0, 10).forEach(corr => {
      context += `- Corrección: "${corr.user_correction}" (para: "${corr.agent_response}")\n`;
    });
  }
  
  if (facts.length > 0) {
    context += '\n=== CONOCIMIENTO ACUMULADO ===\n';
    facts.slice(0, 10).forEach(fact => {
      context += `- ${fact.fact}\n`;
    });
  }
  
  return context;
}

export function buildContextForLLM(strictMode = false) {
  const shortTerm = getShortTermMemoryAsContext();
  const longTerm = getLongTermMemoryAsContext();
  
  let systemPrompt = `Eres un asistente de IA útil. Has sido diseñado para aprender de las correcciones que te hace el usuario.

INSTRUCCIONES IMPORTANTES:
1. Si el usuario te corrige, debes recordar esa corrección para futuras respuestas.
2. Cuando respondas, considera el contexto de conversaciones anteriores.
3. Si detectas hechos que el usuario te ha confirmado como correctos, úsalos en tus respuestas.
4. Sé conciso y claro en tus respuestas.`;

  if (strictMode) {
    systemPrompt += `

MODO ESTRICTO ACTIVADO:
- SOLO responde con información que esté en los hechos aprendidos
- Si no tienes información verificada, indica que no puedes responder con certeza
- NO inventes datos ni hagas suposiciones
- Prioriza la precisión sobre la completitud`;
  }

  if (longTerm) {
    systemPrompt += `\n${longTerm}`;
  }
  
  if (shortTerm) {
    systemPrompt += `\n\n=== CONVERSACIÓN ACTUAL ===\n${shortTerm}`;
  }
  
  return systemPrompt;
}

export function extractFactsFromCorrection(userMessage, agentResponse, userCorrection) {
  const facts = [];
  
  const correctionLower = userCorrection.toLowerCase();
  
  if (correctionLower.includes('en realidad') || 
      correctionLower.includes('correcto es') || 
      correctionLower.includes('la respuesta correcta')) {
    const match = userCorrection.match(/(?:es|son|sería|serían)\s+["']?([^"'.\n]+)/i);
    if (match) {
      facts.push({ fact: match[1].trim(), category: 'correction' });
    }
  }
  
  if (correctionLower.includes('recuerda que') || 
      correctionLower.includes('no olvides que')) {
    const match = userCorrection.match(/(?:que|recuerda que|no olvides que)\s+["']?([^"'.\n]+)/i);
    if (match) {
      facts.push({ fact: match[1].trim(), category: 'reminder' });
    }
  }
  
  return facts;
}
