import React from 'react';
import { Faculty, SubjectAllocation, UserMe } from '../../types';

interface TeacherAssignmentsViewProps {
  user: UserMe;
  faculty: Faculty[];
  allocations: SubjectAllocation[];
  onViewAvailability: (facultyId: number) => void;
}

export const TeacherAssignmentsView: React.FC<TeacherAssignmentsViewProps> = ({
  user,
  faculty,
  allocations,
  onViewAvailability,
}) => {
  return (
    <div>
      <div className="row sp" style={{ alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <div className="lab">Faculty Management</div>
          <h1>Teacher Assignments &amp; Workload</h1>
          <p className="sub" style={{ marginBottom: 0 }}>
            College-wide teacher registry. Teachers are shared across departments and never double-booked.
          </p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '20px' }}>
        <div className="row sp">
          <div>
            <b>Centralized Teacher Coordination Rule</b>
            <div className="sm">
              Each teacher has one global identity across the college. When another department assigns a
              teacher, that period becomes occupied college-wide.
            </div>
          </div>
          <span className="tag ok">Cross-College Sync Active</span>
        </div>
      </div>

      <div className="gw">
        <table className="l">
          <thead>
            <tr>
              <th>Teacher Name</th>
              <th>Home Department</th>
              <th>Designation</th>
              <th>Assigned in {user.department.name}</th>
              <th>Other Dept Commitments</th>
              <th>Total College Load</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {faculty.map((f) => {
              const mySubs = allocations.filter((a) => a.faculty_id === f.id);
              const otherDepts = (f.allocations_by_dept || []).filter(
                (x) => x.department !== user.department.name
              );
              const pct = Math.min(100, Math.round((f.sessions / f.max_weekly_sessions) * 100));
              const barClass = pct >= 100 ? 'ov' : pct >= 80 ? 'hi' : '';

              return (
                <tr key={f.id}>
                  <td>
                    <b>{f.name}</b> <span className="sm">({f.faculty_code})</span>
                  </td>
                  <td>{f.department}</td>
                  <td>{f.designation || 'Faculty'}</td>
                  <td>
                    {mySubs.length ? (
                      mySubs.map((a) => `${a.subject} (${a.sessions_per_week}s)`).join(', ')
                    ) : (
                      <span className="sm">None</span>
                    )}
                  </td>
                  <td>
                    {otherDepts.length ? (
                      otherDepts.map((x) => `${x.department}: ${x.sessions}s`).join(' · ')
                    ) : (
                      <span className="sm">No other depts</span>
                    )}
                  </td>
                  <td>
                    <div>
                      <b>{f.sessions}</b> / {f.max_weekly_sessions} sessions
                      <div className={`bar ${barClass}`}>
                        <i style={{ width: `${pct}%` }}></i>
                      </div>
                    </div>
                  </td>
                  <td>
                    <div className="row">
                      <button className="btn sm" onClick={() => onViewAvailability(f.id)}>
                        View Availability
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
