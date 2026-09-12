import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { Bell, LogOut, Menu, Moon, Search, Sun, User } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { useAuth } from '@/lib/auth/useAuth'
import { useThemeStore } from '@/stores/themeStore'
import { toast } from '@/stores/toastStore'

interface TopbarProps {
  onMenuClick?: () => void
}

export function Topbar({ onMenuClick }: TopbarProps) {
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useThemeStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [workspaceSearch, setWorkspaceSearch] = useState('')
  const pageTitle = ({ '/': 'Dashboard', '/products': 'Products', '/warehouses': 'Warehouses', '/inventory': 'Inventory', '/orders': 'Orders', '/profile': 'Profile' } as Record<string, string>)[location.pathname] || 'Order details'

  const initials = user
    ? `${user.first_name?.[0] ?? ''}${user.last_name?.[0] ?? ''}`.toUpperCase()
    : '?'

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  function handleSearch(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key !== 'Enter' || !workspaceSearch.trim()) return
    navigate(`/products?q=${encodeURIComponent(workspaceSearch.trim())}`)
  }

  return (
    <header className="flex h-[72px] items-center justify-between border-b border-slate-200/80 bg-white/85 px-4 backdrop-blur lg:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <button
          className="rounded-xl p-2 hover:bg-accent lg:hidden"
          onClick={onMenuClick}
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="hidden sm:block"><p className="text-sm font-bold text-slate-800">{pageTitle}</p><p className="text-[11px] text-slate-400">Commerce operations workspace</p></div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <div className="relative hidden w-56 lg:block">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input value={workspaceSearch} onChange={(event) => setWorkspaceSearch(event.target.value)} onKeyDown={handleSearch} className="h-9 w-full rounded-xl border border-slate-200 bg-slate-50 pl-9 pr-3 text-xs outline-none transition focus:border-blue-300 focus:bg-white" placeholder="Search products…" />
        </div>
        <Button variant="ghost" size="icon" onClick={() => toast({ title: 'You’re all caught up', description: 'There are no new operational notifications.' })} className="relative rounded-xl text-slate-500" aria-label="Notifications"><Bell className="h-4 w-4" /><span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-blue-600 ring-2 ring-white" /></Button>
        <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Toggle theme">
          {theme === 'light' ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-2 rounded-xl p-1 hover:bg-accent">
              <Avatar>
                <AvatarFallback>{initials}</AvatarFallback>
              </Avatar>
              <div className="hidden text-left md:block"><p className="max-w-28 truncate text-xs font-bold text-slate-700">{user?.first_name} {user?.last_name}</p><p className="text-[10px] font-semibold uppercase tracking-wider text-primary">{user?.role?.replace('_', ' ')}</p></div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span>{user?.first_name} {user?.last_name}</span>
                <span className="text-xs font-normal text-muted-foreground">{user?.email}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => navigate('/profile')}>
              <User className="mr-2 h-4 w-4" />
              Profile
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut className="mr-2 h-4 w-4" />
              Logout
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
