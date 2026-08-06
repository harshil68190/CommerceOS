import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/lib/auth/useAuth'
import { formatDate } from '@/lib/utils'

export default function ProfilePage() {
  const { user } = useAuth()

  if (!user) {
    return null
  }

  const rows: Array<{ label: string; value: string }> = [
    { label: 'Email', value: user.email },
    { label: 'Username', value: user.username },
    { label: 'Name', value: `${user.first_name} ${user.last_name}` },
    { label: 'Phone', value: user.phone || '—' },
    { label: 'Role', value: user.role },
    { label: 'Member since', value: formatDate(user.created_at) },
    { label: 'Last login', value: user.last_login ? formatDate(user.last_login) : '—' },
  ]

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Profile</h1>
        <p className="text-sm text-muted-foreground">Your account information</p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardContent className="flex flex-col items-center py-8">
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary text-2xl font-bold text-primary-foreground">
              {user.first_name[0]}
              {user.last_name[0]}
            </div>
            <h2 className="mt-4 text-lg font-semibold">
              {user.first_name} {user.last_name}
            </h2>
            <p className="text-sm text-muted-foreground">{user.email}</p>
            <Badge className="mt-3">{user.role}</Badge>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Account Details</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {rows.map((row, i) => (
                <div key={row.label}>
                  {i > 0 && <Separator className="mb-3" />}
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">{row.label}</span>
                    <span className="text-sm font-medium">{row.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
