import { useState, useEffect } from 'react';
import { getTokenUsage, getTokenUsageBySession } from '../services/api';

export default function TokenCounter({ sessionId, refreshInterval = 30000 }) {
  const [usage, setUsage] = useState(null);
  const [sessionUsage, setSessionUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchUsage = async () => {
    try {
      const [totalData, sessionData] = await Promise.all([
        getTokenUsage(),
        getTokenUsageBySession()
      ]);
      setUsage(totalData.total);
      setSessionUsage(sessionData.session);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsage();
    const interval = setInterval(fetchUsage, refreshInterval);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  if (loading) {
    return (
      <div className="token-counter loading">
        <span>Cargando tokens...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="token-counter error">
        <span>Error: {error}</span>
      </div>
    );
  }

  const formatNumber = (num) => {
    if (!num) return '0';
    return new Intl.NumberFormat().format(num);
  };

  return (
    <div className="token-counter">
      <div className="token-header">
        <h3>Uso de Tokens</h3>
        <button onClick={fetchUsage} className="refresh-btn" title="Actualizar">
          ↻
        </button>
      </div>

      <div className="token-sections">
        <div className="token-section">
          <h4>Sesión Actual</h4>
          <div className="token-stats">
            <div className="stat">
              <span className="label">Requests</span>
              <span className="value">{formatNumber(sessionUsage?.requests || 0)}</span>
            </div>
            <div className="stat">
              <span className="label">Prompt</span>
              <span className="value">{formatNumber(sessionUsage?.prompt_tokens || 0)}</span>
            </div>
            <div className="stat">
              <span className="label">Respuesta</span>
              <span className="value">{formatNumber(sessionUsage?.completion_tokens || 0)}</span>
            </div>
            <div className="stat highlight">
              <span className="label">Total</span>
              <span className="value">{formatNumber(sessionUsage?.total_tokens || 0)}</span>
            </div>
          </div>
        </div>

        <div className="token-section">
          <h4>Total Global</h4>
          <div className="token-stats">
            <div className="stat">
              <span className="label">Requests</span>
              <span className="value">{formatNumber(usage?.total_requests || 0)}</span>
            </div>
            <div className="stat">
              <span className="label">Prompt</span>
              <span className="value">{formatNumber(usage?.total_prompt_tokens || 0)}</span>
            </div>
            <div className="stat">
              <span className="label">Respuesta</span>
              <span className="value">{formatNumber(usage?.total_completion_tokens || 0)}</span>
            </div>
            <div className="stat highlight">
              <span className="label">Total</span>
              <span className="value">{formatNumber(usage?.total_tokens || 0)}</span>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .token-counter {
          background: #1a1a2e;
          border-radius: 8px;
          padding: 12px;
          margin-bottom: 16px;
          border: 1px solid #2d2d44;
          width: 100%;
        }
        
        .token-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }
        
        .token-header h3 {
          margin: 0;
          color: #e0e0e0;
          font-size: 14px;
        }
        
        .refresh-btn {
          background: #3d3d5c;
          border: none;
          color: #a0a0c0;
          padding: 4px 8px;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
        }
        
        .refresh-btn:hover {
          background: #4d4d6c;
        }
        
        .token-sections {
          display: flex;
          gap: 16px;
        }
        
        .token-section {
          flex: 1;
        }
        
        .token-section h4 {
          margin: 0 0 8px 0;
          color: #808090;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        
        .token-stats {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
        }
        
        .stat {
          background: #252540;
          padding: 8px;
          border-radius: 6px;
          text-align: center;
        }
        
        .stat.highlight {
          background: #2d3a5a;
          border: 1px solid #3d4a6a;
        }
        
        .stat .label {
          display: block;
          color: #707090;
          font-size: 9px;
          text-transform: uppercase;
          margin-bottom: 2px;
        }
        
        .stat .value {
          display: block;
          color: #e0e0f0;
          font-size: 14px;
          font-weight: 600;
        }
        
        .stat.highlight .value {
          color: #60a0ff;
        }
        
        .loading, .error {
          padding: 12px;
          text-align: center;
          color: #808090;
          font-size: 12px;
        }
        
        .error {
          color: #ff6060;
        }
      `}</style>
    </div>
  );
}
