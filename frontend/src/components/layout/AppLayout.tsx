import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { cn } from '@/lib/utils'

/** Main authenticated app shell: sidebar + topbar + content outlet. */
export function AppLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <div className="flex h-screen overflow-hidden bg-[#f6f8fb]">
      {/* Desktop sidebar */}
      <aside className="hidden w-[272px] shrink-0 border-r border-slate-200/80 bg-white lg:block">
        <Sidebar />
      </aside>

      {/* Mobile drawer */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileMenuOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-[272px] bg-card shadow-2xl">
            <Sidebar onNavigate={() => setMobileMenuOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenuClick={() => setMobileMenuOpen(true)} />
        <main className={cn('flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8')}>
          <div className="mx-auto w-full max-w-[1440px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
