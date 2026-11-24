import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ToastProvider } from './components/Toast';
import { AuthProvider } from './context/AuthContext';
import { RegistryAuthProvider } from './context/RegistryAuthContext';

import { DepartmentWorkspace } from './pages/DepartmentWorkspace';
import { Registry } from './pages/Registry';
import { Login } from './pages/Login';
import { RegistryLogin } from './pages/RegistryLogin';
import { Signup } from './pages/Signup';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <RegistryAuthProvider>
            <Routes>
              {/* Department Workspace */}
              <Route path="/" element={<DepartmentWorkspace />} />
              <Route path="/index.html" element={<DepartmentWorkspace />} />

              {/* Department Login */}
              <Route path="/login" element={<Login />} />
              <Route path="/login.html" element={<Login />} />

              {/* Registry Login */}
              <Route path="/registry-login" element={<RegistryLogin />} />
              <Route path="/registry-login.html" element={<RegistryLogin />} />

              {/* Registry Dashboard */}
              <Route path="/registry" element={<Registry />} />
              <Route path="/registry.html" element={<Registry />} />

              {/* Signup Notice */}
              <Route path="/signup" element={<Signup />} />
              <Route path="/signup.html" element={<Signup />} />

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </RegistryAuthProvider>
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
};
export default App;
