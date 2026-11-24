import React from 'react';
import { ConflictResponse, GenerationResult } from '../../types';

interface ConflictCenterViewProps {
  conflicts: ConflictResponse;
  generationResult: GenerationResult | null;
}

export const ConflictCenterView: React.FC<ConflictCenterViewProps> = ({
  conflicts,
  generationResult,
}) => {
  const items = (generationResult && generationResult.issues) || conflicts.items || [];

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Diagnostics</div>
          <h1>Conflict Detection Center</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            College-wide teacher conflict verification. Zero double-booking guarantee.
          </p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <div className="row sp">
          <div>
            <b>Teacher-Centric Conflict Diagnostics</b>
            <div className="sm">
              Verifies: Simultaneous assignments across departments, unavailable period violations, and
              workload limits.
            </div>
          </div>
          <span className={`tag ${items.length === 0 ? 'ok' : 'c'}`}>
            {items.length === 0 ? 'All Clear ✓' : `${items.length} Active Conflict(s)`}
          </span>
        </div>
      </div>

      <h2>Detected Conflicts &amp; Actionable Solutions</h2>

      {items.length ? (
        items.map((x, idx) => (
          <div key={idx} className="card" style={{ borderLeft: '4px solid var(--crit)' }}>
            <div className="row sp">
              <span className="tag c">Teacher Conflict</span>
              <span className="sm">Affects schedule generation</span>
            </div>
            <h2 style={{ fontSize: '16px', margin: '8px 0 4px' }}>{x.issue}</h2>
            <div style={{ fontSize: '13.5px', color: 'var(--mute)', marginTop: '6px' }}>
              <b>Recommended Fix:</b> {x.fix}
            </div>
          </div>
        ))
      ) : (
        <div className="empty">
          <h2>✓ No teacher scheduling conflicts</h2>
          <p>
            All teacher allocations and MDC/Minor offerings are completely synchronized and conflict-free across
            the college.
          </p>
        </div>
      )}
    </div>
  );
};
