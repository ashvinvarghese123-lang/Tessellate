import React from 'react';
import { UserMe, SubjectAllocation, Faculty, ConflictResponse } from '../../types';

interface OverviewViewProps {
  user: UserMe;
  dashboard: { sessions?: number };
  allocations: SubjectAllocation[];
  faculty: Faculty[];
  conflicts: ConflictResponse;
  onNavigate: (view: string) => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  user,
  dashboard,
  allocations,
  faculty,
  conflicts,
  onNavigate,
}) => {
  const assignedTeachers = new Set(allocations.map((a) => a.faculty_id)).size;
  const issuesCount = conflicts.items ? conflicts.items.length : 0;
  const cat = user.department?.category || 'Aided';

  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Department Workspace</div>
          <h1>{user.department.name} Department</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            Institutional Category: {cat} · Guaranteed Equal Scheduling Priority
          </p>
        </div>
        <button className="btn p noprint" onClick={() => onNavigate('gen')}>
          Generate Timetable
        </button>
      </div>

      <div className="stats">
        <div>
          <b>{allocations.length}</b>
          <span className="sm">Subjects Offered</span>
        </div>
        <div>
          <b>{assignedTeachers}</b>
          <span className="sm">Assigned Teachers</span>
        </div>
        <div>
          <b>{dashboard.sessions || 0}</b>
          <span className="sm">Scheduled Sessions</span>
        </div>
        <div>
          <b style={{ color: issuesCount > 0 ? 'var(--crit)' : 'var(--acc)' }}>
            {issuesCount === 0 ? '0 Clashes' : `${issuesCount} Issues`}
          </b>
          <span className="sm">Conflict Status</span>
        </div>
      </div>

      <div className="cols">
        <div>
          <h2>Quick Actions</h2>
          <div className="card">
            <p className="sm" style={{ marginTop: 0 }}>
              Essential steps for generating a conflict-free department timetable:
            </p>
            <div className="item row sp">
              <div>
                <b>1. Subject Management</b>
                <div className="sm">Add regular, MDC and Minor subjects offered this semester.</div>
              </div>
              <button className="btn sm" onClick={() => onNavigate('su')}>
                Manage Subjects
              </button>
            </div>
            <div className="item row sp">
              <div>
                <b>2. Teacher Assignments</b>
                <div className="sm">Assign teachers and review cross-department workloads.</div>
              </div>
              <button className="btn sm" onClick={() => onNavigate('ta')}>
                View Teachers
              </button>
            </div>
            <div className="item row sp">
              <div>
                <b>3. MDC &amp; Minor Template</b>
                <div className="sm">Fix agreed MDC and Minor periods directly on your schedule.</div>
              </div>
              <button className="btn sm" onClick={() => onNavigate('mdc')}>
                Common Template
              </button>
            </div>
            <div className="item row sp">
              <div>
                <b>4. Generate Timetable</b>
                <div className="sm">Solve teacher constraints and produce a valid schedule.</div>
              </div>
              <button className="btn sm p" onClick={() => onNavigate('gen')}>
                Generate
              </button>
            </div>
          </div>
        </div>

        <div>
          <h2>Coordination &amp; Synchronization Status</h2>
          <div className="card">
            <div className="item">
              <div className="row sp">
                <b>Teacher Availability</b>
                <span className="tag ok sm">Synchronized</span>
              </div>
              <p className="sm" style={{ margin: '4px 0 0' }}>
                All {faculty.length} college faculty records are checked college-wide. Teachers can never be
                assigned simultaneously across departments.
              </p>
            </div>
            <div className="item">
              <div className="row sp">
                <b>MDC &amp; Minor Slots</b>
                <span className="tag mdc sm">Department Configured</span>
              </div>
              <p className="sm" style={{ margin: '4px 0 0' }}>
                Departments discuss common periods among themselves and fix them directly on their schedule,
                just like fixing free periods.
              </p>
            </div>
            <div className="item">
              <div className="row sp">
                <b>Cross-Department Isolation</b>
                <span className="tag ok sm">Enforced</span>
              </div>
              <p className="sm" style={{ margin: '4px 0 0' }}>
                Generating or updating your timetable will never silently overwrite or modify another
                department's existing schedule.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
