import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../lib/api';

export const RegistryLogin: React.FC = () => {
  const [username, setUsername] = useState('registry');
  const [password, setPassword] = useState('registry123');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Registry sign in · Tessellate';
    api('/api/registry/me')
      .then(() => navigate('/registry.html', { replace: true }))
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
      const res = await api<{ signed_in: boolean }>('/api/registry/auth/login', {
        method: 'POST',
        body: { username: u, password },
      });
      if (res.signed_in) {
        window.location.replace('/registry.html');
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
          <h2>One registry. Centralized governance.</h2>
          <p>Master records for all departments, faculty, classes, and credentials.</p>
        </div>
        <div className="sub" style={{ fontSize: '13px' }}>
          College Registry Management
        </div>
      </aside>

      <main className="login-side">
        <div className="login-box">
          <form onSubmit={handleSubmit} noValidate>
            <div className="lab">College Registry</div>
            <h1 style={{ fontSize: '30px', margin: '6px 0 8px', lineHeight: 1.15 }}>Registry sign in</h1>
            <p className="sub" style={{ margin: '0 0 16px' }}>
              Manage college departments, faculty records, classes, and login accounts.
            </p>

            <div className="cred-card">
              <div className="c-lab">Operator Login Credentials</div>
              <div>Username: <b>registry</b></div>
              <div>Password: <b>registry123</b></div>
            </div>

            <label htmlFor="u" style={{ display: 'block', margin: '16px 0 6px', fontSize: '13px', color: 'var(--mute)' }}>
              Registry username
            </label>
            <input
              id="u"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck="false"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              style={{ width: '100%' }}
            />

            <label htmlFor="p" style={{ display: 'block', margin: '16px 0 6px', fontSize: '13px', color: 'var(--mute)' }}>
              Password
            </label>
            <div className="pw-wrap">
              <input
                id="p"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
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
                marginTop: '20px',
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

            <div className="foot" style={{ marginTop: '28px' }}>
              Protected Registry operator access.
              <br />
              <Link to="/login.html" className="lk" style={{ marginTop: '10px' }}>
                &larr; Return to Department Sign In
              </Link>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
};
