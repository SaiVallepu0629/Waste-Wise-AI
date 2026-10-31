import { useCallback, useEffect, useState } from 'react'
import DataTable from './DataTable'
import {
  createInventoryItem,
  deleteInventoryItem,
  fetchInventoryItems,
  fetchRuleBasedRecommendations,
  updateInventoryItem,
} from '../services/api'

const PAGE_SIZE = 25
const today = new Date().toISOString().slice(0, 10)

function emptyForm() {
  return {
    product_name: '',
    category: '',
    quantity: '0',
    price: '0',
    stock_date: today,
    expiry_date: today,
    estimated_daily_demand: '',
  }
}

function formFromItem(item) {
  return {
    product_name: item.product_name,
    category: item.category,
    quantity: String(item.quantity),
    price: String(item.price),
    stock_date: item.stock_date,
    expiry_date: item.expiry_date,
    estimated_daily_demand:
      item.estimated_daily_demand == null
        ? ''
        : String(item.estimated_daily_demand),
  }
}

function formatValue(value, digits = 1) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(digits) : '—'
}

function statusLabel(status) {
  return {
    in_stock: 'In stock',
    low_stock: 'Low stock',
    expiring_soon: 'Expiring soon',
    expired: 'Expired',
    out_of_stock: 'Out of stock',
  }[status] || status
}

