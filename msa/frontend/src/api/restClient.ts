type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

type QueryValue = string | number | boolean | null | undefined

export type RestRequestOptions<TBody = unknown> = {
  method?: HttpMethod
  query?: Record<string, QueryValue>
  headers?: Record<string, string>
  body?: TBody
  credentials?: RequestCredentials
  timeoutMs?: number
}

export type RestResponse<TData> = {
  status: number
  data: TData
}

export class RestApiError extends Error {
  status: number
  data: unknown

  constructor(message: string, status: number, data: unknown) {
    super(message)
    this.name = 'RestApiError'
    this.status = status
    this.data = data
  }
}

function buildUrl(url: string, query?: Record<string, QueryValue>) {
  const requestUrl = new URL(url)

  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      requestUrl.searchParams.set(key, String(value))
    }
  })

  return requestUrl.toString()
}

async function parseBody(response: Response) {
  if (response.status === 204) {
    return null
  }

  const contentType = response.headers.get('content-type') ?? ''

  if (contentType.includes('application/json')) {
    return response.json()
  }

  return response.text()
}

export async function requestRestApi<TData, TBody = unknown>(
  url: string,
  options: RestRequestOptions<TBody> = {},
): Promise<RestResponse<TData>> {
  const {
    method = 'GET',
    query,
    headers,
    body,
    // Cookie-based JWT auth usually needs credentials: 'include'.
    // Keep same-origin as the neutral default until the auth strategy is decided.
    credentials = 'same-origin',
    timeoutMs = 10000,
  } = options
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(buildUrl(url, query), {
      method,
      credentials,
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })

    const data = await parseBody(response)

    if (!response.ok) {
      throw new RestApiError('REST API request failed', response.status, data)
    }

    return {
      status: response.status,
      data: data as TData,
    }
  } finally {
    window.clearTimeout(timeoutId)
  }
}
