import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';

interface ToastContextType {
  toast: (message: string, isOk?: boolean) => void;
}

const ToastContext = createContext<ToastContextType>({
  toast: () => {},
});

export const useToast = () => useContext(ToastContext);

export const ToastProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [toastData, setToastData] = useState<{ message: string; ok: boolean } | null>(null);

  const showToast = useCallback((message: string, isOk: boolean = false) => {
    setToastData({ message, ok: isOk });
    setTimeout(() => {
      setToastData(null);
    }, 5000);
  }, []);

  return (
    <ToastContext.Provider value={{ toast: showToast }}>
      {children}
      {toastData && (
        <div className="toast" role="status">
          <span>{toastData.ok ? '✓ ' : '⚠ '}</span>
          <span>{toastData.message}</span>
        </div>
      )}
    </ToastContext.Provider>
  );
};
