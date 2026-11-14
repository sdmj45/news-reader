/**
 * State that survives a reload, kept in `localStorage`.
 *
 * Every read and write is guarded. `localStorage` throws in a private window with site data
 * blocked, and it returns null in a fresh one, so a component that assumes it works renders
 * nothing for the readers most likely to be confused by that. The fallback is always the
 * default value and a working interface.
 */

import { useCallback, useEffect, useState } from 'react'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function useLocalState<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => read(key, fallback))

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value))
    } catch {
      // Storage full, or blocked. The interface keeps working with in-memory state; losing
      // a remembered filter on reload is a far smaller failure than crashing.
    }
  }, [key, value])

  return [value, setValue] as const
}

/** Saved articles, stored whole so the list works offline and survives a backend wipe. */
export function useFavourites() {
  const [ids, setIds] = useLocalState<string[]>('newsreader.favourites', [])

  const toggle = useCallback(
    (id: string) =>
      setIds((current) =>
        current.includes(id) ? current.filter((x) => x !== id) : [id, ...current],
      ),
    [setIds],
  )

  const has = useCallback((id: string) => ids.includes(id), [ids])

  return { ids, toggle, has }
}
