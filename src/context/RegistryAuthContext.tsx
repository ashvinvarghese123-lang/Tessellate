import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { RegistryMe } from '../types';
import { api } from '../lib/api';

interface RegistryAuthContextType {
  operator: RegistryMe | null;
  loading: boolean;
  refreshOperator: () => Promise<void>;
  logout: () => Promise<void>;
}

const RegistryAuthContext = createContext<RegistryAuthContextType>({
  operator: null,
  loading: true,
  refreshOperator: async () => {},
  logout: async () => {},
});

export const useRegistryAuth = () => useContext(RegistryAuthContext);

export const RegistryAuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [operator, setOperator] = useState<RegistryMe | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshOperator = useCallback(async () => {
    try {
      const data = await api<RegistryMe>('/api/registry/auth/me');
      setOperator(data);
    } catch {
      setOperator(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api('/api/registry/auth/logout', { method: 'POST' });
    } finally {
      setOperator(null);
      window.location.replace('/registry-login.html');
    }
  }, []);

  useEffect(() => {
    refreshOperator();
  }, [refreshOperator]);

  return (
    <RegistryAuthContext.Provider value={{ operator, loading, refreshOperator, logout }}>
      {children}
    </RegistryAuthContext.Provider>
  );
};
