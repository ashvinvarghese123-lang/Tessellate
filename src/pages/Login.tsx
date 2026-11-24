import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../lib/api';

export const Login: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Sign in · Tessellate';
    api('/api/auth/me')
      .then(() => navigate('/', { replace: true }))
      .catch(() => {});
  }, [navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const u = username.trim();
    if (!u || !password) {
      setError('Please enter your username and password.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await api<{ signed_in: boolean }>('/api/auth/login', {
        method: 'POST',
        body: { username: u, password },
      });
      if (res.signed_in) {
        window.location.replace('/');
      }
    } catch (err: any) {
      setError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-wrap">
      <aside className="login-brand" aria-hidden="false">
        <div className="mark">Tessellate</div>
        <div>
          <div className="login-grid" aria-hidden="true">
            <i className="on"></i><i></i><i></i><i className="on"></i><i></i>
            <i></i><i className="on"></i><i></i><i></i><i className="on"></i>
            <i className="on"></i><i></i><i></i><i className="on"></i><i></i>
            <i></i><i></i><i className="on"></i><i></i><i className="on"></i>
            <i className="on"></i><i></i><i></i><i className="on"></i><i></i>
          </div>
          <h2>Every department. Equal priority. Perfectly aligned.</h2>
          <p>College timetables and shared resources, kept in step across every department.</p>
        </div>
        <div className="sub" style={{ fontSize: '13px' }}>
          Centralized College Registry &amp; Department Management.
        </div>
      </aside>

      <main className="login-side">
        <div className="login-box">
          <form onSubmit={handleSubmit} noValidate>
            <div className="lab">Department Workspace</div>
            <h1 style={{ fontSize: '30px', margin: '6px 0 8px', lineHeight: 1.15 }}>Sign in</h1>
            <p className="sub" style={{ margin: '0 0 20px' }}>
              Enter your department credentials issued by the College Registry.
            </p>

            <label htmlFor="u" style={{ display: 'block', margin: '18px 0 6px', fontSize: '13px', color: 'var(--mute)' }}>
              Username
            </label>
            <input
              id="u"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck="false"
              placeholder="e.g. cs, maths, chemistry"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              style={{ width: '100%' }}
            />

            <label htmlFor="p" style={{ display: 'block', margin: '18px 0 6px', fontSize: '13px', color: 'var(--mute)' }}>
              Password
            </label>
            <div className="pw-wrap">
              <input
                id="p"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Enter password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>

            <button
              type="submit"
              className="btn"
              disabled={submitting}
              style={{
                width: '100%',
                marginTop: '24px',
                background: 'var(--ink)',
                color: 'var(--bg)',
                border: '1px solid var(--ink)',
                borderRadius: '7px',
                minHeight: '46px',
              }}
            >
              Sign in
            </button>

            <div className="err" role="alert">
              {error}
            </div>

            <div className="foot">
              Department accounts are provisioned centrally by the College Registry.
              <br />
              <Link to="/registry-login.html" className="lk" style={{ marginTop: '10px' }}>
                Sign in as Registry Operator &rarr;
              </Link>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
};
