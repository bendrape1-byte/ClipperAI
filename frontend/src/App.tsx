import { useState } from 'react'
import UploadView from './views/UploadView'
import ProcessingView from './views/ProcessingView'
import ClipsView from './views/ClipsView'

type View = 'upload' | 'processing' | 'clips'

export default function App() {
  const [view, setView] = useState<View>('upload')
  const [mediaId, setMediaId] = useState<number | null>(null)

  const handleUploaded = (id: number) => {
    setMediaId(id)
    setView('processing')
  }

  return (
    <div className="app">
      <header className="header">
        <span className="header-title" style={{ cursor: 'pointer' }} onClick={() => setView('upload')}>
          <span>clip</span> engine
        </span>
        <nav className="header-nav">
          {mediaId && (
            <>
              <button
                className={`nav-btn ${view === 'processing' ? 'active' : ''}`}
                onClick={() => setView('processing')}
              >
                Processing
              </button>
              <button
                className={`nav-btn ${view === 'clips' ? 'active' : ''}`}
                onClick={() => setView('clips')}
              >
                Clips
              </button>
            </>
          )}
        </nav>
      </header>
      <main className="main">
        {view === 'upload' && (
          <UploadView onUploaded={handleUploaded} />
        )}
        {view === 'processing' && mediaId !== null && (
          <ProcessingView
            mediaId={mediaId}
            onViewClips={() => setView('clips')}
          />
        )}
        {view === 'clips' && mediaId !== null && (
          <ClipsView mediaId={mediaId} />
        )}
      </main>
    </div>
  )
}
