import { useEffect, useState } from 'react'
import { Clip, approveClip, rejectClip } from '../api'

interface Props {
  clip: Clip
  onRefresh: () => void
}

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

export default function ClipCard({ clip: initialClip, onRefresh }: Props) {
  const [clip, setClip] = useState<Clip>(initialClip)
  const [transcriptOpen, setTranscriptOpen] = useState(false)

  // Sync with parent poll
  useEffect(() => {
    setClip(initialClip)
  }, [initialClip])

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
        <div className="clip-player-wrap">
          <video
            key={`/api/clips/${clip.id}/download`}
            className="clip-player"
            src={`/api/clips/${clip.id}/download`}
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
        <div className="dl-group">
          {clip.preview_path && (
            <a className="btn btn-ghost btn-sm" href={`/api/clips/${clip.id}/download`} download>16:9 Raw</a>
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
    </section>
  )
}
