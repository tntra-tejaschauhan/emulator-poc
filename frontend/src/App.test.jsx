import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App.jsx'

const HEALTH = {
  status: 'ok',
  emulator_reachable: true,
  account_id: '000000000000',
  region: 'us-east-1',
}

const ITEM = {
  file_id: 'abc123',
  filename: 'sample.txt',
  content_type: 'text/plain',
  size_bytes: 11,
  s3_key: 'uploads/abc123/sample.txt',
  status: 'PROCESSED',
  created_at: '2026-01-01T00:00:00+00:00',
  processed_at: '2026-01-01T00:00:01+00:00',
  line_count: 1,
  word_count: 2,
  sha256: 'deadbeef',
}

const PENDING_ITEM = {
  file_id: 'new1',
  filename: 'fresh.txt',
  content_type: 'text/plain',
  size_bytes: 5,
  s3_key: 'uploads/new1/fresh.txt',
  status: 'PENDING',
  created_at: '2026-01-01T00:00:00+00:00',
}

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    json: async () => data,
    text: async () => JSON.stringify(data),
  }
}

function mockFetch(handler) {
  return vi.fn(async (url, options = {}) => handler(String(url), options))
}

const routes = {
  '/health': () => jsonResponse(HEALTH),
  '/files': (options) =>
    options.method === 'POST'
      ? jsonResponse({ file_id: 'new1', status: 'PENDING' }, 201)
      : jsonResponse([ITEM]),
  '/files/abc123': () => jsonResponse(ITEM),
  '/files/new1': () => jsonResponse(PENDING_ITEM),
}

function standardFetch() {
  return mockFetch((url, options) => {
    const path = url.replace('http://127.0.0.1:8000', '')
    const handler = routes[path]
    if (!handler) throw new Error(`unexpected request: ${options.method || 'GET'} ${path}`)
    return handler(options)
  })
}

beforeEach(() => {
  global.fetch = standardFetch()
})

afterEach(() => {
  cleanup() // auto-cleanup needs globals; without them, unmount explicitly
  vi.restoreAllMocks()
})

test('details click renders the file detail instead of crashing', async () => {
  render(<App />)
  expect(await screen.findByText('sample.txt')).toBeTruthy()
  fireEvent.click(screen.getByText('Details'))
  expect(await screen.findByText('deadbeef')).toBeTruthy()
  expect(screen.getByText('abc123')).toBeTruthy()
  // Page still intact after the interaction (no white-screen unmount).
  expect(screen.getByText('File pipeline')).toBeTruthy()
})

test('upload selects the new file and shows its pending detail', async () => {
  render(<App />)
  expect(await screen.findByText('sample.txt')).toBeTruthy()
  const input = screen.getByLabelText('file to upload')
  fireEvent.change(input, {
    target: { files: [new File(['fresh'], 'fresh.txt', { type: 'text/plain' })] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
  expect(await screen.findByText('fresh.txt', { selector: 'dd' })).toBeTruthy()
  expect(screen.getByText('File pipeline')).toBeTruthy()
})

test('oversize file is rejected with a message, page intact', async () => {
  render(<App />)
  expect(await screen.findByText('sample.txt')).toBeTruthy()
  const input = screen.getByLabelText('file to upload')
  const big = new File(['x'.repeat(1024 * 1024 + 1)], 'big.bin')
  fireEvent.change(input, { target: { files: [big] } })
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }))
  expect(await screen.findByText(/limit is 1 MiB/)).toBeTruthy()
})

test('a render crash shows an error message, not a blank page', async () => {
  global.fetch = mockFetch((url) => {
    const path = String(url).replace('http://127.0.0.1:8000', '')
    if (path === '/health') return jsonResponse(HEALTH)
    return jsonResponse(null) // malformed: list render throws on .length/.map
  })
  render(<App />)
  expect(await screen.findByText(/Something went wrong/)).toBeTruthy()
})
