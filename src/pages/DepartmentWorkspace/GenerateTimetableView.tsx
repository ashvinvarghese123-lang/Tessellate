import React from 'react';
import { SubjectAllocation, Faculty, SettingsResponse, ConflictResponse, GenerationResult } from '../../types';

interface GenerateTimetableViewProps {
  allocations: SubjectAllocation[];
  faculty: Faculty[];
  settings: SettingsResponse | null;
  conflicts: ConflictResponse;
  generationResult: GenerationResult | null;
  onGenerate: () => void;
  onNavigate: (view: string) => void;
}

export const GenerateTimetableView: React.FC<GenerateTimetableViewProps> = ({
  allocations,
  settings,
  conflicts,
  generationResult,
  onGenerate,
  onNavigate,
}) => {
  const unassigned = allocations.filter((a) => !a.faculty_id);
  const hasSubjects = allocations.length > 0;
  const issues = (generationResult && generationResult.issues) || conflicts.items || [];

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Solver Engine</div>
          <h1>Generate Timetable</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Run the automated constraint-based scheduler to create a conflict-free department timetable.
          </p>
        </div>
      </div>

      <div className="cols">
        <div>
          <h2>Readiness Checklist</h2>
          <div className="card">
            <div className="item row sp">
              <div>
                <b>Department Subjects</b>
                <div className="sm">{allocations.length} subjects configured</div>
              </div>
              <span className={`tag ${hasSubjects ? 'ok' : 'w'}`}>
                {hasSubjects ? '✓ Ready' : '⚠ Add Subjects'}
              </span>
            </div>
            <div className="item row sp">
              <div>
                <b>Teacher Allocations</b>
                <div className="sm">
                  {unassigned.length === 0
                    ? 'All subjects assigned to teachers'
                    : `${unassigned.length} unassigned subjects`}
                </div>
              </div>
              <span className={`tag ${unassigned.length === 0 ? 'ok' : 'c'}`}>
                {unassigned.length === 0 ? '✓ Ready' : '⚠ Incomplete'}
              </span>
            </div>
            <div className="item row sp">
              <div>
                <b>Scheduling Rules</b>
                <div className="sm">
                  {settings ? `${settings.config.days.length} working days, ${settings.config.periods.length} periods/day` : 'Loading...'}
                </div>
              </div>
              <span className="tag ok">✓ Configured</span>
            </div>
            <div className="item row sp">
              <div>
                <b>Cross-Department Synchronization</b>
                <div className="sm">Real-time teacher availability synced with college</div>
              </div>
              <span className="tag ok">✓ Synced</span>
            </div>
          </div>

          <div className="card" style={{ marginTop: '20px', textAlign: 'center', padding: '32px 20px' }}>
            <h2 style={{ marginTop: 0 }}>Ready to Generate?</h2>
            <p className="sm" style={{ maxWidth: '440px', margin: '0 auto 20px' }}>
              The solver checks all teacher allocations across every department to guarantee zero double-booking.
            </p>
            <button
              className="btn p"
              onClick={onGenerate}
              style={{ fontSize: '16px', padding: '12px 28px', minHeight: '48px' }}
            >
              Generate Department Timetable
            </button>
          </div>
        </div>

        <div>
          <h2>Generation Results &amp; Status</h2>
          <div className="card">
            {generationResult ? (
              generationResult.status === 'ok' ? (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <span className="tag ok" style={{ fontSize: '14px', padding: '4px 10px' }}>
                    ✓ Timetable Generated
                  </span>
                  <h2 style={{ margin: '14px 0 6px' }}>Valid &amp; Conflict-Free Schedule</h2>
                  <p className="sm">
                    Total placed sessions: <b>{generationResult.sessions}</b> · Quality score:{' '}
                    <b>{generationResult.quality}%</b>
                  </p>
                  <div className="row" style={{ justifyContent: 'center', marginTop: '16px', gap: '10px' }}>
                    <button className="btn p" onClick={() => onNavigate('tt')}>
                      Open Timetable
                    </button>
                    <button className="btn" onClick={() => onNavigate('co')}>
                      Review Conflict Center
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ padding: '10px 0' }}>
                  <span className="tag c" style={{ fontSize: '14px', padding: '4px 10px' }}>
                    ⚠ Constraints Could Not Fit
                  </span>
                  <h2 style={{ margin: '14px 0 6px' }}>Scheduling Bottleneck Detected</h2>
                  <p className="sm">{generationResult.message || 'Could not fit all sessions.'}</p>
                  {issues.map((i, idx) => (
                    <div key={idx} className="item">
                      <span className="tag c">Constraint</span> <b>{i.issue}</b>
                      <div className="sm" style={{ marginTop: '4px' }}>
                        Fix: {i.fix}
                      </div>
                    </div>
                  ))}
                  <button className="btn p" onClick={() => onNavigate('co')} style={{ marginTop: '16px' }}>
                    Go to Conflict Center
                  </button>
                </div>
              )
            ) : (
              <div className="empty" style={{ padding: '30px 10px' }}>
                <h2>No generation run yet this session</h2>
                <p className="sm">Click the generate button to solve your schedule.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
