import { Component, useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

// Last resort: a render crash shows this message instead of a blank page.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <main className="wrap">
          <h1>File pipeline</h1>
          <p className="banner bad">
            Something went wrong: {String(this.state.error.message || this.state.error)}
          </p>
        </main>
      )
    }
    return this.props.children
  }
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const MAX_UPLOAD_BYTES = 1024 * 1024

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  if (res.status === 204) return null
  return res.json()
}

function StatusPill({ status }) {
  const cls = status === 'PROCESSED' ? 'ok' : status === 'FAILED' ? 'bad' : 'wait'
  return <span className={`pill ${cls}`}>{status}</span>
}

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KiB`
}

function App() {
  const [health, setHealth] = useState(null)
  const [files, setFiles] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef(null)

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api('/health'))
    } catch {
      setHealth({ status: 'unreachable', emulator_reachable: false, account_id: null })
    }
  }, [])

  const refreshList = useCallback(async () => {
    try {
      setFiles(await api('/files'))
    } catch {
      /* health banner already shows the outage */
    }
  }, [])

  const refreshDetail = useCallback(
    async (id) => {
      if (!id) return
      try {
        setDetail(await api(`/files/${id}`))
      } catch (e) {
        setDetail({ fetchError: String(e) })
      }
    },
    [],
  )

  useEffect(() => {
    refreshHealth()
    refreshList()
    const t = setInterval(() => {
      refreshList()
      if (selectedId) refreshDetail(selectedId)
    }, 2500)
    return () => clearInterval(t)
  }, [selectedId, refreshHealth, refreshList, refreshDetail])

  useEffect(() => {
    setDetail(null)
    if (selectedId) refreshDetail(selectedId)
  }, [selectedId, refreshDetail])

  async function onUpload(e) {
    e.preventDefault()
    setError('')
    const file = fileInput.current?.files?.[0]
    if (!file) {
      setError('Choose a file first.')
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(`File is ${formatBytes(file.size)}; the limit is 1 MiB.`)
      return
    }
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const created = await api('/files', { method: 'POST', body: form })
      fileInput.current.value = ''
      setSelectedId(created.file_id)
      await refreshList()
    } catch (e) {
      setError(`Upload failed: ${e.message}`)
    } finally {
      setUploading(false)
    }
  }

  async function onDelete(id) {
    setError('')
    try {
      await api(`/files/${id}`, { method: 'DELETE' })
      if (selectedId === id) {
        setSelectedId(null)
        setDetail(null)
      }
      await refreshList()
    } catch (e) {
      setError(`Delete failed: ${e.message}`)
    }
  }

  const apiDown = !health || health.status !== 'ok' || !health.emulator_reachable

  return (
    <main className="wrap">
      <header>
        <h1>File pipeline</h1>
        <p className="sub">
          Upload → S3 + DynamoDB + SQS → worker → results. API:{' '}
          <code>{API_BASE}</code>
        </p>
        {health && (
          <p className={apiDown ? 'banner bad' : 'banner ok'}>
            {apiDown
              ? 'API or emulator unreachable — start them (see README) and this page recovers on its own.'
              : `API ok · emulator reachable · account ${health.account_id} · ${health.region}`}
          </p>
        )}
      </header>

      <section>
        <h2>Upload</h2>
        <form onSubmit={onUpload} className="row">
          <input type="file" ref={fileInput} aria-label="file to upload" />
          <button type="submit" disabled={uploading || apiDown}>
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
          <span className="hint">Max 1 MiB.</span>
        </form>
        {error && <p className="banner bad">{error}</p>}
      </section>

      <section>
        <h2>Files ({files.length})</h2>
        {files.length === 0 ? (
          <p className="hint">No files yet — upload one above.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Filename</th>
                <th>Status</th>
                <th>Size</th>
                <th>Words</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.file_id} className={f.file_id === selectedId ? 'sel' : ''}>
                  <td className="mono">{f.filename}</td>
                  <td><StatusPill status={f.status} /></td>
                  <td>{formatBytes(f.size_bytes)}</td>
                  <td>{f.word_count ?? '—'}</td>
                  <td className="actions">
                    <button type="button" onClick={() => setSelectedId(f.file_id)}>Details</button>
                    <a href={`${API_BASE}/files/${f.file_id}/download`}>Download</a>
                    <button type="button" className="danger" onClick={() => onDelete(f.file_id)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selectedId && (
        <section>
          <h2>Details</h2>
          {!detail ? (
            <p className="hint">Loading…</p>
          ) : detail.fetchError ? (
            <p className="banner bad">{detail.fetchError}</p>
          ) : (
            <dl className="detail">
              <dt>File id</dt><dd className="mono">{detail.file_id}</dd>
              <dt>Filename</dt><dd className="mono">{detail.filename}</dd>
              <dt>Status</dt><dd><StatusPill status={detail.status} /></dd>
              <dt>Size</dt><dd>{formatBytes(detail.size_bytes)} ({detail.size_bytes} bytes)</dd>
              <dt>Lines</dt><dd>{detail.line_count ?? '—'}</dd>
              <dt>Words</dt><dd>{detail.word_count ?? '—'}</dd>
              <dt>SHA-256</dt><dd className="mono small">{detail.sha256 ?? '—'}</dd>
              <dt>Content type</dt><dd>{detail.content_type}</dd>
              <dt>S3 key</dt><dd className="mono small">{detail.s3_key}</dd>
              <dt>Created</dt><dd>{detail.created_at}</dd>
              {detail.processed_at && (<><dt>Processed</dt><dd>{detail.processed_at}</dd></>)}
              {detail.status === 'FAILED' && (<><dt>Error</dt><dd className="mono small">{detail.error}</dd></>)}
            </dl>
          )}
        </section>
      )}
    </main>
  )
}

export default function AppWithBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
}
