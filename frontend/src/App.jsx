import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DataTable from './components/DataTable'
import AuthScreen from './components/AuthScreen'
import ExpiryRiskChart from './components/ExpiryRiskChart'
import ForecastLineChart from './components/ForecastLineChart'
import InventoryManager from './components/InventoryManager'
import MetricCard from './components/MetricCard'
import Sidebar from './components/Sidebar'
import {
  fetchCurrentUser,
  fetchDashboardData,
  fetchForecastProducts,
  fetchForecastSummary,
  fetchProductForecast,
  loginUser,
  logoutUser,
  registerUser,
  setAccessToken,
  setUnauthorizedHandler,
} from './services/api'
import './App.css'

const EMPTY_ARRAY = Object.freeze([])

const pageTitles = {
  dashboard: 'Dashboard',
  inventory: 'Inventory',
  'expiry-risk': 'Expiry Risk',
  'demand-forecasting': 'Demand Forecasting',
  'discount-recommendations': 'Discount Recommendations',
}

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? numberFormat.format(number) : '—'
}

function formatMetric(value, decimals = 2) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(decimals) : '—'
}

function SnapshotBadge({ status }) {
  const label = {
    latest_available_snapshot: 'Latest available',
    historical_snapshot: 'Historical',
    future_snapshot: 'Future-dated',
  }[status] || 'Unknown'

  return <span className={`badge ${status || 'unknown'}`}>{label}</span>
}

function SectionHeading({ eyebrow, title, description, actions }) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        {description && <p className="section-description">{description}</p>}
      </div>
      {actions}
    </div>
  )
}

