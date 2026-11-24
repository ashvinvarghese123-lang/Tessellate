import React, { useState, useEffect } from 'react';
import { DepartmentConfig, RuleDef, SettingsResponse } from '../../types';
import { api, DAYS, STD, tmn } from '../../lib/api';
import { useToast } from '../../components/Toast';

export const SchedulingRulesView: React.FC = () => {
  const { toast } = useToast();
  const [config, setConfig] = useState<DepartmentConfig | null>(null);
  const [ruleDefs, setRuleDefs] = useState<Record<string, RuleDef>>({});
  const [stale, setStale] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<SettingsResponse>('/api/settings')
      .then((res) => {
        setConfig(res.config);
        setRuleDefs(res.rule_defs);
        setStale(!!res.stale);
      })
      .catch((err) => toast(err.message));
  }, [toast]);

  if (!config) {
    return <p className="sub">Loading scheduling rules…</p>;
  }

  const handleDayToggle = (day: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const currentDays = prev.days;
      let newDays: number[];
      if (currentDays.includes(day)) {
        if (currentDays.length < 2) {
          toast('Keep at least one working day.');
          return prev;
        }
        newDays = currentDays.filter((d) => d !== day);
      } else {
        newDays = [...new Set([...currentDays, day])].sort();
      }
      return {
        ...prev,
        days: newDays,
        free: prev.free.filter(([d]) => newDays.includes(d)),
        mdc_slots: prev.mdc_slots.filter(([d]) => newDays.includes(d)),
        minor_slots: prev.minor_slots.filter(([d]) => newDays.includes(d)),
      };
    });
  };

  const handlePeriodChange = (index: number, field: 'start' | 'end', value: string) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const newPeriods = [...prev.periods];
      newPeriods[index] = { ...newPeriods[index], [field]: value };
      return { ...prev, periods: newPeriods };
    });
  };

  const handleRemovePeriod = (index: number) => {
    setConfig((prev) => {
      if (!prev || prev.periods.length < 2) return prev;
      const newPeriods = prev.periods.filter((_, i) => i !== index);
      return {
        ...prev,
        periods: newPeriods,
        free: prev.free.filter(([_, p]) => p < newPeriods.length),
        mdc_slots: prev.mdc_slots.filter(([_, p]) => p < newPeriods.length),
        minor_slots: prev.minor_slots.filter(([_, p]) => p < newPeriods.length),
      };
    });
  };

  const handleAddPeriod = () => {
    setConfig((prev) => {
      if (!prev) return prev;
      if (prev.periods.length >= 12) {
        toast('No room for another period today.');
        return prev;
      }
      const last = prev.periods[prev.periods.length - 1];
      const startMinutes = last ? tmn(last.end) + 15 : 540;
      const endMinutes = startMinutes + 60;
      if (endMinutes > 1439) {
        toast('No room for another period today.');
        return prev;
      }
      const fmt = (n: number) =>
        `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;
      return {
        ...prev,
        periods: [...prev.periods, { start: fmt(startMinutes), end: fmt(endMinutes) }],
      };
    });
  };

  const handleUsePreset = () => {
    setConfig((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        periods: STD.map(([start, end]) => ({ start, end })),
        free: prev.free.filter(([_, p]) => p < 6),
        mdc_slots: prev.mdc_slots.filter(([_, p]) => p < 6),
        minor_slots: prev.minor_slots.filter(([_, p]) => p < 6),
      };
    });
  };

  const handleRuleModeChange = (ruleKey: string, mode: 'off' | 'prefer' | 'require') => {
    setConfig((prev) => {
      if (!prev) return prev;
      const currentRule = prev.rules[ruleKey] || { mode: 'off' };
      return {
        ...prev,
        rules: {
          ...prev.rules,
          [ruleKey]: { ...currentRule, mode },
        },
      };
    });
  };

  const handleRuleParamChange = (ruleKey: string, paramKey: string, value: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const currentRule = prev.rules[ruleKey] || { mode: 'prefer' };
      return {
        ...prev,
        rules: {
          ...prev.rules,
          [ruleKey]: { ...currentRule, [paramKey]: value },
        },
      };
    });
  };

  const toggleFreePeriod = (d: number, p: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const exists = prev.free.some(([day, per]) => day === d && per === p);
      let newFree: Array<[number, number]>;
      if (exists) {
        newFree = prev.free.filter(([day, per]) => !(day === d && per === p));
      } else {
        newFree = [...prev.free, [d, p]];
      }
      return {
        ...prev,
        free: newFree,
        mdc_slots: prev.mdc_slots.filter(([day, per]) => !(day === d && per === p)),
        minor_slots: prev.minor_slots.filter(([day, per]) => !(day === d && per === p)),
      };
    });
  };

  const toggleMdcPeriod = (d: number, p: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const exists = prev.mdc_slots.some(([day, per]) => day === d && per === p);
      let newMdc: Array<[number, number]>;
      if (exists) {
        newMdc = prev.mdc_slots.filter(([day, per]) => !(day === d && per === p));
      } else {
        newMdc = [...prev.mdc_slots, [d, p]];
      }
      return {
        ...prev,
        mdc_slots: newMdc,
        free: prev.free.filter(([day, per]) => !(day === d && per === p)),
        minor_slots: prev.minor_slots.filter(([day, per]) => !(day === d && per === p)),
      };
    });
  };

  const toggleMinorPeriod = (d: number, p: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      const exists = prev.minor_slots.some(([day, per]) => day === d && per === p);
      let newMinor: Array<[number, number]>;
      if (exists) {
        newMinor = prev.minor_slots.filter(([day, per]) => !(day === d && per === p));
      } else {
        newMinor = [...prev.minor_slots, [d, p]];
      }
      return {
        ...prev,
        minor_slots: newMinor,
        free: prev.free.filter(([day, per]) => !(day === d && per === p)),
        mdc_slots: prev.mdc_slots.filter(([day, per]) => !(day === d && per === p)),
      };
    });
  };

  const handleSaveRules = async () => {
    if (!config) return;
    setSaving(true);
    try {
      const formattedRules: Record<string, any> = {};
      for (const [k, df] of Object.entries(ruleDefs)) {
        const r = config.rules[k] || { mode: 'off' };
        formattedRules[k] = { mode: r.mode };
        if (df.param) {
          formattedRules[k][df.param.key] = Number(r[df.param.key] ?? df.param.default);
        }
      }

      const res = await api<SettingsResponse>('/api/settings', {
        method: 'PUT',
        body: {
          days: config.days,
          periods: config.periods,
          rules: formattedRules,
          free: config.free || [],
          mdc_slots: config.mdc_slots || [],
          minor_slots: config.minor_slots || [],
        },
      });
      setConfig(res.config);
      setStale(!!res.stale);
      toast('Rules saved. Generate timetable to apply them.', true);
    } catch (err: any) {
      toast(err.message);
    } finally {
      setSaving(false);
    }
  };

  const MODE_LABELS: Record<string, string> = {
    off: 'Off',
    prefer: 'Prefer when possible',
    require: 'Always required',
  };

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Department Policy</div>
          <h1>Scheduling Rules</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Configure working days, period hours, breaks, optimization rules, and reserved periods.
          </p>
        </div>
        <button className="btn p noprint" onClick={handleSaveRules} disabled={saving}>
          Save Rules
        </button>
      </div>

      {stale && (
        <div className="card" style={{ borderColor: 'var(--warn)' }}>
          <b>Your timing settings changed.</b> Save and generate again to apply them to your schedule.
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Working Days</h2>
        <div className="row">
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <label key={d} className="chk">
              <input
                type="checkbox"
                checked={config.days.includes(d)}
                onChange={() => handleDayToggle(d)}
              />{' '}
              {DAYS[d].slice(0, 3)}
            </label>
          ))}
        </div>

        <h2>Period Timings &amp; Breaks</h2>
        <div className="gw">
          <table className="l">
            <thead>
              <tr>
                <th>#</th>
                <th>Start Time</th>
                <th>End Time</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {config.periods.map((p, i) => {
                const prev = config.periods[i - 1];
                const hasBreak = prev && tmn(p.start) > tmn(prev.end);
                return (
                  <React.Fragment key={i}>
                    {hasBreak && (
                      <tr className="gapnote">
                        <td></td>
                        <td colSpan={3} className="sm">
                          Break · {tmn(p.start) - tmn(prev.end)} min
                        </td>
                      </tr>
                    )}
                    <tr>
                      <td>{i + 1}</td>
                      <td>
                        <input
                          type="time"
                          value={p.start}
                          onChange={(e) => handlePeriodChange(i, 'start', e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="time"
                          value={p.end}
                          onChange={(e) => handlePeriodChange(i, 'end', e.target.value)}
                        />
                      </td>
                      <td>
                        <button
                          className="btn sm"
                          onClick={() => handleRemovePeriod(i)}
                          disabled={config.periods.length < 2}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="row noprint" style={{ marginTop: '10px' }}>
          <button className="btn sm" onClick={handleAddPeriod}>
            Add Period
          </button>
          <button className="btn sm" onClick={handleUsePreset}>
            Use Standard 6 Periods
          </button>
        </div>

        <h2>Department Scheduling Constraints</h2>
        {Object.entries(ruleDefs).map(([k, df]) => {
          const r = config.rules[k] || { mode: 'off' };
          return (
            <div key={k} className="item">
              <div className="row sp">
                <div style={{ maxWidth: '560px' }}>
                  <b>{df.title}</b>
                  <div className="sm">{df.help}</div>
                </div>
                <div className="row">
                  <select
                    value={r.mode}
                    onChange={(e) => handleRuleModeChange(k, e.target.value as any)}
                    aria-label={df.title}
                  >
                    {df.modes.map((m) => (
                      <option key={m} value={m}>
                        {MODE_LABELS[m]}
                      </option>
                    ))}
                  </select>
                  {df.param && (
                    <label className="sm">
                      {df.param.label}&nbsp;
                      <input
                        type="number"
                        min={df.param.min}
                        max={df.param.max}
                        value={r[df.param.key] ?? df.param.default}
                        onChange={(e) => handleRuleParamChange(k, df.param!.key, Number(e.target.value))}
                        disabled={r.mode === 'off'}
                        style={{ width: '70px' }}
                      />
                    </label>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        <h2>Reserved Free Periods</h2>
        <p className="sm">
          Mark periods that none of your department's regular subjects should occupy (e.g. departmental
          seminar or common break).
        </p>
        <div className="gw">
          <table className="g" style={{ minWidth: '440px' }}>
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
                  <td className="t">{p.start}</td>
                  {config.days.map((d) => {
                    const isFree = config.free.some(([day, per]) => day === d && per === i);
                    return (
                      <td key={d} style={{ height: '40px' }}>
                        <button
                          type="button"
                          className={`tg ${isFree ? 'on' : ''}`}
                          onClick={() => toggleFreePeriod(d, i)}
                          aria-pressed={isFree}
                        >
                          {isFree ? 'Kept free' : 'Use'}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>MDC Common Periods (Department Fixed)</h2>
        <p className="sm">
          Periods agreed in discussion with other departments for MDC courses. Regular subjects will avoid
          these periods.
        </p>
        <div className="gw">
          <table className="g" style={{ minWidth: '440px' }}>
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
                  <td className="t">{p.start}</td>
                  {config.days.map((d) => {
                    const isMdc = config.mdc_slots.some(([day, per]) => day === d && per === i);
                    return (
                      <td key={d} style={{ height: '40px' }}>
                        <button
                          type="button"
                          className={`tg ${isMdc ? 'on' : ''}`}
                          style={
                            isMdc
                              ? {
                                  background: 'rgba(31,122,99,.15)',
                                  color: 'var(--mdc)',
                                  border: '1px solid var(--mdc)',
                                  fontWeight: 600,
                                }
                              : {}
                          }
                          onClick={() => toggleMdcPeriod(d, i)}
                          aria-pressed={isMdc}
                        >
                          {isMdc ? 'MDC Slot' : 'Regular'}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h2>Minor Common Periods (Department Fixed)</h2>
        <p className="sm">
          Periods agreed in discussion with other departments for Minor courses. Regular subjects will avoid
          these periods.
        </p>
        <div className="gw">
          <table className="g" style={{ minWidth: '440px' }}>
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
                  <td className="t">{p.start}</td>
                  {config.days.map((d) => {
                    const isMinor = config.minor_slots.some(([day, per]) => day === d && per === i);
                    return (
                      <td key={d} style={{ height: '40px' }}>
                        <button
                          type="button"
                          className={`tg ${isMinor ? 'on' : ''}`}
                          style={
                            isMinor
                              ? {
                                  background: 'rgba(42,93,168,.15)',
                                  color: 'var(--minor)',
                                  border: '1px solid var(--minor)',
                                  fontWeight: 600,
                                }
                              : {}
                          }
                          onClick={() => toggleMinorPeriod(d, i)}
                          aria-pressed={isMinor}
                        >
                          {isMinor ? 'Minor Slot' : 'Regular'}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="row noprint" style={{ marginTop: '24px' }}>
          <button className="btn p" onClick={handleSaveRules} disabled={saving}>
            Save Rules
          </button>
        </div>
      </div>
    </div>
  );
};
