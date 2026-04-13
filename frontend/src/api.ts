export interface MediaStatus {
  id: number
  status: string
}

export interface Clip {
  id: number
  media_asset_id: number
  start_sec: number
  end_sec: number
  title: string
  hook: string
  reasoning: string
  score: number
  transcript_excerpt: string
  preview_path: string | null
  srt_path: string | null
  vertical_path: string | null
  vertical_status: string | null
  captioned_path: string | null
  vertical_captioned_path: string | null
  broll_path: string | null
  vertical_broll_path: string | null
  produced_path: string | null
  vertical_produced_path: string | null
  production_status: string | null
  production_step: string | null
  render_status: string
  status: string
  created_at: string
}

export async function uploadMedia(file: File): Promise<{ id: number; status: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/media/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getMediaStatus(id: number): Promise<MediaStatus> {
  const res = await fetch(`/api/media/${id}/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface MediaAsset {
  id: number
  filename: string
  duration_seconds: number | null
  status: string
  source_type: string | null
  source_url: string | null
  title: string | null
  thumbnail_url: string | null
  channel_name: string | null
  profile_id: number | null
  clips_rendered: number
  clips_total: number
  created_at: string
}

export async function getMedia(id: number): Promise<MediaAsset> {
  const res = await fetch(`/api/media/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitYoutube(url: string, profileId?: number): Promise<{ id: number; status: string }> {
  const res = await fetch('/api/media/youtube', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, profile_id: profileId ?? null }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function triggerAnalysis(mediaId: number, context = '', profileId?: number): Promise<void> {
  const res = await fetch(`/api/media/${mediaId}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context, profile_id: profileId ?? null }),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function getClips(mediaId: number): Promise<Clip[]> {
  const res = await fetch(`/api/media/${mediaId}/clips`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return data.clips
}

export async function getClip(clipId: number): Promise<Clip> {
  const res = await fetch(`/api/clips/${clipId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function approveClip(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/approve`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function rejectClip(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function produceClip(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/produce`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function renderClip(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/render`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function generateSrt(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/generate-srt`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function generateAllSrt(mediaId: number): Promise<{ queued: number }> {
  const res = await fetch(`/api/media/${mediaId}/generate-all-srt`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function extendClip(clipId: number, startDelta: number, endDelta: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/extend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ start_delta: startDelta, end_delta: endDelta }),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function renderAll(mediaId: number): Promise<{ queued: number }> {
  const res = await fetch(`/api/media/${mediaId}/render-all`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function renderVertical(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/render-vertical`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function renderAllVertical(mediaId: number): Promise<{ queued: number }> {
  const res = await fetch(`/api/media/${mediaId}/render-all-vertical`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function burnCaptions(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/burn-captions`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export interface BrollSuggestion {
  id: number
  clip_id: number
  start_sec: number
  end_sec: number
  search_query: string
  reason: string | null
  pexels_video_id: number | null
  pexels_url: string | null
  pexels_thumbnail_url: string | null
  photographer_name: string | null
  broll_file_path: string | null
  status: string
  created_at: string
}

export async function suggestBroll(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/suggest-broll`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function getBroll(clipId: number): Promise<BrollSuggestion[]> {
  const res = await fetch(`/api/clips/${clipId}/broll`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function approveBroll(suggestionId: number): Promise<BrollSuggestion> {
  const res = await fetch(`/api/broll/${suggestionId}/approve`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function rejectBroll(suggestionId: number): Promise<BrollSuggestion> {
  const res = await fetch(`/api/broll/${suggestionId}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function swapBroll(suggestionId: number, searchQuery: string): Promise<BrollSuggestion> {
  const res = await fetch(`/api/broll/${suggestionId}/swap`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_query: searchQuery }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function compositeBroll(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/composite-broll`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export interface ClipProfile {
  id: number
  name: string
  host_name: string
  host_description: string | null
  guest_name: string | null
  guest_description: string | null
  topic: string | null
  tone: string
  audience: string
  priorities: string
  avoid: string
  additional_notes: string | null
  transition_sfx_id: number | null
  transition_style: string
  created_at: string
}

export interface ClipProfileInput {
  name: string
  host_name: string
  host_description?: string
  guest_name?: string
  guest_description?: string
  topic?: string
  tone: string[]
  audience: string[]
  priorities: string[]
  avoid: string[]
  additional_notes?: string
  transition_sfx_id?: number | null
  transition_style?: string
}

export interface SfxEntry {
  id: number
  name: string
  filename: string
  duration_seconds: number
  category: string
  is_default: boolean
  created_at: string
}

export async function listSfx(): Promise<SfxEntry[]> {
  const res = await fetch('/api/sfx')
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadSfx(file: File, name: string, category: string): Promise<SfxEntry> {
  const form = new FormData()
  form.append('file', file)
  form.append('name', name)
  form.append('category', category)
  const res = await fetch('/api/sfx/upload', { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSfx(id: number): Promise<void> {
  const res = await fetch(`/api/sfx/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export function sfxPreviewUrl(id: number): string {
  return `/api/sfx/${id}/preview`
}

export async function previewTransition(
  transitionStyle: string,
  sfxId: number | null,
): Promise<string> {
  const res = await fetch('/api/profiles/preview-transition', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transition_style: transitionStyle, sfx_id: sfxId }),
  })
  if (!res.ok) throw new Error(await res.text())
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

export async function listProfiles(): Promise<ClipProfile[]> {
  const res = await fetch('/api/profiles')
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function createProfile(data: ClipProfileInput): Promise<ClipProfile> {
  const res = await fetch('/api/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getProfile(id: number): Promise<ClipProfile> {
  const res = await fetch(`/api/profiles/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateProfile(id: number, data: ClipProfileInput): Promise<ClipProfile> {
  const res = await fetch(`/api/profiles/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
