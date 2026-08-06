import { useToastStore } from '@/stores/toastStore'
import type { ToastProps } from '@/components/ui/toast'
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from '@/components/ui/toast'

export function Toaster() {
  const { toasts } = useToastStore()

  return (
    <ToastProvider>
      {toasts.map(({ id, title, description, variant, action }) => (
        <Toast key={id} variant={variant as ToastProps['variant']}>
          <div className="grid gap-1">
            {title && <ToastTitle>{title}</ToastTitle>}
            {description && <ToastDescription>{description}</ToastDescription>}
          </div>
          {action}
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  )
}