function App() {
  const [accessToken, setAccessTokenState] = useState(null)
  const [sessionExpiresAt, setSessionExpiresAt] = useState(null)
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authNotice, setAuthNotice] = useState('')
  const [page, setPage] = useState('dashboard')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)
  const [inventoryRefreshToken, setInventoryRefreshToken] = useState(0)
  const [recommendationSearch, setRecommendationSearch] = useState('')
  const [discountFilter, setDiscountFilter] = useState('all')
  const [forecastSummary, setForecastSummary] = useState(null)
  const [forecastProducts, setForecastProducts] = useState(EMPTY_ARRAY)
  const [forecastProductId, setForecastProductId] = useState('')
  const forecastProductIdRef = useRef('')
  const [productForecast, setProductForecast] = useState(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState('')

  const clearSession = useCallback((notice = '') => {
    setAccessToken(null)
    setAccessTokenState(null)
    setSessionExpiresAt(null)
    setUser(null)
    setData(null)
    setForecastSummary(null)
    setForecastProducts(EMPTY_ARRAY)
    setProductForecast(null)
    setPage('dashboard')
    setAuthNotice(notice)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => clearSession('Your session expired. Please sign in again.'))
    return () => setUnauthorizedHandler(null)
  }, [clearSession])

  useEffect(() => {
    if (!accessToken || !sessionExpiresAt) return undefined
    const timerId = window.setTimeout(
      () => clearSession('Your session expired. Please sign in again.'),
      Math.max(0, sessionExpiresAt - Date.now()),
    )
    return () => window.clearTimeout(timerId)
  }, [accessToken, clearSession, sessionExpiresAt])

  const authenticate = async (credentials, mode) => {
    setAuthLoading(true)
    setAuthError('')
    setAuthNotice('')
    try {
      const session = mode === 'register'
        ? await registerUser(credentials)
        : await loginUser(credentials)
      setAccessToken(session.access_token)
      const profile = await fetchCurrentUser()
      setAccessTokenState(session.access_token)
      setSessionExpiresAt(Date.now() + session.expires_in * 1000)
      setUser(profile)
      setPage('dashboard')
    } catch (requestError) {
      setAccessToken(null)
      setAuthError(requestError.message || 'Authentication failed. Please try again.')
    } finally {
      setAuthLoading(false)
    }
  }

  const logout = async () => {
    setAuthLoading(true)
    try {
      await logoutUser()
      clearSession('')
    } catch (requestError) {
      clearSession(
        `Signed out on this device. The server could not revoke the token: ${requestError.message}`,
      )
    } finally {
      setAuthLoading(false)
    }
  }

  const refreshData = useCallback(async () => {
    if (!accessToken) return
    setLoading(true)
    setError('')
    try {
      const nextData = await fetchDashboardData()
      setData(nextData)
      setLastUpdated(new Date())
    } catch (requestError) {
      setError(requestError.message || 'The dashboard data could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [accessToken])

  const refreshForecastSummary = useCallback(async () => {
    if (!accessToken) return
    setForecastError('')
    try {
      setForecastSummary(await fetchForecastSummary())
    } catch (requestError) {
      setForecastError(
        requestError.message || 'Demand model evaluation could not be loaded.',
      )
    }
  }, [accessToken])

  useEffect(() => {
    if (!accessToken) return undefined
    const timerId = window.setTimeout(() => refreshData(), 0)
    return () => window.clearTimeout(timerId)
  }, [accessToken, refreshData])

  useEffect(() => {
    if (!accessToken || page !== 'dashboard' || forecastSummary) return undefined
    const timerId = window.setTimeout(() => refreshForecastSummary(), 0)
    return () => window.clearTimeout(timerId)
  }, [accessToken, forecastSummary, page, refreshForecastSummary])

  const refreshForecast = useCallback(async (requestedProductId) => {
    if (!accessToken) return
    setForecastLoading(true)
    setForecastError('')
    try {
      const [summary, products] = await Promise.all([
        fetchForecastSummary(),
        fetchForecastProducts(),
      ])
      const chosenProductId =
        requestedProductId ||
        (products.some(
          (product) => String(product.product_id) === forecastProductIdRef.current,
        )
          ? forecastProductIdRef.current
          : String(products[0]?.product_id ?? ''))
      const detail = chosenProductId
        ? await fetchProductForecast(chosenProductId)
        : null
      setForecastSummary(summary)
      setForecastProducts(products)
      forecastProductIdRef.current = chosenProductId
      setForecastProductId(chosenProductId)
      setProductForecast(detail)
    } catch (requestError) {
      setForecastError(
        requestError.message || 'Demand forecasting data could not be loaded.',
      )
    } finally {
      setForecastLoading(false)
    }
  }, [accessToken])

  useEffect(() => {
    if (!accessToken || page !== 'demand-forecasting') return undefined
    const timerId = window.setTimeout(() => refreshForecast(), 0)
    return () => window.clearTimeout(timerId)
  }, [accessToken, page, refreshForecast])

  const refreshCurrentPage = () => {
    refreshData()
    if (page === 'dashboard') refreshForecastSummary()
    if (page === 'inventory') {
      setInventoryRefreshToken((current) => current + 1)
    }
    if (page === 'demand-forecasting') refreshForecast()
  }

  const inventory = data?.inventory?.records ?? EMPTY_ARRAY
  const recommendations = data?.recommendations ?? EMPTY_ARRAY
  const liveRecommendations = data?.liveRecommendations ?? EMPTY_ARRAY
  const expiryRisk = data?.expiryRisk

  const recommendationsWithProduct = useMemo(() => {
    const productNames = new Map(
      inventory.map((row) => [String(row.product_id), row.product_name]),
    )
    return recommendations.map((row) => ({
      ...row,
      product_name: productNames.get(String(row.product_id)) || `Product ${row.product_id}`,
    }))
  }, [inventory, recommendations])

  const filteredRecommendations = useMemo(() => {
    const query = recommendationSearch.trim().toLowerCase()
    return recommendationsWithProduct.filter((row) => {
      const matchesSearch = !query || [
        row.product_name,
        row.product_id,
        row.batch_id,
      ].some((value) => String(value ?? '').toLowerCase().includes(query))
      const matchesDiscount =
        discountFilter === 'all' ||
        Number(row.recommended_discount_pct) === Number(discountFilter)
      return matchesSearch && matchesDiscount
    })
  }, [discountFilter, recommendationSearch, recommendationsWithProduct])

  const productCount = new Set(inventory.map((row) => String(row.product_id))).size
  const unsoldUnits = recommendations.reduce(
    (total, row) => total + (Number(row.estimated_unsold_units) || 0),
    0,
  )
  const averageDiscount = recommendations.length
    ? recommendations.reduce(
      (total, row) => total + (Number(row.recommended_discount_pct) || 0),
      0,
    ) / recommendations.length
    : null
  const futureSnapshots = inventory.filter(
    (row) => row.snapshot_status === 'future_snapshot',
  ).length
  const highRiskLiveItems = liveRecommendations.filter(
    (row) => row.risk_level === 'High',
  ).length
  const liveUnitsAtRisk = liveRecommendations.reduce(
    (total, row) => total + (Number(row.quantity_at_risk) || 0),
    0,
  )

  const recommendationColumns = [
    { key: 'product_name', label: 'Product' },
    { key: 'batch_id', label: 'Batch ID' },
    {
      key: 'recommended_discount_pct',
      label: 'Recommended discount',
      render: (row) => `${formatNumber(row.recommended_discount_pct)}%`,
    },
    {
      key: 'estimated_units_sold_simulated',
      label: 'Est. units sold',
      render: (row) => formatNumber(row.estimated_units_sold_simulated),
    },
    {
      key: 'estimated_unsold_units',
      label: 'Est. unsold',
      render: (row) => formatNumber(row.estimated_unsold_units),
    },
    {
      key: 'estimated_gross_margin_simulated',
      label: 'Est. gross margin',
      render: (row) => formatNumber(row.estimated_gross_margin_simulated),
    },
    {
      key: 'recommendation_type',
      label: 'Basis',
      render: () => <span className="badge simulation">Simulation</span>,
    },
  ]

  const expiryColumns = [
    { key: 'product_name', label: 'Product' },
    { key: 'batch_id', label: 'Batch ID' },
    { key: 'snapshot_date', label: 'Snapshot date' },
    { key: 'expiry_date', label: 'Expiry date' },
    {
      key: 'days_to_expiry_at_snapshot',
      label: 'Days at snapshot',
      render: (row) => formatNumber(row.days_to_expiry_at_snapshot),
    },
    {
      key: 'risk_status',
      label: 'Source risk label',
      render: (row) => (
        <span className={`badge ${row.expiry_risk_label === 1 ? 'risk' : 'safe'}`}>
          {row.risk_status}
        </span>
      ),
    },
    {
      key: 'rule_based_risk_level_at_snapshot',
      label: 'Estimated risk',
      render: (row) => (
        <span className={`badge risk-${row.rule_based_risk_level_at_snapshot?.toLowerCase()}`}>
          {row.rule_based_risk_level_at_snapshot}
        </span>
      ),
    },
    {
      key: 'quantity_at_risk_estimate',
      label: 'Est. units at risk',
      render: (row) => formatNumber(row.quantity_at_risk_estimate),
    },
    {
      key: 'likely_to_expire_unsold_estimate',
      label: 'Est. unsold at expiry',
      render: (row) => row.likely_to_expire_unsold_estimate ? 'Yes' : 'No',
    },
    {
      key: 'snapshot_status',
      label: 'Record type',
      render: (row) => <SnapshotBadge status={row.snapshot_status} />,
    },
  ]

  const liveRiskColumns = [
    { key: 'product_name', label: 'Product' },
    {
      key: 'days_to_expiry',
      label: 'Days to expiry',
      render: (row) => formatNumber(row.days_to_expiry),
    },
    {
      key: 'risk_level',
      label: 'Rule-based risk',
      render: (row) => (
        <span className={`badge risk-${row.risk_level.toLowerCase()}`}>
          {row.risk_level}
        </span>
      ),
    },
    {
      key: 'quantity_at_risk',
      label: 'Units at risk',
      render: (row) => row.quantity_at_risk == null
        ? 'Demand needed'
        : formatNumber(row.quantity_at_risk),
    },
    {
      key: 'likely_to_expire_unsold',
      label: 'Unsold before expiry',
      render: (row) => row.likely_to_expire_unsold == null
        ? 'Demand needed'
        : row.likely_to_expire_unsold ? 'Possible' : 'Not indicated',
    },
    {
      key: 'recommended_discount_pct',
      label: 'Suggested discount',
      render: (row) => row.recommended_discount_pct == null
        ? 'Not available'
        : `${row.recommended_discount_pct}%`,
    },
  ]

  const renderLiveInventoryRisk = (maxRows = 100) => (
    <section className="panel">
      <SectionHeading
        eyebrow="LIVE SQLITE STOCK"
        title="Expiry and discount guidance"
        description={`${liveRecommendations.length} live items; ${highRiskLiveItems} high-risk and ${formatNumber(liveUnitsAtRisk)} estimated units at risk. Rule-based estimates use user-entered daily demand, not trained-model predictions.`}
      />
      <p className="data-note">
        At-risk units estimate quantity remaining after expected demand before expiry.
        Expired stock is never given a sale discount; missing demand leaves surplus
        unknown. Discount tiers do not model price elasticity or margin.
      </p>
      <DataTable
        columns={liveRiskColumns}
        emptyMessage="No live inventory items yet. Add stock on the Inventory page to see expiry and discount guidance."
        maxRows={maxRows}
        rowKey="item_id"
        rows={liveRecommendations}
      />
    </section>
  )

  const renderRecommendations = () => (
    <section className="panel">
      <SectionHeading
        eyebrow="SIMULATED SCENARIOS"
        title="Discount recommendations"
        description="Estimated outcomes from the discount simulation, not confirmed real-world sales."
      />
      <div className="table-controls">
        <label className="search-field">
          <span className="sr-only">Search recommendations</span>
          <span aria-hidden="true">⌕</span>
          <input
            onChange={(event) => setRecommendationSearch(event.target.value)}
            placeholder="Search product or batch"
            value={recommendationSearch}
          />
        </label>
        <label className="filter-field">
          <span>Discount</span>
          <select
            onChange={(event) => setDiscountFilter(event.target.value)}
            value={discountFilter}
          >
            <option value="all">All discounts</option>
            {[...new Set(recommendations.map((row) => Number(row.recommended_discount_pct)))]
              .sort((a, b) => a - b)
              .map((discount) => (
                <option key={discount} value={discount}>{discount}%</option>
              ))}
          </select>
        </label>
      </div>
      <DataTable
        columns={recommendationColumns}
        emptyMessage="No recommendations match these filters."
        rowKey="batch_id"
        rows={filteredRecommendations}
      />
    </section>
  )

  const renderInventory = () => (
    <InventoryManager
      onInventoryChanged={refreshData}
      refreshToken={inventoryRefreshToken}
    />
  )

  const renderExpiryRisk = () => (
    <>
      {renderLiveInventoryRisk()}
      <section className="panel">
        <SectionHeading
          eyebrow="SOURCE-DATA ANALYSIS"
          title="Expiry risk overview"
          description={`Source labels and rule-based snapshot estimates; the latest available snapshot is ${data?.expiryRisk?.latest_available_snapshot_date || '—'}.`}
        />
        {expiryRisk?.note && <p className="data-note">{expiryRisk.note}</p>}
        <ExpiryRiskChart
          riskCounts={expiryRisk?.summary?.risk_label_counts}
          snapshotCounts={expiryRisk?.summary?.snapshot_status_counts}
        />
      </section>
      <section className="panel">
        <SectionHeading
          eyebrow="BATCH DETAILS"
          title="Expiry records"
          description="Historical, latest, and future-dated records are explicitly identified."
        />
        <DataTable
          columns={expiryColumns}
          emptyMessage="No expiry-risk records are available."
          rowKey="batch_id"
          rows={expiryRisk?.records || []}
        />
      </section>
    </>
  )

  const renderDashboard = () => (
    <>
      <section className="welcome-panel">
        <div>
          <p className="eyebrow">WASTE LESS, PLAN BETTER</p>
          <h2>Make every batch count.</h2>
          <p>
            A snapshot of your inventory data, expiry labels, and simulated
            discount scenarios.
          </p>
        </div>
        <div className="welcome-mark" aria-hidden="true">↗</div>
      </section>

      <section className="metric-grid" aria-label="Inventory summary">
        <MetricCard
          icon="▦"
          label="Inventory batches"
          note="Snapshot records"
          value={formatNumber(inventory.length)}
        />
        <MetricCard
          icon="◇"
          label="Products"
          note="Unique product IDs"
          tone="mint"
          value={formatNumber(productCount)}
        />
        <MetricCard
          icon="↘"
          label="Estimated unsold units"
          note="Simulation estimate"
          tone="amber"
          value={formatNumber(unsoldUnits)}
        />
        <MetricCard
          icon="%"
          label="Average recommended discount"
          note="Simulation scenarios"
          tone="blue"
          value={averageDiscount === null ? '—' : `${formatNumber(averageDiscount)}%`}
        />
      </section>

      {renderLiveInventoryRisk(8)}

      <div className="content-grid">
        <section className="panel chart-panel">
          <SectionHeading
            eyebrow="EXPIRY MONITOR"
            title="Expiry-risk data"
            description="Source labels and snapshot coverage"
            actions={
              <button
                className="text-button"
                onClick={() => setPage('expiry-risk')}
                type="button"
              >
                View analysis <span aria-hidden="true">→</span>
              </button>
            }
          />
          {expiryRisk?.note && <p className="data-note compact">{expiryRisk.note}</p>}
          <ExpiryRiskChart
            riskCounts={expiryRisk?.summary?.risk_label_counts}
            snapshotCounts={expiryRisk?.summary?.snapshot_status_counts}
          />
        </section>
        <section className="panel snapshot-panel">
          <p className="eyebrow">DATA FRESHNESS</p>
          <h3>Snapshot, not live stock</h3>
          <p>
            Latest available snapshot:{' '}
            <strong>{data?.inventory?.latest_available_snapshot_date || '—'}</strong>
          </p>
          {futureSnapshots > 0 && (
            <p className="future-warning">
              {futureSnapshots.toLocaleString()} rows have snapshot dates after{' '}
              {data?.inventory?.current_date || 'today'} and are marked future-dated.
            </p>
          )}
          <p className="updated-note">
            Dashboard refreshed {lastUpdated ? lastUpdated.toLocaleTimeString() : '—'}
          </p>
        </section>
      </div>

      <section className="panel">
        <SectionHeading
          eyebrow="LATEST SCENARIOS"
          title="Discount recommendations"
          description="All values are simulated estimates."
          actions={
            <button
              className="text-button"
              onClick={() => setPage('discount-recommendations')}
              type="button"
            >
              View all <span aria-hidden="true">→</span>
            </button>
          }
        />
        <DataTable
          columns={recommendationColumns.slice(0, 6)}
          emptyMessage="No recommendation data is available."
          maxRows={8}
          rowKey="batch_id"
          rows={recommendationsWithProduct}
        />
      </section>
      <section className="panel">
        <SectionHeading
          eyebrow="SAVED MODEL VALIDATION"
          title="Demand model performance"
          description="Historical held-out evaluation metrics for the existing saved model; not live or future sales predictions."
          actions={forecastError && !forecastSummary && (
            <button
              className="secondary-button"
              onClick={refreshForecastSummary}
              type="button"
            >
              Retry
            </button>
          )}
        />
        {forecastSummary ? (
          <>
            <div className="forecast-metric-grid">
              <article className="forecast-metric">
                <span>Model</span>
                <strong>{forecastSummary.model.name}</strong>
                <small>Existing saved artifact</small>
              </article>
              <article className="forecast-metric">
                <span>MAE</span>
                <strong>{formatMetric(forecastSummary.evaluation.metrics.mae)}</strong>
                <small>Held-out error, units</small>
              </article>
              <article className="forecast-metric">
                <span>RMSE</span>
                <strong>{formatMetric(forecastSummary.evaluation.metrics.rmse)}</strong>
                <small>Held-out error, units</small>
              </article>
              <article className="forecast-metric">
                <span>R²</span>
                <strong>{formatMetric(forecastSummary.evaluation.metrics.r2, 3)}</strong>
                <small>Chronological held-out score</small>
              </article>
            </div>
            <div className="forecast-disclosure">
              <strong>Future forecasts are unavailable.</strong>
              <span>{forecastSummary.future_forecast.reason}</span>
            </div>
          </>
        ) : forecastError ? (
          <div className="error-banner" role="alert">{forecastError}</div>
        ) : (
          <p className="data-note">Loading saved-model evaluation…</p>
        )}
      </section>
    </>
  )

  const renderDemandForecasting = () => {
    if (forecastLoading && (!forecastSummary || !productForecast)) {
      return (
        <div className="loading-panel" role="status">
          <span className="spinner" />
          <strong>Loading saved model results…</strong>
          <span>Preparing the verified chronological evaluation</span>
        </div>
      )
    }

    if (forecastError && (!forecastSummary || !productForecast)) {
      return (
        <section className="empty-panel" role="alert">
          <h2>Demand forecasts could not be loaded</h2>
          <p>{forecastError}</p>
          <button
            className="secondary-button"
            onClick={() => refreshForecast()}
            type="button"
          >
            Try again
          </button>
        </section>
      )
    }

    if (!forecastSummary || !productForecast) {
      return (
        <section className="empty-panel">
          <h2>No forecast evaluation is available</h2>
          <p>The API did not return usable saved-model results.</p>
        </section>
      )
    }

    const historicalPoints = productForecast.historical_sales.map((point) => ({
      date: point.date,
      value: point.actual_units,
    }))
    const actualHeldOutPoints = productForecast.held_out_predictions.map((point) => ({
      date: point.date,
      value: point.actual_units,
    }))
    const predictedPoints = productForecast.held_out_predictions.map((point) => ({
      date: point.date,
      value: point.predicted_units,
    }))
    const predictionColumns = [
      { key: 'date', label: 'Date' },
      {
        key: 'actual_units',
        label: 'Actual units',
        render: (row) => formatNumber(row.actual_units),
      },
      {
        key: 'predicted_units',
        label: 'Model prediction',
        render: (row) => formatNumber(row.predicted_units),
      },
      {
        key: 'error',
        label: 'Prediction error',
        render: (row) => formatNumber(row.predicted_units - row.actual_units),
      },
    ]

    return (
      <>
        <section className="panel forecast-intro">
          <div className="forecast-intro-copy">
            <p className="eyebrow">SAVED RANDOM FOREST MODEL</p>
            <h2>Historical demand and held-out predictions</h2>
            <p>
              Actual sales and rolling one-day-ahead predictions from the existing
              model. These are evaluation results, not future sales commitments.
            </p>
          </div>
          <label className="forecast-product-select">
            <span>Product</span>
            <select
              disabled={forecastLoading}
              onChange={(event) => {
                forecastProductIdRef.current = event.target.value
                setForecastProductId(event.target.value)
                setProductForecast(null)
                refreshForecast(event.target.value)
              }}
              value={forecastProductId}
            >
              {forecastProducts.map((product) => (
                <option key={product.product_id} value={product.product_id}>
                  {product.product_name}
                </option>
              ))}
            </select>
          </label>
        </section>

        {forecastError && (
          <div className="error-banner" role="alert">
            <strong>Refresh failed</strong>
            <span>{forecastError}</span>
            <button onClick={() => refreshForecast()} type="button">Try again</button>
          </div>
        )}

        <section className="forecast-metric-grid">
          <article className="forecast-metric">
            <span>MAE</span>
            <strong>{formatMetric(forecastSummary.evaluation.metrics.mae)}</strong>
            <small>Average absolute error, units</small>
          </article>
          <article className="forecast-metric">
            <span>RMSE</span>
            <strong>{formatMetric(forecastSummary.evaluation.metrics.rmse)}</strong>
            <small>Root mean squared error, units</small>
          </article>
          <article className="forecast-metric">
            <span>R²</span>
            <strong>{formatMetric(forecastSummary.evaluation.metrics.r2, 3)}</strong>
            <small>Held-out evaluation score</small>
          </article>
          <article className="forecast-metric">
            <span>Evaluation window</span>
            <strong>
              {forecastSummary.evaluation.test_start_date}
              <span className="date-range-divider">—</span>
              {forecastSummary.evaluation.test_end_date}
            </strong>
            <small>
              {forecastSummary.evaluation.test_rows.toLocaleString()} pooled product-days
            </small>
          </article>
        </section>

        <div className="forecast-disclosure">
          <strong>Future forecasts are currently unavailable.</strong>
          <span>{forecastSummary.future_forecast.reason}</span>
          <span>
            Evaluation split: {forecastSummary.evaluation.method}; predictions use
            previous observed sales on each test date.
          </span>
        </div>

        <section className="panel">
          <SectionHeading
            eyebrow="OBSERVED SALES"
            title={`${productForecast.product.product_name} — historical demand`}
            description={`${forecastSummary.data.first_observation_date} through ${forecastSummary.data.last_observation_date}; data source ${forecastSummary.data.source}.`}
          />
          <ForecastLineChart
            description="Recorded daily units sold from the CSV."
            emptyMessage="No historical sales observations are available."
            lines={[{ name: 'Actual sales', className: 'actual', points: historicalPoints }]}
            title="Historical sales"
          />
        </section>

        <section className="panel">
          <SectionHeading
            eyebrow="HELD-OUT MODEL RESULTS"
            title="Actual versus predicted sales"
            description={`One-day-ahead test rows for ${productForecast.product.product_name}; the model uses observed prior-day sales, including within the test window.`}
          />
          <ForecastLineChart
            description="Predictions start at the chronological test cutoff; actuals and model output are shown for the same dates."
            emptyMessage="No held-out predictions are available for this product."
            lines={[
              { name: 'Actual units', className: 'actual', points: actualHeldOutPoints },
              { name: 'Model prediction', className: 'predicted', points: predictedPoints },
            ]}
            title="Held-out actual versus predicted sales"
          />
        </section>

        <section className="panel">
          <SectionHeading
            eyebrow="PREDICTION DETAILS"
            title="Held-out one-day-ahead results"
            description="These are predictions for historical test dates, not a future forecast."
          />
          <DataTable
            columns={predictionColumns}
            emptyMessage="No held-out prediction dates are available."
            maxRows={100}
            rowKey="date"
            rows={productForecast.held_out_predictions}
          />
        </section>
      </>
    )
  }

  let pageContent
  if (page === 'inventory') pageContent = renderInventory()
  else if (page === 'expiry-risk') pageContent = renderExpiryRisk()
  else if (page === 'demand-forecasting') pageContent = renderDemandForecasting()
  else if (page === 'discount-recommendations') pageContent = renderRecommendations()
  else pageContent = renderDashboard()

  if (!accessToken || !user) {
    return (
      <AuthScreen
        error={authError}
        loading={authLoading}
        notice={authNotice}
        onAuthenticate={authenticate}
      />
    )
  }

  return (
    <div className="app-shell">
      <Sidebar activePage={page} onNavigate={setPage} />
      <main className="main-content">
        <header className="topbar">
          <div className="mobile-brand">
            <span className="brand-mark" aria-hidden="true">W</span>
            <strong>WasteWise</strong>
          </div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span aria-hidden="true">/</span>
            <strong>{pageTitles[page]}</strong>
          </div>
          <div className="topbar-actions">
            <span className={`api-status${error ? ' offline' : data ? ' online' : ''}`}>
              <span className="status-dot" />
              {error ? 'API unavailable' : data ? 'API connected' : 'Connecting'}
            </span>
            <div className="user-profile">
              <span className="profile-avatar" aria-hidden="true">
                {user.email.charAt(0).toUpperCase()}
              </span>
              <span className="profile-email">{user.email}</span>
              <button
                className="logout-button"
                disabled={authLoading}
                onClick={logout}
                type="button"
              >
                {authLoading ? 'Signing out…' : 'Sign out'}
              </button>
            </div>
            <button
              className="refresh-button"
              disabled={loading || forecastLoading}
              onClick={refreshCurrentPage}
              type="button"
            >
              <span aria-hidden="true">{loading || forecastLoading ? '…' : '↻'}</span>
              <span>{loading || forecastLoading ? 'Refreshing' : 'Refresh data'}</span>
            </button>
          </div>
        </header>

        <div className="page-content">
          <div className="page-title-row">
            <div>
              <p className="eyebrow">WASTEWISE AI / OPERATIONS</p>
              <h1>{pageTitles[page]}</h1>
            </div>
            <span className="data-source-tag">
              <span className="status-dot" />
              API / SQLite + CSV
            </span>
          </div>

          {error && (
            <div className="error-banner" role="alert">
              <strong>Could not load dashboard data</strong>
              <span>{error}</span>
              <button onClick={refreshData} type="button">Try again</button>
            </div>
          )}

          {loading && !data ? (
            <div className="loading-panel" role="status">
              <span className="spinner" />
              <strong>Loading WasteWise data…</strong>
              <span>Connecting to the FastAPI service</span>
            </div>
          ) : !data && error ? (
            <div className="empty-panel">
              <h2>Dashboard data is unavailable</h2>
              <p>Check the API service connection and configuration, then refresh.</p>
            </div>
          ) : (
            pageContent
          )}

          <footer className="page-footer">
            <span>WasteWise-AI</span>
            <span>Model outputs, simulations, and rules are labeled by source.</span>
          </footer>
        </div>
      </main>
    </div>
  )
}

export default App
