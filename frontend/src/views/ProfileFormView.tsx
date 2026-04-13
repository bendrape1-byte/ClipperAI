import { useEffect, useRef, useState } from 'react'
import { createProfile, updateProfile, listSfx, uploadSfx, sfxPreviewUrl, previewTransition, ClipProfile, SfxEntry } from '../api'

const TONE_OPTIONS = [
  { value: 'educational', label: 'Educational', hint: 'Teaches something concrete' },
  { value: 'contrarian', label: 'Contrarian', hint: 'Challenges conventional wisdom' },
  { value: 'inspirational', label: 'Inspirational', hint: 'Motivates or uplifts' },
  { value: 'entertainment', label: 'Entertainment', hint: 'Fun, engaging, lighter content' },
  { value: 'raw_unfiltered', label: 'Raw & Unfiltered', hint: 'Honest, unpolished moments' },
  { value: 'storytelling', label: 'Storytelling', hint: 'Narrative-driven moments' },
]

const AUDIENCE_OPTIONS = [
  { value: 'entrepreneurs', label: 'Entrepreneurs' },
  { value: 'marketers', label: 'Marketers' },
  { value: 'general', label: 'General Audience' },
  { value: 'creators', label: 'Creators' },
  { value: 'technical', label: 'Technical' },
  { value: 'executives', label: 'Executives' },
]

const PRIORITY_OPTIONS = [
  { value: 'strong_hooks', label: 'Strong Hooks', hint: 'Clips with a scroll-stopping opener' },
  { value: 'actionable_advice', label: 'Actionable Advice', hint: 'Concrete steps the viewer can take' },
  { value: 'emotional_moments', label: 'Emotional Moments', hint: 'Vulnerability, frustration, revelation' },
  { value: 'controversial_takes', label: 'Controversial Takes', hint: 'Opinions that spark debate' },
  { value: 'funny_moments', label: 'Funny Moments', hint: 'Genuine laughs, not forced' },
  { value: 'storytelling', label: 'Storytelling', hint: 'Clips with a clear narrative arc' },
  { value: 'data_driven', label: 'Data-Driven', hint: 'Specific numbers, stats, results' },
]

const AVOID_OPTIONS = [
  { value: 'inside_jokes', label: 'Inside Jokes', hint: 'References only regulars get' },
  { value: 'heavy_jargon', label: 'Heavy Jargon', hint: 'Industry terms without explanation' },
  { value: 'requires_context', label: 'Requires Context', hint: 'Can\'t stand alone without prior episode knowledge' },
  { value: 'self_promotion', label: 'Self-Promotion', hint: 'Plugs for products, courses, sponsors' },
  { value: 'vague_motivation', label: 'Vague Motivation', hint: '"Believe in yourself" style content' },
  { value: 'long_intros', label: 'Long Intros', hint: 'Slow wind-ups before the real point' },
]

const TRANSITION_OPTIONS = [
  { value: 'crossfade',    label: 'Crossfade', hint: 'Smooth opacity blend (0.15s)' },
  { value: 'dip_to_black', label: 'Dip to Black', hint: 'Cinematic fade through black (0.2s)' },
  { value: 'wipe_left',   label: 'Wipe Left', hint: 'Dynamic left wipe (0.2s)' },
  { value: 'cut',          label: 'Hard Cut', hint: 'Editorial — no transition effect' },
]

function toggle(arr: string[], val: string): string[] {
  return arr.includes(val) ? arr.filter(v => v !== val) : [...arr, val]
}

function parseArr(val: string | null | undefined): string[] {
  try { return JSON.parse(val || '[]') } catch { return [] }
}

interface Props {
  onSaved: (profileId: number) => void
  onBack: () => void
  initialProfile?: ClipProfile
}

