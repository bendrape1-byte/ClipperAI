import { useEffect, useRef, useState } from 'react'
import { listSfx, uploadSfx, deleteSfx, sfxPreviewUrl, SfxEntry } from '../api'

const CATEGORY_LABELS: Record<string, string> = {
  transition: 'Transition',
  impact: 'Impact',
  subtle: 'Subtle',
  musical: 'Musical',
}

export default function SfxLibraryView() {
  const [sfxList, setSfxList] = useState<SfxEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadName, setUploadName] = useState('')
  const [uploadCategory, setUploadCategory] = useState('transition')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)

  const refresh = () =>
    listSfx()
      .then(setSfxList)
      .catch(() => {})
      .finally(() => setLoading(false))

  useEffect(() => { refresh() }, [])

  const playPreview = (id: number) => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.onended = null
    }
    const a = new Audio(sfxPreviewUrl(id))
    audioRef.current = a
    setPlayingId(id)
    a.onended = () => setPlayingId(null)
    a.play().catch(() => setPlayingId(null))
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this sound effect?')) return
    try {
      await deleteSfx(id)
      setSfxList(prev => prev.filter(s => s.id !== id))
    } catch (e: any) {
      alert(e.message || 'Delete failed')
    }
  }

  const handleUpload = async () => {
    if (!uploadFile || !uploadName.trim()) return
    setUploading(true)
    setUploadError(null)
    try {
      await uploadSfx(uploadFile, uploadName.trim(), uploadCategory)
      setUploadFile(null)
      setUploadName('')
      await refresh()
    } catch (e: any) {
      setUploadError(e.message || 'Upload failed')
    }
    setUploading(false)
  }

  const grouped = sfxList.reduce<Record<string, SfxEntry[]>>((acc, s) => {
    const cat = s.category || 'other'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(s)
    return acc
  }, {})

  if (loading) return <div className="loading">Loading sound library…</div>

  return (
    <div className="sfx-library-view">
      <h1 className="sfx-library-title">Sound Library</h1>
      <p className="text-secondary" style={{ marginBottom: '2rem' }}>
        Sound effects used for B-roll transitions when producing clips.
        Default sounds cannot be deleted.
      </p>

      {/* Upload form */}
      <div className="sfx-upload-card">
        <div className="sfx-upload-card-title">Upload Custom Sound</div>
        <p className="text-secondary" style={{ fontSize: 12, marginBottom: '0.75rem' }}>
          .wav or .mp3 only — max 2 seconds
        </p>
        <div className="sfx-upload-form">
          <input
            type="file"
            accept=".wav,.mp3"
            onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
          />
          <input
            className="field-input"
            type="text"
            placeholder="Name (e.g. Deep Thud)"
            value={uploadName}
            onChange={e => setUploadName(e.target.value)}
          />
          <select
            className="field-input"
            value={uploadCategory}
            onChange={e => setUploadCategory(e.target.value)}
          >
            <option value="transition">Transition</option>
            <option value="impact">Impact</option>
            <option value="subtle">Subtle</option>
            <option value="musical">Musical</option>
          </select>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleUpload}
            disabled={uploading || !uploadFile || !uploadName.trim()}
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {uploadError && <p className="error-text" style={{ marginTop: '0.5rem' }}>{uploadError}</p>}
      </div>

      {/* SFX list grouped by category */}
      {Object.entries(grouped).map(([cat, entries]) => (
        <div key={cat} className="sfx-category-section">
          <div className="sfx-category-label">{CATEGORY_LABELS[cat] ?? cat}</div>
          <div className="sfx-list">
            {entries.map(s => (
              <div key={s.id} className="sfx-row">
                <div className="sfx-row-info">
                  <span className="sfx-row-name">{s.name}</span>
                  {s.is_default && <span className="sfx-default-badge">default</span>}
                  <span className="sfx-row-duration">{s.duration_seconds.toFixed(2)}s</span>
                </div>
                <div className="sfx-row-actions">
                  <button
                    className={`btn-xs${playingId === s.id ? ' active' : ''}`}
                    onClick={() => playPreview(s.id)}
                  >
                    {playingId === s.id ? '■ Stop' : '▶ Play'}
                  </button>
                  {!s.is_default && (
                    <button className="btn-xs btn-xs-danger" onClick={() => handleDelete(s.id)}>
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {sfxList.length === 0 && (
        <p className="review-empty">No sound effects found.</p>
      )}
    </div>
  )
}
