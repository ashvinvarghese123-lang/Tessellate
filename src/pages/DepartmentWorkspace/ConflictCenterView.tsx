import React, { useState } from 'react';
import { ConflictItem, ConflictResponse, GenerationResult } from '../../types';
import { api } from '../../lib/api';
import { useToast } from '../../components/Toast';

interface ConflictCenterViewProps {
  conflicts: ConflictResponse;
  generationResult: GenerationResult | null;
  onRefreshData?: () => void;
  onNavigate?: (view: string) => void;
}

export const ConflictCenterView: React.FC<ConflictCenterViewProps> = ({
  conflicts,
  generationResult,
  onRefreshData,
  onNavigate,
}) => {
  const { toast } = useToast();
  const items: ConflictItem[] = (generationResult && generationResult.issues) || conflicts.items || [];
  const [expandedIdx, setExpandedIdx] = useState<number | null>(items.length > 0 ? 0 : null);
  const [selectedSlotMap, setSelectedSlotMap] = useState<Record<number, string>>({});
  const [selectedFacMap, setSelectedFacMap] = useState<Record<number, number>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);

  const handleAutoResolve = async (idx: number, entryId: number) => {
    setLoadingAction(`auto-${idx}`);
    try {
      const res = await api<{ ok: boolean; message: string }>('/api/conflicts/fix/auto-resolve', {
        method: 'POST',
        body: { entry_id: entryId },
      });
      toast(res.message || 'Conflict resolved successfully!');
      if (onRefreshData) onRefreshData();
    } catch (err: any) {
      toast(err.message || 'Failed to auto-resolve conflict.');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleMoveSlot = async (idx: number, entryId: number) => {
    const slotKey = selectedSlotMap[idx];
    if (!slotKey) {
      toast('Please choose a target period slot.');
      return;
    }
    const [dayStr, periodStr] = slotKey.split('-');
    const day = parseInt(dayStr, 10);
    const period = parseInt(periodStr, 10);

    setLoadingAction(`move-${idx}`);
    try {
      const res = await api<{ ok: boolean; message: string }>('/api/conflicts/fix/move-slot', {
        method: 'POST',
        body: { entry_id: entryId, day, period },
      });
      toast(res.message || 'Session moved. Conflict resolved!');
      if (onRefreshData) onRefreshData();
    } catch (err: any) {
      toast(err.message || 'Failed to move session.');
    } finally {
      setLoadingAction(null);
    }
  };

  const handleReassignTeacher = async (idx: number, entryId: number) => {
    const facultyId = selectedFacMap[idx];
    if (!facultyId) {
      toast('Please select an available teacher to reassign.');
      return;
    }

    setLoadingAction(`reassign-${idx}`);
    try {
      const res = await api<{ ok: boolean; message: string }>('/api/conflicts/fix/reassign-teacher', {
        method: 'POST',
        body: { entry_id: entryId, faculty_id: facultyId, update_allocation: true },
      });
      toast(res.message || 'Teacher reassigned. Conflict resolved!');
      if (onRefreshData) onRefreshData();
    } catch (err: any) {
      toast(err.message || 'Failed to reassign teacher.');
    } finally {
      setLoadingAction(null);
    }
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Diagnostics &amp; Resolution</div>
          <h1>Conflict Detection Center</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            College-wide teacher conflict verification with intelligent in-department resolution.
          </p>
        </div>
        {onRefreshData && (
          <button className="btn sm" onClick={onRefreshData}>
            ↻ Check for Conflicts
          </button>
        )}
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
        items.map((x, idx) => {
          const isExpanded = expandedIdx === idx;
          const entryId = x.department_session?.entry_id || (x.entry_ids && x.entry_ids[0]);
          const canFix = x.can_fix_internally !== false && !!entryId;

          return (
            <div
              key={idx}
              className="card"
              style={{
                borderLeft: `4px solid ${canFix ? 'var(--warn)' : 'var(--crit)'}`,
                marginBottom: '16px',
                transition: 'border-color 0.2s ease',
              }}
            >
              <div
                className="row sp"
                style={{ cursor: 'pointer', userSelect: 'none' }}
                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
              >
                <div className="row" style={{ gap: '8px', flexWrap: 'wrap' }}>
                  <span className={`tag ${canFix ? 'w' : 'c'}`}>
                    {x.type === 'teacher_unavailable'
                      ? 'Teacher Unavailable'
                      : x.type === 'teacher_clash_internal'
                      ? 'Internal Teacher Clash'
                      : x.type === 'teacher_capacity'
                      ? 'Workload Limit'
                      : 'Teacher Conflict'}
                  </span>
                  {x.teacher_name && (
                    <span className="tag p">
                      {x.teacher_name} {x.faculty_code ? `(${x.faculty_code})` : ''}
                    </span>
                  )}
                  {canFix ? (
                    <span className="tag ok">Fixable in Department ✓</span>
                  ) : (
                    <span className="tag w">Requires Coordination</span>
                  )}
                </div>
                <button
                  type="button"
                  className="btn sm"
                  style={{ fontSize: '12px', padding: '4px 10px' }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpandedIdx(isExpanded ? null : idx);
                  }}
                >
                  {isExpanded ? 'Hide Options ▴' : 'Manage & Fix Conflict ▾'}
                </button>
              </div>

              <h2
                style={{
                  fontSize: '16.5px',
                  margin: '10px 0 6px',
                  cursor: 'pointer',
                }}
                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
              >
                {x.issue}
              </h2>

              {/* Teacher Busy & Session Details */}
              {(x.busy_details || x.department_session) && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                    gap: '12px',
                    margin: '12px 0',
                    padding: '12px 14px',
                    background: 'var(--panel)',
                    border: '1px solid var(--line)',
                    borderRadius: '7px',
                  }}
                >
                  {x.busy_details && (
                    <div>
                      <div className="lab" style={{ color: 'var(--warn)', marginBottom: '4px' }}>
                        Where Teacher is Busy
                      </div>
                      <div style={{ fontSize: '13.5px', fontWeight: 600 }}>
                        {x.busy_details.teacher_name}{' '}
                        {x.busy_details.faculty_code ? `(${x.busy_details.faculty_code})` : ''}
                      </div>
                      <div className="sm" style={{ marginTop: '2px' }}>
                        {x.busy_details.department && (
                          <span>
                            Department: <b>{x.busy_details.department}</b>
                            <br />
                          </span>
                        )}
                        {x.busy_details.subject && (
                          <span>
                            Course / Subject: <b>{x.busy_details.subject}</b>
                            <br />
                          </span>
                        )}
                        {x.busy_details.day_name && (
                          <span>
                            Scheduled Time:{' '}
                            <b>
                              {x.busy_details.day_name} {x.busy_details.start}–{x.busy_details.end}
                            </b>
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {x.department_session && (
                    <div>
                      <div className="lab" style={{ color: 'var(--acc)', marginBottom: '4px' }}>
                        Conflicting Session in Your Department
                      </div>
                      <div style={{ fontSize: '13.5px', fontWeight: 600 }}>
                        {x.department_session.subject}
                      </div>
                      <div className="sm" style={{ marginTop: '2px' }}>
                        {x.department_session.class_name && (
                          <span>
                            Class: <b>{x.department_session.class_name}</b>
                            <br />
                          </span>
                        )}
                        {x.department_session.day_name && (
                          <span>
                            Current Slot:{' '}
                            <b>
                              {x.department_session.day_name}{' '}
                              {x.department_session.period !== undefined
                                ? `Period ${x.department_session.period + 1} `
                                : ''}
                              ({x.department_session.start}–{x.department_session.end})
                            </b>
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div style={{ fontSize: '13.5px', color: 'var(--mute)', marginTop: '6px' }}>
                <b>Recommended Fix:</b> {x.fix}
              </div>

              {/* Interactive In-Department Resolution Drawer */}
              {isExpanded && (
                <div
                  style={{
                    marginTop: '16px',
                    paddingTop: '16px',
                    borderTop: '1px solid var(--line)',
                  }}
                >
                  {canFix ? (
                    <div>
                      <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '12px' }}>
                        Resolve this conflict within your department:
                      </div>

                      <div
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '14px',
                        }}
                      >
                        {/* Option 1: Auto Resolve */}
                        <div
                          style={{
                            padding: '12px 14px',
                            background: 'var(--accbg)',
                            borderRadius: '7px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: '10px',
                          }}
                        >
                          <div>
                            <b style={{ color: 'var(--acc)' }}>1-Click Instant Resolution</b>
                            <div className="sm" style={{ color: 'var(--ink)' }}>
                              Automatically finds the earliest conflict-free period where this teacher and class
                              are both free.
                            </div>
                          </div>
                          <button
                            type="button"
                            className="btn p sm"
                            disabled={loadingAction === `auto-${idx}`}
                            onClick={() => handleAutoResolve(idx, entryId)}
                          >
                            {loadingAction === `auto-${idx}` ? 'Resolving…' : '⚡ Auto-Move to Free Slot'}
                          </button>
                        </div>

                        {/* Option 2: Move to Specific Slot */}
                        {x.available_slots && x.available_slots.length > 0 && (
                          <div
                            style={{
                              padding: '12px 14px',
                              background: 'var(--panel)',
                              border: '1px solid var(--line)',
                              borderRadius: '7px',
                            }}
                          >
                            <b>Choose an Alternative Conflict-Free Period:</b>
                            <div className="sm" style={{ marginBottom: '8px' }}>
                              These slots are verified free of any teacher, class, or room double-booking.
                            </div>
                            <div className="row" style={{ gap: '10px', flexWrap: 'wrap' }}>
                              <select
                                style={{ flex: '1', minWidth: '220px' }}
                                value={selectedSlotMap[idx] || ''}
                                onChange={(e) =>
                                  setSelectedSlotMap({ ...selectedSlotMap, [idx]: e.target.value })
                                }
                              >
                                <option value="">Select conflict-free period…</option>
                                {x.available_slots.map((s, sIdx) => (
                                  <option key={sIdx} value={`${s.day}-${s.period}`}>
                                    {s.day_name} · {s.period_label || `Period ${s.period + 1}`} ({s.start}–
                                    {s.end})
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="btn sm"
                                disabled={!selectedSlotMap[idx] || loadingAction === `move-${idx}`}
                                onClick={() => handleMoveSlot(idx, entryId)}
                              >
                                {loadingAction === `move-${idx}` ? 'Moving…' : 'Move to Selected Slot'}
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Option 3: Reassign to Another Teacher */}
                        {x.available_faculty && x.available_faculty.length > 0 && (
                          <div
                            style={{
                              padding: '12px 14px',
                              background: 'var(--panel)',
                              border: '1px solid var(--line)',
                              borderRadius: '7px',
                            }}
                          >
                            <b>Reassign Subject to Another Available Teacher:</b>
                            <div className="sm" style={{ marginBottom: '8px' }}>
                              Teachers listed below are completely free during this time and within their weekly
                              limit.
                            </div>
                            <div className="row" style={{ gap: '10px', flexWrap: 'wrap' }}>
                              <select
                                style={{ flex: '1', minWidth: '220px' }}
                                value={selectedFacMap[idx] || ''}
                                onChange={(e) =>
                                  setSelectedFacMap({
                                    ...selectedFacMap,
                                    [idx]: parseInt(e.target.value, 10),
                                  })
                                }
                              >
                                <option value="">Choose available faculty member…</option>
                                {x.available_faculty.map((f) => (
                                  <option key={f.id} value={f.id}>
                                    {f.name} ({f.faculty_code}) · Load: {f.current_load ?? 0}/
                                    {f.max_load ?? 18} sessions
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="btn sm"
                                disabled={!selectedFacMap[idx] || loadingAction === `reassign-${idx}`}
                                onClick={() => handleReassignTeacher(idx, entryId)}
                              >
                                {loadingAction === `reassign-${idx}` ? 'Reassigning…' : 'Reassign Teacher'}
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Option 4: Open in Timetable Editor */}
                        {onNavigate && (
                          <div className="row sp" style={{ marginTop: '4px' }}>
                            <span className="sm">Prefer dragging and dropping visually?</span>
                            <button
                              type="button"
                              className="btn sm"
                              onClick={() => onNavigate('tt')}
                              style={{ fontSize: '12.5px' }}
                            >
                              Open in Timetable Grid &rarr;
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: '8px 0' }}>
                      <p className="sm" style={{ margin: '0 0 10px' }}>
                        This conflict involves institution-wide constraints or teacher availability limits that
                        can be adjusted in your department rules or faculty assignments:
                      </p>
                      <div className="row" style={{ gap: '8px' }}>
                        {onNavigate && (
                          <>
                            <button className="btn sm" onClick={() => onNavigate('ta')}>
                              Teacher Assignments
                            </button>
                            <button className="btn sm" onClick={() => onNavigate('av')}>
                              Teacher Availability
                            </button>
                            <button className="btn sm" onClick={() => onNavigate('rul')}>
                              Scheduling Rules
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })
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
