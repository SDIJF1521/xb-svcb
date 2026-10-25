export type ThemeImageFormat = 'png' | 'jpeg' | 'webp' | 'gif' | 'avif' | 'heif' | 'unknown'

const HEIF_BRANDS = new Set(['heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'mif1', 'msf1'])
const AVIF_BRANDS = new Set(['avif', 'avis'])

function ascii(bytes: Uint8Array, start: number, length: number): string {
  return String.fromCharCode(...bytes.slice(start, start + length))
}

export function detectThemeImageFormat(bytes: Uint8Array): ThemeImageFormat {
  if (
    bytes.length >= 8
    && bytes[0] === 0x89
    && ascii(bytes, 1, 3) === 'PNG'
    && bytes[4] === 0x0d
    && bytes[5] === 0x0a
    && bytes[6] === 0x1a
    && bytes[7] === 0x0a
  ) return 'png'

  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return 'jpeg'
  }
  if (bytes.length >= 12 && ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 4) === 'WEBP') {
    return 'webp'
  }
  if (bytes.length >= 6 && (ascii(bytes, 0, 6) === 'GIF87a' || ascii(bytes, 0, 6) === 'GIF89a')) {
    return 'gif'
  }

  if (bytes.length >= 12 && ascii(bytes, 4, 4) === 'ftyp') {
    const brands = new Set<string>()
    for (let offset = 8; offset + 4 <= bytes.length; offset += 4) {
      brands.add(ascii(bytes, offset, 4))
    }
    if ([...brands].some((brand) => HEIF_BRANDS.has(brand))) return 'heif'
    if ([...brands].some((brand) => AVIF_BRANDS.has(brand))) return 'avif'
  }

  return 'unknown'
}

export async function detectThemeImageFile(file: Blob): Promise<ThemeImageFormat> {
  const header = new Uint8Array(await file.slice(0, 64).arrayBuffer())
  return detectThemeImageFormat(header)
}

export async function convertHeifThemeImage(file: File): Promise<File> {
  const { default: heic2any } = await import('heic2any')
  const result = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.9 })
  const blob = Array.isArray(result) ? result[0] : result
  if (!blob) throw new Error('HEIC conversion returned no image')

  const name = file.name.replace(/\.[^.]+$/, '') || 'theme-background'
  return new File([blob], `${name}.jpg`, {
    type: 'image/jpeg',
    lastModified: file.lastModified,
  })
}
