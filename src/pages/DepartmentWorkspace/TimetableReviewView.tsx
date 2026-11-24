import React, { useState, useEffect } from 'react';
import { ClassItem, Faculty, TimetableEntry, DepartmentConfig } from '../../types';
import { api, DAYS, tmn } from '../../lib/api';
import { useToast } from '../../components/Toast';

interface TimetableReviewViewProps {
  classes: ClassItem[];
  faculty: Faculty[];
  config: DepartmentConfig | null;
  onNavigate: (view: string) => void;
}

export const TimetableReviewView: React.FC<TimetableReviewViewProps> = ({
  classes,
  faculty,
  config,
  onNavigate,
}) => {
  const { toast } = useToast();
  const [mode, setMode] = useState<'class' | 'teacher'>('class');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [overSlot, setOverSlot] = useState<{ day: number; period: number } | null>(null);

  const entities =
    mode === 'class'
      ? classes.map((c) => ({ id: c.id, label: c.name }))
      : faculty.map((f) => ({ id: f.id, label: `${f.name} (${f.faculty_code})` }));

  useEffect(() => {
    if (!entities.some((e) => e.id === selectedId)) {
      setSelectedId(entities.length ? entities[0].id : null);
    }
  }, [mode, entities, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setEntries([]);
      return;
    }
    const url = mode === 'class' ? `/api/timetable/${selectedId}` : `/api/faculty/${selectedId}/timetable`;
    api<TimetableEntry[]>(url)
      .then(setEntries)
      .catch((err) => toast(err.message));
  }, [selectedId, mode, toast]);

  if (!config) {
    return <p className="sub">Loading timetable configuration…</p>;
  }

  const periods = config.periods.map((p, i) => ({ s: p.start, e: p.end, p: i }));
  const otherPeriods: Array<{ s: string; e: string; p: number }> = [];
  const seenTimes = new Set<string>();

  entries.forEach((r) => {
    const k = `${r.start}-${r.end}`;
    if (!seenTimes.has(k)) {
      seenTimes.add(k);
      otherPeriods.push({ s: r.start, e: r.end, p: -1 });
    }
  });

  const knownTimes = new Set(periods.map((r) => `${r.s}-${r.e}`));
  let allRows =
    mode === 'class'
      ? periods.concat(otherPeriods.filter((o) => !knownTimes.has(`${o.s}-${o.e}`)))
      : otherPeriods.length
      ? otherPeriods
      : periods;

  allRows = allRows.sort((a, b) => (a.s < b.s ? -1 : a.s > b.s ? 1 : 0));
  const days = Array.from(new Set(config.days.concat(entries.map((r) => r.day)))).sort((a, b) => a - b);

  const handleDragStart = (id: number) => {
    setDraggedId(id);
  };

  const handleDragOver = (e: React.DragEvent, d: number, p: number) => {
    if (mode !== 'class' || p < 0 || !draggedId) return;
    e.preventDefault();
    setOverSlot({ day: d, period: p });
  };

  const handleDragLeave = () => {
    setOverSlot(null);
  };

  const handleDrop = async (e: React.DragEvent, d: number, p: number) => {
    e.preventDefault();
    setOverSlot(null);
    if (!draggedId || p < 0) return;

    const idToMove = draggedId;
    setDraggedId(null);
    try {
      await api(`/api/entries/${idToMove}/move`, {
        method: 'POST',
        body: { day: d, period: p },
      });
      toast('Session moved.', true);
      // Reload timetable
      const url = `/api/timetable/${selectedId}`;
      const updated = await api<TimetableEntry[]>(url);
      setEntries(updated);
    } catch (err: any) {
      toast(err.message);
    }
  };

  const renderCell = (d: number, r: { s: string; e: string; p: number }) => {
    const e = entries.find((x) => x.day === d && x.start === r.s && x.end === r.e);
    if (!e) {
      const isKeptFree = (config.free || []).some(([day, per]) => day === d && per === r.p);
      return <div className="fr">{isKeptFree ? 'Kept free' : 'Free'}</div>;
    }
    const isMdc = e.course_type === 'MDC';
    const isMinor = e.course_type === 'Minor';
    const cardClass = isMdc ? 'c-mdc' : isMinor ? 'c-minor' : '';

    return (
      <div
        className={`c ${cardClass}`}
        draggable={mode === 'class'}
        onDragStart={() => handleDragStart(e.id)}
        tabIndex={0}
      >
        <div className="row sp">
          <b>{e.subject}</b>
          {isMdc ? (
            <span className="tag mdc sm">MDC</span>
          ) : isMinor ? (
            <span className="tag minor sm">Minor</span>
          ) : null}
        </div>
        <span>{mode === 'class' ? e.teacher : e.class_name}</span>
      </div>
    );
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Schedule Review</div>
          <h1>Department Timetable</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            {mode === 'class'
              ? 'Drag a session to another period to move it. Cross-college teacher availability is checked instantly.'
              : 'Shared college faculty timetable view.'}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={() => window.print()}>
            Print
          </button>
          <button className="btn p" onClick={() => onNavigate('gen')}>
            Generate
          </button>
        </div>
      </div>

      <div className="row noprint" style={{ marginBottom: '14px', gap: '12px' }}>
        <div className="seg" role="group" aria-label="View mode">
          <button
            onClick={() => setMode('class')}
            aria-pressed={mode === 'class'}
          >
            View by Class
          </button>
          <button
            onClick={() => setMode('teacher')}
            aria-pressed={mode === 'teacher'}
          >
            View by Teacher
          </button>
        </div>

        <select
          value={selectedId || ''}
          onChange={(e) => setSelectedId(Number(e.target.value))}
          style={{ minWidth: '240px' }}
        >
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.label}
            </option>
          ))}
        </select>
      </div>

      <div className="gw">
        <table className="g" style={{ minWidth: '680px' }}>
          <thead>
            <tr>
              <th></th>
              {days.map((d) => (
                <th key={d}>{DAYS[d]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {allRows.map((r, idx) => {
              const prev = allRows[idx - 1];
              const hasBreak = prev && tmn(r.s) - tmn(prev.e) >= 5;
              return (
                <React.Fragment key={idx}>
                  {hasBreak && (
                    <tr>
                      <td className="t"></td>
                      <td className="br" colSpan={days.length}>
                        BREAK · {tmn(r.s) - tmn(prev.e)} MIN
                      </td>
                    </tr>
                  )}
                  <tr>
                    <td className="t">
                      {r.s}
                      <br />
                      {r.e}
                    </td>
                    {days.map((d) => {
                      const isOver = overSlot?.day === d && overSlot?.period === r.p;
                      return (
                        <td
                          key={d}
                          className={isOver ? 'over' : ''}
                          onDragOver={(e) => handleDragOver(e, d, r.p)}
                          onDragLeave={handleDragLeave}
                          onDrop={(e) => handleDrop(e, d, r.p)}
                        >
                          {renderCell(d, r)}
                        </td>
                      );
                    })}
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
