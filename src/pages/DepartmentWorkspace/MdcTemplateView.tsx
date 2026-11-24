import React, { useState, useEffect } from 'react';
import { SubjectAllocation, SlotsOverview, DepartmentConfig } from '../../types';
import { api, DAYS } from '../../lib/api';
import { useToast } from '../../components/Toast';

interface MdcTemplateViewProps {
  allocations: SubjectAllocation[];
}

export const MdcTemplateView: React.FC<MdcTemplateViewProps> = ({ allocations }) => {
  const { toast } = useToast();
  const [overview, setOverview] = useState<SlotsOverview | null>(null);
  const [config, setConfig] = useState<DepartmentConfig | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<SlotsOverview>('/api/department/slots-overview')
      .then((res) => {
        setOverview(res);
        setConfig(res.config);
      })
      .catch((err) => toast(err.message));
  }, [toast]);

  if (!config || !overview) {
    return <p className="sub">Loading MDC &amp; Minor template…</p>;
  }

  const mdcSubjects = allocations.filter((a) => a.course_category === 'MDC');
  const minorSubjects = allocations.filter((a) => a.course_category === 'Minor');
  const totalMdcReq = mdcSubjects.reduce((s, a) => s + a.sessions_per_week, 0);
  const totalMinorReq = minorSubjects.reduce((s, a) => s + a.sessions_per_week, 0);

  const cycleSlot = (d: number, p: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const inMdc = prev.mdc_slots.some(([day, per]) => day === d && per === p);
      const inMinor = prev.minor_slots.some(([day, per]) => day === d && per === p);

      let newMdc = [...prev.mdc_slots];
      let newMinor = [...prev.minor_slots];
      let newFree = prev.free.filter(([day, per]) => !(day === d && per === p));

      if (!inMdc && !inMinor) {
        // Regular -> MDC
        newMdc.push([d, p]);
      } else if (inMdc) {
        // MDC -> Minor
        newMdc = newMdc.filter(([day, per]) => !(day === d && per === p));
        newMinor.push([d, p]);
      } else {
        // Minor -> Regular
        newMinor = newMinor.filter(([day, per]) => !(day === d && per === p));
      }

      return {
        ...prev,
        free: newFree,
        mdc_slots: newMdc,
        minor_slots: newMinor,
      };
    });
  };

  const handleResetAll = () => {
    setConfig((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        mdc_slots: [],
        minor_slots: [],
      };
    });
    toast('All slots reset to regular periods. Click Save to persist.', true);
  };

  const handleSaveSlots = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api('/api/settings', {
        method: 'PUT',
        body: {
          days: config.days,
          periods: config.periods,
          rules: config.rules,
          free: config.free || [],
          mdc_slots: config.mdc_slots || [],
          minor_slots: config.minor_slots || [],
        },
      });
      toast('MDC & Minor slot template saved.', true);
    } catch (err: any) {
      toast(err.message);
    } finally {
      setSaving(false);
    }
  };

  const renderCell = (d: number, i: number) => {
    const isMdc = config.mdc_slots.some(([day, per]) => day === d && per === i);
    const isMinor = config.minor_slots.some(([day, per]) => day === d && per === i);
    const isFree = config.free.some(([day, per]) => day === d && per === i);

    if (isMdc) {
      return (
        <button
          type="button"
          className="tg"
          style={{
            background: 'rgba(31,122,99,.15)',
            color: 'var(--mdc)',
            border: '1px solid var(--mdc)',
            fontWeight: 600,
          }}
          onClick={() => cycleSlot(d, i)}
          title="Click to change: MDC -> Minor -> Regular"
        >
          <span className="tag mdc sm" style={{ pointerEvents: 'none' }}>
            MDC Slot
          </span>
        </button>
      );
    }
    if (isMinor) {
      return (
        <button
          type="button"
          className="tg"
          style={{
            background: 'rgba(42,93,168,.15)',
            color: 'var(--minor)',
            border: '1px solid var(--minor)',
            fontWeight: 600,
          }}
          onClick={() => cycleSlot(d, i)}
          title="Click to change: Minor -> Regular -> MDC"
        >
          <span className="tag minor sm" style={{ pointerEvents: 'none' }}>
            Minor Slot
          </span>
        </button>
      );
    }
    if (isFree) {
      return (
        <button
          type="button"
          className="tg on"
          style={{ opacity: 0.6 }}
          onClick={() => cycleSlot(d, i)}
          title="Click to change"
        >
          <span className="sm" style={{ pointerEvents: 'none' }}>
            Kept free
          </span>
        </button>
      );
    }
    return (
      <button
        type="button"
        className="tg"
        onClick={() => cycleSlot(d, i)}
        title="Click to designate: Regular -> MDC -> Minor"
      >
        <span className="sm" style={{ pointerEvents: 'none' }}>
          Regular
        </span>
      </button>
    );
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Department Coordination</div>
          <h1>MDC &amp; Minor Slot Template</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Departments discuss and fix MDC and Minor periods collaboratively. Configure your department's
            designated periods below.
          </p>
        </div>
        <button className="btn p noprint" onClick={handleSaveSlots} disabled={saving}>
          Save MDC &amp; Minor Slots
        </button>
      </div>

      <div className="card">
        <div className="row sp">
          <div>
            <b>Collaborative Department Slot Agreement</b>
            <p className="sm" style={{ margin: '4px 0 0' }}>
              Common MDC and Minor slots are discussed and agreed upon directly between departments (no
              Registry operator setup needed).
              <br />
              Click any slot on your department grid below to cycle between:{' '}
              <b>Regular Period → MDC Slot → Minor Slot → Regular</b>.
            </p>
          </div>
          <span className="tag ok">Department Fixed</span>
        </div>
      </div>

      <div className="card">
        <div className="row sp" style={{ marginBottom: '12px' }}>
          <div>
            <h2 style={{ margin: '0 0 4px' }}>Weekly Slot Designation Grid</h2>
            <div className="sm">
              Click a period cell to cycle its assignment. Designated MDC and Minor slots will be reserved for
              those subjects.
            </div>
          </div>
          <div className="row noprint" style={{ gap: '8px' }}>
            <button className="btn sm" onClick={handleResetAll}>
              Reset All to Regular
            </button>
            <button className="btn sm p" onClick={handleSaveSlots} disabled={saving}>
              Save Slots
            </button>
          </div>
        </div>

        <div className="gw">
          <table className="g" style={{ minWidth: '600px' }}>
            <thead>
              <tr>
                <th></th>
                {config.days.map((d) => (
                  <th key={d}>{DAYS[d].slice(0, 3)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {config.periods.map((p, i) => (
                <tr key={i}>
                  <td className="t">
                    {p.start}
                    <br />
                    {p.end}
                  </td>
                  {config.days.map((d) => (
                    <td key={d} style={{ height: '54px' }}>
                      {renderCell(d, i)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="cols">
        <div>
          <h2>Department Offering Status</h2>
          <div className="card">
            <div className="item row sp">
              <div>
                <b>MDC Course Slots</b>
                <div className="sm">
                  {config.mdc_slots.length} period(s) designated · {totalMdcReq} weekly session(s) needed
                </div>
              </div>
              <span className={`tag ${config.mdc_slots.length >= totalMdcReq ? 'ok' : 'w'}`}>
                {config.mdc_slots.length >= totalMdcReq
                  ? '✓ Configured'
                  : `${config.mdc_slots.length} / ${totalMdcReq}`}
              </span>
            </div>
            <div className="item row sp">
              <div>
                <b>Minor Course Slots</b>
                <div className="sm">
                  {config.minor_slots.length} period(s) designated · {totalMinorReq} weekly session(s) needed
                </div>
              </div>
              <span className={`tag ${config.minor_slots.length >= totalMinorReq ? 'ok' : 'w'}`}>
                {config.minor_slots.length >= totalMinorReq
                  ? '✓ Configured'
                  : `${config.minor_slots.length} / ${totalMinorReq}`}
              </span>
            </div>

            <h2 style={{ fontSize: '15px', margin: '16px 0 8px' }}>Department Subjects in Template</h2>
            {mdcSubjects.length || minorSubjects.length ? (
              <div className="gw">
                <table className="l">
                  <thead>
                    <tr>
                      <th>Subject</th>
                      <th>Category</th>
                      <th>Teacher</th>
                      <th>Sessions/Wk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...mdcSubjects, ...minorSubjects].map((a) => (
                      <tr key={a.id}>
                        <td>{a.subject}</td>
                        <td>
                          <span className={`tag ${a.course_category === 'MDC' ? 'mdc' : 'minor'}`}>
                            {a.course_category}
                          </span>
                        </td>
                        <td>
                          {a.teacher} <span className="sm">({a.faculty_code})</span>
                        </td>
                        <td>{a.sessions_per_week} sess/wk</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="sm">No MDC or Minor subjects added yet. Add them in Subjects.</p>
            )}
          </div>
        </div>

        <div>
          <h2>Other Departments' Configured Slots</h2>
          <div className="card">
            <p className="sm" style={{ marginTop: 0 }}>
              See the MDC &amp; Minor periods configured by other departments to verify college-wide
              discussion and alignment:
            </p>
            {overview.other_departments.length ? (
              overview.other_departments.map((dp) => (
                <div key={dp.id} className="item">
                  <div className="row sp">
                    <b>{dp.name}</b> <span className="sm">{dp.code}</span>
                  </div>
                  <div className="sm" style={{ marginTop: '4px' }}>
                    {dp.mdc_slots.length > 0 && (
                      <div>
                        <span className="tag mdc sm">MDC</span>{' '}
                        {dp.mdc_slots
                          .map((s) => `${s.day_name} P${s.period + 1} (${s.start}–${s.end})`)
                          .join(', ')}
                      </div>
                    )}
                    {dp.minor_slots.length > 0 && (
                      <div style={{ marginTop: '2px' }}>
                        <span className="tag minor sm">Minor</span>{' '}
                        {dp.minor_slots
                          .map((s) => `${s.day_name} P${s.period + 1} (${s.start}–${s.end})`)
                          .join(', ')}
                      </div>
                    )}
                    {!dp.mdc_slots.length && !dp.minor_slots.length && (
                      <span>No MDC/Minor slots set yet</span>
                    )}
                  </div>
                </div>
              ))
            ) : (
              <p className="sm">Other departments have not saved their MDC/Minor slots yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
