export interface Department {
  id: number;
  name: string;
  code: string;
  category: string;
  category_name?: string;
  description?: string;
  classes?: number;
  faculty?: number;
  username?: string;
  password?: string;
  active?: boolean;
}

export interface UserMe {
  id: number;
  username: string;
  department: Department;
}

export interface RegistryMe {
  id: number;
  username: string;
  email_hint: string;
  token_hash: string;
}

export interface Faculty {
  id: number;
  name: string;
  faculty_code: string;
  department: string;
  department_id?: number;
  designation?: string;
  phone?: string;
  email?: string;
  specialization?: string;
  sessions: number;
  max_weekly_sessions: number;
  active?: boolean;
  assigned_departments?: string[];
  allocations_by_dept?: Array<{ department: string; sessions: number }>;
}

export interface ClassItem {
  id: number;
  name: string;
  department: string;
  department_id?: number;
  semester: number;
  section: string;
  students?: number;
  subjects?: number;
  program_name?: string;
  course_name?: string;
}

export interface SubjectAllocation {
  id: number;
  subject: string;
  subject_code?: string;
  code?: string;
  course_category: 'Regular' | 'MDC' | 'Minor';
  class_id: number;
  class_name: string;
  faculty_id: number;
  teacher: string;
  faculty_code: string;
  sessions_per_week: number;
  duration?: number;
  placed: number;
}

export interface PeriodTiming {
  start: string;
  end: string;
}

export interface RuleDef {
  title: string;
  help: string;
  modes: Array<'off' | 'prefer' | 'require'>;
  param?: {
    key: string;
    label: string;
    min: number;
    max: number;
    default: number;
  };
}

export interface DepartmentConfig {
  days: number[];
  periods: PeriodTiming[];
  rules: Record<string, { mode: 'off' | 'prefer' | 'require'; [key: string]: any }>;
  free: Array<[number, number]>;
  mdc_slots: Array<[number, number]>;
  minor_slots: Array<[number, number]>;
}

export interface SettingsResponse {
  config: DepartmentConfig;
  rule_defs: Record<string, RuleDef>;
  stale?: boolean;
}

export interface AvailabilitySlot {
  day: number;
  period: number;
  start: string;
  end: string;
  state: 'available' | 'unavailable' | 'busy';
  reason?: string;
}

export interface TimetableEntry {
  id: number;
  day: number;
  period: number;
  start: string;
  end: string;
  subject: string;
  course_type?: 'Regular' | 'MDC' | 'Minor';
  teacher?: string;
  class_name?: string;
}

export interface ConflictItem {
  issue: string;
  fix: string;
  type?: 'teacher_clash' | 'teacher_clash_internal' | 'teacher_unavailable' | 'teacher_capacity' | 'student_clash' | 'room' | 'rule' | 'class_overlap' | 'common_slot' | string;
  can_fix_internally?: boolean;
  teacher_id?: number;
  teacher_name?: string;
  faculty_code?: string;
  busy_details?: {
    teacher_name?: string;
    faculty_code?: string;
    department?: string;
    subject?: string;
    class_name?: string;
    day?: number;
    day_name?: string;
    period?: number;
    start?: string;
    end?: string;
    reason?: string;
  };
  department_session?: {
    entry_id?: number;
    class_id?: number;
    class_name?: string;
    subject?: string;
    day?: number;
    day_name?: string;
    period?: number;
    start?: string;
    end?: string;
  };
  available_slots?: Array<{
    day: number;
    day_name: string;
    period: number;
    period_label?: string;
    start: string;
    end: string;
  }>;
  available_faculty?: Array<{
    id: number;
    name: string;
    faculty_code: string;
    current_load?: number;
    max_load?: number;
  }>;
  cells?: Array<{ day: number; period: number }>;
  entry_ids?: number[];
}

export interface ConflictResponse {
  items: ConflictItem[];
}

export interface SlotsOverview {
  config: DepartmentConfig;
  other_departments: Array<{
    id: number;
    name: string;
    code: string;
    mdc_slots: Array<{ day: number; day_name: string; period: number; start: string; end: string }>;
    minor_slots: Array<{ day: number; day_name: string; period: number; start: string; end: string }>;
  }>;
  allocations: Array<{
    id: number;
    subject: string;
    code: string;
    course_category: string;
    sessions_per_week: number;
    teacher: string;
    faculty_id: number;
    faculty_code: string;
  }>;
}

export interface GenerationResult {
  status: 'ok' | 'fail' | 'infeasible';
  sessions?: number;
  quality?: number;
  message?: string;
  issues?: ConflictItem[];
}
