// Role-based authorization middleware
// Validates that the requesting user has the required role

export const requireRole = (...allowedRoles) => {
  return (req, res, next) => {
    const userId = req.headers['x-user-id'];
    const userRol = req.headers['x-user-rol'];

    if (!userId || !userRol) {
      return res.status(401).json({ 
        error: 'No autenticado. Se requiere x-user-id y x-user-rol' 
      });
    }

    if (!allowedRoles.includes(userRol)) {
      return res.status(403).json({ 
        error: `Acceso denegado. Roles permitidos: ${allowedRoles.join(', ')}` 
      });
    }

    req.user = { id: parseInt(userId), rol: userRol };
    next();
  };
};

export const optionalAuth = (req, res, next) => {
  const userId = req.headers['x-user-id'];
  const userRol = req.headers['x-user-rol'];

  if (userId && userRol) {
    req.user = { id: parseInt(userId), rol: userRol };
  }
  
  next();
};
