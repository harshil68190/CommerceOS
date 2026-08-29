const ACCESS_KEY = 'commerceos.access_token'

export const tokenStorage = {
  getAccessToken: () => localStorage.getItem(ACCESS_KEY),
  getRefreshToken: () => null,
  setTokens: (access: string, _refresh?: string) => {
    localStorage.setItem(ACCESS_KEY, access)
  },
  setAccessToken: (access: string) => {
    localStorage.setItem(ACCESS_KEY, access)
  },
  clear: () => {
    localStorage.removeItem(ACCESS_KEY)
  },
}
