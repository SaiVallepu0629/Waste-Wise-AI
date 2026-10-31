const navigationItems = [
  { id: 'dashboard', label: 'Dashboard', icon: '⌂' },
  { id: 'inventory', label: 'Inventory', icon: '▦' },
  { id: 'expiry-risk', label: 'Expiry Risk', icon: '◷' },
  { id: 'demand-forecasting', label: 'Demand Forecasting', icon: '⌁' },
  { id: 'discount-recommendations', label: 'Discount Recommendations', icon: '%' },
]

export default function Sidebar({ activePage, onNavigate }) {
  return (
    <aside className="sidebar">
      <a className="brand" href="#dashboard" onClick={() => onNavigate('dashboard')}>
        <span className="brand-mark" aria-hidden="true">W</span>
        <span>
          <strong>WasteWise</strong>
          <small>SMART INVENTORY</small>
        </span>
      </a>

      <p className="sidebar-label">WORKSPACE</p>
      <nav className="navigation" aria-label="Main navigation">
        {navigationItems.map((item) => (
          <button
            className={`nav-item${activePage === item.id ? ' active' : ''}`}
            key={item.id}
            onClick={() => onNavigate(item.id)}
            type="button"
          >
            <span className="nav-icon" aria-hidden="true">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <span className="status-dot" />
        <span>Food smarter. Waste less.</span>
      </div>
    </aside>
  )
}
