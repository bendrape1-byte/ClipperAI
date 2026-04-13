import { useState } from 'react'
import { ClipProfile } from './api'
import UploadView from './views/UploadView'
import ProcessingView from './views/ProcessingView'
import ClipsView from './views/ClipsView'
import ProfileFormView from './views/ProfileFormView'
import SfxLibraryView from './views/SfxLibraryView'

type View = 'upload' | 'processing' | 'clips' | 'profile-form' | 'sfx-library'

export default function App() {
  const [view, setView] = useState<View>('upload')
  const [mediaId, setMediaId] = useState<number | null>(null)
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null)
  const [editingProfile, setEditingProfile] = useState<ClipProfile | null>(null)

  const handleUploaded = (id: number) => {
    setMediaId(id)
    setView('processing')
  }

  const handleCreateProfile = () => {
    setEditingProfile(null)
    setView('profile-form')
  }

  const handleEditProfile = (profile: ClipProfile) => {
    setEditingProfile(profile)
    setView('profile-form')
  }

  const handleProfileSaved = (id: number) => {
    setSelectedProfileId(id)
    setEditingProfile(null)
    setView('upload')
  }

  const handleProfileBack = () => {
    setEditingProfile(null)
    setView('upload')
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
          <button
            className={`nav-btn ${view === 'sfx-library' ? 'active' : ''}`}
            onClick={() => setView('sfx-library')}
          >
            Sound Library
          </button>
        </nav>
      </header>
      <main className="main">
        {view === 'upload' && (
          <UploadView
            onUploaded={handleUploaded}
            selectedProfileId={selectedProfileId}
            onSelectProfile={setSelectedProfileId}
            onCreateProfile={handleCreateProfile}
            onEditProfile={handleEditProfile}
          />
        )}
        {view === 'profile-form' && (
          <ProfileFormView
            onSaved={handleProfileSaved}
            onBack={handleProfileBack}
            initialProfile={editingProfile ?? undefined}
          />
        )}
        {view === 'processing' && mediaId !== null && (
          <ProcessingView
            mediaId={mediaId}
            profileId={selectedProfileId}
            onViewClips={() => setView('clips')}
          />
        )}
        {view === 'clips' && mediaId !== null && (
          <ClipsView mediaId={mediaId} />
        )}
        {view === 'sfx-library' && (
          <SfxLibraryView />
        )}
      </main>
    </div>
  )
}
