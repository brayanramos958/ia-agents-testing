const AGENT_BASE = '/agent';

async function fetchAgent(endpoint, options = {}) {
  const response = await fetch(`${AGENT_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Error desconocido' }));
    throw new Error(error.detail || error.error || 'Error en la petición');
  }
  
  return response.json();
}

/**
 * Envía un mensaje al agente IA
 * @param {number} userId - ID del usuario
 * @param {string} userRol - Rol del usuario (creador, resolutor, supervisor)
 * @param {string} message - Mensaje del usuario
 * @param {string} threadId - ID del hilo de conversación (opcional, se genera si no se proporciona)
 * @returns {Promise<{reply: string, thread_id: string}>}
 */
export const sendToAgent = async (userId, userRol, message, threadId = null) => {
  // Generar thread_id consistente basado en user_id si no se proporciona
  const consistentThreadId = threadId || `user-${userId}`;
  
  return fetchAgent('/chat', {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      user_rol: userRol,
      message: message,
      thread_id: consistentThreadId
    })
  });
};
