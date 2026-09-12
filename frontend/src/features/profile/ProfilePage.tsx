import { useEffect, useState } from 'react'
import { Loader2, Pencil, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { useAuth } from '@/lib/auth/useAuth'
import { formatDate } from '@/lib/utils'
import { toast } from '@/stores/toastStore'

export default function ProfilePage() {
  const { user, updateProfile } = useAuth()
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [phone, setPhone] = useState('')

  useEffect(() => {
    if (!user) return
    setFirstName(user.first_name)
    setLastName(user.last_name)
    setPhone(user.phone ?? '')
  }, [user])

  if (!user) return null

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!firstName.trim() || !lastName.trim()) {
      toast({ title: 'Name is required', description: 'Enter both a first and last name.', variant: 'destructive' })
      return
    }
    setSaving(true)
    try {
      await updateProfile({ first_name: firstName.trim(), last_name: lastName.trim(), phone: phone.trim() || null })
      setEditing(false)
      toast({ title: 'Profile updated', description: 'Your account details are now up to date.', variant: 'success' })
    } catch (error) {
      toast({ title: 'Could not update profile', description: error instanceof Error ? error.message : 'Please try again.', variant: 'destructive' })
    } finally {
      setSaving(false)
    }
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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="page-eyebrow">Account settings</p>
          <h1 className="mt-1 text-3xl font-bold tracking-[-.04em]">Profile</h1>
          <p className="text-sm text-muted-foreground">Manage your personal details and workspace identity.</p>
        </div>
        {!editing && <Button variant="outline" onClick={() => setEditing(true)}><Pencil className="mr-2 h-4 w-4" />Edit profile</Button>}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardContent className="flex flex-col items-center py-8">
            <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary text-2xl font-bold text-primary-foreground">
              {user.first_name[0]}{user.last_name[0]}
            </div>
            <h2 className="mt-4 text-lg font-semibold">{user.first_name} {user.last_name}</h2>
            <p className="text-sm text-muted-foreground">{user.email}</p>
            <Badge className="mt-3">{user.role.replace('_', ' ')}</Badge>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle>{editing ? 'Edit account details' : 'Account details'}</CardTitle>
            {editing && <Button variant="ghost" size="icon" onClick={() => setEditing(false)} aria-label="Cancel editing"><X className="h-4 w-4" /></Button>}
          </CardHeader>
          <CardContent>
            {editing ? (
              <form onSubmit={handleSave} className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2"><Label htmlFor="profile-first-name">First name</Label><Input id="profile-first-name" value={firstName} onChange={(event) => setFirstName(event.target.value)} /></div>
                  <div className="space-y-2"><Label htmlFor="profile-last-name">Last name</Label><Input id="profile-last-name" value={lastName} onChange={(event) => setLastName(event.target.value)} /></div>
                </div>
                <div className="space-y-2"><Label htmlFor="profile-phone">Phone</Label><Input id="profile-phone" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+1 555 123 4567" /></div>
                <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setEditing(false)}>Cancel</Button><Button type="submit" disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save changes</Button></div>
              </form>
            ) : (
              <div className="space-y-3">
                {rows.map((row, index) => <div key={row.label}>{index > 0 && <Separator className="mb-3" />}<div className="flex items-center justify-between gap-4"><span className="text-sm text-muted-foreground">{row.label}</span><span className="text-right text-sm font-medium capitalize">{row.value}</span></div></div>)}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
