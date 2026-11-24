import React, { useEffect, useState } from 'react';

interface EngineOverlayProps {
  isOpen: boolean;
  departmentName: string;
  steps: string[];
  finalMessage?: string;
}

export const EngineOverlay: React.FC<EngineOverlayProps> = ({
  isOpen,
  departmentName,
  steps,
  finalMessage,
}) => {
  const [displayedSteps, setDisplayedSteps] = useState<string[]>([]);

  useEffect(() => {
    if (!isOpen) {
      setDisplayedSteps([]);
      return;
    }

    let i = 0;
    const interval = setInterval(() => {
      if (i < steps.length) {
        setDisplayedSteps((prev) => [...prev, steps[i]]);
        i++;
      } else {
        clearInterval(interval);
      }
    }, 350);

    return () => clearInterval(interval);
  }, [isOpen, steps]);

  if (!isOpen) return null;

  return (
    <div className="ov" role="dialog" aria-label="Processing">
      <div className="box">
        <div className="lab">Automated Timetable Generation</div>
        <h1 style={{ fontSize: '24px' }}>{departmentName || 'Tessellate Engine'}</h1>
        <ul aria-live="polite">
          {displayedSteps.map((step, idx) => (
            <li key={idx}>{step}</li>
          ))}
          {finalMessage && <li style={{ fontWeight: 600, marginTop: '8px' }}>{finalMessage}</li>}
        </ul>
      </div>
    </div>
  );
};
