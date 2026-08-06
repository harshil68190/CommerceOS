import { create } from 'zustand'

export interface ToastItem {
  id: string
  title?: string
  description?: string
  variant?: 'default' | 'destructive' | 'success'
  action?: import('react').ReactNode
}

interface ToastState {
  toasts: ToastItem[]
  add: (toast: Omit<ToastItem, 'id'>) => void
  dismiss: (id: string) => void
  remove: (id: string) => void
}

let counter = 0

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  add: (toast) =>
    set((state) => ({
      toasts: [...state.toasts, { ...toast, id: `toast-${++counter}` }],
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
  remove: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}))

/** Convenience toast helper used across the app. */
export function toast(
  props: Omit<ToastItem, 'id'>,
  duration = 4000,
) {
  useToastStore.getState().add(props)
  if (duration > 0) {
    setTimeout(() => {
      const s = useToastStore.getState()
      const item = s.toasts.find((t) => t.title === props.title)
      if (item) s.dismiss(item.id)
    }, duration)
  }
}
