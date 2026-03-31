export default function ConfidenceBadge({ confidence, validation }) {
  const getConfidenceLevel = (score) => {
    if (score >= 0.8) return { level: 'high', label: 'Alta', color: '#4caf50' };
    if (score >= 0.6) return { level: 'medium', label: 'Media', color: '#ff9800' };
    if (score >= 0.4) return { level: 'low', label: 'Baja', color: '#f44336' };
    return { level: 'very-low', label: 'Muy Baja', color: '#9c27b0' };
  };

  const { level, label, color } = getConfidenceLevel(confidence || 0);
  const percentage = Math.round((confidence || 0) * 100);

  return (
    <div className="confidence-badge-container">
      <div className={`confidence-badge ${level}`}>
        <div className="confidence-indicator">
          <div
            className="confidence-bar"
            style={{ width: `${percentage}%`, backgroundColor: color }}
          />
        </div>
        <div className="confidence-info">
          <span className="confidence-label">Confianza:</span>
          <span className="confidence-value" style={{ color }}>
            {label} ({percentage}%)
          </span>
        </div>
      </div>

      {validation && (
        <div className="validation-details">
          {validation.valid === false && (
            <div className="validation-warning">
              ⚠ Posible contradicción detectada
            </div>
          )}
          {validation.details && (
            <div className="validation-breakdown">
              <span title="Coincidencia con hechos aprendidos">
                📚 {Math.round((validation.details.factScore || 0) * 100)}%
              </span>
              <span title="Consistencia con correcciones previas">
                ✓ {Math.round((validation.details.correctionScore || 0) * 100)}%
              </span>
              <span title="Estructura de respuesta">
                📝 {Math.round((validation.details.structureScore || 0) * 100)}%
              </span>
              <span title="Relevancia con la pregunta">
                🎯 {Math.round((validation.details.relevanceScore || 0) * 100)}%
              </span>
            </div>
          )}
        </div>
      )}

      <style>{`
        .confidence-badge-container {
          margin-top: 8px;
          margin-bottom: 4px;
        }
        
        .confidence-badge {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 6px 10px;
          background: rgba(30, 30, 50, 0.8);
          border-radius: 6px;
          border: 1px solid rgba(100, 100, 140, 0.3);
        }
        
        .confidence-indicator {
          width: 60px;
          height: 6px;
          background: rgba(60, 60, 80, 0.8);
          border-radius: 3px;
          overflow: hidden;
        }
        
        .confidence-bar {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s ease;
        }
        
        .confidence-info {
          display: flex;
          align-items: center;
          gap: 4px;
        }
        
        .confidence-label {
          color: #808090;
          font-size: 10px;
        }
        
        .confidence-value {
          font-size: 11px;
          font-weight: 600;
        }
        
        .confidence-badge.high {
          border-color: rgba(76, 175, 80, 0.3);
        }
        
        .confidence-badge.medium {
          border-color: rgba(255, 152, 0, 0.3);
        }
        
        .confidence-badge.low {
          border-color: rgba(244, 67, 54, 0.3);
        }
        
        .confidence-badge.very-low {
          border-color: rgba(156, 39, 176, 0.3);
        }
        
        .validation-details {
          margin-top: 6px;
        }
        
        .validation-warning {
          color: #ff9800;
          font-size: 10px;
          padding: 4px 8px;
          background: rgba(255, 152, 0, 0.1);
          border-radius: 4px;
          margin-bottom: 4px;
        }
        
        .validation-breakdown {
          display: flex;
          gap: 12px;
          font-size: 10px;
          color: #000000ff;
          padding: 4px 8px;
          background: rgba(40, 40, 60, 0.5);
          border-radius: 4px;
        }
        
        .validation-breakdown span {
          cursor: help;
        }
        
        .validation-breakdown span:hover {
          color: #a0a0c0;
        }
      `}</style>
    </div>
  );
}
