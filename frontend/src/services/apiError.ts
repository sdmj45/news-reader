/**
 * The one error type both data sources raise.
 *
 * In its own module so `api.ts` and `staticData.ts` can each import it without the two
 * importing each other - `api.ts` already imports `staticData.ts` to choose a mode.
 *
 * The message is a tag, not prose: `offline` and `timeout` are matched by the UI, which
 * owns the wording because the wording is translated.
 */

export class ApiError extends Error {
  // Declared and assigned rather than a parameter property: the project's TypeScript config
  // sets `erasableSyntaxOnly`, which forbids syntax that emits runtime code.
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
