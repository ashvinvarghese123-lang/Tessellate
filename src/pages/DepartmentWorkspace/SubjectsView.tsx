import React, { useState } from 'react';
import { SubjectAllocation, ClassItem, Faculty } from '../../types';
import { api } from '../../lib/api';
import { useToast } from '../../components/Toast';

interface SubjectsViewProps {
  allocations: SubjectAllocation[];
  classes: ClassItem[];
  faculty: Faculty[];
  onRefresh: () => void;
}

export const SubjectsView: React.FC<SubjectsViewProps> = ({
  allocations,
  classes,
  faculty,
  onRefresh,
}) => {
  const { toast } = useToast();
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [category, setCategory] = useState<'Regular' | 'MDC' | 'Minor'>('Regular');
  const [classId, setClassId] = useState<number>(classes[0]?.id || 0);
  const [facultyId, setFacultyId] = useState<number>(faculty[0]?.id || 0);
  const [sessions, setSessions] = useState(3);
  const [duration, setDuration] = useState(60);
  const [submitting, setSubmitting] = useState(false);

  const handleAddSubject = async (e: React.FormEvent) => {
    e.preventDefault();
    const subName = name.trim();
    if (!subName) return toast('Please enter a subject name.');
    if (!classId) return toast('Please select a class.');

    setSubmitting(true);
    try {
      await api('/api/allocations', {
        method: 'POST',
        body: {
          class_id: classId,
          subject: subName,
          code: code.trim(),
          course_category: category,
          faculty_id: facultyId,
          sessions,
          duration,
        },
      });
      toast('Subject added successfully.', true);
      setName('');
      setCode('');
      setSessions(3);
      onRefresh();
    } catch (err: any) {
      toast(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this subject offering?')) return;
    try {
      await api(`/api/allocations/${id}`, { method: 'DELETE' });
      toast('Subject deleted.', true);
      onRefresh();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const renderCatBadge = (cat: string) => {
    if (cat === 'MDC') return <span className="tag mdc">MDC</span>;
    if (cat === 'Minor') return <span className="tag minor">Minor</span>;
    return <span className="tag reg">Regular</span>;
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Curriculum</div>
          <h1>Subject Management</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Each department adds and manages the subjects it offers. Categorize as Regular, MDC, or Minor.
          </p>
        </div>
      </div>

      <div className="card noprint">
        <h2 style={{ marginTop: 0 }}>Add Department Subject</h2>
        <form onSubmit={handleAddSubject}>
          <div className="row" style={{ gap: '14px' }}>
            <label style={{ flex: '1 1 200px' }}>
              Subject Name
              <br />
              <input
                placeholder="e.g. Data Structures"
                style={{ width: '100%' }}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>

            <label style={{ flex: '1 1 120px' }}>
              Subject Code
              <br />
              <input
                placeholder="e.g. CS-201"
                style={{ width: '100%' }}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>

            <label style={{ flex: '1 1 140px' }}>
              Course Category
              <br />
              <select
                style={{ width: '100%' }}
                value={category}
                onChange={(e) => setCategory(e.target.value as any)}
              >
                <option value="Regular">Regular</option>
                <option value="MDC">MDC</option>
                <option value="Minor">Minor</option>
              </select>
            </label>

            <label style={{ flex: '1 1 160px' }}>
              Class (from Registry)
              <br />
              <select
                style={{ width: '100%' }}
                value={classId}
                onChange={(e) => setClassId(Number(e.target.value))}
              >
                {classes.length ? (
                  classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))
                ) : (
                  <option value="">No classes configured in Registry</option>
                )}
              </select>
            </label>

            <label style={{ flex: '1 1 180px' }}>
              Assigned Teacher
              <br />
              <select
                style={{ width: '100%' }}
                value={facultyId}
                onChange={(e) => setFacultyId(Number(e.target.value))}
              >
                {faculty.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.faculty_code} · {f.department})
                  </option>
                ))}
              </select>
            </label>

            <label style={{ flex: '0 0 100px' }}>
              Sessions/Wk
              <br />
              <input
                type="number"
                min="1"
                max="10"
                value={sessions}
                onChange={(e) => setSessions(Number(e.target.value))}
                style={{ width: '100%' }}
              />
            </label>

            <label style={{ flex: '0 0 110px' }}>
              Duration
              <br />
              <select
                style={{ width: '100%' }}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
              >
                <option value="60">60 min</option>
                <option value="45">45 min</option>
                <option value="90">90 min</option>
              </select>
            </label>

            <label style={{ alignSelf: 'flex-end' }}>
              <button type="submit" className="btn p" disabled={submitting}>
                Add Subject
              </button>
            </label>
          </div>
        </form>

        <div className="row" style={{ marginTop: '14px', gap: '12px', fontSize: '12.5px', color: 'var(--mute)' }}>
          <div>
            <span className="tag reg">Regular</span> Scheduled within department's regular timetable.
          </div>
          <div>
            <span className="tag mdc">MDC</span> Assigned to agreed MDC common periods.
          </div>
          <div>
            <span className="tag minor">Minor</span> Assigned to agreed Minor common periods.
          </div>
        </div>
      </div>

      {allocations.length ? (
        <div className="gw">
          <table className="l">
            <thead>
              <tr>
                <th>Code</th>
                <th>Subject Name</th>
                <th>Category</th>
                <th>Class</th>
                <th>Assigned Teacher</th>
                <th>Sessions</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {allocations.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{a.subject_code || a.code || '—'}</b>
                  </td>
                  <td>{a.subject}</td>
                  <td>{renderCatBadge(a.course_category)}</td>
                  <td>{a.class_name}</td>
                  <td>
                    {a.teacher} <span className="sm">({a.faculty_code})</span>
                  </td>
                  <td>{a.sessions_per_week} sess/wk</td>
                  <td>{a.duration || 60} min</td>
                  <td>
                    <b>{a.placed}</b> / {a.sessions_per_week} placed
                  </td>
                  <td>
                    <div className="row" style={{ gap: '6px' }}>
                      <button className="btn sm" onClick={() => handleDelete(a.id)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty">
          <h2>No subjects defined yet</h2>
          <p>Use the form above to add your first subject offering.</p>
        </div>
      )}
    </div>
  );
};
