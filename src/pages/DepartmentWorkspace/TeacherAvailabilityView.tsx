import React, { useState, useEffect } from 'react';
import { Faculty, AvailabilitySlot } from '../../types';
import { api, DAYS } from '../../lib/api';
import { useToast } from '../../components/Toast';

interface TeacherAvailabilityViewProps {
  faculty: Faculty[];
  selectedFacultyId: number | null;
  onSelectFaculty: (id: number) => void;
}

export const TeacherAvailabilityView: React.FC<TeacherAvailabilityViewProps> = ({
  faculty,
  selectedFacultyId,
  onSelectFaculty,
}) => {
  const { toast } = useToast();
  const [currentFacId, setCurrentFacId] = useState<number>(selectedFacultyId || faculty[0]?.id || 0);
  const [availability, setAvailability] = useState<AvailabilitySlot[]>([]);
  const [unavailableSet, setUnavailableSet] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (selectedFacultyId && selectedFacultyId !== currentFacId) {
      setCurrentFacId(selectedFacultyId);
    }
  }, [selectedFacultyId, currentFacId]);

  useEffect(() => {
    if (!currentFacId) return;
    let active = true;

    Promise.all([
      api<AvailabilitySlot[]>(`/api/faculty/${currentFacId}/availability`),
      api<AvailabilitySlot[]>(`/api/faculty/${currentFacId}/base-availability`),
    ])
      .then(([av, base]) => {
        if (!active) return;
        setAvailability(av);
        const un = new Set(
          base.filter((c) => c.state === 'unavailable').map((c) => `${c.day},${c.period}`)
        );
        setUnavailableSet(un);
      })
      .catch((err) => toast(err.message));

    return () => {
      active = false;
    };
  }, [currentFacId, toast]);

  const curFac = faculty.find((f) => f.id === currentFacId) || faculty[0];

  const handleTeacherChange = (id: number) => {
    setCurrentFacId(id);
    onSelectFaculty(id);
  };

  const toggleSlot = (d: number, p: number) => {
    const key = `${d},${p}`;
    setUnavailableSet((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleSave = async () => {
    if (!curFac) return;
    setSaving(true);
    try {
      const slots = Array.from(unavailableSet).map((k) => k.split(',').map(Number));
      await api(`/api/faculty/${curFac.id}/unavailable`, {
        method: 'PUT',
        body: { slots },
      });
      toast('Teacher availability saved.', true);
      // Refresh current availability
      const av = await api<AvailabilitySlot[]>(`/api/faculty/${curFac.id}/availability`);
      setAvailability(av);
    } catch (err: any) {
      toast(err.message);
    } finally {
      setSaving(false);
    }
  };

  const days = Array.from(new Set(availability.map((x) => x.day))).sort((a, b) => a - b);
  const pers = Array.from(new Set(availability.map((x) => x.period))).sort((a, b) => a - b);
  const getPeriodTime = (p: number) => {
    const slot = availability.find((x) => x.period === p);
    return slot ? slot.start : '';
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Faculty Constraints</div>
          <h1>Teacher Availability</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Define when teachers are available or unavailable. The scheduler strictly respects these rules.
          </p>
        </div>
      </div>

      <div className="card noprint">
        <div className="row sp">
          <div className="row" style={{ gap: '12px' }}>
            <label>
              <b>Select Teacher:</b>
              <br />
              <select
                style={{ minWidth: '260px' }}
                value={currentFacId}
                onChange={(e) => handleTeacherChange(Number(e.target.value))}
              >
                {faculty.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.faculty_code} · {f.department})
                  </option>
                ))}
              </select>
            </label>
            {curFac && (
              <div style={{ alignSelf: 'flex-end' }}>
                <span className="sm">
                  Home Department: <b>{curFac.department}</b> · Scheduled: <b>{curFac.sessions}</b> /{' '}
                  {curFac.max_weekly_sessions} sessions
                </span>
              </div>
            )}
          </div>
          <div style={{ alignSelf: 'flex-end' }}>
            <button className="btn p" onClick={handleSave} disabled={saving}>
              Save Availability Changes
            </button>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: '14px' }}>
        <p className="sm" style={{ margin: '0 0 10px' }}>
          Click any slot to toggle between <b>Available</b> and <b>Unavailable</b>. Slots marked{' '}
          <b>Busy (Teaching)</b> are locked by active scheduled classes.
        </p>

        <div className="gw">
          <table className="g" style={{ minWidth: '600px' }}>
            <thead>
              <tr>
                <th></th>
                {days.map((d) => (
                  <th key={d}>{DAYS[d].slice(0, 3)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pers.map((p) => (
                <tr key={p}>
                  <td className="t">{getPeriodTime(p)}</td>
                  {days.map((d) => {
                    const c = availability.find((x) => x.day === d && x.period === p);
                    if (c && c.state === 'busy') {
                      return (
                        <td key={d} style={{ height: '50px' }}>
                          <div className="bz off" title={c.reason}>
                            Busy (Teaching)
                          </div>
                        </td>
                      );
                    }
                    const isUn = unavailableSet.has(`${d},${p}`);
                    return (
                      <td key={d} style={{ height: '50px' }}>
                        <button
                          type="button"
                          className={`tg ${isUn ? 'on' : ''}`}
                          onClick={() => toggleSlot(d, p)}
                          aria-pressed={isUn}
                        >
                          {isUn ? 'Unavailable' : 'Available'}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
