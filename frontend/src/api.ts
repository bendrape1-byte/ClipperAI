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
  clips_rendered: number
  clips_total: number
  created_at: string
}

export async function getMedia(id: number): Promise<MediaAsset> {
  const res = await fetch(`/api/media/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitYoutube(url: string): Promise<{ id: number; status: string }> {
  const res = await fetch('/api/media/youtube', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function triggerAnalysis(mediaId: number, context = ''): Promise<void> {
  const res = await fetch(`/api/media/${mediaId}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ context }),
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

export async function renderClip(clipId: number): Promise<void> {
  const res = await fetch(`/api/clips/${clipId}/render`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
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
