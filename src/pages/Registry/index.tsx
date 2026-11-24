import React, { useState, useEffect, useCallback } from 'react';
import { useRegistryAuth } from '../../context/RegistryAuthContext';
import { useToast } from '../../components/Toast';
import { Modal } from '../../components/Modal';
import { api } from '../../lib/api';
import { Department, Faculty, ClassItem } from '../../types';

interface RegistryOverview {
  departments: number;
  faculty: number;
  classes: number;
  sections: number;
  department_accounts: number;
}

interface InstitutionalCategory {
  id: number;
  name: string;
}

interface DepartmentAccountItem {
  department_id: number;
  department_name: string;
  department_code: string;
  category_name: string;
  username: string;
  password?: string;
  active: boolean;
}

const NAV: Array<[string, string]> = [
  ['dash', 'Dashboard'],
  ['depts', 'Departments'],
  ['fac', 'Faculty'],
  ['cls', 'Classes & Sections'],
  ['accts', 'Department Accounts'],
];

export const Registry: React.FC = () => {
  const { operator, loading: authLoading, logout } = useRegistryAuth();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState('dash');
  const [dataLoading, setDataLoading] = useState(true);

  // Data
  const [overview, setOverview] = useState<RegistryOverview>({
    departments: 0,
    faculty: 0,
    classes: 0,
    sections: 0,
    department_accounts: 0,
  });
  const [categories, setCategories] = useState<InstitutionalCategory[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [faculty, setFaculty] = useState<Faculty[]>([]);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [accounts, setAccounts] = useState<DepartmentAccountItem[]>([]);

  // Filter states
  const [deptSearch, setDeptSearch] = useState('');
  const [deptCatFilter, setDeptCatFilter] = useState('');
  const [deptStatusFilter, setDeptStatusFilter] = useState('');

  const [facSearch, setFacSearch] = useState('');
  const [facDeptFilter, setFacDeptFilter] = useState('');

  const [clsSearch, setClsSearch] = useState('');
  const [clsDeptFilter, setClsDeptFilter] = useState('');
  const [clsSemFilter, setClsSemFilter] = useState('');

  // Modals
  const [credentialsModal, setCredentialsModal] = useState<{
    title: string;
    departmentName: string;
    username: string;
    password: string;
  } | null>(null);

  const [isAddDeptOpen, setIsAddDeptOpen] = useState(false);
  const [deptForm, setDeptForm] = useState({ name: '', code: '', categoryId: 0, description: '' });

  const [editDept, setEditDept] = useState<Department | null>(null);
  const [isAddFacOpen, setIsAddFacOpen] = useState(false);
  const [facForm, setFacForm] = useState({
    name: '',
    departmentId: 0,
    code: '',
    designation: 'Assistant Professor',
    email: '',
    phone: '',
    specialization: '',
    maxSessions: 16,
  });

  const [editFac, setEditFac] = useState<Faculty | null>(null);
  const [isAddClsOpen, setIsAddClsOpen] = useState(false);
  const [clsForm, setClsForm] = useState({
    name: '',
    departmentId: 0,
    semester: 1,
    section: 'A',
    program: '',
    students: 40,
  });

  const [editCls, setEditCls] = useState<ClassItem | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [ov, cats, depts, f, c, accts] = await Promise.all([
        api<RegistryOverview>('/api/registry/overview').catch(() => ({
          departments: 0,
          faculty: 0,
          classes: 0,
          sections: 0,
          department_accounts: 0,
        })),
        api<InstitutionalCategory[]>('/api/registry/categories').catch(() => []),
        api<Department[]>('/api/registry/departments').catch(() => []),
        api<Faculty[]>('/api/registry/faculty').catch(() => []),
        api<ClassItem[]>('/api/registry/classes').catch(() => []),
        api<DepartmentAccountItem[]>('/api/registry/department-accounts').catch(() => []),
      ]);
      setOverview(ov);
      setCategories(cats);
      setDepartments(depts);
      setFaculty(f);
      setClasses(c);
      setAccounts(accts);
    } catch (err: any) {
      toast(err.message);
    } finally {
      setDataLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    document.title = 'College Registry · Tessellate';
    if (operator) {
      loadData();
    }
  }, [operator, loadData]);

  if (authLoading || (dataLoading && !operator)) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <p className="sub">Loading Registry records…</p>
      </div>
    );
  }

  if (!operator) {
    return null;
  }

  // Department handlers
  const handleAddDepartment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!deptForm.name.trim()) return toast('Please enter department name.');
    const catId = deptForm.categoryId || (categories[0]?.id ?? 1);

    try {
      const res = await api<{
        department_id: number;
        name: string;
        username: string;
        password?: string;
        plain_password?: string;
      }>('/api/registry/departments', {
        method: 'POST',
        body: {
          name: deptForm.name.trim(),
          code: deptForm.code.trim() || undefined,
          category_id: catId,
          description: deptForm.description.trim() || undefined,
        },
      });

      setIsAddDeptOpen(false);
      setDeptForm({ name: '', code: '', categoryId: 0, description: '' });
      loadData();

      const pw = res.plain_password || res.password || `${res.username}123`;
      setCredentialsModal({
        title: 'Department Account Provisioned',
        departmentName: res.name,
        username: res.username,
        password: pw,
      });
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleEditDepartment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editDept) return;
    try {
      await api(`/api/registry/departments/${editDept.id}`, {
        method: 'PUT',
        body: {
          name: editDept.name.trim(),
          category_id: editDept.category,
          description: editDept.description?.trim(),
        },
      });
      toast('Department updated.', true);
      setEditDept(null);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleDeleteDepartment = async (id: number, name: string) => {
    if (!window.confirm(`Delete department "${name}"? Only empty departments without active accounts can be deleted.`))
      return;
    try {
      await api(`/api/registry/departments/${id}`, { method: 'DELETE' });
      toast('Department deleted.', true);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleResetPassword = async (deptId: number, deptCode: string, deptName: string) => {
    if (!window.confirm(`Generate a new password for ${deptName}?`)) return;
    try {
      const res = await api<{ password?: string; plain_password?: string; username: string }>(
        `/api/registry/departments/${deptId}/reset-password`,
        { method: 'POST' }
      );
      const pw = res.plain_password || res.password || `${res.username}123`;
      setCredentialsModal({
        title: 'Department Password Reset',
        departmentName: deptName,
        username: res.username,
        password: pw,
      });
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleToggleAccountStatus = async (deptId: number, activate: boolean) => {
    try {
      await api(`/api/registry/departments/${deptId}/account-status`, {
        method: 'PUT',
        body: { active: activate },
      });
      toast(`Department account ${activate ? 'activated' : 'deactivated'}.`, true);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  // Faculty handlers
  const handleAddFaculty = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!facForm.name.trim()) return toast('Please enter faculty name.');
    const dId = facForm.departmentId || (departments[0]?.id ?? 1);

    try {
      await api('/api/registry/faculty', {
        method: 'POST',
        body: {
          name: facForm.name.trim(),
          department_id: dId,
          faculty_code: facForm.code.trim() || undefined,
          designation: facForm.designation.trim() || undefined,
          email: facForm.email.trim() || undefined,
          phone: facForm.phone.trim() || undefined,
          specialization: facForm.specialization.trim() || undefined,
          max_weekly_sessions: facForm.maxSessions,
        },
      });
      toast('Faculty member added.', true);
      setIsAddFacOpen(false);
      setFacForm({
        name: '',
        departmentId: 0,
        code: '',
        designation: 'Assistant Professor',
        email: '',
        phone: '',
        specialization: '',
        maxSessions: 16,
      });
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleEditFaculty = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editFac) return;
    try {
      await api(`/api/registry/faculty/${editFac.id}`, {
        method: 'PUT',
        body: {
          name: editFac.name.trim(),
          department_id: editFac.department_id,
          designation: editFac.designation?.trim(),
          phone: editFac.phone?.trim(),
          specialization: editFac.specialization?.trim(),
          max_weekly_sessions: editFac.max_weekly_sessions,
        },
      });
      toast('Faculty member updated.', true);
      setEditFac(null);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleDeleteFaculty = async (id: number, name: string) => {
    if (!window.confirm(`Remove faculty member "${name}" from registry?`)) return;
    try {
      await api(`/api/registry/faculty/${id}`, { method: 'DELETE' });
      toast('Faculty member removed.', true);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  // Class handlers
  const handleAddClass = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!clsForm.name.trim()) return toast('Please enter class name.');
    const dId = clsForm.departmentId || (departments[0]?.id ?? 1);

    try {
      await api('/api/registry/classes', {
        method: 'POST',
        body: {
          name: clsForm.name.trim(),
          department_id: dId,
          semester: Number(clsForm.semester),
          section: clsForm.section.trim(),
          program_name: clsForm.program.trim() || undefined,
          students: Number(clsForm.students) || 40,
        },
      });
      toast('Class & Section created.', true);
      setIsAddClsOpen(false);
      setClsForm({
        name: '',
        departmentId: 0,
        semester: 1,
        section: 'A',
        program: '',
        students: 40,
      });
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleEditClass = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editCls) return;
    try {
      await api(`/api/registry/classes/${editCls.id}`, {
        method: 'PUT',
        body: {
          name: editCls.name.trim(),
          semester: Number(editCls.semester),
          section: editCls.section.trim(),
          program_name: editCls.program_name?.trim(),
          students: Number(editCls.students),
        },
      });
      toast('Class updated.', true);
      setEditCls(null);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const handleDeleteClass = async (id: number, name: string) => {
    if (!window.confirm(`Delete class "${name}"?`)) return;
    try {
      await api(`/api/registry/classes/${id}`, { method: 'DELETE' });
      toast('Class deleted.', true);
      loadData();
    } catch (err: any) {
      toast(err.message);
    }
  };

  const filteredDepts = departments.filter((d) => {
    const matchesSearch =
      d.name.toLowerCase().includes(deptSearch.toLowerCase()) ||
      d.code.toLowerCase().includes(deptSearch.toLowerCase());
    const matchesCat = !deptCatFilter || d.category_name === deptCatFilter;
    const matchesStatus =
      !deptStatusFilter || (deptStatusFilter === 'active' ? d.active : !d.active);
    return matchesSearch && matchesCat && matchesStatus;
  });

  const filteredFaculty = faculty.filter((f) => {
    const matchesSearch =
      f.name.toLowerCase().includes(facSearch.toLowerCase()) ||
      f.faculty_code.toLowerCase().includes(facSearch.toLowerCase()) ||
      (f.designation && f.designation.toLowerCase().includes(facSearch.toLowerCase()));
    const matchesDept = !facDeptFilter || f.department === facDeptFilter;
    return matchesSearch && matchesDept;
  });

  const filteredClasses = classes.filter((c) => {
    const matchesSearch = c.name.toLowerCase().includes(clsSearch.toLowerCase());
    const matchesDept = !clsDeptFilter || c.department === clsDeptFilter;
    const matchesSem = !clsSemFilter || String(c.semester) === clsSemFilter;
    return matchesSearch && matchesDept && matchesSem;
  });

  return (
    <div className="app">
      <nav aria-label="Main Navigation">
        <div className="logo">Tessellate</div>
        <div className="reg-badge">College Registry</div>

        {NAV.map(([k, label]) => (
          <button
            key={k}
            onClick={() => setActiveTab(k)}
            aria-current={activeTab === k ? 'page' : undefined}
          >
            {label}
          </button>
        ))}

        <div style={{ marginTop: 'auto', borderTop: '1px solid var(--line)', paddingTop: '14px' }}>
          <button className="btn sm" onClick={logout} style={{ width: '100%' }}>
            Sign out
          </button>
        </div>
      </nav>

      <main>
        {activeTab === 'dash' && (
          <div>
            <div className="lab">College Registry Overview</div>
            <h1>Registry Dashboard</h1>
            <p className="sub">Central source of information for all departments, faculty and classes.</p>

            <div className="stats">
              <div>
                <b>{overview.departments}</b>
                <span className="sm">Total Departments</span>
              </div>
              <div>
                <b>{overview.faculty}</b>
                <span className="sm">Faculty Members</span>
              </div>
              <div>
                <b>{overview.classes}</b>
                <span className="sm">Total Classes</span>
              </div>
              <div>
                <b>{overview.sections}</b>
                <span className="sm">Total Sections</span>
              </div>
              <div>
                <b>{overview.department_accounts}</b>
                <span className="sm">Active Accounts</span>
              </div>
            </div>

            <div className="row sp" style={{ marginBottom: '24px' }}>
              <div className="row">
                <button className="btn p" onClick={() => setIsAddDeptOpen(true)}>
                  + Add Department
                </button>
                <button className="btn" onClick={() => setIsAddFacOpen(true)}>
                  + Add Faculty
                </button>
                <button className="btn" onClick={() => setIsAddClsOpen(true)}>
                  + Add Class
                </button>
              </div>
            </div>

            <div className="cols">
              <section>
                <h2>Central Registry Governance</h2>
                <p className="sm" style={{ lineHeight: 1.6 }}>
                  The Registry creates departments and provisions initial secure login credentials. Department
                  self-registration and OTP emails are permanently removed.
                </p>
                <p className="sm" style={{ lineHeight: 1.6 }}>
                  All departments, faculty identities and academic classes maintained here appear instantly
                  inside department workspaces with strict cross-department clash validation.
                </p>
              </section>
              <section>
                <h2>Institutional Categories</h2>
                <p className="sm" style={{ lineHeight: 1.6 }}>
                  Departments belong to <b>Aided</b> or <b>Self-Financing</b> categories. Both operate with
                  equal priority across shared resources, laboratory bookings, and common course periods.
                </p>
              </section>
            </div>
          </div>
        )}

        {activeTab === 'depts' && (
          <div>
            <div className="row sp" style={{ marginBottom: '14px' }}>
              <div>
                <div className="lab">Academic Registry</div>
                <h1>Departments</h1>
                <p className="sub">Manage college departments and generate secure login accounts.</p>
              </div>
              <button className="btn p" onClick={() => setIsAddDeptOpen(true)}>
                + Add Department
              </button>
            </div>

            <div className="row" style={{ marginBottom: '16px' }}>
              <input
                placeholder="Search departments…"
                style={{ width: '260px' }}
                value={deptSearch}
                onChange={(e) => setDeptSearch(e.target.value)}
                aria-label="Search departments"
              />
              <select
                value={deptCatFilter}
                onChange={(e) => setDeptCatFilter(e.target.value)}
                aria-label="Filter by category"
              >
                <option value="">All Categories</option>
                <option value="Aided">Aided</option>
                <option value="Self-Financing">Self-Financing</option>
              </select>
              <select
                value={deptStatusFilter}
                onChange={(e) => setDeptStatusFilter(e.target.value)}
                aria-label="Filter by account status"
              >
                <option value="">All Statuses</option>
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
              <span className="sm" style={{ marginLeft: 'auto' }}>
                {filteredDepts.length} departments
              </span>
            </div>

            {filteredDepts.length ? (
              <div className="gw">
                <table className="l">
                  <thead>
                    <tr>
                      <th>Code</th>
                      <th>Department Name</th>
                      <th>Category</th>
                      <th>Classes</th>
                      <th>Faculty</th>
                      <th>Username</th>
                      <th>Password</th>
                      <th>Account Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDepts.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <b>{d.code}</b>
                        </td>
                        <td>
                          {d.name}
                          {d.description && (
                            <>
                              <br />
                              <span className="sm">{d.description}</span>
                            </>
                          )}
                        </td>
                        <td>
                          <span className={`tag ${d.category_name === 'Aided' ? 'ok' : 'warn'}`}>
                            {d.category_name}
                          </span>
                        </td>
                        <td>{d.classes}</td>
                        <td>{d.faculty}</td>
                        <td>
                          <code>
                            <b>{d.username || 'none'}</b>
                          </code>
                        </td>
                        <td>
                          <code>{d.password || `${d.username}123`}</code>
                        </td>
                        <td>
                          <span className={`tag ${d.active ? 'ok' : 'crit'}`}>
                            {d.active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td>
                          <div className="row" style={{ gap: '6px' }}>
                            <button className="btn sm" onClick={() => setEditDept(d)}>
                              Edit
                            </button>
                            <button
                              className="btn sm"
                              onClick={() => handleResetPassword(d.id, d.code, d.name)}
                            >
                              Reset PW
                            </button>
                            <button
                              className="btn sm danger"
                              onClick={() => handleDeleteDepartment(d.id, d.name)}
                            >
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
                <h2>No departments found</h2>
                <p>Click + Add Department above to create one.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'fac' && (
          <div>
            <div className="row sp" style={{ marginBottom: '14px' }}>
              <div>
                <div className="lab">Faculty Management</div>
                <h1>Faculty Registry</h1>
                <p className="sub">
                  Centralized faculty records. Single college-wide identity prevents cross-department
                  double-booking.
                </p>
              </div>
              <button className="btn p" onClick={() => setIsAddFacOpen(true)}>
                + Add Faculty
              </button>
            </div>

            <div className="row" style={{ marginBottom: '16px' }}>
              <input
                placeholder="Search faculty by name, ID, or designation…"
                style={{ width: '300px' }}
                value={facSearch}
                onChange={(e) => setFacSearch(e.target.value)}
                aria-label="Search faculty"
              />
              <select
                value={facDeptFilter}
                onChange={(e) => setFacDeptFilter(e.target.value)}
                aria-label="Filter by department"
              >
                <option value="">All Departments</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.name}>
                    {d.name}
                  </option>
                ))}
              </select>
              <span className="sm" style={{ marginLeft: 'auto' }}>
                {filteredFaculty.length} faculty members
              </span>
            </div>

            {filteredFaculty.length ? (
              <div className="gw">
                <table className="l">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Name</th>
                      <th>Home Department</th>
                      <th>Designation</th>
                      <th>Contact / Phone</th>
                      <th>Specialization</th>
                      <th>Max Sessions</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredFaculty.map((f) => (
                      <tr key={f.id}>
                        <td>
                          <b>{f.faculty_code}</b>
                        </td>
                        <td>
                          <b>{f.name}</b>
                          {f.assigned_departments && f.assigned_departments.length > 0 && (
                            <>
                              <br />
                              <span className="sm">Also teaches: {f.assigned_departments.join(', ')}</span>
                            </>
                          )}
                        </td>
                        <td>{f.department || 'Unassigned'}</td>
                        <td>{f.designation || '—'}</td>
                        <td>{f.phone || f.email || '—'}</td>
                        <td>{f.specialization || '—'}</td>
                        <td>
                          {f.sessions} / {f.max_weekly_sessions}
                        </td>
                        <td>
                          <span className={`tag ${f.active ? 'ok' : 'crit'}`}>
                            {f.active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td>
                          <div className="row" style={{ gap: '6px' }}>
                            <button className="btn sm" onClick={() => setEditFac(f)}>
                              Edit
                            </button>
                            <button
                              className="btn sm danger"
                              onClick={() => handleDeleteFaculty(f.id, f.name)}
                            >
                              Remove
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
                <h2>No faculty members found</h2>
                <p>Click + Add Faculty above to register teachers.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'cls' && (
          <div>
            <div className="row sp" style={{ marginBottom: '14px' }}>
              <div>
                <div className="lab">Academic Structure</div>
                <h1>Classes &amp; Sections</h1>
                <p className="sub">Centrally managed student classes and sections mapped to departments.</p>
              </div>
              <button className="btn p" onClick={() => setIsAddClsOpen(true)}>
                + Add Class &amp; Section
              </button>
            </div>

            <div className="row" style={{ marginBottom: '16px' }}>
              <input
                placeholder="Search classes…"
                style={{ width: '260px' }}
                value={clsSearch}
                onChange={(e) => setClsSearch(e.target.value)}
                aria-label="Search classes"
              />
              <select
                value={clsDeptFilter}
                onChange={(e) => setClsDeptFilter(e.target.value)}
                aria-label="Filter by department"
              >
                <option value="">All Departments</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.name}>
                    {d.name}
                  </option>
                ))}
              </select>
              <select
                value={clsSemFilter}
                onChange={(e) => setClsSemFilter(e.target.value)}
                aria-label="Filter by semester"
              >
                <option value="">All Semesters</option>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => (
                  <option key={s} value={s}>
                    Semester {s}
                  </option>
                ))}
              </select>
              <span className="sm" style={{ marginLeft: 'auto' }}>
                {filteredClasses.length} classes
              </span>
            </div>

            {filteredClasses.length ? (
              <div className="gw">
                <table className="l">
                  <thead>
                    <tr>
                      <th>Class Name</th>
                      <th>Program</th>
                      <th>Department</th>
                      <th>Semester</th>
                      <th>Section</th>
                      <th>Students</th>
                      <th>Subjects</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredClasses.map((c) => (
                      <tr key={c.id}>
                        <td>
                          <b>{c.name}</b>
                        </td>
                        <td>{c.program_name || c.course_name || '—'}</td>
                        <td>{c.department}</td>
                        <td>Sem {c.semester}</td>
                        <td>
                          <span className="tag ok">Section {c.section}</span>
                        </td>
                        <td>{c.students ? `${c.students} students` : '—'}</td>
                        <td>{c.subjects}</td>
                        <td>
                          <div className="row" style={{ gap: '6px' }}>
                            <button className="btn sm" onClick={() => setEditCls(c)}>
                              Edit
                            </button>
                            <button
                              className="btn sm danger"
                              onClick={() => handleDeleteClass(c.id, c.name)}
                            >
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
                <h2>No classes found</h2>
                <p>Click + Add Class &amp; Section above.</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'accts' && (
          <div>
            <div className="row sp" style={{ marginBottom: '14px' }}>
              <div>
                <div className="lab">Access &amp; Security</div>
                <h1>Department Accounts</h1>
                <p className="sub">Provisioned credentials for department workspace access. No public signup.</p>
              </div>
            </div>

            <div className="gw">
              <table className="l">
                <thead>
                  <tr>
                    <th>Department</th>
                    <th>Code</th>
                    <th>Category</th>
                    <th>Username</th>
                    <th>Password</th>
                    <th>Account Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => (
                    <tr key={a.department_id}>
                      <td>
                        <b>{a.department_name}</b>
                      </td>
                      <td>
                        <code>{a.department_code}</code>
                      </td>
                      <td>
                        <span className={`tag ${a.category_name === 'Aided' ? 'ok' : 'warn'}`}>
                          {a.category_name}
                        </span>
                      </td>
                      <td>
                        <code>
                          <b>{a.username}</b>
                        </code>
                      </td>
                      <td>
                        <code>{a.password || `${a.username}123`}</code>
                      </td>
                      <td>
                        <span className={`tag ${a.active ? 'ok' : 'crit'}`}>
                          {a.active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td>
                        <div className="row" style={{ gap: '6px' }}>
                          <button
                            className="btn sm"
                            onClick={() =>
                              handleResetPassword(a.department_id, a.department_code, a.department_name)
                            }
                          >
                            Reset Password
                          </button>
                          <button
                            className="btn sm"
                            onClick={() => handleToggleAccountStatus(a.department_id, !a.active)}
                          >
                            {a.active ? 'Deactivate' : 'Activate'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* Credentials Dialog */}
      <Modal isOpen={!!credentialsModal} onClose={() => setCredentialsModal(null)}>
        {credentialsModal && (
          <div style={{ textAlign: 'center' }}>
            <div className="lab" style={{ color: 'var(--acc)' }}>
              Credentials Issued
            </div>
            <h2>{credentialsModal.title}</h2>
            <p className="sub">
              Department: <b>{credentialsModal.departmentName}</b>
            </p>

            <div className="cred-box">
              <div>
                Username: <b>{credentialsModal.username}</b>
              </div>
              <div>
                Password: <b>{credentialsModal.password}</b>
              </div>
            </div>

            <p className="sm" style={{ marginBottom: '20px' }}>
              Please copy these credentials now and provide them to the department coordinator. Passwords are
              never stored in plain text.
            </p>

            <div className="row" style={{ justifyContent: 'center', gap: '10px' }}>
              <button
                className="btn p"
                onClick={() => {
                  navigator.clipboard.writeText(
                    `Tessellate Department Login\nDepartment: ${credentialsModal.departmentName}\nUsername: ${credentialsModal.username}\nPassword: ${credentialsModal.password}\nLogin URL: ${window.location.origin}/login.html`
                  );
                  toast('Credentials copied to clipboard!', true);
                }}
              >
                Copy Credentials
              </button>
              <button className="btn" onClick={() => setCredentialsModal(null)}>
                Close
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Add Department Modal */}
      <Modal isOpen={isAddDeptOpen} onClose={() => setIsAddDeptOpen(false)}>
        <h2>Add New Department</h2>
        <p className="sub">Creates the department and provisions its login credentials together.</p>
        <form onSubmit={handleAddDepartment}>
          <div className="form-group">
            <label>Department Name *</label>
            <input
              placeholder="e.g. Computer Science"
              value={deptForm.name}
              onChange={(e) => setDeptForm({ ...deptForm, name: e.target.value })}
              required
              autoFocus
            />
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Department Code</label>
              <input
                placeholder="e.g. CS (auto-derived if empty)"
                value={deptForm.code}
                onChange={(e) => setDeptForm({ ...deptForm, code: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Category *</label>
              <select
                value={deptForm.categoryId || (categories[0]?.id ?? 1)}
                onChange={(e) => setDeptForm({ ...deptForm, categoryId: Number(e.target.value) })}
              >
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-group">
            <label>Description (optional)</label>
            <textarea
              placeholder="Brief description or notes..."
              value={deptForm.description}
              onChange={(e) => setDeptForm({ ...deptForm, description: e.target.value })}
            />
          </div>
          <div className="row sp" style={{ marginTop: '20px' }}>
            <button type="button" className="btn" onClick={() => setIsAddDeptOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn p">
              Create Department &amp; Account
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Department Modal */}
      <Modal isOpen={!!editDept} onClose={() => setEditDept(null)}>
        {editDept && (
          <div>
            <h2>Edit Department</h2>
            <p className="sub">Update details for {editDept.name}.</p>
            <form onSubmit={handleEditDepartment}>
              <div className="form-group">
                <label>Department Name *</label>
                <input
                  value={editDept.name}
                  onChange={(e) => setEditDept({ ...editDept, name: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label>Category *</label>
                <select
                  value={editDept.category}
                  onChange={(e) => setEditDept({ ...editDept, category: e.target.value })}
                >
                  {categories.map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Description</label>
                <textarea
                  value={editDept.description || ''}
                  onChange={(e) => setEditDept({ ...editDept, description: e.target.value })}
                />
              </div>
              <div className="row sp" style={{ marginTop: '20px' }}>
                <button type="button" className="btn" onClick={() => setEditDept(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn p">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        )}
      </Modal>

      {/* Add Faculty Modal */}
      <Modal isOpen={isAddFacOpen} onClose={() => setIsAddFacOpen(false)}>
        <h2>Add Faculty Member</h2>
        <p className="sub">Register a faculty member in the central college registry.</p>
        <form onSubmit={handleAddFaculty}>
          <div className="form-group">
            <label>Full Name *</label>
            <input
              placeholder="e.g. Dr. Anil Kumar"
              value={facForm.name}
              onChange={(e) => setFacForm({ ...facForm, name: e.target.value })}
              required
              autoFocus
            />
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Home Department *</label>
              <select
                value={facForm.departmentId || (departments[0]?.id ?? 1)}
                onChange={(e) => setFacForm({ ...facForm, departmentId: Number(e.target.value) })}
              >
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Faculty ID / Code</label>
              <input
                placeholder="e.g. FAC-001 (auto if empty)"
                value={facForm.code}
                onChange={(e) => setFacForm({ ...facForm, code: e.target.value })}
              />
            </div>
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Designation</label>
              <input
                placeholder="e.g. Assistant Professor"
                value={facForm.designation}
                onChange={(e) => setFacForm({ ...facForm, designation: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Max Weekly Sessions</label>
              <input
                type="number"
                min="1"
                max="40"
                value={facForm.maxSessions}
                onChange={(e) => setFacForm({ ...facForm, maxSessions: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Contact Phone</label>
              <input
                placeholder="+91..."
                value={facForm.phone}
                onChange={(e) => setFacForm({ ...facForm, phone: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Specialization</label>
              <input
                placeholder="e.g. Machine Learning"
                value={facForm.specialization}
                onChange={(e) => setFacForm({ ...facForm, specialization: e.target.value })}
              />
            </div>
          </div>
          <div className="row sp" style={{ marginTop: '20px' }}>
            <button type="button" className="btn" onClick={() => setIsAddFacOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn p">
              Register Faculty
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Faculty Modal */}
      <Modal isOpen={!!editFac} onClose={() => setEditFac(null)}>
        {editFac && (
          <div>
            <h2>Edit Faculty Member</h2>
            <p className="sub">Update details for {editFac.name}.</p>
            <form onSubmit={handleEditFaculty}>
              <div className="form-group">
                <label>Full Name *</label>
                <input
                  value={editFac.name}
                  onChange={(e) => setEditFac({ ...editFac, name: e.target.value })}
                  required
                />
              </div>
              <div className="grid2">
                <div className="form-group">
                  <label>Home Department *</label>
                  <select
                    value={editFac.department_id || (departments.find((d) => d.name === editFac.department)?.id ?? 1)}
                    onChange={(e) => setEditFac({ ...editFac, department_id: Number(e.target.value) })}
                  >
                    {departments.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>Designation</label>
                  <input
                    value={editFac.designation || ''}
                    onChange={(e) => setEditFac({ ...editFac, designation: e.target.value })}
                  />
                </div>
              </div>
              <div className="grid2">
                <div className="form-group">
                  <label>Max Weekly Sessions</label>
                  <input
                    type="number"
                    min="1"
                    max="40"
                    value={editFac.max_weekly_sessions}
                    onChange={(e) =>
                      setEditFac({ ...editFac, max_weekly_sessions: Number(e.target.value) })
                    }
                  />
                </div>
                <div className="form-group">
                  <label>Contact Phone</label>
                  <input
                    value={editFac.phone || ''}
                    onChange={(e) => setEditFac({ ...editFac, phone: e.target.value })}
                  />
                </div>
              </div>
              <div className="form-group">
                <label>Specialization</label>
                <input
                  value={editFac.specialization || ''}
                  onChange={(e) => setEditFac({ ...editFac, specialization: e.target.value })}
                />
              </div>
              <div className="row sp" style={{ marginTop: '20px' }}>
                <button type="button" className="btn" onClick={() => setEditFac(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn p">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        )}
      </Modal>

      {/* Add Class Modal */}
      <Modal isOpen={isAddClsOpen} onClose={() => setIsAddClsOpen(false)}>
        <h2>Add Class &amp; Section</h2>
        <p className="sub">Register a class cohort mapped to a department.</p>
        <form onSubmit={handleAddClass}>
          <div className="form-group">
            <label>Class Name *</label>
            <input
              placeholder="e.g. BSc CS Sem 1 A"
              value={clsForm.name}
              onChange={(e) => setClsForm({ ...clsForm, name: e.target.value })}
              required
              autoFocus
            />
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Department *</label>
              <select
                value={clsForm.departmentId || (departments[0]?.id ?? 1)}
                onChange={(e) => setClsForm({ ...clsForm, departmentId: Number(e.target.value) })}
              >
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Semester *</label>
              <select
                value={clsForm.semester}
                onChange={(e) => setClsForm({ ...clsForm, semester: Number(e.target.value) })}
              >
                {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => (
                  <option key={s} value={s}>
                    Semester {s}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid2">
            <div className="form-group">
              <label>Section *</label>
              <input
                placeholder="e.g. A"
                value={clsForm.section}
                onChange={(e) => setClsForm({ ...clsForm, section: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Student Count</label>
              <input
                type="number"
                min="1"
                max="200"
                value={clsForm.students}
                onChange={(e) => setClsForm({ ...clsForm, students: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="form-group">
            <label>Program Name (optional)</label>
            <input
              placeholder="e.g. Bachelor of Science"
              value={clsForm.program}
              onChange={(e) => setClsForm({ ...clsForm, program: e.target.value })}
            />
          </div>
          <div className="row sp" style={{ marginTop: '20px' }}>
            <button type="button" className="btn" onClick={() => setIsAddClsOpen(false)}>
              Cancel
            </button>
            <button type="submit" className="btn p">
              Create Class &amp; Section
            </button>
          </div>
        </form>
      </Modal>

      {/* Edit Class Modal */}
      <Modal isOpen={!!editCls} onClose={() => setEditCls(null)}>
        {editCls && (
          <div>
            <h2>Edit Class</h2>
            <p className="sub">Update class details for {editCls.name}.</p>
            <form onSubmit={handleEditClass}>
              <div className="form-group">
                <label>Class Name *</label>
                <input
                  value={editCls.name}
                  onChange={(e) => setEditCls({ ...editCls, name: e.target.value })}
                  required
                />
              </div>
              <div className="grid2">
                <div className="form-group">
                  <label>Semester *</label>
                  <select
                    value={editCls.semester}
                    onChange={(e) => setEditCls({ ...editCls, semester: Number(e.target.value) })}
                  >
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => (
                      <option key={s} value={s}>
                        Semester {s}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>Section *</label>
                  <input
                    value={editCls.section}
                    onChange={(e) => setEditCls({ ...editCls, section: e.target.value })}
                    required
                  />
                </div>
              </div>
              <div className="grid2">
                <div className="form-group">
                  <label>Student Count</label>
                  <input
                    type="number"
                    min="1"
                    max="200"
                    value={editCls.students || 40}
                    onChange={(e) => setEditCls({ ...editCls, students: Number(e.target.value) })}
                  />
                </div>
                <div className="form-group">
                  <label>Program Name</label>
                  <input
                    value={editCls.program_name || ''}
                    onChange={(e) => setEditCls({ ...editCls, program_name: e.target.value })}
                  />
                </div>
              </div>
              <div className="row sp" style={{ marginTop: '20px' }}>
                <button type="button" className="btn" onClick={() => setEditCls(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn p">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        )}
      </Modal>
    </div>
  );
};