export default function InventoryManager({
  refreshToken = 0,
  onInventoryChanged,
}) {
  const [items, setItems] = useState([])
  const [recommendations, setRecommendations] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (pageIndex = page, searchTerm = search) => {
    setLoading(true)
    setError('')
    try {
      const [inventory, nextRecommendations] = await Promise.all([
        fetchInventoryItems({
          limit: PAGE_SIZE,
          offset: pageIndex * PAGE_SIZE,
          search: searchTerm,
        }),
        fetchRuleBasedRecommendations(),
      ])
      setItems(inventory.items)
      setTotal(inventory.total)
      setRecommendations(nextRecommendations)
      return inventory.total
    } catch (requestError) {
      setError(requestError.message || 'Inventory could not be loaded.')
      return null
    } finally {
      setLoading(false)
    }
  }, [page, search])

  useEffect(() => {
    const timerId = window.setTimeout(() => load(), 0)
    return () => window.clearTimeout(timerId)
  }, [load, refreshToken])

  const updateForm = (event) => {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  const submitForm = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    const payload = {
      ...form,
      quantity: Number(form.quantity),
      price: Number(form.price),
      estimated_daily_demand:
        form.estimated_daily_demand === ''
          ? null
          : Number(form.estimated_daily_demand),
    }

    try {
      if (editingId === null) {
        await createInventoryItem(payload)
        setNotice('Inventory item added.')
      } else {
        await updateInventoryItem(editingId, payload)
        setNotice('Inventory item updated.')
      }
      setForm(emptyForm())
      setEditingId(null)
      setPage(0)
      await load(0)
      onInventoryChanged()
    } catch (requestError) {
      setError(requestError.message || 'Inventory could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const beginEdit = (item) => {
    setEditingId(item.id)
    setForm(formFromItem(item))
    setNotice('')
    setError('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setForm(emptyForm())
  }

  const removeItem = async (item) => {
    if (!window.confirm(`Delete ${item.product_name} from live inventory?`)) return
    setError('')
    setNotice('')
    try {
      await deleteInventoryItem(item.id)
      setNotice('Inventory item deleted.')
      const nextTotal = await load(page)
      if (nextTotal !== null && nextTotal <= page * PAGE_SIZE && page > 0) {
        setPage((current) => current - 1)
      }
      onInventoryChanged()
    } catch (requestError) {
      setError(requestError.message || 'Inventory item could not be deleted.')
    }
  }

  const columns = [
    { key: 'product_name', label: 'Product' },
    { key: 'category', label: 'Category' },
    { key: 'quantity', label: 'Units' },
    { key: 'price', label: 'Unit price', render: (item) => formatValue(item.price, 2) },
    { key: 'stock_date', label: 'Stock date' },
    { key: 'expiry_date', label: 'Expiry date' },
    {
      key: 'inventory_status',
      label: 'Status',
      render: (item) => (
        <span className={`badge ${item.inventory_status}`}>
          {statusLabel(item.inventory_status)}
        </span>
      ),
    },
    {
      key: 'source_type',
      label: 'Record',
      render: (item) => item.source_type === 'manual'
        ? <span className="badge live-record">Live</span>
        : <span className="badge historical_snapshot">CSV snapshot</span>,
    },
    {
      key: 'actions',
      label: 'Actions',
      render: (item) => item.source_type === 'manual' ? (
        <div className="inventory-actions">
          <button className="text-button" onClick={() => beginEdit(item)} type="button">
            Edit
          </button>
          <button className="text-button danger-button" onClick={() => removeItem(item)} type="button">
            Delete
          </button>
        </div>
      ) : <span className="read-only-label">Read only</span>,
    },
  ]

  const recommendationColumns = [
    { key: 'product_name', label: 'Product' },
    { key: 'days_to_expiry', label: 'Days to expiry' },
    {
      key: 'risk_level',
      label: 'Rule-based risk',
      render: (item) => (
        <span className={`badge risk-${item.risk_level.toLowerCase()}`}>
          {item.risk_level} ({item.rule_based_risk_score}/100)
        </span>
      ),
    },
    {
      key: 'quantity_at_risk',
      label: 'Units at risk',
      render: (item) => formatValue(item.quantity_at_risk),
    },
    {
      key: 'likely_to_expire_unsold',
      label: 'Unsold before expiry',
      render: (item) => item.likely_to_expire_unsold == null
        ? 'Demand needed'
        : item.likely_to_expire_unsold ? 'Possible' : 'Not indicated',
    },
    {
      key: 'recommended_discount_pct',
      label: 'Suggested discount',
      render: (item) => item.recommended_discount_pct == null
        ? 'Demand needed'
        : `${item.recommended_discount_pct}%`,
    },
    { key: 'basis', label: 'Basis' },
  ]

  const attentionCount = items.filter((item) =>
    ['low_stock', 'expiring_soon', 'expired', 'out_of_stock'].includes(
      item.inventory_status,
    ),
  ).length
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <section className="inventory-summary" aria-label="Inventory summary">
        <article className="inventory-summary-card">
          <span>Database records</span>
          <strong>{total.toLocaleString()}</strong>
          <small>Live items and preserved CSV snapshots</small>
        </article>
        <article className="inventory-summary-card attention">
          <span>Needs attention on this page</span>
          <strong>{attentionCount}</strong>
          <small>Rule-based stock and expiry status</small>
        </article>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SQLITE INVENTORY</p>
            <h2>Inventory management</h2>
            <p className="section-description">
              Manually managed stock is editable. Imported CSV snapshots remain
              intact and read-only; they are not treated as live inventory.
            </p>
          </div>
          <button
            className="primary-button"
            onClick={() => {
              cancelEdit()
              setNotice('')
              setError('')
            }}
            type="button"
          >
            + Add item
          </button>
        </div>

        {(error || notice) && (
          <div className={error ? 'error-banner' : 'success-banner'} role={error ? 'alert' : 'status'}>
            <strong>{error ? 'Action needed' : 'Saved'}</strong>
            <span>{error || notice}</span>
            {error && <button onClick={() => load()} type="button">Try again</button>}
          </div>
        )}

        <form className="inventory-form" onSubmit={submitForm}>
          <div className="inventory-form-heading">
            <h3>{editingId === null ? 'Add inventory item' : 'Edit inventory item'}</h3>
            <p>Expiry status is calculated from dates; demand is an optional user-entered estimate.</p>
          </div>
          <div className="inventory-form-grid">
            <label>
              Product name
              <input
                autoComplete="off"
                maxLength={160}
                name="product_name"
                onChange={updateForm}
                required
                value={form.product_name}
              />
            </label>
            <label>
              Category
              <input
                maxLength={100}
                name="category"
                onChange={updateForm}
                required
                value={form.category}
              />
            </label>
            <label>
              Quantity
              <input
                min="0"
                name="quantity"
                onChange={updateForm}
                required
                type="number"
                value={form.quantity}
              />
            </label>
            <label>
              Unit price
              <input
                min="0"
                name="price"
                onChange={updateForm}
                required
                step="0.01"
                type="number"
                value={form.price}
              />
            </label>
            <label>
              Stock date
              <input
                name="stock_date"
                onChange={updateForm}
                required
                type="date"
                value={form.stock_date}
              />
            </label>
            <label>
              Expiry date
              <input
                min={form.stock_date}
                name="expiry_date"
                onChange={updateForm}
                required
                type="date"
                value={form.expiry_date}
              />
            </label>
            <label>
              Expected demand (units/day, optional)
              <input
                min="0"
                name="estimated_daily_demand"
                onChange={updateForm}
                placeholder="Needed for a rule-based discount"
                step="0.1"
                type="number"
                value={form.estimated_daily_demand}
              />
            </label>
          </div>
          <div className="inventory-form-actions">
            {editingId !== null && (
              <button className="secondary-button" onClick={cancelEdit} type="button">
                Cancel
              </button>
            )}
            <button className="primary-button" disabled={saving} type="submit">
              {saving ? 'Saving…' : editingId === null ? 'Add inventory' : 'Save changes'}
            </button>
          </div>
        </form>

        <form
          className="inventory-search"
          onSubmit={(event) => {
            event.preventDefault()
            setPage(0)
            setSearch(searchDraft)
          }}
        >
          <label>
            Search inventory
            <input
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="Product or category"
              value={searchDraft}
            />
          </label>
          <button className="secondary-button" type="submit">Search</button>
          {search && (
            <button
              className="text-button"
              onClick={() => {
                setSearchDraft('')
                setSearch('')
                setPage(0)
              }}
              type="button"
            >
              Clear
            </button>
          )}
        </form>

        {loading && items.length === 0 ? (
          <div className="loading-panel compact-loading" role="status">
            <span className="spinner" />
            <strong>Loading inventory…</strong>
          </div>
        ) : (
          <DataTable
            columns={columns}
            emptyMessage={search ? 'No inventory items match this search.' : 'No inventory items yet. Add one above or import the CSV snapshots.'}
            maxRows={PAGE_SIZE}
            rowKey="id"
            rows={items}
          />
        )}

        <div className="inventory-pagination">
          <span>
            {total === 0
              ? 'No records'
              : `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, total)} of ${total.toLocaleString()}`}
          </span>
          <div>
            <button
              className="secondary-button"
              disabled={loading || page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              type="button"
            >
              Previous
            </button>
            <span>Page {page + 1} of {pageCount}</span>
            <button
              className="secondary-button"
              disabled={loading || page + 1 >= pageCount}
              onClick={() => setPage((current) => current + 1)}
              type="button"
            >
              Next
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">LIVE INVENTORY RULES</p>
            <h2>Expiry and discount guidance</h2>
            <p className="section-description">
              Rule-based estimates use live quantity, expiry date, and optional
              user-entered daily demand. They are not ML predictions.
            </p>
          </div>
        </div>
        <DataTable
          columns={recommendationColumns}
          emptyMessage="Add a live inventory item to see its rule-based risk and discount guidance."
          maxRows={100}
          rowKey="item_id"
          rows={recommendations}
        />
      </section>
    </>
  )
}
