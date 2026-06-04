import { useState, useEffect, useRef } from 'react';
import './App.css';
import { sendMessage, submitCorrection, checkHealth, resetMemory, getLearnings, createNewSession } from './services/api';
import TokenCounter from './components/TokenCounter';
import ConfidenceBadge from './components/ConfidenceBadge';
import SettingsPanel from './components/SettingsPanel';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCorrections, setShowCorrections] = useState(false);
  const [healthStatus, setHealthStatus] = useState(null);
  const [learnings, setLearnings] = useState({ corrections: [], facts: [] });
  const [editingMessageId, setEditingMessageId] = useState(null);
  const [correctionInput, setCorrectionInput] = useState('');
  const [settings, setSettings] = useState({
    model: '',
    strictMode: false,
    temperature: 0.5,
    max_tokens: 1024,
    top_p: 0.95
  });
  const [sessionId, setSessionId] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    checkHealthStatus();
    initializeSession();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const checkHealthStatus = async () => {
    try {
      const status = await checkHealth();
      setHealthStatus(status);
      setSessionId(status.sessionId);
    } catch (error) {
      setHealthStatus({ status: 'error', groqInitialized: false });
    }
  };

  const initializeSession = async () => {
    try {
      const result = await createNewSession();
      setSessionId(result.sessionId);
    } catch (error) {
      console.error('Failed to initialize session:', error);
    }
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setInput('');
    setLoading(true);

    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: userMessage,
      conversationId: null
    };
    setMessages(prev => [...prev, userMsg]);

    try {
      const result = await sendMessage(userMessage, settings.model || null, {
        temperature: settings.strictMode ? 0.3 : settings.temperature,
        max_tokens: settings.max_tokens,
        top_p: settings.top_p,
        strictMode: settings.strictMode
      });
      
      const assistantMsg = {
        id: Date.now() + 1,
        role: 'assistant',
        content: result.response,
        conversationId: result.conversationId,
        confidence: result.confidence,
        validation: result.validation,
        usage: result.usage,
        parameters: result.parameters
      };
      setMessages(prev => [...prev, assistantMsg]);
      
      if (result.sessionId) {
        setSessionId(result.sessionId);
      }
    } catch (error) {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'error',
        content: `Error: ${error.message}`
      }]);
    } finally {
      setLoading(false);
    }
  };

  const handleCorrection = async (messageId) => {
    if (!correctionInput.trim()) return;
    
    const message = messages.find(m => m.id === messageId);
    if (!message || !message.conversationId) return;

    try {
      await submitCorrection(
        message.conversationId,
        correctionInput,
        message.content,
        ''
      );
      
      setMessages(prev => prev.map(m => 
        m.id === messageId ? { ...m, corrected: true } : m
      ));
      
      setEditingMessageId(null);
      setCorrectionInput('');
      
      const learningsData = await getLearnings();
      setLearnings(learningsData);
    } catch (error) {
      alert(`Error submitting correction: ${error.message}`);
    }
  };

  const handleReset = async () => {
    if (!confirm('¿Estás seguro de que quieres reiniciar toda la memoria del agente?')) return;
    
    try {
      await resetMemory();
      setMessages([]);
      setLearnings({ corrections: [], facts: [] });
      await initializeSession();
      alert('Memoria reiniciada correctamente');
    } catch (error) {
      alert(`Error resetting memory: ${error.message}`);
    }
  };

  const toggleLearnings = async () => {
    if (!showCorrections) {
      const learningsData = await getLearnings();
      setLearnings(learningsData);
    }
    setShowCorrections(!showCorrections);
  };

  return (
    <div className="app">
      <header className="header">
        <h1>Agente de Aprendizaje</h1>
        <div className="header-actions">
          <span className={`status ${healthStatus?.groqInitialized ? 'connected' : 'disconnected'}`}>
            {healthStatus?.groqInitialized ? '✓ Conectado' : '⚠ Sin conexión'}
          </span>
          <button onClick={toggleLearnings} className="btn-secondary">
            {showCorrections ? 'Ocultar' : 'Ver'} Aprendizajes
          </button>
          <button onClick={handleReset} className="btn-danger">
            Reiniciar Memoria
          </button>
        </div>
      </header>

      <main className="main">
        <div className="sidebar">
          <TokenCounter sessionId={sessionId} />
          <SettingsPanel 
            settings={settings} 
            onSettingsChange={setSettings} 
          />
        </div>

        <div className="chat-container">
          <div className="messages">
            {messages.length === 0 && (
              <div className="welcome-message">
                <h2>¡Bienvenido!</h2>
                <p>Soy un agente de IA que aprende de tus correcciones.</p>
                <p>Si mi respuesta no es correcta, puedes corregirme y recordaré la corrección para mejorar futuras respuestas.</p>
                <div className="welcome-features">
                  <div className="feature">
                    <span className="feature-icon">🎯</span>
                    <span>Modo Estricto disponible</span>
                  </div>
                  <div className="feature">
                    <span className="feature-icon">📊</span>
                    <span>Contador de tokens</span>
                  </div>
                  <div className="feature">
                    <span className="feature-icon">📈</span>
                    <span>Score de confianza</span>
                  </div>
                </div>
              </div>
            )}
            {messages.map(msg => (
              <div key={msg.id} className={`message ${msg.role}`}>
                <div className="message-content">
                  {msg.content}
                </div>
                {msg.role === 'assistant' && msg.confidence !== undefined && (
                  <ConfidenceBadge 
                    confidence={msg.confidence} 
                    validation={msg.validation}
                  />
                )}
                {msg.role === 'assistant' && msg.usage && (
                  <div className="message-tokens">
                    Tokens: {msg.usage.total_tokens || 0}
                  </div>
                )}
                {msg.role === 'assistant' && !msg.corrected && (
                  <button 
                    className="btn-correct"
                    onClick={() => setEditingMessageId(msg.id)}
                  >
                    Corregir
                  </button>
                )}
                {editingMessageId === msg.id && (
                  <div className="correction-form">
                    <textarea
                      value={correctionInput}
                      onChange={(e) => setCorrectionInput(e.target.value)}
                      placeholder="Escribe tu corrección..."
                      rows={3}
                    />
                    <div className="correction-actions">
                      <button 
                        className="btn-primary"
                        onClick={() => handleCorrection(msg.id)}
                      >
                        Enviar Corrección
                      </button>
                      <button 
                        className="btn-secondary"
                        onClick={() => {
                          setEditingMessageId(null);
                          setCorrectionInput('');
                        }}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                )}
                {msg.corrected && (
                  <div className="corrected-badge">✓ Corregido</div>
                )}
              </div>
            ))}
            {loading && (
              <div className="message assistant loading">
                <div className="message-content">
                  <span className="typing-indicator">
                    <span></span><span></span><span></span>
                  </span>
                  Pensando...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <form onSubmit={handleSendMessage} className="input-form">
            <div className="input-wrapper">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={settings.strictMode ? "Pregunta (modo estricto activado)..." : "Escribe tu mensaje..."}
                disabled={loading}
              />
              <button type="submit" disabled={loading || !input.trim()}>
                {loading ? '...' : 'Enviar'}
              </button>
            </div>
            {settings.strictMode && (
              <div className="strict-mode-indicator">
                🔒 Modo Estricto activado - Respuestas solo con información verificada
              </div>
            )}
          </form>
        </div>

        {showCorrections && (
          <div className="learnings-panel">
            <h2>Aprendizajes del Agente</h2>
            
            <div className="learnings-section">
              <h3>Hechos Aprendidos ({learnings.facts?.length || 0})</h3>
              {learnings.facts?.length > 0 ? (
                <ul className="learnings-list">
                  {learnings.facts.map(fact => (
                    <li key={fact.id}>
                      <span className="fact-text">{fact.fact}</span>
                      <span className="confidence">
                        {(fact.confidence_score * 100).toFixed(0)}%
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">No hay hechos aprendidos aún</p>
              )}
            </div>

            <div className="learnings-section">
              <h3>Correcciones ({learnings.corrections?.length || 0})</h3>
              {learnings.corrections?.length > 0 ? (
                <ul className="learnings-list">
                  {learnings.corrections.map(corr => (
                    <li key={corr.id}>
                      <div className="correction-text">"{corr.user_correction}"</div>
                      <div className="correction-meta">
                        {new Date(corr.timestamp).toLocaleString()}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">No hay correcciones aún</p>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
