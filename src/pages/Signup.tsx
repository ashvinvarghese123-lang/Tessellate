import React, { useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';

export const Signup: React.FC = () => {
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'Registration Closed · Tessellate';
    const timer = setTimeout(() => {
      navigate('/login.html', { replace: true });
    }, 1500);
    return () => clearTimeout(timer);
  }, [navigate]);

  return (
    <div
      style={{
        margin: 0,
        minHeight: '100vh',
        background: 'var(--bg)',
        color: 'var(--ink)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div
        className="card"
        style={{
          width: '100%',
          maxWidth: '420px',
          padding: '32px',
          textAlign: 'center',
        }}
      >
        <h1 style={{ fontFamily: 'Fraunces, Georgia, serif', fontWeight: 400, margin: '0 0 12px', fontSize: '26px' }}>
          College Registry Provisioned
        </h1>
        <p style={{ color: 'var(--mute)', margin: '0 0 24px' }}>
          Public self-registration is closed. Department accounts are issued centrally by the College Registry.
        </p>
        <Link
          className="btn"
          to="/login.html"
          style={{
            display: 'inline-block',
            padding: '10px 20px',
            background: 'var(--ink)',
            color: 'var(--bg)',
            textDecoration: 'none',
            borderRadius: '7px',
            fontWeight: 500,
          }}
        >
          Return to Sign In
        </Link>
      </div>
    </div>
  );
};
