import * as crypto from 'crypto'

export function verifyTelegramInitData(initData: string, botToken: string): boolean {
  const urlParams = new URLSearchParams(initData)
  const hash = urlParams.get('hash')
  if (!hash) return false

  urlParams.delete('hash')

  const dataCheckString = Array.from(urlParams.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join('\n')

  const secretKey = crypto
    .createHmac('sha256', 'WebAppData')
    .update(botToken)
    .digest()

  const computedHash = crypto
    .createHmac('sha256', secretKey)
    .update(dataCheckString)
    .digest('hex')

  const authDate = urlParams.get('auth_date')
  if (authDate && Date.now() / 1000 - parseInt(authDate) > 86400) return false

  return computedHash === hash
}
