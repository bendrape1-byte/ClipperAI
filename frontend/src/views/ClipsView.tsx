import { useEffect, useState } from 'react'
import { getMedia, getClips, Clip, MediaAsset } from '../api'
import ClipCard from '../components/ClipCard'

interface Props {
  mediaId: number
}

export default function ClipsView({ mediaId }: Props) {
  const [asset, setAsset] = useState<MediaAsset | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [loading, setLoading] = useState(true)

  const fetchAll = async () => {
    try {
      const [assetData, clipsData] = await Promise.all([
        getMedia(mediaId),
        getClips(mediaId),
      ])
      setAsset(assetData)
      setClips(clipsData)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => {
    fetchAll()
    const id = setInterval(fetchAll, 10000)
    return () => clearInterval(id)
  }, [mediaId])

  if (loading) return <div className="loading">Loading clips…</div>

  const title = asset?.title || asset?.filename || `Media #${mediaId}`
  const approved = clips.filter(c => c.status === 'approved').length
  const rejected = clips.filter(c => c.status === 'rejected').length
  const ready = clips.filter(c => c.render_status === 'ready').length
  const total = clips.length
  const allReady = ready === total

  return (
    <div className="review-page">
      <div className="review-summary">
        <div className="review-summary-left">
          <span className="review-title">{title}</span>
          <span className="review-meta">
            {allReady
              ? <span>{total} clips</span>
              : <span>{ready} of {total} clips ready</span>
            }
            {approved > 0 && <span className="review-tag approved">{approved} approved</span>}
            {rejected > 0 && <span className="review-tag rejected">{rejected} rejected</span>}
          </span>
        </div>
        {approved > 0 && (
          <a
            className="btn btn-ghost"
            href={`/api/media/${mediaId}/download-approved`}
            download="approved_clips.zip"
          >
            Download Approved
          </a>
        )}
      </div>

      <div className="review-clips">
        {clips.map(clip => (
          <ClipCard key={clip.id} clip={clip} onRefresh={fetchAll} />
        ))}
        {clips.length === 0 && (
          <p className="review-empty">No clips found.</p>
        )}
      </div>
    </div>
  )
}
