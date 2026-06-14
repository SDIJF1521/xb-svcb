import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const AVATAR_KEY = 'xb-avatar'
const NAME_KEY = 'xb-nickname'

function read(key: string, fallback = ''): string {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

export const useProfileStore = defineStore('profile', () => {
  const avatar = ref<string>(read(AVATAR_KEY))
  const nickname = ref<string>(read(NAME_KEY, '创作者'))

  const initial = computed(() => (nickname.value || 'X').trim().charAt(0).toUpperCase() || 'X')

  function setAvatar(dataUrl: string) {
    avatar.value = dataUrl
    try {
      localStorage.setItem(AVATAR_KEY, dataUrl)
    } catch {
      /* 超出配额时忽略，仅内存生效 */
    }
  }

  function clearAvatar() {
    avatar.value = ''
    try {
      localStorage.removeItem(AVATAR_KEY)
    } catch {
      /* ignore */
    }
  }

  function setNickname(name: string) {
    nickname.value = name.slice(0, 16)
    try {
      localStorage.setItem(NAME_KEY, nickname.value)
    } catch {
      /* ignore */
    }
  }

  return { avatar, nickname, initial, setAvatar, clearAvatar, setNickname }
})
