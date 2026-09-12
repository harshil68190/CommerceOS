import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Package,
  Warehouse,
  Boxes,
  ShoppingCart,
  User,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth/useAuth'
import type { UserRole } from '@/types/api'

const baseNav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, roles: ['admin', 'seller', 'inventory_manager', 'customer'] as UserRole[] },
  { to: '/products', label: 'Products', icon: Package, roles: ['admin', 'seller', 'inventory_manager', 'customer'] as UserRole[] },
  { to: '/warehouses', label: 'Warehouses', icon: Warehouse, roles: ['admin', 'inventory_manager'] as UserRole[] },
  { to: '/inventory', label: 'Inventory', icon: Boxes, roles: ['admin', 'inventory_manager'] as UserRole[] },
  { to: '/orders', label: 'Orders', icon: ShoppingCart, roles: ['admin', 'seller', 'customer'] as UserRole[] },
  { to: '/profile', label: 'Profile', icon: User, roles: ['admin', 'seller', 'inventory_manager', 'customer'] as UserRole[] },
]

interface SidebarProps {
  onNavigate?: () => void
}

export function Sidebar({ onNavigate }: SidebarProps) {
  const { user } = useAuth()

  const nav = baseNav.filter((item) => {
    if (!user) return false
    return item.roles.includes(user.role)
  })

  return (
    <nav className="flex h-full flex-col p-4">
      <div className="mb-9 flex items-center gap-3 px-2 pt-1">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-white shadow-lg shadow-blue-900/15">
          <Boxes className="h-5 w-5" />
        </div>
        <div>
          <span className="block text-[17px] font-bold tracking-[-0.04em] text-slate-900">CommerceOS</span>
          <span className="block text-[10px] font-semibold uppercase tracking-[.16em] text-slate-400">Operations</span>
        </div>
      </div>
      <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">Workspace</p>
      <div className="space-y-1">
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-all',
              isActive
                ? 'bg-primary text-primary-foreground shadow-md shadow-blue-950/10'
                : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800',
            )
          }
        >
          <item.icon className="h-4 w-4" />
          {item.label}
        </NavLink>
      ))}
      </div>
      <div className="mt-auto rounded-2xl border border-blue-100 bg-blue-50/70 p-3.5">
        <div className="mb-1 text-xs font-bold text-primary">{user?.role === 'customer' ? 'Customer workspace' : 'Operations workspace'}</div>
        <p className="text-[11px] leading-4 text-slate-500">{user?.role === 'customer' ? 'Your catalog and order activity, in one place.' : 'Your commerce network is connected and secure.'}</p>
      </div>
    </nav>
  )
}
