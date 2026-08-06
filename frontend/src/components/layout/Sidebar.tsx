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
    <nav className="flex h-full flex-col gap-1 p-3">
      <div className="mb-4 flex items-center gap-2 px-2">
        <Boxes className="h-6 w-6 text-primary" />
        <span className="text-lg font-bold">CommerceOS</span>
      </div>
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/'}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )
          }
        >
          <item.icon className="h-4 w-4" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
