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
  const [showAdvancedIdx, setShowAdvancedIdx] = useState<number | null>(null);
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
      toast('Please choose a free period first.');
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
      toast('Please select an available teacher from the list.');
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
          <div className="lab">Diagnostics &amp; Easy Resolution</div>
          <h1>Conflict Center</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Identify which teacher is busy and resolve conflicts in one simple step.
          </p>
        </div>
        {onRefreshData && (
          <button className="btn sm" onClick={onRefreshData}>
            ↻ Check for Conflicts
          </button>
        )}
      </div>

      {/* Minimal Status Card */}
      <div className="card" style={{ marginBottom: '22px' }}>
        <div className="row sp">
          <div>
            <b>{items.length === 0 ? '✓ All Timetables Conflict-Free' : '⚠️ Action Needed'}</b>
            <div className="sm" style={{ marginTop: '2px' }}>
              {items.length === 0
                ? 'All teacher allocations and MDC/Minor offerings are synchronized across every department.'
                : `${items.length} scheduling conflict(s) detected. Use the 1-click Auto-Fix button below to instantly resolve each one.`}
            </div>
          </div>
          <span className={`tag ${items.length === 0 ? 'ok' : 'c'}`}>
            {items.length === 0 ? 'All Clear ✓' : `${items.length} Conflict(s)`}
          </span>
        </div>
      </div>

      {items.length > 0 ? (
        <div>
          <h2 style={{ fontSize: '18px', marginBottom: '14px' }}>Active Conflicts ({items.length})</h2>

          {items.map((x, idx) => {
            const entryId = x.department_session?.entry_id || (x.entry_ids && x.entry_ids[0]);
            const canFix = x.can_fix_internally !== false && !!entryId;
            const isAdvanced = showAdvancedIdx === idx;
            const teacherName = x.teacher_name || x.busy_details?.teacher_name;

            return (
              <div
                key={idx}
                className="card"
                style={{
                  borderLeft: `4px solid ${canFix ? 'var(--warn)' : 'var(--crit)'}`,
                  marginBottom: '16px',
                  padding: '18px 20px',
                }}
              >
                {/* Teacher Badge & Conflict Tag */}
                <div className="row sp" style={{ marginBottom: '10px' }}>
                  <div className="row" style={{ gap: '8px', flexWrap: 'wrap' }}>
                    {teacherName ? (
                      <span className="tag p" style={{ fontWeight: 600 }}>
                        👤 Teacher: {teacherName} {x.faculty_code ? `(${x.faculty_code})` : ''}
                      </span>
                    ) : (
                      <span className="tag c">Teacher Conflict</span>
                    )}

                    {canFix ? (
                      <span className="tag ok">1-Click Auto-Fix Available ✓</span>
                    ) : (
                      <span className="tag w">Requires Adjustment</span>
                    )}
                  </div>
                </div>

                {/* Plain English Conflict Summary */}
                <h3 style={{ fontSize: '16px', margin: '0 0 10px', lineHeight: 1.35, fontWeight: 600 }}>
                  {x.issue}
                </h3>

                {/* Clean, Beginner-Friendly Details Box */}
                {(x.busy_details || x.department_session) && (
                  <div
                    style={{
                      background: 'var(--panel)',
                      border: '1px solid var(--line)',
                      borderRadius: '8px',
                      padding: '12px 14px',
                      margin: '12px 0 16px',
                      fontSize: '13.5px',
                    }}
                  >
                    {x.busy_details && (
                      <div style={{ marginBottom: x.department_session ? '8px' : '0' }}>
                        <span style={{ color: 'var(--mute)' }}>Teacher is busy with: </span>
                        <b>{x.busy_details.subject || 'Another subject'}</b>
                        {x.busy_details.department && (
                          <span> in <b>{x.busy_details.department}</b></span>
                        )}
                        {x.busy_details.class_name && (
                          <span> ({x.busy_details.class_name})</span>
                        )}
                        {x.busy_details.day_name && (
                          <span> on <b>{x.busy_details.day_name} {x.busy_details.start}–{x.busy_details.end}</b></span>
                        )}
                      </div>
                    )}

                    {x.department_session && (
                      <div style={{ borderTop: x.busy_details ? '1px dashed var(--line)' : 'none', paddingTop: x.busy_details ? '8px' : '0' }}>
                        <span style={{ color: 'var(--mute)' }}>Clashes in your department with: </span>
                        <b>{x.department_session.subject}</b>
                        {x.department_session.class_name && (
                          <span> ({x.department_session.class_name})</span>
                        )}
                        {x.department_session.day_name && (
                          <span> on <b>{x.department_session.day_name} Period {x.department_session.period !== undefined ? x.department_session.period + 1 : ''} ({x.department_session.start}–{x.department_session.end})</b></span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Minimal Action Area */}
                {canFix ? (
                  <div>
                    <div className="row sp" style={{ gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                      <div className="row" style={{ gap: '10px', flexWrap: 'wrap' }}>
                        {/* 1-Click Primary Action */}
                        <button
                          type="button"
                          className="btn p"
                          disabled={loadingAction === `auto-${idx}`}
                          onClick={() => handleAutoResolve(idx, entryId)}
                          style={{ minHeight: '38px', padding: '6px 18px', fontWeight: 600 }}
                        >
                          {loadingAction === `auto-${idx}` ? 'Resolving…' : '⚡ Auto-Fix (Move to Free Slot)'}
                        </button>

                        {/* Secondary Toggle */}
                        <button
                          type="button"
                          className="btn sm"
                          onClick={() => setShowAdvancedIdx(isAdvanced ? null : idx)}
                          style={{ minHeight: '38px', fontSize: '13px' }}
                        >
                          {isAdvanced ? 'Hide Custom Options ▴' : 'Choose Slot or Teacher ▾'}
                        </button>
                      </div>

                      {onNavigate && (
                        <button
                          type="button"
                          className="btn sm"
                          onClick={() => onNavigate('tt')}
                          style={{ fontSize: '12.5px', color: 'var(--mute)' }}
                        >
                          View in Timetable Grid &rarr;
                        </button>
                      )}
                    </div>

                    {/* Expandable Custom Pickers (Optional for users who want manual control) */}
                    {isAdvanced && (
                      <div
                        style={{
                          marginTop: '14px',
                          paddingTop: '14px',
                          borderTop: '1px solid var(--line)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '12px',
                        }}
                      >
                        {/* Option A: Move to Specific Slot */}
                        {x.available_slots && x.available_slots.length > 0 && (
                          <div>
                            <div className="sm" style={{ fontWeight: 600, marginBottom: '6px' }}>
                              Option A: Choose a verified free period:
                            </div>
                            <div className="row" style={{ gap: '8px', flexWrap: 'wrap' }}>
                              <select
                                style={{ flex: '1', minWidth: '220px' }}
                                value={selectedSlotMap[idx] || ''}
                                onChange={(e) =>
                                  setSelectedSlotMap({ ...selectedSlotMap, [idx]: e.target.value })
                                }
                              >
                                <option value="">Select free period slot…</option>
                                {x.available_slots.map((s, sIdx) => (
                                  <option key={sIdx} value={`${s.day}-${s.period}`}>
                                    {s.day_name} · {s.period_label || `Period ${s.period + 1}`} ({s.start}–{s.end})
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="btn sm"
                                disabled={!selectedSlotMap[idx] || loadingAction === `move-${idx}`}
                                onClick={() => handleMoveSlot(idx, entryId)}
                              >
                                {loadingAction === `move-${idx}` ? 'Moving…' : 'Move to Slot'}
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Option B: Reassign to Another Teacher */}
                        {x.available_faculty && x.available_faculty.length > 0 && (
                          <div>
                            <div className="sm" style={{ fontWeight: 600, marginBottom: '6px' }}>
                              Option B: Or reassign subject to another free teacher:
                            </div>
                            <div className="row" style={{ gap: '8px', flexWrap: 'wrap' }}>
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
                                <option value="">Choose another teacher…</option>
                                {x.available_faculty.map((f) => (
                                  <option key={f.id} value={f.id}>
                                    {f.name} ({f.faculty_code}) · {f.current_load ?? 0}/{f.max_load ?? 18} sessions
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
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ marginTop: '8px' }}>
                    <div className="sm" style={{ color: 'var(--mute)', marginBottom: '8px' }}>
                      Recommended Action: {x.fix}
                    </div>
                    {onNavigate && (
                      <div className="row" style={{ gap: '8px' }}>
                        <button className="btn sm" onClick={() => onNavigate('ta')}>
                          Teacher Assignments
                        </button>
                        <button className="btn sm" onClick={() => onNavigate('av')}>
                          Teacher Availability
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty" style={{ padding: '40px 20px', textAlign: 'center' }}>
          <h2 style={{ fontSize: '20px', marginBottom: '8px' }}>✓ Zero Teacher Conflicts</h2>
          <p className="sub" style={{ maxWidth: '500px', margin: '0 auto' }}>
            All teacher allocations, classes, and MDC/Minor offerings are synchronized with zero double-booking across the entire college.
          </p>
        </div>
      )}
    </div>
  );
};
