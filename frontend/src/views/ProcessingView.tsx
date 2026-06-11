import { Fragment, useEffect, useRef, useState } from 'react'
import { getMedia, triggerAnalysis, MediaAsset } from '../api'

interface Props {
  mediaId: number
  onViewClips: () => void
}

const UPLOAD_STEPS  = ['Upload', 'Extract Audio', 'Transcribe', 'Analyze', 'Render', 'Ready']
const YOUTUBE_STEPS = ['Download', 'Extract Audio', 'Transcribe', 'Analyze', 'Render', 'Ready']

function stepsDone(status: string, isYoutube: boolean): number {
  if (isYoutube) {
    switch (status) {
      case 'downloading':  return 0
      case 'processing':   return 1
      case 'transcribing': return 2
      case 'transcribed':  return 3
      case 'analyzing':    return 3
      case 'rendering':    return 4
      case 'ready':        return 6
      default:             return 0
    }
  }
  switch (status) {
    case 'uploaded':     return 1
    case 'processing':   return 1
    case 'transcribing': return 2
    case 'transcribed':  return 3
    case 'analyzing':    return 3
    case 'rendering':    return 4
    case 'ready':        return 6
    default:             return 0
  }
}

function activeStep(status: string, isYoutube: boolean): number {
  if (isYoutube) {
    switch (status) {
      case 'downloading':  return 0
      case 'processing':   return 1
      case 'transcribing': return 2
      case 'analyzing':    return 3
      case 'rendering':    return 4
      default:             return -1
    }
  }
  switch (status) {
    case 'uploaded':     return 0
    case 'processing':   return 1
    case 'transcribing': return 2
    case 'analyzing':    return 3
    case 'rendering':    return 4
    default:             return -1
  }
}

function estimatedDuration(stepIndex: number, mediaSecs: number, clipsTotal: number): number {
  const d = mediaSecs || 3600
  switch (stepIndex) {
    case 1: return Math.max(20, d / 120)
    case 2: return Math.max(30, Math.ceil(d / 600) * 25)
    case 3: return Math.max(20, Math.ceil(d / 780) * 15)
    case 4: return Math.max(60, (clipsTotal * 90) / 3)  // ~90s/clip, 3 parallel
    default: return 30
  }
}

function remainingText(stepIndex: number, mediaSecs: number, startMs: number, clipsTotal = 0): string {
  const elapsed = (Date.now() - startMs) / 1000
  const est = estimatedDuration(stepIndex, mediaSecs, clipsTotal)
  const rem = Math.max(0, est - elapsed)
  if (rem < 8) return 'Almost done…'
  if (rem < 60) return `~${Math.round(rem)}s left`
  const m = Math.floor(rem / 60)
  const s = Math.round(rem % 60)
  return s > 0 ? `~${m}m ${s}s left` : `~${m}m left`
}

