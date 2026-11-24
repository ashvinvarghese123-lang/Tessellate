import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../components/Toast';
import { Modal } from '../../components/Modal';
import { EngineOverlay } from '../../components/EngineOverlay';
import { api } from '../../lib/api';
import {
  SubjectAllocation,
  Faculty,
  ClassItem,
  SettingsResponse,
  ConflictResponse,
  GenerationResult,
} from '../../types';

import { OverviewView } from './OverviewView';
import { SubjectsView } from './SubjectsView';
import { TeacherAssignmentsView } from './TeacherAssignmentsView';
import { TeacherAvailabilityView } from './TeacherAvailabilityView';
import { SchedulingRulesView } from './SchedulingRulesView';
import { MdcTemplateView } from './MdcTemplateView';
import { GenerateTimetableView } from './GenerateTimetableView';
import { TimetableReviewView } from './TimetableReviewView';
import { ConflictCenterView } from './ConflictCenterView';

const NAV: Array<[string, string]> = [
  ['dash', 'Overview'],
  ['su', 'Subjects'],
  ['ta', 'Teacher Assignments'],
  ['tav', 'Teacher Availability'],
  ['ru', 'Scheduling Rules'],
  ['mdc', 'MDC & Minor Template'],
  ['gen', 'Generate Timetable'],
  ['tt', 'Timetable'],
  ['co', 'Conflict Center'],
];

