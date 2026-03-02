import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Landing from '@/pages/Landing'
import Explorer from '@/pages/Explorer'
import CaseStudyPage from '@/pages/CaseStudy'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/"                  element={<Landing />} />
        <Route path="/explore"           element={<Explorer />} />
        <Route path="/explore/:aoiId"    element={<Explorer />} />
        <Route path="/cases/:slug"       element={<CaseStudyPage />} />
      </Routes>
    </BrowserRouter>
  )
}
