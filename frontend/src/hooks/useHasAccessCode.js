import { useEffect, useState } from 'react'
import { ACCESS_CODE_EVENT, getAccessCode } from '../services/api'

// Whether an access code is stored, kept in sync when it is set (homepage unlock)
// or changed in another tab.
export function useHasAccessCode() {
  const [hasCode, setHasCode] = useState(() => Boolean(getAccessCode()))

  useEffect(() => {
    const sync = () => setHasCode(Boolean(getAccessCode()))
    window.addEventListener(ACCESS_CODE_EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(ACCESS_CODE_EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  return hasCode
}
