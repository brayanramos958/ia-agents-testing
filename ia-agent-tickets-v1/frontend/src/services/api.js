const API_BASE = '/api';

async function fetchApi(endpoint, options = {}) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Error desconocido' }));
    throw new Error(error.error || 'Error en la petición');
  }
  
  return response.json();
}

// Users
export const getUsers = (rol) => fetchApi(`/users${rol ? `?rol=${rol}` : ''}`);
export const getUser = (id) => fetchApi(`/users/${id}`);

// Tickets
export const getTickets = (filters = {}) => {
  const params = new URLSearchParams(filters).toString();
  return fetchApi(`/tickets${params ? `?${params}` : ''}`);
};
export const getTicket = (id) => fetchApi(`/tickets/${id}`);
export const createTicket = (data, userId, userRol) => 
  fetchApi('/tickets', {
    method: 'POST',
    headers: {
      'x-user-id': userId,
      'x-user-rol': userRol
    },
    body: JSON.stringify(data)
  });
export const updateTicket = (id, data, userId, userRol) =>
  fetchApi(`/tickets/${id}`, {
    method: 'PUT',
    headers: {
      'x-user-id': userId,
      'x-user-rol': userRol
    },
    body: JSON.stringify(data)
  });
export const assignTicket = (id, asignado_a, userId, userRol) =>
  fetchApi(`/tickets/${id}/assign`, {
    method: 'PUT',
    headers: {
      'x-user-id': userId,
      'x-user-rol': userRol
    },
    body: JSON.stringify({ asignado_a })
  });
export const resolveTicket = (id, resolucion, userId, userRol) =>
  fetchApi(`/tickets/${id}/resolve`, {
    method: 'PUT',
    headers: {
      'x-user-id': userId,
      'x-user-rol': userRol
    },
    body: JSON.stringify({ resolucion })
  });
export const reopenTicket = (id, motivo, userId, userRol) =>
  fetchApi(`/tickets/${id}/reopen`, {
    method: 'PUT',
    headers: {
      'x-user-id': userId,
      'x-user-rol': userRol
    },
    body: JSON.stringify({ motivo })
  });

// History
export const getTicketHistory = (id) => fetchApi(`/tickets/${id}/history`);