export default function ProfileFormView({ onSaved, onBack, initialProfile }: Props) {
  const p = initialProfile
  const isEditing = !!p

  const [name, setName] = useState(p?.name ?? '')
  const [hostName, setHostName] = useState(p?.host_name ?? '')
  const [hostDescription, setHostDescription] = useState(p?.host_description ?? '')
  const [guestName, setGuestName] = useState(p?.guest_name ?? '')
  const [guestDescription, setGuestDescription] = useState(p?.guest_description ?? '')
  const [topic, setTopic] = useState(p?.topic ?? '')
  const [tone, setTone] = useState<string[]>(() => parseArr(p?.tone))
  const [audience, setAudience] = useState<string[]>(() => parseArr(p?.audience))
  const [priorities, setPriorities] = useState<string[]>(() => parseArr(p?.priorities))
  const [avoid, setAvoid] = useState<string[]>(() => parseArr(p?.avoid))
  const [notes, setNotes] = useState(p?.additional_notes ?? '')
  const [transitionStyle, setTransitionStyle] = useState(p?.transition_style ?? 'crossfade')
  const [transitionSfxId, setTransitionSfxId] = useState<number | null>(p?.transition_sfx_id ?? null)
  const [sfxList, setSfxList] = useState<SfxEntry[]>([])
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadName, setUploadName] = useState('')
  const [uploadCategory, setUploadCategory] = useState('transition')
  const [uploading, setUploading] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => {
    listSfx().then(setSfxList).catch(() => {})
  }, [])

  const playPreview = (sfxId: number) => {
    if (audioRef.current) {
      audioRef.current.pause()
    }
    const a = new Audio(sfxPreviewUrl(sfxId))
    audioRef.current = a
    a.play().catch(() => {})
  }

  const handleUploadSfx = async () => {
    if (!uploadFile || !uploadName.trim()) return
    setUploading(true)
    try {
      const entry = await uploadSfx(uploadFile, uploadName.trim(), uploadCategory)
      setSfxList(prev => [...prev, entry])
      setTransitionSfxId(entry.id)
      setUploadOpen(false)
      setUploadFile(null)
      setUploadName('')
    } catch (e: any) {
      alert(e.message || 'Upload failed')
    }
    setUploading(false)
  }

  const handlePreview = async () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl(null)
    setPreviewError(null)
    setPreviewing(true)
    try {
      const url = await previewTransition(transitionStyle, transitionSfxId)
      setPreviewUrl(url)
    } catch (e: any) {
      setPreviewError(e.message || 'Preview failed')
    }
    setPreviewing(false)
  }

  const handleSave = async () => {
    if (!name.trim() || !hostName.trim()) {
      setError('Show name and host name are required.')
      return
    }
    setSaving(true)
    setError(null)
    const data = {
      name: name.trim(),
      host_name: hostName.trim(),
      host_description: hostDescription.trim(),
      guest_name: guestName.trim(),
      guest_description: guestDescription.trim(),
      topic: topic.trim(),
      tone,
      audience,
      priorities,
      avoid,
      additional_notes: notes.trim(),
      transition_style: transitionStyle,
      transition_sfx_id: transitionSfxId,
    }
    try {
      const profile = isEditing
        ? await updateProfile(p!.id, data)
        : await createProfile(data)
      onSaved(profile.id)
    } catch {
      setError('Failed to save profile. Is the server running?')
      setSaving(false)
    }
  }

  return (
    <div className="profile-form-view">
      <div className="profile-form-header">
        <button className="btn-back" onClick={onBack}>← Back</button>
        <div>
          <h1>{isEditing ? 'Edit Clip Profile' : 'New Clip Profile'}</h1>
          <p className="text-secondary">Tell us about the show — we'll handle the prompting.</p>
        </div>
      </div>

      <div className="profile-form">

        <div className="form-section">
          <div className="form-section-title">Show</div>
          <div className="input-group">
            <label className="input-label">Show name <span className="required">*</span></label>
            <input
              className="field-input"
              type="text"
              placeholder="e.g. The Tim Ferriss Show"
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Host</div>
          <div className="form-row">
            <div className="input-group">
              <label className="input-label">Host name <span className="required">*</span></label>
              <input
                className="field-input"
                type="text"
                placeholder="e.g. Tim Ferriss"
                value={hostName}
                onChange={e => setHostName(e.target.value)}
              />
            </div>
            <div className="input-group">
              <label className="input-label">One-line description</label>
              <input
                className="field-input"
                type="text"
                placeholder="e.g. Author, investor, podcaster"
                value={hostDescription}
                onChange={e => setHostDescription(e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Guest <span className="optional-label">optional</span></div>
          <div className="form-row">
            <div className="input-group">
              <label className="input-label">Guest name</label>
              <input
                className="field-input"
                type="text"
                placeholder="e.g. Jocko Willink"
                value={guestName}
                onChange={e => setGuestName(e.target.value)}
              />
            </div>
            <div className="input-group">
              <label className="input-label">One-line description</label>
              <input
                className="field-input"
                type="text"
                placeholder="e.g. Former Navy SEAL, author"
                value={guestDescription}
                onChange={e => setGuestDescription(e.target.value)}
              />
            </div>
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Episode</div>
          <div className="input-group">
            <label className="input-label">What is this episode about?</label>
            <input
              className="field-input"
              type="text"
              placeholder="e.g. Building mental resilience and leadership under pressure"
              value={topic}
              onChange={e => setTopic(e.target.value)}
            />
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Tone</div>
          <p className="form-section-hint">What's the overall vibe of this show?</p>
          <div className="checkbox-group">
            {TONE_OPTIONS.map(opt => (
              <label key={opt.value} className={`checkbox-item ${tone.includes(opt.value) ? 'checked' : ''}`}>
                <input
                  type="checkbox"
                  checked={tone.includes(opt.value)}
                  onChange={() => setTone(toggle(tone, opt.value))}
                />
                <div className="checkbox-text">
                  <span className="checkbox-label">{opt.label}</span>
                  <span className="checkbox-hint">{opt.hint}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Target Audience</div>
          <p className="form-section-hint">Who watches this show?</p>
          <div className="checkbox-group">
            {AUDIENCE_OPTIONS.map(opt => (
              <label key={opt.value} className={`checkbox-item ${audience.includes(opt.value) ? 'checked' : ''}`}>
                <input
                  type="checkbox"
                  checked={audience.includes(opt.value)}
                  onChange={() => setAudience(toggle(audience, opt.value))}
                />
                <div className="checkbox-text">
                  <span className="checkbox-label">{opt.label}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Clip Priorities</div>
          <p className="form-section-hint">What kind of moments perform best for this show?</p>
          <div className="checkbox-group">
            {PRIORITY_OPTIONS.map(opt => (
              <label key={opt.value} className={`checkbox-item ${priorities.includes(opt.value) ? 'checked' : ''}`}>
                <input
                  type="checkbox"
                  checked={priorities.includes(opt.value)}
                  onChange={() => setPriorities(toggle(priorities, opt.value))}
                />
                <div className="checkbox-text">
                  <span className="checkbox-label">{opt.label}</span>
                  <span className="checkbox-hint">{opt.hint}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">Avoid</div>
          <p className="form-section-hint">What types of clips don't work for this audience?</p>
          <div className="checkbox-group">
            {AVOID_OPTIONS.map(opt => (
              <label key={opt.value} className={`checkbox-item ${avoid.includes(opt.value) ? 'checked' : ''}`}>
                <input
                  type="checkbox"
                  checked={avoid.includes(opt.value)}
                  onChange={() => setAvoid(toggle(avoid, opt.value))}
                />
                <div className="checkbox-text">
                  <span className="checkbox-label">{opt.label}</span>
                  <span className="checkbox-hint">{opt.hint}</span>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-title">
            Additional Notes <span className="optional-label">optional</span>
          </div>
          <p className="form-section-hint">Anything else we should know about this show or episode?</p>
          <textarea
            className="context-textarea"
            rows={3}
            placeholder="e.g. The guest mentions a product launch mid-episode — deprioritize those moments"
            value={notes}
            onChange={e => setNotes(e.target.value)}
          />
        </div>

        <div className="form-section">
          <div className="form-section-title">Transitions &amp; Sound</div>
          <p className="form-section-hint">How B-roll cuts look and sound when using Produce.</p>

          <div className="input-group" style={{ marginBottom: '1.25rem' }}>
            <label className="input-label">Transition style</label>
            <div className="transition-radio-group">
              {TRANSITION_OPTIONS.map(opt => (
                <label
                  key={opt.value}
                  className={`transition-radio-item${transitionStyle === opt.value ? ' selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="transition_style"
                    value={opt.value}
                    checked={transitionStyle === opt.value}
                    onChange={() => setTransitionStyle(opt.value)}
                  />
                  <div className="transition-radio-text">
                    <span className="transition-radio-label">{opt.label}</span>
                    <span className="transition-radio-hint">{opt.hint}</span>
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className="input-group">
            <label className="input-label">Transition sound effect</label>
            <div className="sfx-select-row">
              <select
                className="field-input sfx-select"
                value={transitionSfxId ?? ''}
                onChange={e => setTransitionSfxId(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">Default (Soft Whoosh)</option>
                {sfxList.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.name} — {s.category} ({s.duration_seconds.toFixed(2)}s)
                    {s.is_default ? ' ★' : ''}
                  </option>
                ))}
              </select>
              {(transitionSfxId || sfxList.length > 0) && (
                <button
                  type="button"
                  className="btn-xs sfx-preview-btn"
                  onClick={() => {
                    const id = transitionSfxId ?? sfxList.find(s => s.category === 'transition' && s.is_default)?.id
                    if (id) playPreview(id)
                  }}
                >
                  ▶ Preview
                </button>
              )}
            </div>
          </div>

          {!uploadOpen ? (
            <button
              type="button"
              className="btn-xs sfx-upload-toggle"
              onClick={() => setUploadOpen(true)}
              style={{ marginTop: '0.75rem' }}
            >
              + Upload custom sound
            </button>
          ) : (
            <div className="sfx-upload-inline">
              <input
                type="file"
                accept=".wav,.mp3"
                onChange={e => setUploadFile(e.target.files?.[0] ?? null)}
              />
              <input
                className="field-input"
                type="text"
                placeholder="Name (e.g. Deep Whoosh)"
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
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleUploadSfx}
                  disabled={uploading || !uploadFile || !uploadName.trim()}
                >
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setUploadOpen(false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div className="transition-preview-row">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handlePreview}
              disabled={previewing}
            >
              {previewing
                ? <><span className="spinner" style={{ width: 12, height: 12 }} />&nbsp;Generating…</>
                : 'Preview Transition'}
            </button>
            {previewError && (
              <p className="error-text" style={{ margin: '0.5rem 0 0' }}>{previewError}</p>
            )}
          </div>

          {previewUrl && (
            <video
              key={previewUrl}
              className="transition-preview-video"
              src={previewUrl}
              autoPlay
              loop
              controls
              playsInline
            />
          )}
        </div>

        {error && <p className="error-text">{error}</p>}

        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onBack}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : isEditing ? 'Save Changes' : 'Save Profile'}
          </button>
        </div>
      </div>
    </div>
  )
}
