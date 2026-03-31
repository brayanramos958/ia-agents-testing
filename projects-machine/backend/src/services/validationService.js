import { getLearnedFacts, getHighConfidenceFacts } from '../models/learnedFacts.js';
import { getAllCorrections, getRecentCorrections } from '../models/correction.js';

const HIGH_CONFIDENCE_THRESHOLD = 0.7;
const VALIDATION_WEIGHT = {
  factMatch: 0.4,
  correctionConsistency: 0.3,
  structure: 0.2,
  relevance: 0.1
};

export function validateResponse(response, userMessage, options = {}) {
  const { strictMode = false } = options;

  const facts = strictMode
    ? getHighConfidenceFacts(HIGH_CONFIDENCE_THRESHOLD)
    : getLearnedFacts();

  const corrections = getRecentCorrections(50);

  const factScore = calculateFactAlignment(response, facts);
  const correctionScore = checkCorrectionConsistency(response, corrections);
  const structureScore = evaluateStructure(response);
  const relevanceScore = evaluateRelevance(response, userMessage);

  const confidence = (
    factScore * VALIDATION_WEIGHT.factMatch +
    correctionScore * VALIDATION_WEIGHT.correctionConsistency +
    structureScore * VALIDATION_WEIGHT.structure +
    relevanceScore * VALIDATION_WEIGHT.relevance
  );

  const contradictions = findContradictions(response, facts, corrections);

  return {
    confidence: Math.round(confidence * 100) / 100,
    valid: contradictions.length === 0,
    contradictions,
    details: {
      factScore: Math.round(factScore * 100) / 100,
      correctionScore: Math.round(correctionScore * 100) / 100,
      structureScore: Math.round(structureScore * 100) / 100,
      relevanceScore: Math.round(relevanceScore * 100) / 100
    }
  };
}

function calculateFactAlignment(response, facts) {
  if (!facts || facts.length === 0) return 0.8;

  const responseLower = response.toLowerCase();
  let matchCount = 0;

  facts.forEach(fact => {
    const factWords = fact.fact.toLowerCase().split(' ').filter(w => w.length > 3);
    const matches = factWords.filter(word => responseLower.includes(word));
    if (matches.length >= factWords.length * 0.5) {
      matchCount++;
    }
  });

  return Math.min(1, 0.5 + (matchCount / Math.max(facts.length, 1)) * 0.5);
}

function checkCorrectionConsistency(response, corrections) {
  if (!corrections || corrections.length === 0) return 1;

  const responseLower = response.toLowerCase();
  let penalty = 0;

  corrections.slice(0, 20).forEach(corr => {
    const originalWrong = (corr.agent_response || '').toLowerCase();
    const correction = (corr.user_correction || '').toLowerCase();

    if (originalWrong.length > 10 && responseLower.includes(originalWrong.substring(0, 30))) {
      penalty += 0.15;
    }
  });

  return Math.max(0, 1 - penalty);
}

function evaluateStructure(response) {
  if (!response || response.trim().length === 0) return 0;

  let score = 0.5;

  if (response.length > 20 && response.length < 2000) score += 0.2;
  if (response.includes('.') || response.includes('!') || response.includes('?')) score += 0.1;
  if (response.split(' ').length >= 5) score += 0.1;
  if (!response.includes('undefined') && !response.includes('null')) score += 0.1;

  return Math.min(1, score);
}

function evaluateRelevance(response, userMessage) {
  if (!userMessage || !response) return 0.5;

  const questionWords = userMessage.toLowerCase().split(' ').filter(w => w.length > 3);
  const responseWords = response.toLowerCase();

  const matches = questionWords.filter(word => responseWords.includes(word));
  const relevance = matches.length / Math.max(questionWords.length, 1);

  return Math.min(1, 0.3 + relevance * 0.7);
}

function findContradictions(response, facts, corrections) {
  const contradictions = [];
  const responseLower = response.toLowerCase();

  corrections.slice(0, 20).forEach(corr => {
    const wrongResponse = (corr.agent_response || '').toLowerCase();
    const correction = (corr.user_correction || '').toLowerCase();

    if (correction.includes('no es') || correction.includes('incorrecto')) {
      const wrongFact = extractWrongFact(correction);
      if (wrongFact && responseLower.includes(wrongFact.toLowerCase())) {
        contradictions.push({
          type: 'correction_conflict',
          message: `Respuesta contradice corrección previa: "${corr.user_correction}"`,
          severity: 'high'
        });
      }
    }
  });

  return contradictions;
}

function extractWrongFact(correction) {
  const patterns = [
    /no es\s+["']?([^"'.\n]+)/i,
    /incorrecto\s+["']?([^"'.\n]+)/i,
    /en realidad\s+["']?([^"'.\n]+)/i
  ];

  for (const pattern of patterns) {
    const match = correction.match(pattern);
    if (match) return match[1].trim();
  }

  return null;
}

export function shouldRegenerateResponse(validation, options = {}) {
  const { minConfidence = 0.5, strictMode = false } = options;
  const threshold = strictMode ? 0.7 : minConfidence;

  if (!validation.valid) return true;
  if (validation.confidence < threshold) return true;

  return false;
}

export function getConstraintPrompt(strictMode = false) {
  if (strictMode) {
    return `
RESTRICCIONES ESTRICTAS (MODO PRECISIÓN):
- SOLO responde con información confirmada y verificada
- NO inventes datos, fechas o hechos
- Si no estás seguro, di "No tengo información suficiente para responder con certeza"
- Usa EXCLUSIVAMENTE los hechos aprendidos proporcionados en el contexto
- Mantén respuestas concisas y directas
- NO agregues información no solicitada
`;
  }

  return `
RESTRICCIONES GENERALES:
- Basa tus respuestas en hechos aprendidos cuando estén disponibles
- Si hay una corrección previa sobre el tema, úsala
- Si no estás seguro, indica tu nivel de incertidumbre
- Mantén coherencia con conversaciones anteriores
- Cuando te pregunten sobre datos empresariales como correo de Recursos humanos da el siguiente,
`;
}
