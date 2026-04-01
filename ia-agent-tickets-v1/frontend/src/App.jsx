import { useState, useEffect } from 'react'
import './App.css'
import { getUsers, getTickets, getTicket, createTicket, assignTicket, resolveTicket, reopenTicket, getTicketHistory } from './services/api'
import { sendToAgent } from './services/agentApi'

function App() {
  const [users, setUsers] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [tickets, setTickets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  
  // Navigation state - 'tickets' or 'chat'
  const [activeView, setActiveView] = useState('tickets')
  
  // Chat state
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [agentThreadId, setAgentThreadId] = useState(null)
  const [agentLoading, setAgentLoading] = useState(false)
  
  // Modal state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedTicket, setSelectedTicket] = useState(null)
  const [ticketHistory, setTicketHistory] = useState([])

  useEffect(() => {
    loadUsers()
  }, [])

  useEffect(() => {
    if (currentUser) {
      loadTickets()
    }
  }, [currentUser])

  const loadUsers = async () => {
    try {
      const data = await getUsers()
      setUsers(data)
      // Auto-select first user for demo
      if (data.length > 0) {
        setCurrentUser(data[0])
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const loadTickets = async () => {
    try {
      let filters = {}
      if (currentUser.rol === 'resueltor') {
        filters = { asignado_a: currentUser.id }
      }
      const data = await getTickets(filters)
      setTickets(data)
    } catch (err) {
      setError(err.message)
    }
  }

  const showError = (msg) => {
    setError(msg)
    setTimeout(() => setError(null), 5000)
  }

  // Chat functions
  const handleSendMessage = async () => {
    if (!chatInput.trim()) return
    
    const userMessage = {
      id: Date.now(),
      text: chatInput,
      sender: 'user',
      time: new Date().toISOString()
    }
    
    setChatMessages(prev => [...prev, userMessage])
    
    const messageText = chatInput
    setChatInput('')
    
    // Llamar al agente IA real
    setAgentLoading(true)
    try {
      const response = await sendToAgent(
        currentUser.id,
        currentUser.rol,
        messageText,
        agentThreadId
      )
      
      // Guardar el thread_id para siguientes mensajes
      if (response.thread_id) {
        setAgentThreadId(response.thread_id)
      }
      
      const agentMessage = {
        id: Date.now() + 1,
        text: response.reply,
        sender: 'agent',
        time: new Date().toISOString()
      }
      setChatMessages(prev => [...prev, agentMessage])
    } catch (err) {
      // Mostrar error en el chat
      const errorMessage = {
        id: Date.now() + 1,
        text: `Error: ${err.message}. Asegúrate de que el agente esté corriendo en http://localhost:8000`,
        sender: 'agent',
        time: new Date().toISOString()
      }
      setChatMessages(prev => [...prev, errorMessage])
    } finally {
      setAgentLoading(false)
    }
  }

  // Reiniciar chat cuando cambia el usuario
  const handleNewChat = () => {
    setChatMessages([])
    setAgentThreadId(null)
  }

  const handleCreateTicket = async (formData) => {
    try {
      setError(null)
      await createTicket(formData, currentUser.id, currentUser.rol)
      setShowCreateModal(false)
      loadTickets()
    } catch (err) {
      showError(err.message)
    }
  }

  const handleAssign = async (ticketId, asignado_a) => {
    if (!asignado_a) {
      showError('Debe seleccionar un resolutor')
      return
    }
    try {
      setError(null)
      await assignTicket(ticketId, asignado_a, currentUser.id, currentUser.rol)
      setShowDetailModal(false)
      setSelectedTicket(null)
      loadTickets()
    } catch (err) {
      showError(err.message)
    }
  }

  const handleResolve = async (ticketId, resolucionText = '') => {
    try {
      setError(null)
      await resolveTicket(ticketId, resolucionText, currentUser.id, currentUser.rol)
      setShowDetailModal(false)
      loadTickets()
    } catch (err) {
      showError(err.message)
    }
  }

  const handleReopen = async (ticketId, motivo) => {
    try {
      setError(null)
      await reopenTicket(ticketId, motivo, currentUser.id, currentUser.rol)
      setShowDetailModal(false)
      loadTickets()
    } catch (err) {
      showError(err.message)
    }
  }

  const openTicketDetail = async (ticket) => {
    try {
      const [detail, history] = await Promise.all([
        getTicket(ticket.id),
        getTicketHistory(ticket.id)
      ])
      setSelectedTicket(detail)
      setTicketHistory(history)
      setShowDetailModal(true)
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <div className="loading">Cargando...</div>

  const resolutores = users.filter(u => u.rol === 'resueltor')

  const getDashboardTitle = () => {
    switch (currentUser?.rol) {
      case 'creador': return 'Mis Tickets'
      case 'resueltor': return 'Tickets Asignados a Mí'
      case 'supervisor': return 'Todos los Tickets'
      default: return 'Dashboard'
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>🎫 Help Desk - Tickets</h1>
        <div className="user-info">
          <div className="role-selector">
            <span>Usuario:</span>
            <select 
              value={currentUser?.id || ''} 
              onChange={(e) => {
                const user = users.find(u => u.id === parseInt(e.target.value))
                setCurrentUser(user)
              }}
            >
              {users.map(user => (
                <option key={user.id} value={user.id}>
                  {user.nombre} ({user.rol})
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <main className="main">
        <div className="nav-tabs">
          <button 
            className={`nav-tab ${activeView === 'tickets' ? 'active' : ''}`}
            onClick={() => setActiveView('tickets')}
          >
            🎫 Tickets
          </button>
          <button 
            className={`nav-tab ${activeView === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveView('chat')}
          >
            💬 Chat con Agente
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        {activeView === 'tickets' ? (
          <div className="tickets-view">
            <div className="dashboard-header">
              <h2>{getDashboardTitle()}</h2>
              <p>Rol: {currentUser?.rol} • {currentUser?.cargo} • {currentUser?.area}</p>
            </div>

            <div className="actions">
              {currentUser?.rol === 'creador' && (
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                  + Crear Ticket
                </button>
              )}
              <button className="btn btn-secondary" onClick={loadTickets}>
                🔄 Actualizar
              </button>
            </div>

            {tickets.length === 0 ? (
              <div className="empty-state">
                <h3>No hay tickets</h3>
                <p>No se encontraron tickets para mostrar.</p>
              </div>
            ) : (
              <div className="ticket-list">
                {tickets.map(ticket => (
                  <TicketCard 
                    key={ticket.id} 
                    ticket={ticket}
                    currentUser={currentUser}
                    resolutores={resolutores}
                    onView={() => openTicketDetail(ticket)}
                    onAssign={handleAssign}
                    onResolve={handleResolve}
                  />
                ))}
              </div>
            )}
          </div>
        ) : null}
      </main>

      {/* Chat View - Agente IA por rol */}
      {activeView === 'chat' && (
        <RoleChatView 
          currentUser={currentUser}
          messages={chatMessages}
          chatInput={chatInput}
          agentLoading={agentLoading}
          onInputChange={setChatInput}
          onSendMessage={handleSendMessage}
          onNewChat={handleNewChat}
        />
      )}

      {showCreateModal && (
        <CreateTicketModal 
          users={users}
          currentUser={currentUser}
          onSubmit={handleCreateTicket}
          onClose={() => setShowCreateModal(false)}
        />
      )}

      {showDetailModal && selectedTicket && (
        <TicketDetailModal 
          ticket={selectedTicket}
          history={ticketHistory}
          currentUser={currentUser}
          resolutores={resolutores}
          onAssign={handleAssign}
          onResolve={handleResolve}
          onReopen={handleReopen}
          onClose={() => {
            setShowDetailModal(false)
            setSelectedTicket(null)
          }}
        />
      )}
    </div>
  )
}

function TicketCard({ ticket, currentUser, resolutores, onView, onAssign, onResolve }) {
  return (
    <div className="ticket-card">
      <div className="ticket-info">
        <h3>#{ticket.id} - {ticket.tipo_requerimiento}</h3>
        <div className="ticket-meta">
          <span>📁 {ticket.categoria}</span>
          <span>📅 {new Date(ticket.created_at).toLocaleDateString()}</span>
          {ticket.asignado_nombre && (
            <span>👤 Asignado: {ticket.asignado_nombre}</span>
          )}
        </div>
        {ticket.descripcion && (
          <p style={{fontSize: '0.875rem', color: 'var(--text-muted)', marginBottom: '0.5rem'}}>
            {ticket.descripcion.length > 80 ? ticket.descripcion.substring(0, 80) + '...' : ticket.descripcion}
          </p>
        )}
        <div className="ticket-badges">
          <span className={`badge badge-estado ${ticket.estado}`}>{ticket.estado}</span>
          <span className={`badge badge-urgencia ${ticket.urgencia}`}>{ticket.urgencia}</span>
          <span className={`badge badge-prioridad ${ticket.prioridad}`}>{ticket.prioridad}</span>
        </div>
      </div>
      <div className="ticket-actions">
        <button className="btn btn-secondary btn-sm" onClick={onView}>Ver</button>
        {currentUser.rol === 'supervisor' && ticket.estado !== 'cerrado' && !ticket.asignado_a && (
          <select 
            className="btn btn-sm btn-secondary"
            onChange={(e) => e.target.value && onAssign(ticket.id, parseInt(e.target.value))}
            defaultValue=""
          >
            <option value="">Asignar...</option>
            {resolutores.map(r => (
              <option key={r.id} value={r.id}>{r.nombre}</option>
            ))}
          </select>
        )}
        {currentUser.rol === 'resueltor' && ticket.estado === 'asignado' && (
          <button className="btn btn-success btn-sm" onClick={onView}>
            ✓ Resolver
          </button>
        )}
      </div>
    </div>
  )
}

function CreateTicketModal({ users, currentUser, onSubmit, onClose }) {
  const [formData, setFormData] = useState({
    tipo_requerimiento: 'Solicitud',
    categoria: 'Software',
    descripcion: '',
    urgencia: 'media',
    impacto: 'medio',
    prioridad: 'media'
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!formData.tipo_requerimiento || !formData.categoria) {
      alert('Por favor complete los campos requeridos')
      return
    }
    onSubmit(formData)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h2>Crear Ticket</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Tipo de Requerimiento</label>
            <select 
              value={formData.tipo_requerimiento}
              onChange={e => setFormData({...formData, tipo_requerimiento: e.target.value})}
            >
              <option value="Incidente">Incidente</option>
              <option value="Solicitud">Solicitud</option>
              <option value="Problema">Problema</option>
            </select>
          </div>
          <div className="form-group">
            <label>Categoría</label>
            <select 
              value={formData.categoria}
              onChange={e => setFormData({...formData, categoria: e.target.value})}
            >
              <option value="Hardware">Hardware</option>
              <option value="Software">Software</option>
              <option value="Red">Red</option>
              <option value="Seguridad">Seguridad</option>
              <option value="Otro">Otro</option>
            </select>
          </div>
          <div className="form-group">
            <label>Descripción del Problema</label>
            <textarea 
              value={formData.descripcion}
              onChange={e => setFormData({...formData, descripcion: e.target.value})}
              placeholder="Describa el problema o solicitud..."
              rows={4}
            />
          </div>
          <div className="form-group">
            <label>Urgencia</label>
            <select 
              value={formData.urgencia}
              onChange={e => setFormData({...formData, urgencia: e.target.value})}
            >
              <option value="baja">Baja</option>
              <option value="media">Media</option>
              <option value="alta">Alta</option>
              <option value="critica">Crítica</option>
            </select>
          </div>
          <div className="form-group">
            <label>Impacto</label>
            <select 
              value={formData.impacto}
              onChange={e => setFormData({...formData, impacto: e.target.value})}
            >
              <option value="bajo">Bajo</option>
              <option value="medio">Medio</option>
              <option value="alto">Alto</option>
            </select>
          </div>
          <div className="form-group">
            <label>Prioridad</label>
            <select 
              value={formData.prioridad}
              onChange={e => setFormData({...formData, prioridad: e.target.value})}
            >
              <option value="baja">Baja</option>
              <option value="media">Media</option>
              <option value="alta">Alta</option>
              <option value="urgente">Urgente</option>
            </select>
          </div>
          <div className="form-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancelar</button>
            <button type="submit" className="btn btn-primary">Crear</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function TicketDetailModal({ ticket, history, currentUser, resolutores, onAssign, onResolve, onReopen, onClose }) {
  const [asignado_a, setAsignado_a] = useState(ticket.asignado_a || '')
  const [motivo, setMotivo] = useState('')
  const [resolucionText, setResolucionText] = useState('')

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{maxWidth: '600px'}}>
        <h2>Ticket #{ticket.id}</h2>
        
        <div className="ticket-badges" style={{marginBottom: '1rem'}}>
          <span className={`badge badge-estado ${ticket.estado}`}>{ticket.estado}</span>
          <span className={`badge badge-urgencia ${ticket.urgencia}`}>{ticket.urgencia}</span>
          <span className={`badge badge-prioridad ${ticket.prioridad}`}>{ticket.prioridad}</span>
        </div>

        <div style={{display: 'grid', gap: '0.75rem', marginBottom: '1.5rem'}}>
          <div><strong>Tipo:</strong> {ticket.tipo_requerimiento}</div>
          <div><strong>Categoría:</strong> {ticket.categoria}</div>
          {ticket.descripcion && (
            <div><strong>Descripción:</strong><br/>{ticket.descripcion}</div>
          )}
          <div><strong>Impacto:</strong> {ticket.impacto}</div>
          <div><strong>Creado:</strong> {new Date(ticket.created_at).toLocaleString()}</div>
          {ticket.asignado_nombre && (
            <div><strong>Asignado a:</strong> {ticket.asignado_nombre} ({ticket.asignado_cargo})</div>
          )}
          {ticket.resolucion && (
            <div><strong>Resolución:</strong> {ticket.resolucion}</div>
          )}
        </div>

        {currentUser.rol === 'supervisor' && ticket.estado !== 'cerrado' && (
          <div className="form-group">
            <label>Reasignar Ticket</label>
            <div style={{display: 'flex', gap: '0.5rem'}}>
              <select 
                value={asignado_a}
                onChange={e => setAsignado_a(e.target.value)}
                style={{flex: 1}}
              >
                <option value="">Seleccionar resolutor...</option>
                {resolutores.map(r => (
                  <option key={r.id} value={r.id}>{r.nombre}</option>
                ))}
              </select>
              <button 
                className="btn btn-primary btn-sm"
                onClick={() => asignado_a && onAssign(ticket.id, parseInt(asignado_a))}
                disabled={!asignado_a}
              >
                Asignar
              </button>
            </div>
          </div>
        )}

        {currentUser.rol === 'resueltor' && ticket.estado === 'asignado' && (
          <div className="form-group">
            <label>Descripción de la solución (opcional)</label>
            <textarea 
              value={resolucionText}
              onChange={e => setResolucionText(e.target.value)}
              placeholder="Describa cómo solucionó el problema..."
              rows={3}
              style={{marginBottom: '0.5rem'}}
            />
            <button className="btn btn-success" onClick={() => onResolve(ticket.id, resolucionText)}>
              ✓ Marcar como Resuelto
            </button>
          </div>
        )}

        {currentUser.rol === 'supervisor' && ticket.estado === 'resuelto' && (
          <div className="form-group">
            <label>Reabrir Ticket (motivo)</label>
            <div style={{display: 'flex', gap: '0.5rem'}}>
              <input 
                type="text"
                value={motivo}
                onChange={e => setMotivo(e.target.value)}
                placeholder="Motivo de reapertura..."
                style={{flex: 1}}
              />
              <button 
                className="btn btn-danger btn-sm"
                onClick={() => onReopen(ticket.id, motivo)}
              >
                Reabrir
              </button>
            </div>
          </div>
        )}

        <h3 style={{marginTop: '1.5rem', marginBottom: '0.75rem', fontSize: '1rem'}}>
          📋 Historial
        </h3>
        {history.length === 0 ? (
          <p style={{color: 'var(--text-muted)', fontSize: '0.875rem'}}>
            Sin historial
          </p>
        ) : (
          <div className="history-list">
            {history.map(item => (
              <div key={item.id} className="history-item">
                <div className="icon">{item.accion.charAt(0).toUpperCase()}</div>
                <div className="details">
                  <strong>{item.accion}</strong>
                  {item.detalle && <span> - {item.detalle}</span>}
                  <br/>
                  <small>
                    {item.usuario_nombre} • {new Date(item.fecha).toLocaleString()}
                  </small>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="form-actions">
          <button className="btn btn-secondary" onClick={onClose}>Cerrar</button>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// COMPONENTE ROLE CHAT VIEW - Chat con Agente IA por rol
// ============================================================
function RoleChatView({ currentUser, messages, chatInput, agentLoading, onInputChange, onSendMessage, onNewChat }) {
  
  const getRoleTitle = () => {
    switch (currentUser?.rol) {
      case 'creador': return '🤖 Agente IA - Crear Tickets'
      case 'resolutor': return '🤖 Agente IA - Mis Tickets Asignados'
      case 'supervisor': return '🤖 Agente IA - Supervisión'
      default: return '🤖 Agente IA'
    }
  }
  
  const getRoleDescription = () => {
    switch (currentUser?.rol) {
      case 'creador': return 'Crea tickets y consulta los que has creado'
      case 'resolutor': return 'Consulta y resuelve tus tickets asignados'
      case 'supervisor': return 'Supervisa todos los tickets y asígnalos'
      default: return 'Asistente de mesa de ayuda'
    }
  }
  
  const getWelcomeMessage = () => {
    switch (currentUser?.rol) {
      case 'creador': return '¡Hola! Soy tu asistente de mesa de ayuda. Puedo ayudarte a crear tickets para reportar problemas o solicitudes. ¿Qué necesitas?'
      case 'resolutor': return '¡Hola! Soy tu asistente de mesa de ayuda. Aquí puedes ver tus tickets asignados y resolverlos. ¿En qué te puedo ayudar?'
      case 'supervisor': return '¡Hola! Soy tu asistente de mesa de ayuda. Puedo ayudarte a supervisar todos los tickets, asignarlos y reabrirlos. ¿Qué necesitas?'
      default: return '¡Hola! Soy tu asistente de mesa de ayuda. ¿En qué te puedo ayudar?'
    }
  }
  
  // Mostrar mensaje de bienvenida si no hay mensajes
  const displayMessages = messages.length === 0 
    ? [{
        id: 'welcome',
        text: getWelcomeMessage(),
        sender: 'agent',
        time: new Date().toISOString()
      }]
    : messages
  
  return (
    <div className="role-chat-container">
      {/* Header del chat */}
      <div className="role-chat-header">
        <div className="role-chat-info">
          <h3>{getRoleTitle()}</h3>
          <p>{getRoleDescription()}</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={onNewChat}>
          + Nueva Conversación
        </button>
      </div>
      
      {/* Lista de tickets rápidos según rol */}
      <QuickTicketList currentUser={currentUser} />
      
      {/* Área de chat */}
      <div className="role-chat-main">
        <div className="chat-messages">
          {displayMessages.map(msg => (
            <div key={msg.id} className={`chat-message ${msg.sender}`}>
              <div className="message-content">{msg.text}</div>
              <span className="message-time">
                {new Date(msg.time).toLocaleTimeString()}
              </span>
            </div>
          ))}
          {agentLoading && (
            <div className="chat-message agent">
              <div className="agent-typing">
                🤖 Escribiendo...
              </div>
            </div>
          )}
        </div>
        
        <div className="chat-input-container">
          <input 
            type="text"
            value={chatInput}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && !agentLoading && onSendMessage()}
            placeholder={agentLoading ? "Esperando respuesta..." : "Escribe un mensaje al agente..."}
            disabled={agentLoading}
          />
          <button 
            className="btn btn-primary" 
            onClick={onSendMessage}
            disabled={agentLoading || !chatInput.trim()}
          >
            {agentLoading ? '...' : 'Enviar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Componente para mostrar tickets rápidos según el rol
function QuickTicketList({ currentUser }) {
  const [tickets, setTickets] = useState([])
  const [loading, setLoading] = useState(false)
  
  useEffect(() => {
    if (currentUser) {
      loadQuickTickets()
    }
  }, [currentUser])
  
  const loadQuickTickets = async () => {
    setLoading(true)
    try {
      let filters = {}
      if (currentUser.rol === 'creador') {
        filters = { created_by: currentUser.id }
      } else if (currentUser.rol === 'resolutor') {
        filters = { asignado_a: currentUser.id }
      }
      // Supervisores ven todos, no cargamos aquí
      
      if (Object.keys(filters).length > 0) {
        const data = await getTickets(filters)
        setTickets(data.slice(0, 5)) // Solo primeros 5
      }
    } catch (err) {
      console.error('Error loading tickets:', err)
    } finally {
      setLoading(false)
    }
  }
  
  if (currentUser?.rol === 'supervisor') return null // Supervisores no ven esto
  
  if (loading) return <div className="quick-tickets-loading">Cargando tickets...</div>
  
  if (tickets.length === 0) return null
  
  return (
    <div className="quick-tickets">
      <h4>Tus Tickets</h4>
      <div className="quick-tickets-list">
        {tickets.map(ticket => (
          <div key={ticket.id} className="quick-ticket-item">
            <span className={`badge badge-estado ${ticket.estado}`}>{ticket.estado}</span>
            <span className="quick-ticket-id">#{ticket.id}</span>
            <span className="quick-ticket-type">{ticket.tipo_requerimiento}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