export const DepartmentWorkspace: React.FC = () => {
  const { user, loading: authLoading, logout } = useAuth();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState('dash');
  const [selectedFacultyId, setSelectedFacultyId] = useState<number | null>(null);

  // Department data states
  const [dashboard, setDashboard] = useState<{ sessions?: number }>({});
  const [allocations, setAllocations] = useState<SubjectAllocation[]>([]);
  const [faculty, setFaculty] = useState<Faculty[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [conflicts, setConflicts] = useState<ConflictResponse>({ items: [] });
  const [generationResult, setGenerationResult] = useState<GenerationResult | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  // Engine overlay state
  const [isSolving, setIsSolving] = useState(false);
  const [finalSolveMsg, setFinalSolveMsg] = useState<string | undefined>(undefined);

  // Password modal state
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  const [curPassword, setCurPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);

  const loadAllData = useCallback(async () => {
    try {
      const [d, a, f, c, s, conf] = await Promise.all([
        api<{ sessions?: number }>('/api/dashboard').catch(() => ({})),
        api<SubjectAllocation[]>('/api/allocations').catch(() => []),
        api<Faculty[]>('/api/faculty').catch(() => []),
        api<ClassItem[]>('/api/classes').catch(() => []),
        api<SettingsResponse>('/api/settings').catch(() => null),
        api<ConflictResponse>('/api/conflicts').catch(() => ({ items: [] })),
      ]);
      setDashboard(d);
      setAllocations(a);
      setFaculty(f);
      setClasses(c);
      setSettings(s);
      setConflicts(conf);
    } catch (err: any) {
      toast(err.message);
    } finally {
      setDataLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    document.title = 'Tessellate · Department Workspace';
    if (user) {
      loadAllData();
    } else if (!authLoading) {
      window.location.replace('/login.html');
    }
  }, [user, authLoading, loadAllData]);

  if (authLoading || (dataLoading && !user)) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <p className="sub">Loading department workspace…</p>
      </div>
    );
  }

  if (!user) {
    return null; // Will redirect via auth context / api handler
  }

  const handleGenerate = async () => {
    setIsSolving(true);
    setFinalSolveMsg(undefined);

    const solverSteps = [
      'Checking faculty availability…',
      'Checking shared college allocations…',
      'Synchronizing MDC & Minor slots…',
      'Solving timetable constraints…',
      'Finalizing schedule…',
    ];

    try {
      const res = await api<GenerationResult>('/api/generate', {
        method: 'POST',
        body: {},
      });
      setTimeout(() => {
        setFinalSolveMsg(
          res.status === 'ok' ? '✓ Timetable ready · no clashes' : 'We couldn’t fit every session'
        );
        setTimeout(() => {
          setIsSolving(false);
          setGenerationResult(res);
          loadAllData();
          if (res.status === 'ok') {
            setActiveTab('tt');
          } else {
            setActiveTab('co');
          }
        }, 1000);
      }, 1800);
    } catch (err: any) {
      setIsSolving(false);
      toast(err.message);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!curPassword || !newPassword) return;
    if (newPassword.length < 6) {
      toast('New password must be at least 6 characters.');
      return;
    }
    setChangingPassword(true);
    try {
      await api('/api/auth/change-password', {
        method: 'POST',
        body: { current: curPassword, new: newPassword },
      });
      toast('Password updated.', true);
      setIsPasswordModalOpen(false);
      setCurPassword('');
      setNewPassword('');
    } catch (err: any) {
      toast(err.message);
    } finally {
      setChangingPassword(false);
    }
  };

  const cat = user.department?.category;
  const catBadge = cat ? (
    <span
      className={`tag ${cat === 'Aided' ? 'ok' : 'w'}`}
      title="Institutional category · Equal scheduling priority"
    >
      {cat}
    </span>
  ) : null;

  return (
    <div className="app">
      <nav aria-label="Department navigation">
        <div className="logo">Tessellate</div>
        <div
          className="sm"
          style={{
            margin: '0 10px 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--ink)' }}>{user.department.name}</span>
          {catBadge}
        </div>

        {NAV.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setActiveTab(k)}
            aria-current={activeTab === k ? 'page' : undefined}
          >
            {label}
          </button>
        ))}

        <div
          style={{
            marginTop: 'auto',
            paddingTop: '18px',
            borderTop: '1px solid var(--line)',
            fontSize: '12px',
            color: 'var(--mute)',
          }}
        >
          <div style={{ marginBottom: '6px' }}>
            Signed in as <b>{user.username}</b>
          </div>
          <div className="row" style={{ gap: '8px' }}>
            <button className="btn sm" onClick={() => setIsPasswordModalOpen(true)}>
              Password
            </button>
            <button className="btn sm" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </nav>

      <main>
        {activeTab === 'dash' && (
          <OverviewView
            user={user}
            dashboard={dashboard}
            allocations={allocations}
            faculty={faculty}
            conflicts={conflicts}
            onNavigate={(v) => setActiveTab(v)}
          />
        )}
        {activeTab === 'su' && (
          <SubjectsView
            allocations={allocations}
            classes={classes}
            faculty={faculty}
            onRefresh={loadAllData}
          />
        )}
        {activeTab === 'ta' && (
          <TeacherAssignmentsView
            user={user}
            faculty={faculty}
            allocations={allocations}
            onViewAvailability={(fid) => {
              setSelectedFacultyId(fid);
              setActiveTab('tav');
            }}
          />
        )}
        {activeTab === 'tav' && (
          <TeacherAvailabilityView
            faculty={faculty}
            selectedFacultyId={selectedFacultyId}
            onSelectFaculty={(fid) => setSelectedFacultyId(fid)}
          />
        )}
        {activeTab === 'ru' && <SchedulingRulesView />}
        {activeTab === 'mdc' && <MdcTemplateView allocations={allocations} />}
        {activeTab === 'gen' && (
          <GenerateTimetableView
            allocations={allocations}
            faculty={faculty}
            settings={settings}
            conflicts={conflicts}
            generationResult={generationResult}
            onGenerate={handleGenerate}
            onNavigate={(v) => setActiveTab(v)}
          />
        )}
        {activeTab === 'tt' && (
          <TimetableReviewView
            classes={classes}
            faculty={faculty}
            config={settings ? settings.config : null}
            onNavigate={(v) => setActiveTab(v)}
          />
        )}
        {activeTab === 'co' && (
          <ConflictCenterView
            conflicts={conflicts}
            generationResult={generationResult}
            onRefreshData={loadAllData}
            onNavigate={(v) => setActiveTab(v)}
          />
        )}
      </main>

      <EngineOverlay
        isOpen={isSolving}
        departmentName={user.department.name}
        steps={[
          'Checking faculty availability…',
          'Checking shared college allocations…',
          'Synchronizing MDC & Minor slots…',
          'Solving timetable constraints…',
          'Finalizing schedule…',
        ]}
        finalMessage={finalSolveMsg}
      />

      <Modal isOpen={isPasswordModalOpen} onClose={() => setIsPasswordModalOpen(false)}>
        <h2>Change Password</h2>
        <p className="sub">Update your department workspace password.</p>
        <form onSubmit={handleChangePassword}>
          <div className="form-group">
            <label>Current Password *</label>
            <input
              type="password"
              value={curPassword}
              onChange={(e) => setCurPassword(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div className="form-group">
            <label>New Password (min 6 characters) *</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </div>
          <div className="row sp" style={{ marginTop: '20px' }}>
            <button
              type="button"
              className="btn"
              onClick={() => setIsPasswordModalOpen(false)}
            >
              Cancel
            </button>
            <button type="submit" className="btn p" disabled={changingPassword}>
              Update Password
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
