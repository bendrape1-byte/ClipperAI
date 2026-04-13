import { useEffect, useRef, useState } from 'react'
import {
  Clip, BrollSuggestion,
  approveClip, rejectClip,
  produceClip, getClip,
  getBroll, swapBroll, rejectBroll,
} from '../api'

interface Props {
  clip: Clip
  onRefresh: () => void
}

type Aspect = '16:9' | '9:16'

function fmt(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function scoreClass(score: number): string {
  if (score >= 8) return 'score-green'
  if (score >= 5) return 'score-yellow'
  return 'score-red'
}

const PRODUCTION_STEPS = [
  { key: 'burn_captions', label: 'Burning captions' },
  { key: 'suggest_broll', label: 'Finding B-roll footage' },
  { key: 'approve_broll', label: 'Processing footage' },
  { key: 'composite_16',  label: 'Compositing 16:9' },
  { key: 'composite_9',   label: 'Compositing 9:16' },
]

function ProductionProgress({ step }: { step: string | null }) {
  const idx = PRODUCTION_STEPS.findIndex(s => s.key === step)
  const current = PRODUCTION_STEPS[idx] ?? PRODUCTION_STEPS[0]
  const pct = idx < 0 ? 5 : Math.round(((idx + 1) / PRODUCTION_STEPS.length) * 100)

  return (
    <div className="produce-progress">
      <div className="produce-progress-bar">
        <div className="produce-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="produce-progress-label">
        <span className="spinner" />{current.label}…
      </span>
    </div>
  )
}

export default function ClipCard({ clip: initialClip, onRefresh }: Props) {
  const [clip, setClip] = useState<Clip>(initialClip)
  const [aspect, setAspect] = useState<Aspect>('16:9')
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [brollOpen, setBrollOpen] = useState(false)
  const [brollSuggestions, setBrollSuggestions] = useState<BrollSuggestion[]>([])
  const [swapId, setSwapId] = useState<number | null>(null)
  const [swapQuery, setSwapQuery] = useState('')
  const [swapping, setSwapping] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Sync with parent poll when not in an active produce cycle
  useEffect(() => {
    if (clip.production_status !== 'producing') {
      setClip(initialClip)
    }
  }, [initialClip])

  // Poll every 3s while producing
  useEffect(() => {
    if (clip.production_status === 'producing' && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const fresh = await getClip(clip.id)
          setClip(fresh)
          if (fresh.production_status !== 'producing') {
            clearInterval(pollRef.current!)
            pollRef.current = null
            onRefresh()
          }
        } catch { /* ignore */ }
      }, 3000)
    }
    return () => {
      if (pollRef.current && clip.production_status !== 'producing') {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [clip.production_status])

  useEffect(() => {
    if (brollOpen) {
      getBroll(clip.id).then(setBrollSuggestions).catch(() => {})
    }
  }, [brollOpen, clip.id])

  const isProducing = clip.production_status === 'producing'
  const hasProduced = !!(clip.produced_path)
  const has9 = !!(clip.vertical_path || clip.vertical_produced_path)

  const videoSrc = (() => {
    const useV = aspect === '9:16' && has9
    if (useV) {
      if (hasProduced && clip.vertical_produced_path) return `/api/clips/${clip.id}/download-vertical-produced`
      return `/api/clips/${clip.id}/download-vertical`
    }
    if (hasProduced) return `/api/clips/${clip.id}/download-produced`
    return `/api/clips/${clip.id}/download`
  })()

  const versionLabel = (() => {
    const useV = aspect === '9:16' && has9
    if (useV) return hasProduced && clip.vertical_produced_path ? 'Produced' : 'Raw'
    return hasProduced ? 'Produced' : 'Raw'
  })()

  const duration = clip.end_sec - clip.start_sec
  const isApproved = clip.status === 'approved'
  const isRejected = clip.status === 'rejected'

  const handleApprove = async () => {
    const next = isApproved ? 'ready' : 'approved'
    setClip(c => ({ ...c, status: next }))
    if (next === 'approved') await approveClip(clip.id).catch(() => {})
    else await rejectClip(clip.id).catch(() => {}) // toggle off = reject
    onRefresh()
  }

  const handleReject = async () => {
    const next = isRejected ? 'ready' : 'rejected'
    setClip(c => ({ ...c, status: next }))
    if (next === 'rejected') await rejectClip(clip.id).catch(() => {})
    else await approveClip(clip.id).catch(() => {}) // toggle off = approve
    onRefresh()
  }

  const handleProduce = async () => {
    try {
      await produceClip(clip.id)
      setClip(c => ({ ...c, production_status: 'producing' }))
    } catch { /* ignore */ }
  }

  const handleSwap = async (suggestionId: number) => {
    if (!swapQuery.trim()) return
    setSwapping(true)
    try {
      const updated = await swapBroll(suggestionId, swapQuery.trim())
      setBrollSuggestions(prev => prev.map(s => s.id === suggestionId ? updated : s))
      setSwapId(null)
      setSwapQuery('')
    } catch { /* ignore */ }
    setSwapping(false)
  }

  const handleRejectBroll = async (suggestionId: number) => {
    await rejectBroll(suggestionId).catch(() => {})
    setBrollSuggestions(prev =>
      prev.map(s => s.id === suggestionId ? { ...s, status: 'rejected' } : s)
    )
  }

  if (clip.render_status !== 'ready') {
    return (
      <section className="clip-section clip-placeholder">
        <div className="clip-placeholder-inner">
          <div className="clip-placeholder-meta">
            <span className={`score-large ${scoreClass(clip.score)}`}>{clip.score}</span>
            <span className="clip-duration">{fmt(duration)}</span>
          </div>
          <h2 className="clip-title-large">{clip.title}</h2>
          <div className="clip-placeholder-status">
            <span className="spinner" />
            <span>Rendering…</span>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className={`clip-section clip-fadein${isRejected ? ' clip-rejected' : ''}`}>

      {/* ── Video player ─────────────────────────────────────── */}
      <div className="clip-hero">
        <div className="clip-hero-bar">
          <div className="aspect-toggles">
            <button
              className={`btn-xs${aspect === '16:9' ? ' active' : ''}`}
              onClick={() => setAspect('16:9')}
            >16:9</button>
            {has9 && (
              <button
                className={`btn-xs${aspect === '9:16' ? ' active' : ''}`}
                onClick={() => setAspect('9:16')}
              >9:16</button>
            )}
          </div>
          <span className="version-label">{versionLabel}</span>
        </div>
        <div className={`clip-player-wrap${aspect === '9:16' ? ' vertical' : ''}`}>
          <video
            key={videoSrc}
            className="clip-player"
            src={videoSrc}
            controls
            preload="metadata"
          />
        </div>
      </div>

      {/* ── Clip info ────────────────────────────────────────── */}
      <div className="clip-info">
        <div className="clip-info-row">
          <span className={`score-large ${scoreClass(clip.score)}`}>{clip.score}</span>
          <span className="clip-duration">{fmt(duration)}</span>
        </div>
        <h2 className="clip-title-large">{clip.title}</h2>
        {clip.hook && <p className="clip-hook-large">"{clip.hook}"</p>}
        {clip.reasoning && <p className="clip-reasoning-large">{clip.reasoning}</p>}
      </div>

      {/* ── Actions ──────────────────────────────────────────── */}
      <div className="clip-actions-row">

        <button
          className="btn btn-primary produce-btn"
          onClick={handleProduce}
          disabled={isProducing}
        >
          {isProducing
            ? 'Producing…'
            : clip.production_status === 'error'
              ? 'Retry Produce'
              : hasProduced ? 'Re-produce' : 'Produce'}
        </button>

        {isProducing && <ProductionProgress step={clip.production_step ?? null} />}

        <div className="dl-group">
          {clip.preview_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download`} download>16:9 Raw</a>
          )}
          {clip.vertical_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download-vertical`} download>9:16 Raw</a>
          )}
          {clip.produced_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download-produced`} download>16:9 Produced</a>
          )}
          {clip.vertical_produced_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download-vertical-produced`} download>9:16 Produced</a>
          )}
          {clip.srt_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download-srt`} download>SRT</a>
          )}
        </div>

        <div className="approve-reject-pair">
          <button
            className={`btn btn-sm${isApproved ? ' btn-approved' : ' btn-ghost'}`}
            onClick={handleApprove}
          >
            {isApproved ? '✓ Approved' : 'Approve'}
          </button>
          <button
            className={`btn btn-sm${isRejected ? ' btn-rejected' : ' btn-ghost'}`}
            onClick={handleReject}
          >
            {isRejected ? '✗ Rejected' : 'Reject'}
          </button>
        </div>
      </div>

      {/* ── Transcript ───────────────────────────────────────── */}
      <div className="clip-expand">
        <button className="clip-expand-trigger" onClick={() => setTranscriptOpen(o => !o)}>
          <span>Transcript</span>
          <span className="expand-icon">{transcriptOpen ? '▲' : '▼'}</span>
        </button>
        {transcriptOpen && (
          <div className="clip-expand-body">
            <p className="transcript-text">
              {clip.transcript_excerpt || 'No transcript excerpt available.'}
            </p>
          </div>
        )}
      </div>

      {/* ── B-Roll details (after production) ────────────────── */}
      {hasProduced && (
        <div className="clip-expand">
          <button className="clip-expand-trigger" onClick={() => setBrollOpen(o => !o)}>
            <span>B-Roll Details</span>
            <span className="expand-icon">{brollOpen ? '▲' : '▼'}</span>
          </button>
          {brollOpen && (
            <div className="clip-expand-body">
              {brollSuggestions.length === 0 ? (
                <p className="no-broll">No B-roll suggestions were used.</p>
              ) : (
                <div className="broll-list">
                  {brollSuggestions.map(s => (
                    <div
                      key={s.id}
                      className={`broll-item${s.status === 'approved' ? ' broll-approved' : s.status === 'rejected' ? ' broll-rejected' : ''}`}
                    >
                      {s.pexels_thumbnail_url && (
                        <img className="broll-thumb" src={s.pexels_thumbnail_url} alt="" />
                      )}
                      <div className="broll-info">
                        <div className="broll-meta">
                          <span className="broll-query">{s.search_query}</span>
                          <span className="broll-time">{s.start_sec.toFixed(1)}s – {s.end_sec.toFixed(1)}s</span>
                        </div>
                        {s.reason && <p className="broll-reason">{s.reason}</p>}
                        {swapId === s.id ? (
                          <div className="broll-swap-form">
                            <input
                              className="broll-swap-input"
                              placeholder="New search query…"
                              value={swapQuery}
                              onChange={e => setSwapQuery(e.target.value)}
                              onKeyDown={e => e.key === 'Enter' && handleSwap(s.id)}
                              autoFocus
                            />
                            <button className="btn-xs active" onClick={() => handleSwap(s.id)} disabled={swapping}>
                              {swapping ? '…' : 'Go'}
                            </button>
                            <button className="btn-xs" onClick={() => { setSwapId(null); setSwapQuery('') }}>✕</button>
                          </div>
                        ) : (
                          <div className="broll-actions">
                            <button className="btn-xs" onClick={() => { setSwapId(s.id); setSwapQuery('') }}>Swap</button>
                            {s.status !== 'rejected' && (
                              <button className="btn-xs" onClick={() => handleRejectBroll(s.id)}>Reject</button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div style={{ marginTop: '0.75rem' }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={handleProduce}
                  disabled={isProducing}
                >
                  {isProducing ? 'Re-producing…' : 'Re-produce with changes'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