export default function ProcessingView({ mediaId, onViewClips }: Props) {
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [status, setStatus] = useState('uploaded')
  const [analyzing, setAnalyzing] = useState(false)
  const [stepStartTimes, setStepStartTimes] = useState<Record<number, number>>({})
  const [progress, setProgress] = useState<Record<number, number>>({})
  const prevActiveRef = useRef(-2)

  const isYoutube = asset?.source_type === 'youtube'
  const STEPS = isYoutube ? YOUTUBE_STEPS : UPLOAD_STEPS
  const mediaDuration = asset?.duration_seconds ?? 0
  const clipsTotal = asset?.clips_total ?? 0
  const clipsRendered = asset?.clips_rendered ?? 0

  // Poll full media asset every 3s — picks up title/channel as they become available
  useEffect(() => {
    let stopped = false
    const poll = async () => {
      if (stopped) return
      try {
        const data = await getMedia(mediaId)
        setAsset(data)
        setStatus(data.status)
      } catch { /* ignore */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { stopped = true; clearInterval(id) }
  }, [mediaId])

  const done = stepsDone(status, isYoutube)
  const active = activeStep(status, isYoutube)

  // Record start time when active step changes
  useEffect(() => {
    if (active !== prevActiveRef.current) {
      prevActiveRef.current = active
      if (active >= 0) {
        setStepStartTimes(prev => ({ ...prev, [active]: Date.now() }))
      }
    }
  }, [active])

  // Tick progress every second
  useEffect(() => {
    const id = setInterval(() => {
      setProgress(prev => {
        const next = { ...prev }
        for (let i = 0; i < done; i++) next[i] = 100
        if (status === 'ready') STEPS.forEach((_, i) => { next[i] = 100 })
        if (active >= 0 && active !== 4 && stepStartTimes[active]) {
          const elapsed = (Date.now() - stepStartTimes[active]) / 1000
          const est = estimatedDuration(active, mediaDuration, clipsTotal)
          next[active] = Math.min(92, (elapsed / est) * 100)
        }
        if (active === 4 && clipsTotal > 0) {
          next[4] = Math.round((clipsRendered / clipsTotal) * 100)
        }
        return next
      })
    }, 1000)
    return () => clearInterval(id)
  }, [done, active, stepStartTimes, mediaDuration, clipsTotal, clipsRendered, status, STEPS])

  const handleAnalyze = async () => {
    setAnalyzing(true)
    try {
      await triggerAnalysis(mediaId, '')
    } catch {
      setAnalyzing(false)
    }
  }

  const displayTitle = asset?.title || asset?.filename || `Media #${mediaId}`
  const displayChannel = asset?.channel_name

  return (
    <div className="processing-view">
      <div className="processing-header">
        <h1>{displayTitle}</h1>
        {displayChannel && <p className="text-secondary">{displayChannel}</p>}
        {!displayChannel && <p className="text-secondary">Media #{mediaId}</p>}
      </div>

      <div className="stepper">
        {STEPS.map((label, i) => {
          const isComplete = i < done || status === 'ready'
          const isActive = i === active
          const pct = progress[i] ?? 0
          const showBar = i > 0 && i < 5

          const isRenderStep = i === 4
          const renderTimeText = isRenderStep && isActive && clipsTotal > 0
            ? `${clipsRendered} of ${clipsTotal}`
            : isRenderStep && isComplete
              ? '✓ done'
              : ''

          return (
            <Fragment key={i}>
              <div className={`step ${isComplete ? 'complete' : isActive ? 'active' : 'pending'}`}>
                <div className="step-circle">
                  {isComplete ? '✓' : isActive ? <span className="spinner" /> : i + 1}
                </div>
                <div className="step-label">{label}</div>
                {showBar && (
                  <div className="step-progress">
                    <div className="step-progress-bar">
                      <div className="step-progress-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="step-time">
                      {isRenderStep
                        ? renderTimeText
                        : isComplete
                          ? '✓ done'
                          : isActive && stepStartTimes[i]
                            ? remainingText(i, mediaDuration, stepStartTimes[i])
                            : ''}
                    </span>
                  </div>
                )}
              </div>
              {i < STEPS.length - 1 && (
                <div className={`step-connector ${isComplete ? 'complete' : ''}`} />
              )}
            </Fragment>
          )
        })}
      </div>

      {status === 'transcribed' && (
        <div className="action-card">
          <p>Transcription complete. Ready to analyze.</p>
          <button className="btn btn-primary" onClick={handleAnalyze} disabled={analyzing}>
            {analyzing ? 'Starting…' : 'Start Analysis'}
          </button>
        </div>
      )}

      {status === 'rendering' && clipsTotal > 0 && (
        <div className="action-card">
          <p>
            Rendering clip {Math.min(clipsRendered + 1, clipsTotal)} of {clipsTotal}…
            &nbsp;(16:9)
          </p>
        </div>
      )}

      {status === 'error' && (
        <div className="action-card error">
          <p>Something went wrong. Check the server logs for details.</p>
        </div>
      )}

      {status === 'ready' && (
        <div className="action-card">
          <p>All {clipsTotal} clips rendered and ready to review.</p>
          <div className="action-buttons">
            <button className="btn btn-primary" onClick={onViewClips}>
              View Clips
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
