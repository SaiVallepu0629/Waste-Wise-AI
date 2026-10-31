import { useState } from 'react'

export default function AuthScreen({
  loading,
  error,
  notice,
  onAuthenticate,
}) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [validationError, setValidationError] = useState('')

  const isRegistration = mode === 'register'

  const submit = async (event) => {
    event.preventDefault()
    setValidationError('')
    if (isRegistration && password !== confirmation) {
      setValidationError('The passwords do not match.')
      return
    }
    await onAuthenticate({ email: email.trim(), password }, mode)
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <a className="auth-brand" href="#login">
          <span className="brand-mark" aria-hidden="true">W</span>
          <span>
            <strong>WasteWise</strong>
            <small>SMART INVENTORY</small>
          </span>
        </a>
        <p className="eyebrow">SECURE WORKSPACE</p>
        <h1 id="auth-title">{isRegistration ? 'Create your account' : 'Welcome back'}</h1>
        <p className="auth-description">
          {isRegistration
            ? 'Create a private workspace for your inventory.'
            : 'Sign in to manage your inventory and analytics.'}
        </p>

        {notice && <div className="auth-notice" role="status">{notice}</div>}
        {(validationError || error) && (
          <div className="auth-error" role="alert">{validationError || error}</div>
        )}

        <form className="auth-form" onSubmit={submit}>
          <label>
            Email
            <input
              autoComplete="email"
              maxLength={254}
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            Password
            <input
              autoComplete={isRegistration ? 'new-password' : 'current-password'}
              maxLength={128}
              minLength={12}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
            {isRegistration && <small>Use at least 12 characters.</small>}
          </label>
          {isRegistration && (
            <label>
              Confirm password
              <input
                autoComplete="new-password"
                maxLength={128}
                minLength={12}
                onChange={(event) => setConfirmation(event.target.value)}
                required
                type="password"
                value={confirmation}
              />
            </label>
          )}
          <button className="primary-button auth-submit" disabled={loading} type="submit">
            {loading
              ? 'Please wait…'
              : isRegistration ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <p className="auth-switch">
          {isRegistration ? 'Already have an account?' : 'New to WasteWise?'}
          <button
            disabled={loading}
            onClick={() => {
              setMode(isRegistration ? 'login' : 'register')
              setValidationError('')
            }}
            type="button"
          >
            {isRegistration ? 'Sign in' : 'Create an account'}
          </button>
        </p>
      </section>
    </main>
  )
}
