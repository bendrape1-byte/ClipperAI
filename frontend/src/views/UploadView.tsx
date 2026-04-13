import { useState, useRef, useEffect } from 'react'
import { uploadMedia, submitYoutube, listProfiles, ClipProfile } from '../api'

interface Props {
  onUploaded: (id: number) => void
  selectedProfileId: number | null
  onSelectProfile: (id: number | null) => void
  onCreateProfile: () => void
  onEditProfile: (profile: ClipProfile) => void
}

const YOUTUBE_RE = /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)[\w-]+/

export default function UploadView({ onUploaded, selectedProfileId, onSelectProfile, onCreateProfile, onEditProfile }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [youtubeLoading, setYoutubeLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [profiles, setProfiles] = useState<ClipProfile[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    listProfiles().then(setProfiles).catch(() => {})
  }, [])

  const acceptFile = (f: File) => {
    if (f.name.toLowerCase().endsWith('.mp4')) {
      setFile(f)
      setYoutubeUrl('')
      setError(null)
    } else {
      setError('Only .mp4 files are supported.')
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) acceptFile(f)
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) acceptFile(f)
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const result = await uploadMedia(file)
      onUploaded(result.id)
    } catch {
      setError('Upload failed. Is the server running?')
      setUploading(false)
    }
  }

  const handleYoutubeSubmit = async () => {
    if (!youtubeUrl.trim()) return
    if (!YOUTUBE_RE.test(youtubeUrl.trim())) {
      setError('Please enter a valid YouTube URL.')
      return
    }
    setYoutubeLoading(true)
    setError(null)
    try {
      const result = await submitYoutube(youtubeUrl.trim(), selectedProfileId ?? undefined)
      onUploaded(result.id)
    } catch (e: any) {
      setError(e.message || 'Failed to start YouTube download.')
      setYoutubeLoading(false)
    }
  }

  const selectedProfile = profiles.find(p => p.id === selectedProfileId)

  return (
    <div className="upload-view">
      <div className="upload-header">
        <h1>New Upload</h1>
        <p className="text-secondary">Upload a video or paste a YouTube link</p>
      </div>

      <div className="input-group">
        <label className="input-label">YouTube URL</label>
        <div className="youtube-input-row">
          <input
            className="field-input"
            type="text"
            placeholder="https://youtube.com/watch?v=..."
            value={youtubeUrl}
            onChange={e => { setYoutubeUrl(e.target.value); setFile(null); setError(null) }}
            onKeyDown={e => { if (e.key === 'Enter') handleYoutubeSubmit() }}
          />
          <button
            className="btn btn-ghost"
            onClick={handleYoutubeSubmit}
            disabled={!youtubeUrl.trim() || youtubeLoading}
          >
            {youtubeLoading ? 'Starting…' : 'Use URL'}
          </button>
        </div>
        <p className="youtube-fallback-note">
          If YouTube blocks the download, download the video manually and use the file upload instead.
        </p>
      </div>

      <div className="divider"><span>or upload a file</span></div>

      <div
        className={`drop-zone ${isDragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".mp4"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
        {file ? (
          <div className="file-selected">
            <span className="file-icon">▶</span>
            <span className="file-name">{file.name}</span>
            <span className="file-size">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
          </div>
        ) : (
          <div className="drop-prompt">
            <span className="drop-icon">↑</span>
            <span>Drop an MP4 here, or click to browse</span>
          </div>
        )}
      </div>

      <div className="profile-select-group">
        <div className="profile-select-header">
          <label className="input-label">Clip Profile</label>
          <button className="btn-link" onClick={onCreateProfile}>+ New profile</button>
        </div>
        {profiles.length === 0 ? (
          <div className="profile-empty">
            <span>No profiles yet. </span>
            <button className="btn-link" onClick={onCreateProfile}>Create your first one</button>
            <span> to get better clips.</span>
          </div>
        ) : (
          <select
            className="profile-select"
            value={selectedProfileId ?? ''}
            onChange={e => onSelectProfile(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">No profile — use default settings</option>
            {profiles.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
        {selectedProfile && (
          <div className="profile-badge">
            <div className="profile-badge-info">
              <span className="profile-badge-name">{selectedProfile.name}</span>
              {selectedProfile.host_name && (
                <span className="profile-badge-meta">Host: {selectedProfile.host_name}</span>
              )}
            </div>
            <button className="btn-link" onClick={() => onEditProfile(selectedProfile)}>Edit</button>
          </div>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      <button
        className="btn btn-primary upload-btn"
        onClick={handleUpload}
        disabled={!file || uploading}
      >
        {uploading ? 'Uploading…' : 'Upload'}
      </button>
    </div>
  )
}
